from __future__ import annotations
from typing import Optional


def extrair_pix(state: dict) -> Optional[str]:
    """
    Magalu — Pix explícito.
    Se bestPrice.paymentMethodId == 'pix',
    o totalAmount é o preço Pix.
    """

    def walk(node: object) -> Optional[str]:
        if isinstance(node, dict):
            method = str(node.get("paymentMethodId") or node.get("paymentMethod") or "").strip().lower()
            if method == "pix":
                for key in ("totalAmount", "amount", "value", "price"):
                    total = node.get(key)
                    if _is_valid_price(total):
                        return _format_brl(total)
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found:
                    return found
        return None

    found = walk(state)
    if found:
        return found

    return None


def _is_valid_price(v) -> bool:
    return isinstance(v, (int, float)) and 10 <= v <= 200000


def _format_brl(value: float) -> str:
    inteiro = int(value)
    centavos = int(round((value - inteiro) * 100))
    s = f"{inteiro:,}".replace(",", ".")
    return f"R$ {s},{centavos:02d}"
