from __future__ import annotations

from typing import Any, Optional


def extrair_avista(state: dict) -> Optional[str]:
    """
    Mercado Livre — preço final exibido ao cliente.
    Origem: blocos type="price" com state="VISIBLE".
    """

    price = _find_visible_price_value(state)
    if _is_valid_price(price):
        return _format_brl(price)

    return None


# ---------------- helpers ----------------

def _find_visible_price_value(obj: Any) -> Optional[float]:
    if isinstance(obj, dict):
        # padrão confirmado pelo JSON real
        if (
            obj.get("type") == "price"
            and obj.get("state") == "VISIBLE"
            and isinstance(obj.get("price"), dict)
        ):
            value = obj["price"].get("value")
            if isinstance(value, (int, float)):
                return float(value)

        for v in obj.values():
            found = _find_visible_price_value(v)
            if found is not None:
                return found

    elif isinstance(obj, list):
        for it in obj:
            found = _find_visible_price_value(it)
            if found is not None:
                return found

    return None


def _is_valid_price(v: Any) -> bool:
    return isinstance(v, (int, float)) and 10 <= v <= 200000


def _format_brl(value: float) -> str:
    inteiro = int(value)
    centavos = int(round((value - inteiro) * 100))
    s = f"{inteiro:,}".replace(",", ".")
    return f"R$ {s},{centavos:02d}"
