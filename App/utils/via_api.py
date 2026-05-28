# utils/via_api.py
from __future__ import annotations

import requests
from decimal import Decimal
from typing import Optional


MOBILE_HEADERS = {
    "User-Agent": "CasasBahiaApp/7.45.0 (Android)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


class ViaAPIError(Exception):
    pass


def fetch_offers_by_sku(sku: str, session: requests.Session | None = None) -> dict:
    """
    Endpoint típico usado pelo app mobile do grupo Via.
    Pode variar, mas este padrão é comum.
    """
    s = session or requests.Session()
    s.headers.update(MOBILE_HEADERS)

    url = f"https://services.viavarejo.com.br/checkout/price/{sku}"

    resp = s.get(url, timeout=15)
    if resp.status_code != 200:
        raise ViaAPIError(f"HTTP {resp.status_code}")

    return resp.json()
