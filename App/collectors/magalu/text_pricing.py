from __future__ import annotations

import re
import unicodedata
from typing import Optional


PRICE_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})")
PIX_PATTERNS = (
    re.compile(r"(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*(?:no|via)\s*pix", re.IGNORECASE),
    re.compile(r"pix\s*(?:de|por)?\s*(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))", re.IGNORECASE),
)
AVISTA_PATTERNS = (
    re.compile(r"a\s*vista\s*(?:de|por)?\s*(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))", re.IGNORECASE),
    re.compile(r"(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*a\s*vista", re.IGNORECASE),
    re.compile(r"ou\s*(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))", re.IGNORECASE),
)
PARCELA_RE = re.compile(
    r"(\d{1,2})\s*x\s*de\s*(R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})(?:\s*(?:sem|com)\s*juros)?)",
    re.IGNORECASE,
)


def _normalize_ascii(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _compact(text: str) -> str:
    return " ".join(str(text or "").split())


def _clean_lines(text: str) -> list[str]:
    return [_compact(line) for line in str(text or "").splitlines() if line.strip()]


def _normalize_price(candidate: str | None) -> str | None:
    if not candidate:
        return None
    match = PRICE_RE.search(candidate)
    if not match:
        return None
    return _compact(match.group(0))


def _money_to_float(candidate: str | None) -> float:
    normalized = _normalize_price(candidate)
    if not normalized:
        return 0.0
    raw = normalized.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return 0.0


def _format_brl(value: float) -> str:
    inteiro = int(value)
    centavos = int(round((value - inteiro) * 100))
    inteiro_str = f"{inteiro:,}".replace(",", ".")
    return f"R$ {inteiro_str},{centavos:02d}"


def _is_ignored(candidate: str | None, ignored_prices: Optional[set[str]] = None) -> bool:
    if not candidate:
        return False
    return candidate in (ignored_prices or set())


def sanitize_result_prices(result: dict, ignored_prices: Optional[set[str]] = None) -> dict:
    out = dict(result or {})
    ignored = ignored_prices or set()
    if not ignored:
        return out

    for key in ("pix", "avista"):
        candidate = _normalize_price(out.get(key))
        if candidate and candidate in ignored:
            out[key] = None

    prazo = str(out.get("prazo") or "").strip()
    if prazo:
        candidate = _normalize_price(prazo)
        if candidate and candidate in ignored:
            out["prazo"] = None

    return out


def extract_pix_from_text(text: str, ignored_prices: Optional[set[str]] = None) -> Optional[str]:
    if not text:
        return None

    compact_ascii = _normalize_ascii(_compact(text))
    for pattern in PIX_PATTERNS:
        match = pattern.search(compact_ascii)
        if not match:
            continue
        candidate = _normalize_price(match.group(1))
        if candidate and not _is_ignored(candidate, ignored_prices):
            return candidate

    lines = [_normalize_ascii(line) for line in _clean_lines(text)]
    for i, line in enumerate(lines):
        lower = line.lower()
        if "pix" not in lower or "x de r$" in lower:
            continue

        for match in PRICE_RE.finditer(line):
            candidate = _normalize_price(match.group(0))
            if candidate and not _is_ignored(candidate, ignored_prices):
                return candidate

        for j in range(i - 1, max(-1, i - 4), -1):
            prev = lines[j]
            prev_lower = prev.lower()
            if "x de r$" in prev_lower or "parcela" in prev_lower or "juros" in prev_lower:
                continue
            candidate = _normalize_price(prev)
            if candidate and not _is_ignored(candidate, ignored_prices):
                return candidate

    return None


def extract_avista_from_text(
    text: str,
    pix: Optional[str] = None,
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    if not text:
        return None

    compact_ascii = _normalize_ascii(_compact(text))
    for pattern in AVISTA_PATTERNS:
        match = pattern.search(compact_ascii)
        if not match:
            continue
        candidate = _normalize_price(match.group(1))
        if not candidate or _is_ignored(candidate, ignored_prices):
            continue
        if pix and candidate == pix:
            continue
        return candidate

    for line in [_normalize_ascii(line) for line in _clean_lines(text)]:
        lower = line.lower()
        if "pix" in lower:
            continue
        if "a vista" not in lower and "ou " not in lower:
            continue
        if "x de r$" in lower or "parcela" in lower:
            continue
        candidate = _normalize_price(line)
        if not candidate or _is_ignored(candidate, ignored_prices):
            continue
        if pix and candidate == pix:
            continue
        return candidate

    return None


def extract_parcelamento_from_text(
    text: str,
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    if not text:
        return None

    compact_ascii = _normalize_ascii(_compact(text))
    best: tuple[int, int, int, str] | None = None
    for match in PARCELA_RE.finditer(compact_ascii):
        formatted = _compact(match.group(0))
        price_component = _normalize_price(match.group(2))
        if price_component and _is_ignored(price_component, ignored_prices):
            continue
        try:
            qty = int(match.group(1))
        except Exception:
            qty = 0
        has_sem = "sem juros" in formatted.lower()
        rank = (0 if has_sem else 1, -qty, match.start(), formatted)
        if best is None or rank < best:
            best = rank

    return best[3] if best else None


def extract_a_prazo_from_text(
    text: str,
    pix: Optional[str] = None,
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    if text:
        compact_ascii = _normalize_ascii(_compact(text))
        for pattern in AVISTA_PATTERNS:
            match = pattern.search(compact_ascii)
            if not match:
                continue
            candidate = _normalize_price(match.group(1))
            if not candidate:
                continue
            if pix and candidate == pix:
                continue
            return candidate

    parcelamento = extract_parcelamento_from_text(text, ignored_prices=ignored_prices)
    if not parcelamento:
        return None

    match = PARCELA_RE.search(parcelamento)
    if not match:
        return None

    try:
        qty = int(match.group(1))
    except Exception:
        return None

    unit_price = _money_to_float(match.group(2))
    if qty <= 0 or unit_price <= 0:
        return None

    total = _format_brl(qty * unit_price)
    pix_value = _money_to_float(pix)
    total_value = _money_to_float(total)
    if pix_value > 0 and total_value > 0 and total_value < pix_value:
        return None

    return total
