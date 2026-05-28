from __future__ import annotations

from urllib.parse import urlsplit


def _extract_host(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""

    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        host = urlsplit(candidate).netloc.lower().strip()
    except Exception:
        return ""

    if host.startswith("www."):
        host = host[4:]
    return host


def is_mercadolivre_url(url: str) -> bool:
    """
    Detecta links do ecossistema Mercado Livre de forma mais ampla:
    - mercadolivre.* (PT-BR)
    - mercadolibre.* (outros paises)
    - meli.* (encurtadores/redirects)
    """
    raw = (url or "").strip().lower()
    if not raw:
        return False

    host = _extract_host(raw)
    haystack = host or raw

    return (
        "mercadolivre." in haystack
        or "mercadolibre." in haystack
        or "meli." in haystack
    )
