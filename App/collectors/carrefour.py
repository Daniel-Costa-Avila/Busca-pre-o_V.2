from __future__ import annotations

import html
import json
import re
from typing import Any, Optional

import requests


MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})")
PIX_RE = re.compile(
    r"(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*(?:à|a)\s+vista\s+no\s+pix",
    re.IGNORECASE,
)
TOTAL_INSTALLMENT_RE = re.compile(
    r"ou\s*(?P<total>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*em\s*(?:até|ate)?\s*"
    r"(?P<qty>\d{1,2})\s*[xX]\s*de\s*(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))"
    r"(?:\s*(?P<label>sem juros|com juros))?",
    re.IGNORECASE,
)
CARD_CARREFOUR_RE = re.compile(
    r"(?P<qty>\d{1,2})\s*[xX]\s*de\s*(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))"
    r"(?:\s*(?P<label>sem juros|com juros))?\s+no\s+cart[aã]o\s+carrefour",
    re.IGNORECASE,
)


def _format_brl(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = MONEY_RE.search(value)
        if match:
            return match.group(0).strip()
        raw = value.strip()
        if not raw:
            return None
        try:
            value = float(raw.replace(".", "").replace(",", "."))
        except Exception:
            return None
    try:
        number = float(value)
    except Exception:
        return None
    if number <= 0:
        return None
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _money_to_float(price: str | None) -> float:
    raw = str(price or "").replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return 0.0


def _extract_meta_content(page_source: str, field: str) -> Optional[str]:
    pattern = rf'<meta[^>]+(?:property|name)=["\']{re.escape(field)}["\'][^>]+content=["\']([^"\']+)["\']'
    match = re.search(pattern, page_source, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


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


def _extract_from_jsonld(page_source: str) -> Optional[str]:
    matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for raw_json in matches:
        try:
            payload = json.loads(raw_json.strip())
        except Exception:
            continue
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            formatted = _extract_offer_price(node.get("offers"))
            if formatted:
                return formatted
    return None


def _pick_total_installment(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Retorna (total, prazo) a partir do trecho "ou R$ X em ate Nx de R$ Y".
    Prioriza a primeira ocorrencia (normalmente a exibida como opcao principal).
    """
    for match in TOTAL_INSTALLMENT_RE.finditer(text):
        total = match.group("total").strip()
        qty = match.group("qty").strip()
        price = match.group("price").strip()
        label_raw = (match.group("label") or "").strip().lower()
        label = f" {label_raw}" if label_raw else ""
        prazo = f"{qty}x de {price}{label}"
        return total, prazo
    return None, None


def _html_to_text(page_source: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", page_source, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def coletar(driver, link: str | None = None) -> dict:
    if not link:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "LINK AUSENTE"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        response = requests.get(link, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        return {
            "a_prazo": None,
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": f"ERRO DE COLETA: {type(exc).__name__}",
        }

    page_source = response.text or ""
    body_text = _html_to_text(page_source)

    pix = None
    avista = None
    a_prazo = None
    prazo = None

    pix_match = PIX_RE.search(body_text)
    if pix_match:
        pix = pix_match.group("price").strip()
        avista = pix

    a_prazo, prazo = _pick_total_installment(body_text)

    if not prazo:
        card_match = CARD_CARREFOUR_RE.search(body_text)
        if card_match:
            label_raw = (card_match.group("label") or "").strip().lower()
            label = f" {label_raw}" if label_raw else ""
            prazo = f"{card_match.group('qty')}x de {card_match.group('price').strip()}{label} no Cartao Carrefour"

    avista_candidate = _extract_from_jsonld(page_source)
    if not avista_candidate:
        for key in ("product:price:amount", "og:price:amount", "price"):
            avista_candidate = _format_brl(_extract_meta_content(page_source, key))
            if avista_candidate:
                break

    if pix:
        avista = pix
    elif avista_candidate:
        if pix and _money_to_float(avista_candidate) < _money_to_float(pix):
            avista_candidate = None
        avista = avista_candidate or avista

    if a_prazo and pix and prazo:
        status = "OK"
    elif a_prazo and pix:
        status = "OK (SEM PARCELAMENTO)"
    elif a_prazo:
        status = "OK (SOMENTE A PRAZO)"
    elif pix:
        status = "OK (SOMENTE PIX)"
    else:
        status = "DADO NAO DISPONIVEL"

    return {
        "a_prazo": a_prazo,
        "avista": avista,
        "pix": pix,
        "prazo": prazo,
        "status": status,
    }
