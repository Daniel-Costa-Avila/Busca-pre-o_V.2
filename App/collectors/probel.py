from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

import requests
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from App.utils.dom_prices import extract_struck_prices
from App.utils.vtex import (
    VtexError,
    brl_str_from_decimal,
    extract_payment_value_by_name,
    fetch_product_by_slug,
    parse_vtex_base_and_slug,
    pick_avista_from_commercial_offer,
    pick_installment_string_from_offer,
    simulate_checkout,
)


MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})")
PIX_RE = re.compile(r"(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*no\s*pix", re.IGNORECASE)
INSTALLMENT_RE = re.compile(
    r"(?P<qty>\d{1,2})\s*[xX\u00D7]\s*de\s*(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))",
    re.IGNORECASE,
)
OU_TOTAL_INSTALLMENT_RE = re.compile(
    r"ou\s*(?P<total>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*"
    r"(?:em\s*(?:ate|at\u00e9)?\s*)?"
    r"(?P<qty>\d{1,2})\s*[xX\u00D7]\s*de\s*"
    r"(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))"
    r"(?:\s*(?P<label>sem juros|com juros))?",
    re.IGNORECASE,
)
AVISTA_PATTERNS = [
    re.compile(
        "(?:a|\\u00e0)\\s*vista[^R$]{0,30}(R\\$\\s?\\d{1,3}(?:\\.\\d{3})*(?:,\\d{2}))",
        re.IGNORECASE,
    ),
    re.compile(
        "(R\\$\\s?\\d{1,3}(?:\\.\\d{3})*(?:,\\d{2}))[^R$]{0,14}(?:a|\\u00e0)\\s*vista",
        re.IGNORECASE,
    ),
]


def _all_money(text: str, ignored_prices: Optional[set[str]] = None) -> list[str]:
    if not text:
        return []
    ignored = ignored_prices or set()
    return [m.group(0).strip() for m in MONEY_RE.finditer(text) if m.group(0).strip() not in ignored]


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _clean_lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in (text or "").splitlines() if line.strip()]


def _money_to_float(price: str) -> float:
    raw = (price or "").replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return 0.0


def _norm(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(normalized.lower().split())


def _is_noise_line(line_norm: str) -> bool:
    if not line_norm:
        return False
    return any(token in line_norm for token in ("economizando", "% off", "desconto", "off", "acumule", "pontos"))


def _extract_primary_scope(text: str, pix_match, bundle_match=None) -> str:
    if not text:
        return ""
    anchor = pix_match or bundle_match
    if anchor is None:
        return text[:5000]
    start = max(0, anchor.start() - 600)
    end = min(len(text), anchor.end() + 1400)
    return text[start:end]


def _extract_pix_price(text: str, ignored_prices: Optional[set[str]] = None) -> Optional[str]:
    if not text:
        return None

    match = PIX_RE.search(text)
    if match and match.group(1).strip() not in (ignored_prices or set()):
        return match.group(1).strip()

    lines = _clean_lines(text)
    for i, line in enumerate(lines):
        lower = _norm(line)
        if "pix" not in lower or _is_noise_line(lower):
            continue

        candidate = MONEY_RE.search(line)
        if candidate and "x de r$" not in lower:
            money = candidate.group(0).strip()
            if money not in (ignored_prices or set()):
                return money

        for j in range(i - 1, max(-1, i - 4), -1):
            prev = lines[j]
            prev_lower = _norm(prev)
            if "x de r$" in prev_lower or "parcela" in prev_lower or _is_noise_line(prev_lower):
                continue
            candidate = MONEY_RE.search(prev)
            if candidate:
                money = candidate.group(0).strip()
                if money not in (ignored_prices or set()):
                    return money

    return None


def _extract_ou_bundle_candidates(
    text: str,
    ignored_prices: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    compact = _compact_text(text)
    if not compact:
        return []

    out: list[dict[str, Any]] = []
    for match in OU_TOTAL_INSTALLMENT_RE.finditer(compact):
        total = match.group("total").strip()
        price = match.group("price").strip()
        try:
            qty = int(match.group("qty").strip())
        except Exception:
            continue

        total_num = _money_to_float(total)
        unit_num = _money_to_float(price)
        installment_total = qty * unit_num
        if total_num <= 0 or unit_num <= 0 or installment_total <= 0 or total in (ignored_prices or set()):
            continue

        label_raw = (match.group("label") or "").lower()
        has_sem = "sem juros" in label_raw
        suffix = " sem juros" if has_sem else (" com juros" if "com juros" in label_raw else "")
        out.append(
            {
                "start": match.start(),
                "total": total,
                "total_num": total_num,
                "delta": abs(installment_total - total_num),
                "has_sem": has_sem,
                "prazo": f"{qty}x de {price}{suffix}",
            }
        )
    return out


def _pick_ou_bundle_candidate(
    candidates: list[dict[str, Any]],
    pix: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if not candidates:
        return None

    pool = list(candidates)
    consistent = [item for item in pool if item["delta"] <= 1.0]
    if consistent:
        pool = consistent

    px = _money_to_float(pix) if pix else 0.0
    if px > 0:
        filtered = [item for item in pool if item["total_num"] >= px and item["total_num"] <= (px * 2.6)]
        if filtered:
            pool = filtered

    return min(
        pool,
        key=lambda item: (
            item["delta"],
            0 if item["has_sem"] else 1,
            item["start"],
        ),
    )


def _extract_ou_bundle(
    text: str,
    pix: Optional[str] = None,
    ignored_prices: Optional[set[str]] = None,
) -> tuple[Optional[str], Optional[str]]:
    best = _pick_ou_bundle_candidate(
        _extract_ou_bundle_candidates(text, ignored_prices=ignored_prices),
        pix=pix,
    )
    if not best:
        return None, None
    return best["total"], best["prazo"]


def _extract_installment_candidates(
    text: str,
    ignored_prices: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    if not text:
        return []

    out: list[dict[str, Any]] = []
    for match in INSTALLMENT_RE.finditer(text):
        price_raw = match.group("price").strip()
        try:
            qty = int(match.group("qty"))
        except Exception:
            continue

        unit_price = _money_to_float(price_raw)
        if qty <= 0 or unit_price <= 0 or price_raw in (ignored_prices or set()):
            continue

        around = text[max(0, match.start() - 28) : min(len(text), match.end() + 36)].lower()
        has_sem = "sem juros" in around
        has_com = (not has_sem) and ("com juros" in around or "juros" in around)
        label = " com juros" if has_com else (" sem juros" if has_sem else "")
        out.append(
            {
                "qty": qty,
                "start": match.start(),
                "total": qty * unit_price,
                "has_sem": has_sem,
                "formatted": f"{qty}x de {price_raw}{label}",
            }
        )
    return out


def _pick_installment_candidate(
    candidates: list[dict[str, Any]],
    reference_value: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    if not candidates:
        return None

    pool = sorted(candidates, key=lambda item: item["start"])
    ref = float(reference_value or 0.0)
    if ref > 0:
        strict = [item for item in pool if 0.85 <= (item["total"] / ref) <= 1.15]
        broad = [item for item in pool if 0.60 <= (item["total"] / ref) <= 2.20]
        filtered = strict or broad
        if filtered:
            return min(
                filtered,
                key=lambda item: (
                    abs((item["total"] / ref) - 1.0),
                    0 if item["has_sem"] else 1,
                    item["start"],
                ),
            )

    early_pool = pool[:12]
    return min(
        early_pool,
        key=lambda item: (
            item["start"],
            0 if item["has_sem"] else 1,
            -item["qty"],
        ),
    )


def _extract_best_installment(
    text: str,
    reference_value: Optional[float] = None,
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    best = _pick_installment_candidate(
        _extract_installment_candidates(text, ignored_prices=ignored_prices),
        reference_value=reference_value,
    )
    return best["formatted"] if best else None


def _extract_avista(
    text: str,
    pix: Optional[str],
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    if not text:
        return None

    compact = _compact_text(text)
    for pattern in AVISTA_PATTERNS:
        match = pattern.search(compact)
        if not match:
            continue
        candidate = match.group(1).strip()
        if candidate in (ignored_prices or set()):
            continue
        if pix and candidate == pix:
            continue
        return candidate

    for line in _clean_lines(text):
        lower = _norm(line)
        if "pix" in lower or _is_noise_line(lower):
            continue
        if "x de r$" in lower or "parcela" in lower or "juros" in lower:
            continue
        if "a vista" not in lower and "avista" not in lower:
            continue
        for candidate in _all_money(line, ignored_prices=ignored_prices):
            if not pix or candidate != pix:
                return candidate

    return None


def _status_from_prices(
    a_prazo: Optional[str],
    avista: Optional[str],
    pix: Optional[str],
    prazo: Optional[str],
) -> str:
    if a_prazo and pix and prazo:
        return "OK"
    if a_prazo and pix and not prazo:
        return "OK (SEM PARCELAMENTO)"
    if pix and not a_prazo:
        return "OK (SOMENTE PIX)"
    if a_prazo and not pix and prazo:
        return "OK (SEM PIX)"
    if avista:
        return "OK (SOMENTE A VISTA)"
    if a_prazo:
        return "OK (SOMENTE A PRAZO)"
    return "DADO NAO DISPONIVEL"


def _collect_from_vtex(link: str) -> Optional[dict]:
    # Probel uses VTEX; this path avoids DOM noise and is usually more stable.
    if "probel.com.br" not in (link or "").lower():
        return None

    session = requests.Session()
    try:
        base, slug = parse_vtex_base_and_slug(link)
        product = fetch_product_by_slug(base, slug, session=session)
        offer = product.commercial_offer

        avista_dec = pick_avista_from_commercial_offer(offer)
        avista = brl_str_from_decimal(avista_dec)
        a_prazo = avista
        prazo = pick_installment_string_from_offer(offer)

        pix = None
        try:
            sim = simulate_checkout(
                base=base,
                sku_id=product.sku_id,
                seller_id=product.seller_id,
                session=session,
            )
            pix_dec = extract_payment_value_by_name(
                sim,
                wanted_keywords=["pix"],
            )
            pix = brl_str_from_decimal(pix_dec)
        except VtexError:
            pix = None

        if not (a_prazo or avista or pix or prazo):
            return None

        return {
            "a_prazo": a_prazo,
            "avista": avista,
            "pix": pix,
            "prazo": prazo,
            "status": _status_from_prices(a_prazo=a_prazo, avista=avista, pix=pix, prazo=prazo),
        }
    except (VtexError, requests.RequestException):
        return None
    except Exception:
        return None


def coletar(driver, link: str | None = None) -> dict:
    if not link:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "LINK AUSENTE"}

    vtex_result = _collect_from_vtex(link)
    if vtex_result:
        return vtex_result

    if driver is None:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "ERRO DE COLETA"}

    try:
        driver.set_page_load_timeout(25)
        driver.get(link)

        wait = WebDriverWait(driver, 15)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except TimeoutException:
            pass

        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass

        ignored_prices = extract_struck_prices(driver)
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        pix = _extract_pix_price(body_text, ignored_prices=ignored_prices)
        pix_match = PIX_RE.search(body_text)
        bundle_match = re.search(
            r"ou\s*R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})",
            body_text,
            flags=re.IGNORECASE,
        )
        primary_scope = _extract_primary_scope(body_text, pix_match, bundle_match)

        a_prazo, prazo_bundle = _extract_ou_bundle(
            primary_scope,
            pix=pix,
            ignored_prices=ignored_prices,
        )
        if not (a_prazo and prazo_bundle):
            a_prazo_fallback, prazo_fallback = _extract_ou_bundle(
                body_text,
                pix=pix,
                ignored_prices=ignored_prices,
            )
            a_prazo = a_prazo or a_prazo_fallback
            prazo_bundle = prazo_bundle or prazo_fallback

        prazo_ref = _money_to_float(a_prazo) if a_prazo else None
        prazo = (
            prazo_bundle
            or _extract_best_installment(
                primary_scope,
                reference_value=prazo_ref,
                ignored_prices=ignored_prices,
            )
            or _extract_best_installment(
                body_text,
                reference_value=prazo_ref or _money_to_float(pix) or None,
                ignored_prices=ignored_prices,
            )
        )
        avista = (
            _extract_avista(primary_scope, pix=pix, ignored_prices=ignored_prices)
            or _extract_avista(body_text, pix=pix, ignored_prices=ignored_prices)
        )

        if pix and avista:
            px = _money_to_float(pix)
            av = _money_to_float(avista)
            if px > 0 and av > 0 and av < px:
                for candidate in _all_money(primary_scope or body_text, ignored_prices=ignored_prices):
                    value = _money_to_float(candidate)
                    if candidate != pix and value >= px and value <= (px * 1.35):
                        avista = candidate
                        break

        status = _status_from_prices(a_prazo=a_prazo, avista=avista, pix=pix, prazo=prazo)

        return {"a_prazo": a_prazo, "avista": avista, "pix": pix, "prazo": prazo, "status": status}

    except WebDriverException:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "ERRO DE COLETA"}
    except Exception:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "ERRO DE COLETA"}
