# collectors/zema.py
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


DEBUG_DIR = Path("debug_zema")
MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})")
INSTALLMENT_RE = re.compile(
    r"(?P<qty>\d{1,2})\s*[xX\u00D7]\s*de\s*(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))",
    re.IGNORECASE,
)
OU_PRAZO_PRICE_RE = re.compile(
    r"ou\s*(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*em\s*(?:ate|até)?\s*\d{1,2}\s*[xX\u00D7]",
    re.IGNORECASE,
)
INSTALLMENT_RATIO_STRICT_MIN = 0.70
INSTALLMENT_RATIO_STRICT_MAX = 1.80
INSTALLMENT_RATIO_BROAD_MIN = 0.55
INSTALLMENT_RATIO_BROAD_MAX = 2.20
BLOCKED_MARKERS = (
    "captcha",
    "access denied",
    "acesso negado",
    "challenge",
    "cloudflare",
    "suspicious-traffic-frontend",
    "account-verification",
    "mercado livre",
    "mercadolivre.com.br",
)


def _normalize_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().strip()
    except Exception:
        return ""


def _is_zema_host(host: str) -> bool:
    h = (host or "").lower().strip()
    return h == "zema.com" or h.endswith(".zema.com")


def _first_money(text: str) -> Optional[str]:
    if not text:
        return None
    m = MONEY_RE.search(text)
    return m.group(0).strip() if m else None


def _to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        n = float(value)
        return n if n > 0 else None
    raw = str(value).strip()
    if not raw:
        return None
    cleaned = raw.replace("R$", "").replace(" ", "")
    if "." in cleaned and "," in cleaned:
        # Formato BR com milhares e decimal (ex: 1.234,56).
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        # Formato BR sem milhares (ex: 1234,56).
        cleaned = cleaned.replace(",", ".")
    # Se vier apenas com ponto, assume decimal padrao (ex: 1234.56).
    try:
        n = float(cleaned)
    except Exception:
        return None
    return n if n > 0 else None


def _format_brl(value: Any) -> Optional[str]:
    n = _to_number(value)
    if n is None:
        return None
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _money_to_float(price: str) -> float:
    raw = (price or "").replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return 0.0


def _extract_installment_candidates(text: str) -> list[dict[str, Any]]:
    if not text:
        return []

    out: list[dict[str, Any]] = []
    for match in INSTALLMENT_RE.finditer(text):
        qty_raw = match.group("qty")
        price_raw = match.group("price").strip()
        try:
            qty = int(qty_raw)
        except Exception:
            continue

        unit_price = _money_to_float(price_raw)
        if qty <= 0 or unit_price <= 0:
            continue

        around = text[max(0, match.start() - 28) : min(len(text), match.end() + 36)].lower()
        has_sem = "sem juros" in around
        has_com = (not has_sem) and ("com juros" in around or "juros" in around)
        label = " com juros" if has_com else (" sem juros" if has_sem else "")
        formatted = f"{qty}x de {price_raw}{label}"

        out.append(
            {
                "qty": qty,
                "unit_price": unit_price,
                "total": qty * unit_price,
                "has_sem": has_sem,
                "has_com": has_com,
                "start": match.start(),
                "formatted": formatted,
            }
        )
    return out


def _pick_installment_candidate(
    candidates: list[dict[str, Any]], reference_value: Optional[float] = None
) -> Optional[dict[str, Any]]:
    if not candidates:
        return None

    candidates = sorted(candidates, key=lambda c: c["start"])
    ref = float(reference_value or 0.0)
    if ref > 0:
        strict = [
            c
            for c in candidates
            if INSTALLMENT_RATIO_STRICT_MIN <= (c["total"] / ref) <= INSTALLMENT_RATIO_STRICT_MAX
        ]
        broad = [
            c
            for c in candidates
            if INSTALLMENT_RATIO_BROAD_MIN <= (c["total"] / ref) <= INSTALLMENT_RATIO_BROAD_MAX
        ]
        pool = strict or broad
        if pool:
            return min(
                pool,
                key=lambda c: (
                    abs((c["total"] / ref) - 1.0),
                    0 if c["has_sem"] else 1,
                    -c["qty"],
                    c["start"],
                ),
            )

    # Sem referencia confiavel: usa ocorrencias iniciais (geralmente bloco principal do produto).
    early_pool = candidates[:12]
    return min(
        early_pool,
        key=lambda c: (
            c["start"],
            0 if c["has_sem"] else 1,
            -c["qty"],
        ),
    )


def _extract_best_installment(text: str, reference_value: Optional[float] = None) -> Optional[str]:
    candidate = _pick_installment_candidate(
        _extract_installment_candidates(text),
        reference_value=reference_value,
    )
    return candidate["formatted"] if candidate else None


def _installment_total(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    m = INSTALLMENT_RE.search(str(value))
    if not m:
        return None
    try:
        qty = int(m.group("qty"))
    except Exception:
        return None
    unit_price = _money_to_float(m.group("price"))
    if qty <= 0 or unit_price <= 0:
        return None
    return qty * unit_price


def _extract_pix_price(text: str) -> Optional[str]:
    if not text:
        return None

    patterns = [
        r"(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*(?:no|via)?\s*pix",
        r"pix\s*(?:por|de)?\s*(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Caso comum na Zema: preco em uma linha e "OFF no PIX" na linha seguinte.
    lines = _clean_lines(text)
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if "pix" not in line_lower:
            continue

        # 1) tenta extrair no proprio texto da linha
        candidate = _first_money(line)
        if candidate and "x de r$" not in line_lower:
            return candidate

        # 2) busca nas linhas anteriores mais proximas (ignora parcelamento)
        for j in range(i - 1, max(-1, i - 4), -1):
            prev = lines[j]
            prev_lower = prev.lower()
            if "x de r$" in prev_lower or "parcela" in prev_lower:
                continue
            candidate = _first_money(prev)
            if candidate:
                return candidate
    return None


def _extract_ou_price_for_installment(text: str) -> Optional[str]:
    if not text:
        return None
    m = OU_PRAZO_PRICE_RE.search(text)
    if m:
        return m.group(1).strip()
    m = re.search(r"ou\s*(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _extract_meta_content(page_source: str, field: str) -> Optional[str]:
    escaped = re.escape(field)
    patterns = [
        rf'<meta[^>]+(?:property|itemprop)=["\']{escaped}["\'][^>]*content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|itemprop)=["\']{escaped}["\']',
    ]
    for pattern in patterns:
        m = re.search(pattern, page_source, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _extract_from_meta(page_source: str) -> Optional[str]:
    for key in ("product:price:amount", "og:price:amount", "price"):
        content = _extract_meta_content(page_source, key)
        if content:
            formatted = _format_brl(content)
            if formatted:
                return formatted
    return None


def _iter_nodes(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_nodes(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_nodes(item)


def _extract_offer_price(offers: Any) -> Optional[str]:
    if isinstance(offers, dict):
        for key in ("price", "lowPrice", "highPrice"):
            formatted = _format_brl(offers.get(key))
            if formatted:
                return formatted
    elif isinstance(offers, list):
        for item in offers:
            formatted = _extract_offer_price(item)
            if formatted:
                return formatted
    return None


def _is_product_node(node: dict[str, Any]) -> bool:
    raw_type = node.get("@type")
    if isinstance(raw_type, list):
        values = [str(v).lower() for v in raw_type]
    else:
        values = [str(raw_type).lower()]
    if any("product" in v for v in values):
        return True
    return "offers" in node and ("name" in node or "sku" in node)


def _extract_from_jsonld(page_source: str) -> dict:
    out = {"avista": None}
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_source,
        flags=re.DOTALL | re.IGNORECASE,
    )

    for raw in scripts:
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for node in _iter_nodes(data):
            if not isinstance(node, dict) or not _is_product_node(node):
                continue
            formatted = _extract_offer_price(node.get("offers"))
            if formatted:
                out["avista"] = formatted
                return out
    return out


def _find_first_numeric_by_keys(obj: Any, keys: tuple[str, ...]) -> Optional[str]:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                formatted = _format_brl(obj.get(key))
                if formatted:
                    return formatted
        for value in obj.values():
            found = _find_first_numeric_by_keys(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_numeric_by_keys(item, keys)
            if found:
                return found
    return None


def _extract_from_next_data(page_source: str) -> dict:
    out = {"avista": None}
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page_source,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return out

    try:
        data = json.loads(m.group(1))
        out["avista"] = _find_first_numeric_by_keys(
            data,
            keys=(
                "price",
                "salePrice",
                "sellingPrice",
                "spotPrice",
                "cashPrice",
                "bestPrice",
                "currentPrice",
                "value",
                "amount",
            ),
        )
    except Exception:
        pass

    return out


def _clean_lines(text: str) -> list[str]:
    if not text:
        return []
    return [ln.strip() for ln in text.splitlines() if ln and ln.strip()]


def _money_around_index(lines: list[str], idx: int, window: int = 2) -> Optional[str]:
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    for pos in range(start, end):
        line_lower = lines[pos].lower()
        if "x de r$" in line_lower:
            continue
        money = _first_money(lines[pos])
        if money:
            return money
    return None


def _extract_from_body_context(
    body_text: str, reference_value: Optional[float] = None
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    lines = _clean_lines(body_text)
    if not lines:
        return None, None, None

    relevant_idx: set[int] = set()
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(token in line_lower for token in ("pix", "a vista", "avista", "parcel", "x de r$", "juros")):
            for j in range(i - 2, i + 3):
                if 0 <= j < len(lines):
                    relevant_idx.add(j)

    if relevant_idx:
        scope_lines = [lines[i] for i in sorted(relevant_idx)]
    else:
        scope_lines = lines[:220]
    scope_text = "\n".join(scope_lines)

    pix = _extract_pix_price(scope_text)

    # Prioriza explicitamente "ou R$ ... em ate Nx" (padrao do card de produto da Zema).
    avista = _extract_ou_price_for_installment(scope_text)
    for i, line in enumerate(scope_lines):
        if avista:
            break
        line_lower = line.lower()
        if "x de r$" in line_lower:
            continue
        if ("a vista" in line_lower or "avista" in line_lower) and "pix" not in line_lower:
            candidate = _first_money(line) or _money_around_index(scope_lines, i)
            if candidate and candidate != pix:
                avista = candidate
                break

    if not avista:
        for line in scope_lines:
            line_lower = line.lower()
            if "x de r$" in line_lower or "pix" in line_lower:
                continue
            candidate = _first_money(line)
            if candidate and candidate != pix:
                avista = candidate
                break

    body_ref = _money_to_float(avista) or _money_to_float(pix)
    effective_ref = body_ref or (float(reference_value) if reference_value else None)
    prazo = _extract_best_installment(scope_text, reference_value=effective_ref)

    return avista, pix, prazo


def _extract_avista_from_dom(driver) -> Optional[str]:
    selectors = [
        '[data-testid*="price"]',
        ".vtex-product-price-1-x-sellingPriceValue",
        ".vtex-product-price-1-x-currencyContainer",
        ".product-price",
        ".price",
    ]
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        for element in elements[:6]:
            text = " ".join((element.text or "").split())
            if not text:
                continue
            if "x de r$" in text.lower():
                continue
            money = _first_money(text)
            if money:
                return money
    return None


def _looks_blocked_or_wrong_page(current_url: str, page_source: str, body_text: str) -> Optional[str]:
    haystack = " ".join(
        [
            (current_url or "")[:4000],
            (page_source or "")[:20000],
            (body_text or "")[:20000],
        ]
    ).lower()
    for marker in BLOCKED_MARKERS:
        if marker in haystack:
            return "BLOQUEIO/CHALLENGE"
    return None


def _is_404_page(page_source: str) -> bool:
    if not page_source:
        return False
    # Caso simples: sinal direto no HTML (quando nao esta ofuscado).
    if 'pageType":"404"' in page_source or "pageType\":\"404\"" in page_source:
        return True

    # Caso comum na Zema: window.state = JSON.parse(decodeURI("..."))
    try:
        m = re.search(
            r'window\.state\s*=\s*JSON\.parse\(decodeURI\("([^"]+)"\)\)',
            page_source,
            flags=re.IGNORECASE,
        )
        if not m:
            return False
        decoded = unquote(m.group(1))
        return '"pageType":"404"' in decoded or '"route":"/404"' in decoded
    except Exception:
        return False


def _alternate_links(link: str, current_url: str | None = None) -> list[str]:
    seeds = [link]
    if current_url and current_url not in seeds:
        seeds.append(current_url)

    out: list[str] = []
    for raw in seeds:
        try:
            parsed = urlparse(raw)
        except Exception:
            continue
        path = unquote(parsed.path or "")
        if not path:
            continue

        base_path = path.rstrip("/")
        segments = base_path.split("/")
        last = segments[-1] if segments else ""
        if last.lower().endswith("zema") and len(last) > 4:
            new_last = last[:-4]
            new_path = "/".join(segments[:-1] + [new_last])
            alt = parsed._replace(path=quote(new_path, safe="/")).geturl()
            out.append(alt)

        # Tenta com/sem barra final
        if not path.endswith("/"):
            out.append(parsed._replace(path=parsed.path + "/").geturl())
        else:
            out.append(parsed._replace(path=parsed.path.rstrip("/")).geturl())

    # remove duplicados preservando ordem
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        if item and item not in seen and item != link:
            seen.add(item)
            unique.append(item)
    return unique


def _save_debug(driver, page_source: str, status: str, link: str, current_url: str) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    page_path = DEBUG_DIR / f"page_{stamp}.html"
    meta_path = DEBUG_DIR / f"meta_{stamp}.txt"
    shot_path = DEBUG_DIR / f"shot_{stamp}.png"

    page_path.write_text(page_source or "", encoding="utf-8", errors="ignore")
    meta_path.write_text(
        "\n".join(
            [
                f"status={status}",
                f"link={link}",
                f"current_url={current_url}",
                f"timestamp={stamp}",
            ]
        ),
        encoding="utf-8",
        errors="ignore",
    )
    try:
        driver.save_screenshot(str(shot_path))
    except Exception:
        pass


def coletar(driver, link: str | None = None) -> dict:
    if not link:
        return {"avista": None, "pix": None, "prazo": None, "status": "LINK AUSENTE"}

    if driver is None:
        return {"avista": None, "pix": None, "prazo": None, "status": "DADO NAO CONFIAVEL"}

    try:
        driver.set_page_load_timeout(60)
        last_nav_error: Exception | None = None
        for attempt in range(2):
            try:
                driver.get(link)
                last_nav_error = None
                break
            except TimeoutException as exc:
                # Timeout de renderer: tenta continuar com o DOM parcial.
                last_nav_error = exc
                break
            except WebDriverException as exc:
                last_nav_error = exc
                if attempt >= 1:
                    raise
                time.sleep(1.0)
        if last_nav_error is not None:
            raise last_nav_error

        wait = WebDriverWait(driver, 12)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except TimeoutException:
            pass

        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.25)
            driver.execute_script("window.scrollTo(0, 0);")
        except Exception:
            pass

        current_url = str(getattr(driver, "current_url", "") or "")
        current_host = _normalize_host(current_url)
        if not _is_zema_host(current_host):
            page = driver.page_source or ""
            status = f"ZEMA - DOMINIO INESPERADO: {current_host or '-'}"
            _save_debug(driver, page, status, link, current_url)
            return {"avista": None, "pix": None, "prazo": None, "status": status}

        page = driver.page_source or ""
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception:
            body_text = ""

        blocked_reason = _looks_blocked_or_wrong_page(current_url, page, body_text)
        if blocked_reason:
            status = f"ZEMA - {blocked_reason}"
            _save_debug(driver, page, status, link, current_url)
            return {"avista": None, "pix": None, "prazo": None, "status": status}

        if _is_404_page(page):
            # Tentativa extra: normaliza URLs comuns que mudam na Zema.
            recovered = False
            for alt in _alternate_links(link, current_url=current_url):
                try:
                    driver.get(alt)
                except Exception:
                    continue
                try:
                    wait = WebDriverWait(driver, 12)
                    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                except TimeoutException:
                    pass

                current_url = str(getattr(driver, "current_url", "") or "")
                current_host = _normalize_host(current_url)
                if not _is_zema_host(current_host):
                    continue

                page = driver.page_source or ""
                try:
                    body_text = driver.find_element(By.TAG_NAME, "body").text or ""
                except Exception:
                    body_text = ""

                blocked_reason = _looks_blocked_or_wrong_page(current_url, page, body_text)
                if blocked_reason:
                    status = f"ZEMA - {blocked_reason}"
                    _save_debug(driver, page, status, alt, current_url)
                    return {"avista": None, "pix": None, "prazo": None, "status": status}

                if not _is_404_page(page):
                    recovered = True
                    break

            if not recovered:
                status = "ZEMA - PRODUTO NAO ENCONTRADO (404)"
                _save_debug(driver, page, status, link, current_url)
                return {"avista": None, "pix": None, "prazo": None, "status": status}

        meta_avista = (
            _extract_from_meta(page)
            or _extract_from_jsonld(page).get("avista")
            or _extract_from_next_data(page).get("avista")
        )

        meta_ref = _money_to_float(meta_avista)
        body_avista, pix, prazo = _extract_from_body_context(
            body_text,
            reference_value=meta_ref if meta_ref > 0 else None,
        )

        # Dados visiveis no corpo do produto tem prioridade sobre metadados.
        avista = body_avista or meta_avista
        if not avista:
            avista = _extract_avista_from_dom(driver)
        if not pix:
            pix = _extract_pix_price(body_text)

        price_ref = _money_to_float(avista) or _money_to_float(pix)
        if not prazo:
            prazo = _extract_best_installment(body_text, reference_value=price_ref if price_ref > 0 else None)

        if prazo and price_ref > 0:
            prazo_total = _installment_total(prazo)
            if prazo_total is None:
                prazo = None
            else:
                ratio = prazo_total / price_ref
                if ratio < INSTALLMENT_RATIO_STRICT_MIN or ratio > INSTALLMENT_RATIO_STRICT_MAX:
                    repaired = _extract_best_installment(body_text, reference_value=price_ref)
                    repaired_total = _installment_total(repaired)
                    if repaired_total is None:
                        prazo = None
                    else:
                        repaired_ratio = repaired_total / price_ref
                        prazo = (
                            repaired
                            if INSTALLMENT_RATIO_STRICT_MIN
                            <= repaired_ratio
                            <= INSTALLMENT_RATIO_STRICT_MAX
                            else None
                        )

        if avista and pix:
            av = _money_to_float(avista)
            px = _money_to_float(pix)
            if av > 0 and px > (av * 1.08):
                # Indicativo de captura fora de contexto: invalida o pix.
                pix = None

        if avista and pix and prazo:
            status = "OK"
        elif avista and pix and not prazo:
            status = "OK (SEM PARCELAMENTO)"
        elif avista and not pix and prazo:
            status = "OK (SEM PIX)"
        elif avista and not pix and not prazo:
            status = "OK (SOMENTE A VISTA)"
        else:
            status = "DADO NAO CONFIAVEL"

        if not status.startswith("OK"):
            _save_debug(driver, page, status, link, current_url)

        return {
            "avista": avista,
            "pix": pix,
            "prazo": prazo,
            "status": status,
        }

    except WebDriverException as exc:
        return {
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": f"ERRO DE COLETA: {type(exc).__name__} | {exc}",
        }
    except Exception as exc:
        return {
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": f"ERRO DE COLETA: {type(exc).__name__} | {exc}",
        }
