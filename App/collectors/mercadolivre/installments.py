from __future__ import annotations

from typing import Any, Optional, Tuple


def extrair_parcelamento(state: dict) -> Optional[str]:
    """
    Mercado Livre — parcelamento exibido ao cliente.
    Origem: subtitles.values.price_installments
    """

    inst = _find_installment_from_subtitle(state)
    if inst:
        qty, amount = inst
        return f"{qty}x de {_format_brl(amount)}"

    return None


# ---------------- helpers ----------------

def _find_installment_from_subtitle(obj: Any) -> Optional[Tuple[int, float]]:
    if isinstance(obj, dict):
        subtitles = obj.get("subtitles")
        if isinstance(subtitles, list):
            for sub in subtitles:
                if isinstance(sub, dict):
                    text = sub.get("text", "")
                    values = sub.get("values", {})
                    if "x" in text and "price_installments" in values:
                        price_inst = values["price_installments"]
                        if isinstance(price_inst, dict):
                            amount = price_inst.get("value")
                            if isinstance(amount, (int, float)):
                                qty = _extract_qty_from_text(text)
                                if qty:
                                    return qty, float(amount)

        for v in obj.values():
            found = _find_installment_from_subtitle(v)
            if found:
                return found

    elif isinstance(obj, list):
        for it in obj:
            found = _find_installment_from_subtitle(it)
            if found:
                return found

    return None


def _extract_qty_from_text(text: str) -> Optional[int]:
    try:
        # exemplo: "5x {price_installments} sem juros"
        part = text.split("x")[0].strip()
        return int(part)
    except Exception:
        return None


def _format_brl(value: float) -> str:
    inteiro = int(value)
    centavos = int(round((value - inteiro) * 100))
    s = f"{inteiro:,}".replace(",", ".")
    return f"R$ {s},{centavos:02d}"
