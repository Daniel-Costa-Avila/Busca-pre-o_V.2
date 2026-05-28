from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from App.collectors.magalu.installments import extrair_parcelamento
from App.collectors.magalu.pix import extrair_pix
from App.collectors.magalu.pricing import extrair_avista
from App.collectors.magalu.text_pricing import (
    extract_a_prazo_from_text,
    extract_avista_from_text,
    extract_parcelamento_from_text,
    extract_pix_from_text,
    sanitize_result_prices,
)
from App.utils.dom_prices import extract_struck_prices


NEXT_DATA_RE = re.compile(
    r"<script[^>]+id=['\"]__NEXT_DATA__['\"][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

DEBUG_DIR = Path("debug_magalu")


def _env_bool(name: str, default: bool) -> bool:
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    import os

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    if value < minimum or value > maximum:
        return default
    return value


def _save_debug(driver, reason: str, url: str | None = None) -> None:
    """
    Salva artefatos para diagnostico (HTML + screenshot) quando a Magalu nao retorna preco.
    """
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        current_url = ""
        try:
            current_url = str(getattr(driver, "current_url", "") or "")
        except Exception:
            current_url = ""

        page_source = ""
        try:
            page_source = str(getattr(driver, "page_source", "") or "")
        except Exception:
            page_source = ""

        info = (
            f"reason: {reason}\n"
            f"url: {url or ''}\n"
            f"current_url: {current_url}\n"
        )
        (DEBUG_DIR / f"{stamp}_selenium_info.txt").write_text(info, encoding="utf-8", errors="ignore")
        if page_source:
            (DEBUG_DIR / f"{stamp}_selenium.html").write_text(page_source, encoding="utf-8", errors="ignore")

        try:
            driver.get_screenshot_as_file(str(DEBUG_DIR / f"{stamp}_selenium.png"))
        except Exception:
            pass
    except Exception:
        pass


def _looks_blocked(text: str) -> bool:
    if not text:
        return False
    t = " ".join(str(text).lower().split())
    tokens = (
        "erro 403",
        "acesso negado",
        "access denied",
        "nao e possivel acessar a pagina",
        "não é possível acessar a página",
        "captcha",
        "verifique se voce e humano",
        "robot",
        "bloqueado",
        "forbidden",
        "http 403",
        "sec-if-cpt-container",
        "powered and protected by akamai",
        "behavioral-content",
    )
    return any(tok in t for tok in tokens)


def _has_price_signals(text: str) -> bool:
    if not text:
        return False
    t = " ".join(str(text).lower().split())
    markers = (
        "r$",
        "preço",
        "preco",
        "à vista",
        "a vista",
        "pix",
        "sem juros",
        "em até",
        "em ate",
        "vendido por",
        "adicionar à sacola",
        "adicionar a sacola",
        "comprar agora",
    )
    return any(marker in t for marker in markers)


def _wait_for_manual_unblock(driver, url: str | None = None) -> bool:
    """
    Quando a Magalu cair no challenge da Akamai em modo visivel, mantem a pagina
    aberta por um tempo para permitir resolucao manual e reaproveitar a sessao.
    """
    if not _env_bool("MAGALU_MANUAL_UNLOCK_ON_BLOCK", True):
        return False

    timeout_seconds = _env_int("MAGALU_MANUAL_UNLOCK_TIMEOUT_SECONDS", 120, 10, 900)
    poll_seconds = _env_int("MAGALU_MANUAL_UNLOCK_POLL_SECONDS", 2, 1, 10)
    deadline = time.time() + float(timeout_seconds)
    last_url = ""

    print(
        "MAGALU: pagina de bloqueio detectada. "
        f"Aguardando ate {timeout_seconds}s para liberacao manual da sessao..."
    )

    while time.time() < deadline:
        try:
            current_url = str(getattr(driver, "current_url", "") or "")
        except Exception:
            current_url = ""
        if current_url and current_url != last_url:
            print(f"MAGALU: URL atual = {current_url}")
            last_url = current_url

        try:
            page_source = str(getattr(driver, "page_source", "") or "")
        except Exception:
            page_source = ""

        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            body_text = ""

        blocked = _looks_blocked(page_source) or _looks_blocked(body_text)
        state = _extract_product_state_from_next_data(page_source)
        has_product_text = "r$" in str(body_text).lower() or "vendido por" in str(body_text).lower()

        if not blocked and (isinstance(state, dict) or has_product_text):
            print("MAGALU: sessao liberada, retomando coleta.")
            return True

        time.sleep(float(poll_seconds))

    print("MAGALU: tempo esgotado aguardando liberacao manual.")
    _save_debug(driver, "manual_unlock_timeout", url=url)
    return False


def _extract_product_state_from_next_data(raw_html: str) -> dict | None:
    if not raw_html:
        return None

    match = NEXT_DATA_RE.search(raw_html)
    if not match:
        return None

    payload = (match.group(1) or "").strip()
    if not payload:
        return None

    try:
        data = json.loads(payload)
    except Exception:
        return None

    page_props = data.get("props", {}).get("pageProps", {})
    product = page_props.get("product")
    if isinstance(product, dict):
        return product

    product = page_props.get("pdp", {}).get("product")
    if isinstance(product, dict):
        return product

    return None


def coletar(driver, link: str | None = None) -> dict:
    """
    Coletor Magalu via Selenium (fallback do Playwright).
    Prioriza __NEXT_DATA__ e usa texto visivel apenas como fallback.
    Ignora preco riscado/antigo.
    """

    out = {
        "a_prazo": None,
        "avista": None,
        "pix": None,
        "prazo": None,
        "status": "",
    }

    if not link:
        out["status"] = "LINK AUSENTE"
        return out

    try:
        driver.get(link)

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass

        ignored_prices = extract_struck_prices(driver)

        state = _extract_product_state_from_next_data(driver.page_source or "")
        if isinstance(state, dict):
            out["pix"] = extrair_pix(state)
            out["a_prazo"] = extrair_avista(state)
            out["avista"] = out["a_prazo"]
            out["prazo"] = extrair_parcelamento(state)
            out = sanitize_result_prices(out, ignored_prices=ignored_prices)

        text = driver.find_element(By.TAG_NAME, "body").text or ""
        blocked_now = _looks_blocked(driver.page_source or "") or _looks_blocked(text)
        # Se existem sinais reais de produto/preco, evita falso positivo de bloqueio.
        if blocked_now and not _has_price_signals(text):
            if _wait_for_manual_unblock(driver, url=link):
                try:
                    ignored_prices = extract_struck_prices(driver)
                except Exception:
                    ignored_prices = set()
                try:
                    state = _extract_product_state_from_next_data(driver.page_source or "")
                except Exception:
                    state = None
                try:
                    text = driver.find_element(By.TAG_NAME, "body").text or ""
                except Exception:
                    text = ""
            else:
                out["status"] = "MAGALU - BLOQUEADO (SUSPEITA DE CAPTCHA/403)"
                _save_debug(driver, "blocked_suspected", url=link)
                return out

        if not out["pix"]:
            out["pix"] = extract_pix_from_text(text, ignored_prices=ignored_prices)

        if not out["a_prazo"]:
            out["a_prazo"] = extract_a_prazo_from_text(
                text,
                pix=out.get("pix"),
                ignored_prices=ignored_prices,
            )

        if not out["avista"]:
            out["avista"] = out["a_prazo"] or extract_avista_from_text(
                text,
                pix=out.get("pix"),
                ignored_prices=ignored_prices,
            )

        if not out["prazo"]:
            out["prazo"] = extract_parcelamento_from_text(
                text,
                ignored_prices=ignored_prices,
            )

        out = sanitize_result_prices(out, ignored_prices=ignored_prices)

        if out["pix"] and out["avista"]:
            out["status"] = "MAGALU - OK"
        elif out["pix"]:
            out["status"] = "MAGALU - OK (SOMENTE PRECO PRINCIPAL)"
        elif out["avista"] or out["prazo"]:
            out["status"] = "MAGALU - OK (SEM PRECO PRINCIPAL)"
        else:
            out["status"] = "MAGALU - PRECO NAO ENCONTRADO"
            _save_debug(driver, "preco_nao_encontrado", url=link)

        return out

    except Exception:
        out["status"] = "MAGALU - ERRO DE COLETA"
        _save_debug(driver, "erro_de_coleta", url=link)
        return out
