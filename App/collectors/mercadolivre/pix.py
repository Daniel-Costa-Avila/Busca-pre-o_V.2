from __future__ import annotations

from typing import Any, Optional


def extrair_pix(state: dict) -> Optional[str]:
    """
    Mercado Livre — PIX.
    Retorna SOMENTE se:
    - payment_method = pix
    - valor final estiver materializado no JSON
    """

    # 1) components.price.props.payment_methods
    try:
        methods = (
            state.get("components", {})
            .get("price", {})
            .get("props", {})
            .get("payment_methods", [])
        )
        for m in methods:
            if m.get("id") == "pix" and _is_valid_price(m.get("amount")):
                return _format_brl(m["amount"])
    except Exception:
        pass

    # 2) fallback profundo
    return _fallback_pix(state)


# ---------------- helpers ----------------

def _fallback_pix(obj: Any) -> Optional[str]:
    amounts: list[float] = []

    def walk(o: Any):
        if isinstance(o, dict):
            pm = o.get("payment_method_id") or o.get("paymentMethodId")
            if isinstance(pm, str) and pm.lower() == "pix":
                for k in ("amount", "value", "total", "final_amount"):
                    v = o.get(k)
                    if _is_valid_price(v):
                        amounts.append(float(v))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    walk(obj)

    if not amounts:
        return None

    return _format_brl(min(amounts))


def _is_valid_price(v: Any) -> bool:
    return isinstance(v, (int, float)) and 10 <= v <= 200000


def _format_brl(value: float) -> str:
    inteiro = int(value)
    centavos = int(round((value - inteiro) * 100))
    s = f"{inteiro:,}".replace(",", ".")
    return f"R$ {s},{centavos:02d}"
