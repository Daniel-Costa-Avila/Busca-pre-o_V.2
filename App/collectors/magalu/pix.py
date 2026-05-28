from __future__ import annotations
from typing import Optional


def extrair_pix(state: dict) -> Optional[str]:
    """
    Magalu — Pix explícito.
    Se bestPrice.paymentMethodId == 'pix',
    o totalAmount é o preço Pix.
    """

    bp = state.get("bestPrice")
    if isinstance(bp, dict):
        if bp.get("paymentMethodId") == "pix":
            total = bp.get("totalAmount")
            if _is_valid_price(total):
                return _format_brl(total)

    return None


def _is_valid_price(v) -> bool:
    return isinstance(v, (int, float)) and 10 <= v <= 200000


def _format_brl(value: float) -> str:
    inteiro = int(value)
    centavos = int(round((value - inteiro) * 100))
    s = f"{inteiro:,}".replace(",", ".")
    return f"R$ {s},{centavos:02d}"
