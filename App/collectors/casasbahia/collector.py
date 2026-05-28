from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests


BASE_URLS = {
    "HLG": "https://api-mktplace-hlg.viavarejo.com.br",
    "PRD": "https://api-mktplace.viavarejo.com.br",
}

_SKU_CACHE: dict[str, tuple[float, dict]] = {}


def _normalize_env(value: str | None) -> str:
    raw = (value or "").strip().upper()
    return raw if raw in {"HLG", "PRD"} else "HLG"


def _find_first_numeric_by_keys(obj: Any, keys: tuple[str, ...]) -> Optional[float]:
    if isinstance(obj, dict):
        for key in keys:
            if key in obj:
                try:
                    val = float(obj.get(key))
                except Exception:
                    val = None
                if val is not None and val > 0:
                    return val
        for value in obj.values():
            found = _find_first_numeric_by_keys(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_numeric_by_keys(item, keys)
            if found is not None:
                return found
    return None


def _format_brl(value: float | None) -> Optional[str]:
    if value is None:
        return None
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _extract_price_from_precos(payload: dict) -> Optional[float]:
    sku_block = payload.get("sku")
    if not isinstance(sku_block, dict):
        return None
    precos = sku_block.get("precos")
    if not isinstance(precos, list):
        return None

    def _pick_entry(entries: list[dict]) -> Optional[dict]:
        for entry in entries:
            site = entry.get("site") if isinstance(entry, dict) else None
            sigla = site.get("sigla") if isinstance(site, dict) else None
            if str(sigla).strip().upper() == "CB":
                return entry
        return entries[0] if entries else None

    entry = _pick_entry([p for p in precos if isinstance(p, dict)])
    if not entry:
        return None
    for key in ("por", "price", "sellingPrice", "spotPrice", "value"):
        try:
            val = float(entry.get(key))
        except Exception:
            val = None
        if val is not None and val > 0:
            return val
    return None


def _build_headers() -> dict[str, str]:
    access_token = (os.getenv("CASAS_BAHIA_ACCESS_TOKEN") or "").strip()
    client_id = (os.getenv("CASAS_BAHIA_CLIENT_ID") or "").strip()
    if not access_token or not client_id:
        return {}
    return {
        "access_token": access_token,
        "client_id": client_id,
        "Accept": "application/json",
    }


def _cache_ttl_seconds() -> int:
    raw = (os.getenv("CASAS_BAHIA_CACHE_SECONDS") or "").strip()
    try:
        ttl = int(raw) if raw else 180
    except Exception:
        ttl = 180
    return max(0, min(ttl, 3600))


def _cache_get(key: str) -> Optional[dict]:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return None
    entry = _SKU_CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if time.time() > expires_at:
        _SKU_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: dict) -> None:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return
    _SKU_CACHE[key] = (time.time() + ttl, payload)


def _fetch_product_by_sku(sku: str) -> dict:
    env_name = _normalize_env(os.getenv("CASAS_BAHIA_ENV"))
    base = os.getenv("CASAS_BAHIA_BASE_URL", "").strip() or BASE_URLS[env_name]
    url = f"{base}/api/v4/api-front-products-v4/jersey/product/{sku}"

    headers = _build_headers()
    if not headers:
        raise RuntimeError("Credenciais Casas Bahia nao configuradas.")

    cache_key = f"{env_name}:{sku}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    resp = requests.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    payload = resp.json()
    _cache_set(cache_key, payload)
    return payload


def _parse_bool(raw: str | None) -> Optional[bool]:
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def fetch_skus_paginated(
    page: int = 1,
    page_size: int = 50,
    site: str | None = None,
    status: str | None = None,
    flag_lock: str | None = None,
    titulo: str | None = None,
    marca: str | None = None,
    categoria: str | None = None,
    id_sku_site: str | None = None,
) -> dict:
    """
    Lista paginada de SKUs cadastrados (API de ofertas).
    """
    env_name = _normalize_env(os.getenv("CASAS_BAHIA_ENV"))
    base = os.getenv("CASAS_BAHIA_BASE_URL", "").strip() or BASE_URLS[env_name]
    url = f"{base}/api/v4/api-front-products-v4/jersey/product/"

    headers = _build_headers()
    if not headers:
        raise RuntimeError("Credenciais Casas Bahia nao configuradas.")

    params: dict[str, Any] = {
        "pagina": page,
        "itensPorPagina": page_size,
    }
    if site:
        params["site"] = site
    if status:
        params["status"] = status
    if flag_lock is not None:
        params["flagLock"] = flag_lock
    if titulo:
        params["titulo"] = titulo
    if marca:
        params["marca"] = marca
    if categoria:
        params["categoria"] = categoria
    if id_sku_site:
        params["idSkuSite"] = id_sku_site

    resp = requests.get(url, headers=headers, params=params, timeout=25)
    if resp.status_code not in {200, 204}:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.json() if resp.status_code == 200 else {"valido": True, "conteudo": {"itens": []}}


def list_skus_paginated_from_env() -> dict:
    page = int((os.getenv("CASAS_BAHIA_PAGE") or "1").strip() or 1)
    page_size = int((os.getenv("CASAS_BAHIA_PAGE_SIZE") or "50").strip() or 50)
    site = (os.getenv("CASAS_BAHIA_SITE_FILTER") or "").strip() or None
    status = (os.getenv("CASAS_BAHIA_STATUS_FILTER") or "").strip() or None
    flag_lock_raw = os.getenv("CASAS_BAHIA_FLAGLOCK_FILTER")
    flag_lock = None if flag_lock_raw is None else str(_parse_bool(flag_lock_raw)).lower()
    titulo = (os.getenv("CASAS_BAHIA_TITLE_FILTER") or "").strip() or None
    marca = (os.getenv("CASAS_BAHIA_BRAND_FILTER") or "").strip() or None
    categoria = (os.getenv("CASAS_BAHIA_CATEGORY_FILTER") or "").strip() or None
    id_sku_site = (os.getenv("CASAS_BAHIA_SKUSITE_FILTER") or "").strip() or None
    return fetch_skus_paginated(
        page=page,
        page_size=page_size,
        site=site,
        status=status,
        flag_lock=flag_lock,
        titulo=titulo,
        marca=marca,
        categoria=categoria,
        id_sku_site=id_sku_site,
    )


def coletar(driver: Any, link: str | None = None, sku: Optional[str] = None) -> dict:
    if not sku:
        return {
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": "CASAS BAHIA API: SKU ausente",
        }

    try:
        data = _fetch_product_by_sku(sku)
    except Exception as exc:
        return {
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": f"CASAS BAHIA API: {type(exc).__name__} | {exc}",
        }

    price = _find_first_numeric_by_keys(
        data,
        keys=(
            "spotPrice",
            "cashPrice",
            "bestPrice",
            "price",
            "sellingPrice",
            "value",
            "amount",
        ),
    )
    if price is None:
        price = _extract_price_from_precos(data)
    avista = _format_brl(price)

    status = "OK (API)" if avista else "CASAS BAHIA API: PRECO NAO ENCONTRADO"
    return {
        "avista": avista,
        "pix": avista,
        "prazo": None,
        "status": status,
    }
