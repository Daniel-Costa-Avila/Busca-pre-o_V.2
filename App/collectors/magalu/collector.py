from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import requests
except Exception:
    requests = None

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:
    sync_playwright = None
    _PLAYWRIGHT_IMPORT_ERROR = f"{type(exc).__name__} | {exc}"
else:
    _PLAYWRIGHT_IMPORT_ERROR = None

try:
    from App.collectors import magalu_selenium_legacy
    from App.utils.browser import get_driver, resolve_browser_pool
except Exception as exc:
    magalu_selenium_legacy = None
    get_driver = None
    resolve_browser_pool = None
    _SELENIUM_IMPORT_ERROR = f"{type(exc).__name__} | {exc}"
else:
    _SELENIUM_IMPORT_ERROR = None

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


DEBUG_DIR = Path("debug_magalu")
PROFILE_DIR = Path("chrome_profile_magalu")
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(
    r"<script[^>]+id=['\"]__NEXT_DATA__['\"][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

# Evita repetir bootstrap quebrado do Playwright na mesma execucao.
_PLAYWRIGHT_DISABLED_REASON: str | None = None
_PLAYWRIGHT_WARNING_REASON: str | None = None

_force_playwright = os.getenv("MAGALU_FORCE_PLAYWRIGHT", "").strip().lower() in {"1", "true", "yes", "on"}
_disable_playwright = os.getenv("MAGALU_DISABLE_PLAYWRIGHT", "").strip().lower() in {"1", "true", "yes", "on"}
if _disable_playwright:
    _PLAYWRIGHT_DISABLED_REASON = "Playwright desabilitado por MAGALU_DISABLE_PLAYWRIGHT=1."
elif _PLAYWRIGHT_IMPORT_ERROR:
    _PLAYWRIGHT_DISABLED_REASON = f"Playwright indisponivel no ambiente atual: {_PLAYWRIGHT_IMPORT_ERROR}"
elif sys.version_info >= (3, 14) and not _force_playwright:
    _PLAYWRIGHT_DISABLED_REASON = (
        f"Python {sys.version_info.major}.{sys.version_info.minor} nao suportado oficialmente pelo "
        "Playwright nesta versao. Use Python 3.13 ou defina MAGALU_FORCE_PLAYWRIGHT=1 por sua conta."
    )

_SELENIUM_DRIVER = None
_SELENIUM_BROWSER_NAME: str | None = None
_SELENIUM_DISABLED_REASON: str | None = None
_HTTP_DISABLED_REASON: str | None = None


def close_magalu_selenium_driver() -> None:
    global _SELENIUM_DRIVER, _SELENIUM_BROWSER_NAME

    driver = _SELENIUM_DRIVER
    _SELENIUM_DRIVER = None
    _SELENIUM_BROWSER_NAME = None
    if driver is None:
        return

    try:
        driver.quit()
    except Exception:
        pass


def _selenium_status_indicates_block(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    status = " ".join(str(result.get("status") or "").lower().split())
    if not status:
        return False
    tokens = ("bloqueado", "erro 403", "http 403", "forbidden", "access denied")
    return any(tok in status for tok in tokens)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _compact_reason(reason: str | None, limit: int = 260) -> str | None:
    if not reason:
        return None
    normalized = " ".join(str(reason).split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 3)]}..."


def _launch_context(p, headless: bool):
    """
    Tenta abrir contexto persistente (perfil fixo).
    Se falhar (perfil travado/corrompido), cai para contexto temporario.
    Retorna (context, browser_ou_None).
    """
    PROFILE_DIR.mkdir(exist_ok=True)
    args = ["--disable-blink-features=AutomationControlled"]

    try:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            args=args,
            locale="pt-BR",
            user_agent=DEFAULT_UA,
            viewport={"width": 1366, "height": 768},
        )
        return context, None
    except Exception:
        browser = p.chromium.launch(
            headless=headless,
            args=args,
        )
        context = browser.new_context(
            locale="pt-BR",
            user_agent=DEFAULT_UA,
            viewport={"width": 1366, "height": 768},
        )
        return context, browser


def _save_debug(page, reason: str) -> None:
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        info = (
            f"reason: {reason}\n"
            f"url: {page.url}\n"
            f"title: {page.title()}\n"
        )
        (DEBUG_DIR / f"{stamp}_info.txt").write_text(
            info,
            encoding="utf-8",
            errors="ignore",
        )
        (DEBUG_DIR / f"{stamp}.html").write_text(
            page.content(),
            encoding="utf-8",
            errors="ignore",
        )
        page.screenshot(path=str(DEBUG_DIR / f"{stamp}.png"), full_page=True)
    except Exception:
        pass


def _strip_html_to_text(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def _collect_visible_dom_texts(page) -> list[str]:
    texts: list[str] = []

    for selector in (
        '[data-testid="price-method"]',
        '[data-testid="price-installment"]',
        '[data-testid="price-value"]',
    ):
        try:
            items = page.locator(selector).all_inner_texts()
        except Exception:
            items = []
        for item in items:
            normalized = " ".join(str(item or "").split())
            if normalized:
                texts.append(normalized)

    try:
        body_text = page.locator("body").inner_text()
    except Exception:
        body_text = ""
    if body_text:
        texts.append(body_text)

    return texts


def _extract_product_state_from_next_data(raw_html: str) -> dict | None:
    if not raw_html:
        return None

    match = NEXT_DATA_RE.search(raw_html)
    if not match:
        return None

    payload = match.group(1).strip()
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


def _extract_price_texts_from_json_payload(payload: object) -> list[str]:
    """
    Extrai fragmentos de texto "provavelmente relacionados a preco" de um payload JSON.
    Objetivo: reaproveitar os parsers baseados em texto quando a Magalu carrega precos via XHR.
    """

    price_key_tokens = (
        "price",
        "preco",
        "valor",
        "amount",
        "pix",
        "avista",
        "a_vista",
        "boleto",
        "installment",
        "parcel",
        "parcela",
        "total",
    )

    out: list[str] = []

    def format_brl_from_reais(value: float) -> str:
        if value <= 0:
            return ""
        inteiro = int(value)
        centavos = int(round((value - inteiro) * 100))
        inteiro_str = f"{inteiro:,}".replace(",", ".")
        return f"R$ {inteiro_str},{centavos:02d}"

    def walk(obj: object, key_hint: str = "") -> None:
        if obj is None:
            return
        if isinstance(obj, bool):
            return
        if isinstance(obj, (str, int, float)):
            text = str(obj).strip()
            if not text:
                return
            hint = str(key_hint or "").lower()
            if hint and any(tok in hint for tok in price_key_tokens):
                out.append(f"{hint}: {text}")
                # Tenta adicionar tambem no formato "R$ X.XXX,YY" para os parsers baseados em texto.
                try:
                    numeric: float | None = None
                    if isinstance(obj, int):
                        if 1000 <= obj <= 100_000_000:
                            numeric = float(obj) / 100.0
                        elif 1 <= obj <= 100_000:
                            numeric = float(obj)
                    elif isinstance(obj, float) and 0 < obj <= 100_000:
                        numeric = float(obj)
                    if numeric is not None and numeric > 0:
                        formatted = format_brl_from_reais(numeric)
                        if formatted:
                            out.append(f"{hint}: {formatted}")
                except Exception:
                    pass
                return
            if "r$" in text.lower():
                out.append(text)
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, key_hint=str(k))
            return
        if isinstance(obj, list):
            for item in obj:
                walk(item, key_hint=key_hint)
            return

    walk(payload, key_hint="")
    return out


def _should_disable_playwright_after_error(reason_lower: str) -> bool:
    if not reason_lower:
        return False
    disabling_tokens = (
        "acesso negado",
        "winerror 5",
        "not supported",
        "unsupported",
        "no module named 'playwright'",
        "executable doesn't exist",
        "browser_type.launch",
        "failed to launch",
        "future exception was never retrieved",
    )
    return any(token in reason_lower for token in disabling_tokens)


def _page_looks_blocked_playwright(page) -> bool:
    """
    Alguns bloqueios da Magalu retornam 200 com uma pagina de erro/captcha.
    Detecta sinais comuns para evitar tentar parsear preco.
    """
    try:
        title = (page.title() or "").strip().lower()
    except Exception:
        title = ""
    try:
        body_text = (page.locator("body").inner_text() or "").strip().lower()
    except Exception:
        body_text = ""
    haystack = " ".join((title + " " + body_text).split())
    if not haystack:
        return False
    tokens = (
        "não é possível acessar a página",
        "nao e possivel acessar a pagina",
        "erro 403",
        "forbidden",
        "access denied",
        "tente novamente em 1 minuto",
        "verifique se você é humano",
        "verifique se voce e humano",
        "captcha",
    )
    return any(token in haystack for token in tokens)


def _collect_with_http_fallback(url: str, reason: str | None = None) -> dict:
    global _HTTP_DISABLED_REASON

    out = {
        "a_prazo": None,
        "avista": None,
        "pix": None,
        "prazo": None,
        "status": "MAGALU - FALLBACK HTTP: INICIAL",
    }

    prefix = "MAGALU - FALLBACK HTTP"
    reason = _compact_reason(reason)
    if reason:
        prefix = f"{prefix} ({reason})"

    if requests is None:
        out["status"] = f"{prefix}: REQUESTS INDISPONIVEL"
        return out

    if _HTTP_DISABLED_REASON:
        out["status"] = f"{prefix}: HTTP INDISPONIVEL: {_HTTP_DISABLED_REASON}"
        return out

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": DEFAULT_UA,
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            },
            timeout=(12, 35),
        )
    except Exception as exc:
        net_reason = _compact_reason(f"{type(exc).__name__} | {exc}", limit=320) or "erro de rede"
        lowered = net_reason.lower()
        if (
            "winerror 10013" in lowered
            or "failed to establish a new connection" in lowered
            or "connection refused" in lowered
            or "connection reset" in lowered
            or "timed out" in lowered
        ):
            _HTTP_DISABLED_REASON = net_reason
        out["status"] = f"{prefix}: ERRO DE REDE: {net_reason}"
        return out

    if response.status_code >= 400:
        out["status"] = f"{prefix}: HTTP {response.status_code}"
        return out

    html = response.text or ""
    state = _extract_product_state_from_next_data(html)

    if isinstance(state, dict):
        out["pix"] = extrair_pix(state)
        out["a_prazo"] = extrair_avista(state)
        out["avista"] = out["a_prazo"]
        out["prazo"] = extrair_parcelamento(state)

    if not (out["pix"] or out["a_prazo"] or out["prazo"]):
        text = _strip_html_to_text(html)
        out["pix"] = extract_pix_from_text(text)
        out["a_prazo"] = extract_a_prazo_from_text(text, pix=out.get("pix"))
        out["avista"] = out["a_prazo"] or extract_avista_from_text(text, pix=out.get("pix"))
        out["prazo"] = extract_parcelamento_from_text(text)

    if out["pix"] or out["a_prazo"] or out["prazo"]:
        out["status"] = f"{prefix}: OK"
    else:
        out["status"] = f"{prefix}: PRECO NAO ENCONTRADO"

    return out


def _collect_with_selenium_fallback(url: str, headless: bool, reason: str | None = None) -> dict:
    """
    Fallback para ambientes onde Playwright nao inicializa.
    Reutiliza um unico driver Selenium para reduzir overhead.
    """
    global _SELENIUM_DRIVER, _SELENIUM_BROWSER_NAME, _SELENIUM_DISABLED_REASON

    if _SELENIUM_IMPORT_ERROR or get_driver is None or magalu_selenium_legacy is None:
        _SELENIUM_DISABLED_REASON = _compact_reason(
            _SELENIUM_IMPORT_ERROR or "dependencias Selenium nao carregadas",
            limit=220,
        )
        composite_reason = (
            f"{reason} | Selenium indisponivel: {_SELENIUM_DISABLED_REASON}"
            if reason
            else f"Selenium indisponivel: {_SELENIUM_DISABLED_REASON}"
        )
        return _collect_with_http_fallback(url, reason=_compact_reason(composite_reason, limit=260))

    sticky_disable = _env_bool("MAGALU_SELENIUM_STICKY_DISABLE", False)
    if _SELENIUM_DISABLED_REASON and sticky_disable:
        composite_reason = (
            f"{reason} | Selenium indisponivel: {_SELENIUM_DISABLED_REASON}"
            if reason
            else f"Selenium indisponivel: {_SELENIUM_DISABLED_REASON}"
        )
        return _collect_with_http_fallback(url, reason=_compact_reason(composite_reason, limit=260))
    if _SELENIUM_DISABLED_REASON and not sticky_disable:
        # Tenta recuperar automaticamente em falhas transitórias de driver/browser.
        _SELENIUM_DISABLED_REASON = None

    magalu_pool_raw = (os.getenv("MAGALU_SELENIUM_BROWSERS") or "").strip()
    magalu_single = (os.getenv("MAGALU_SELENIUM_BROWSER") or "").strip()

    # Default: tenta Chrome primeiro (maior compatibilidade/estabilidade em muitos PCs),
    # depois Firefox, depois Edge. Ajuste via MAGALU_SELENIUM_BROWSERS / MAGALU_SELENIUM_BROWSER.
    browser_candidates = ["chrome", "firefox", "edge"]
    if resolve_browser_pool is not None:
        try:
            if magalu_pool_raw:
                raw_list = [p.strip().lower() for p in magalu_pool_raw.split(",") if p.strip()]
                browser_candidates = raw_list or browser_candidates
            elif magalu_single:
                browser_candidates = [magalu_single.strip().lower()]
        except Exception:
            browser_candidates = browser_candidates
    if not browser_candidates:
        browser_candidates = ["chrome", "firefox", "edge"]

    # Prioridades: chrome -> firefox -> edge (edge costuma ser mais sensível a bloqueio em alguns PCs).
    ordered: list[str] = []
    for preferred in ("chrome", "firefox", "edge"):
        if preferred in browser_candidates and preferred not in ordered:
            ordered.append(preferred)
    ordered.extend([b for b in browser_candidates if b not in ordered])
    browser_candidates = ordered

    last_error: str | None = None
    driver_errors: list[str] = []
    rotate_on_block = _env_bool("MAGALU_TRY_OTHER_BROWSERS_ON_BLOCK", True)
    magalu_use_profile = _env_bool("MAGALU_SELENIUM_USE_PROFILE", True)
    magalu_profile_dir = (os.getenv("MAGALU_SELENIUM_PROFILE_DIR") or "").strip() or str(PROFILE_DIR)
    reset_driver_on_error = _env_bool("MAGALU_SELENIUM_RESET_ON_ERROR", headless)

    for browser_name in browser_candidates:
        # Reutiliza driver apenas quando ele já é do navegador atual.
        if _SELENIUM_DRIVER is not None and (_SELENIUM_BROWSER_NAME or "").startswith(browser_name):
            driver = _SELENIUM_DRIVER
        else:
            driver = None

        if driver is None:
            try:
                old_use_profile = os.environ.get("SELENIUM_USE_PROFILE")
                old_profile_dir = os.environ.get("SELENIUM_PROFILE_DIR")
                if magalu_use_profile:
                    os.environ["SELENIUM_USE_PROFILE"] = "1"
                    if magalu_profile_dir:
                        os.environ["SELENIUM_PROFILE_DIR"] = magalu_profile_dir
                driver = get_driver(headless=headless, browser_name=browser_name)
                if old_use_profile is None:
                    os.environ.pop("SELENIUM_USE_PROFILE", None)
                else:
                    os.environ["SELENIUM_USE_PROFILE"] = old_use_profile
                if old_profile_dir is None:
                    os.environ.pop("SELENIUM_PROFILE_DIR", None)
                else:
                    os.environ["SELENIUM_PROFILE_DIR"] = old_profile_dir
                _SELENIUM_DRIVER = driver
                _SELENIUM_BROWSER_NAME = browser_name
            except Exception as exc:
                # Restaura env mesmo quando falha.
                try:
                    if "old_use_profile" in locals():
                        if old_use_profile is None:
                            os.environ.pop("SELENIUM_USE_PROFILE", None)
                        else:
                            os.environ["SELENIUM_USE_PROFILE"] = old_use_profile
                    if "old_profile_dir" in locals():
                        if old_profile_dir is None:
                            os.environ.pop("SELENIUM_PROFILE_DIR", None)
                        else:
                            os.environ["SELENIUM_PROFILE_DIR"] = old_profile_dir
                except Exception:
                    pass
                if headless and str(browser_name).strip().lower() == "edge":
                    try:
                        old_use_profile = os.environ.get("SELENIUM_USE_PROFILE")
                        old_profile_dir = os.environ.get("SELENIUM_PROFILE_DIR")
                        if magalu_use_profile:
                            os.environ["SELENIUM_USE_PROFILE"] = "1"
                            if magalu_profile_dir:
                                os.environ["SELENIUM_PROFILE_DIR"] = magalu_profile_dir
                        driver = get_driver(headless=False, browser_name=browser_name)
                        if old_use_profile is None:
                            os.environ.pop("SELENIUM_USE_PROFILE", None)
                        else:
                            os.environ["SELENIUM_USE_PROFILE"] = old_use_profile
                        if old_profile_dir is None:
                            os.environ.pop("SELENIUM_PROFILE_DIR", None)
                        else:
                            os.environ["SELENIUM_PROFILE_DIR"] = old_profile_dir
                        _SELENIUM_DRIVER = driver
                        _SELENIUM_BROWSER_NAME = f"{browser_name} (headless off)"
                    except Exception:
                        driver = None
                if driver is None:
                    compact = _compact_reason(f"{browser_name}: {type(exc).__name__} | {exc}", limit=200)
                    if compact:
                        driver_errors.append(compact)
                    continue

        try:
            raw = magalu_selenium_legacy.coletar(driver, url)
            if not isinstance(raw, dict):
                raise ValueError("Fallback Selenium da Magalu retornou formato invalido.")

            status_base = str(raw.get("status") or "OK")
            browser_note = f" [{_SELENIUM_BROWSER_NAME}]" if _SELENIUM_BROWSER_NAME else ""
            if reason:
                raw["status"] = f"MAGALU - FALLBACK SELENIUM{browser_note} ({reason}): {status_base}"
            else:
                raw["status"] = f"MAGALU - FALLBACK SELENIUM{browser_note}: {status_base}"

            # Se foi bloqueado (403/captcha), tenta o próximo navegador antes de desistir.
            if rotate_on_block and _selenium_status_indicates_block(raw):
                if reset_driver_on_error:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    _SELENIUM_DRIVER = None
                    _SELENIUM_BROWSER_NAME = None
                last_error = status_base
                continue

            _SELENIUM_DISABLED_REASON = None
            return raw
        except Exception as exc:
            last_error = _compact_reason(f"{type(exc).__name__} | {exc}", limit=220)
            if reset_driver_on_error:
                try:
                    driver.quit()
                except Exception:
                    pass
                _SELENIUM_DRIVER = None
                _SELENIUM_BROWSER_NAME = None
            continue

    detail = "; ".join(driver_errors) if driver_errors else (last_error or "nenhum navegador disponivel")
    _SELENIUM_DISABLED_REASON = _compact_reason(detail, limit=320)
    composite_reason = (
        f"{reason} | Selenium indisponivel: {_SELENIUM_DISABLED_REASON}"
        if reason
        else f"Selenium indisponivel: {_SELENIUM_DISABLED_REASON}"
    )
    return _collect_with_http_fallback(url, reason=_compact_reason(composite_reason, limit=260))


def coletar(url: str, headless: bool = False) -> dict:
    """
    Coletor Magalu (Playwright)
    - Pix: somente se explicitamente exibido
    - Avista: total nao-Pix quando disponivel
    - Prazo: texto do parcelamento exibido
    - Ignora preco riscado/antigo
    """

    # Override opcional para evitar instabilidade em headless (ex.: Edge/Chrome em alguns Windows).
    headless = _env_bool("MAGALU_HEADLESS", headless)

    resultado = {
        "a_prazo": None,
        "avista": None,
        "pix": None,
        "prazo": None,
        "status": "INICIAL",
    }

    if not url:
        resultado["status"] = "LINK AUSENTE"
        return resultado

    global _PLAYWRIGHT_DISABLED_REASON
    if _PLAYWRIGHT_DISABLED_REASON:
        return _collect_with_selenium_fallback(url, headless=headless, reason=_PLAYWRIGHT_DISABLED_REASON)
    if sync_playwright is None:
        _PLAYWRIGHT_DISABLED_REASON = _PLAYWRIGHT_IMPORT_ERROR or "Playwright indisponivel"
        return _collect_with_selenium_fallback(url, headless=headless, reason=_PLAYWRIGHT_DISABLED_REASON)

    try:
        with sync_playwright() as p:
            context, browser = _launch_context(p, headless)
            page = context.new_page()

            # Alguns layouts carregam preco via XHR/JSON; capturamos respostas JSON para um fallback de parsing.
            capture_xhr = _env_bool("MAGALU_XHR_CAPTURE", True)
            captured_texts: list[str] = []
            captured_total_chars = 0
            max_total_chars = int(os.getenv("MAGALU_XHR_CAPTURE_MAX_CHARS") or "350000")
            max_response_chars = int(os.getenv("MAGALU_XHR_CAPTURE_MAX_RESPONSE_CHARS") or "120000")

            def on_response(resp) -> None:
                nonlocal captured_total_chars
                if not capture_xhr:
                    return
                if captured_total_chars >= max_total_chars:
                    return
                try:
                    status = int(getattr(resp, "status", 0) or 0)
                except Exception:
                    status = 0
                if status != 200:
                    return
                try:
                    headers = getattr(resp, "headers", {}) or {}
                    content_type = str(headers.get("content-type") or "").lower()
                except Exception:
                    content_type = ""
                if "json" not in content_type:
                    return
                try:
                    raw = resp.text() or ""
                except Exception:
                    return
                if not raw:
                    return
                if len(raw) > max_response_chars:
                    return
                if captured_total_chars + len(raw) > max_total_chars:
                    return
                captured_total_chars += len(raw)
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return
                try:
                    captured_texts.extend(_extract_price_texts_from_json_payload(parsed))
                except Exception:
                    return

            if capture_xhr:
                try:
                    page.on("response", on_response)
                except Exception:
                    pass

            response = page.goto(url, timeout=60000)
            try:
                status_code = int(getattr(response, "status", 0) or 0) if response is not None else 0
            except Exception:
                status_code = 0
            if status_code == 403:
                resultado["status"] = "MAGALU - BLOQUEADO (HTTP 403)"
                _save_debug(page, "http_403")
                context.close()
                if browser is not None:
                    browser.close()
                # Por padrao, NAO tenta outros navegadores: isso aumenta o volume e pode piorar o bloqueio.
                # Ative manualmente se quiser tentar "furar" o rate limit.
                if _env_bool("MAGALU_TRY_SELENIUM_ON_403", False):
                    return _collect_with_selenium_fallback(url, headless=headless, reason="HTTP 403 (Playwright)")
                return resultado

            if _page_looks_blocked_playwright(page):
                resultado["status"] = "MAGALU - BLOQUEADO (PAGINA DE BLOQUEIO)"
                _save_debug(page, "blocked_page")
                context.close()
                if browser is not None:
                    browser.close()
                return resultado

            try:
                page.wait_for_function(
                    """
                    () => {
                        const el = document.querySelector('[data-testid="price-value-integer"]');
                        return el && el.textContent.trim().length > 0;
                    }
                    """,
                    timeout=15000,
                )
            except Exception:
                pass

            try:
                state = _extract_product_state_from_next_data(page.content())
            except Exception:
                state = None

            ignored_prices = extract_struck_prices(page)

            if isinstance(state, dict):
                try:
                    pix_state = extrair_pix(state)
                    if pix_state:
                        resultado["pix"] = pix_state
                except Exception:
                    pass
                try:
                    avista_state = extrair_avista(state)
                    if avista_state:
                        resultado["a_prazo"] = avista_state
                        resultado["avista"] = avista_state
                except Exception:
                    pass
                try:
                    prazo_state = extrair_parcelamento(state)
                    if prazo_state:
                        resultado["prazo"] = prazo_state
                except Exception:
                    pass
                resultado = sanitize_result_prices(resultado, ignored_prices=ignored_prices)

            visible_texts = _collect_visible_dom_texts(page)
            for text in visible_texts:
                if not resultado.get("pix"):
                    resultado["pix"] = extract_pix_from_text(text, ignored_prices=ignored_prices)
                if not resultado.get("avista"):
                    resultado["a_prazo"] = resultado.get("a_prazo") or extract_a_prazo_from_text(
                        text,
                        pix=resultado.get("pix"),
                        ignored_prices=ignored_prices,
                    )
                    resultado["avista"] = resultado["a_prazo"] or extract_avista_from_text(
                        text,
                        pix=resultado.get("pix"),
                        ignored_prices=ignored_prices,
                    )
                if not resultado.get("a_prazo"):
                    resultado["a_prazo"] = extract_a_prazo_from_text(
                        text,
                        pix=resultado.get("pix"),
                        ignored_prices=ignored_prices,
                    )
                if not resultado.get("avista"):
                    resultado["avista"] = extract_avista_from_text(
                        text,
                        pix=resultado.get("pix"),
                        ignored_prices=ignored_prices,
                    )
                if not resultado.get("prazo"):
                    resultado["prazo"] = extract_parcelamento_from_text(
                        text,
                        ignored_prices=ignored_prices,
                    )
                if resultado.get("pix") and resultado.get("prazo") and resultado.get("a_prazo"):
                    break

            # Fallback: tentar extrair precos a partir de JSONs capturados (XHR) durante o carregamento.
            if not (resultado.get("pix") or resultado.get("avista") or resultado.get("a_prazo") or resultado.get("prazo")):
                if captured_texts:
                    payload_text = "\n".join(dict.fromkeys([str(t or "").strip() for t in captured_texts if str(t or "").strip()]))
                    if payload_text:
                        try:
                            if not resultado.get("pix"):
                                resultado["pix"] = extract_pix_from_text(payload_text, ignored_prices=ignored_prices)
                            if not resultado.get("avista"):
                                resultado["a_prazo"] = resultado.get("a_prazo") or extract_a_prazo_from_text(
                                    payload_text,
                                    pix=resultado.get("pix"),
                                    ignored_prices=ignored_prices,
                                )
                                resultado["avista"] = resultado["a_prazo"] or extract_avista_from_text(
                                    payload_text,
                                    pix=resultado.get("pix"),
                                    ignored_prices=ignored_prices,
                                )
                            if not resultado.get("prazo"):
                                resultado["prazo"] = extract_parcelamento_from_text(
                                    payload_text,
                                    ignored_prices=ignored_prices,
                                )
                            resultado = sanitize_result_prices(resultado, ignored_prices=ignored_prices)
                        except Exception:
                            pass

            resultado = sanitize_result_prices(resultado, ignored_prices=ignored_prices)

            try_selenium_on_empty = False
            if resultado["pix"]:
                resultado["status"] = "OK"
            elif resultado["avista"] or resultado["prazo"]:
                resultado["status"] = "MAGALU - PIX REQUER INPUT MANUAL"
            else:
                resultado["status"] = "MAGALU - PRECO NAO DISPONIVEL"
                _save_debug(page, "preco_nao_disponivel")
                # Em alguns cenarios o Playwright abre a pagina mas nao consegue extrair os precos
                # (bloqueio/variacao de layout). Para uso interno, vale tentar Selenium (Edge) como
                # fallback, especialmente quando rodando com navegador visivel.
                try_selenium_on_empty = _env_bool("MAGALU_FALLBACK_SELENIUM_ON_EMPTY", True)

            context.close()
            if browser is not None:
                browser.close()
            if resultado.get("status") == "MAGALU - PRECO NAO DISPONIVEL" and try_selenium_on_empty:
                selenium_out = _collect_with_selenium_fallback(
                    url,
                    headless=headless,
                    reason="Playwright sem preco",
                )
                if isinstance(selenium_out, dict) and (
                    selenium_out.get("pix")
                    or selenium_out.get("avista")
                    or selenium_out.get("a_prazo")
                    or selenium_out.get("prazo")
                ):
                    return selenium_out
                selenium_status = str(selenium_out.get("status") or "").strip() if isinstance(selenium_out, dict) else ""
                if selenium_status:
                    resultado["status"] = f"{resultado['status']} | {selenium_status}"

    except Exception as e:
        reason = _compact_reason(f"{type(e).__name__} | {e}", limit=220) or f"{type(e).__name__} | {e}"
        reason_lower = str(e).lower()
        if _should_disable_playwright_after_error(reason_lower):
            _PLAYWRIGHT_DISABLED_REASON = reason
            return _collect_with_selenium_fallback(url, headless=headless, reason=reason)
        return _collect_with_selenium_fallback(url, headless=headless, reason=reason)

    return resultado
