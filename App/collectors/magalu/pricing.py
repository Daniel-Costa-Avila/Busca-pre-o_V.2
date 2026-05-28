from __future__ import annotations
from typing import Optional


def extrair_avista(state: dict) -> Optional[str]:
    """
    Magalu — preço à vista REAL exibido ao cliente.
    Quando o preço vem por método de pagamento (ex: Pix),
    usamos bestPrice.totalAmount.
    """

    bp = state.get("bestPrice")
    if isinstance(bp, dict):
        # Evita confundir valor de Pix com "a vista" geral.
        payment_method = str(bp.get("paymentMethodId") or "").strip().lower()
        if payment_method == "pix":
            return None
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
