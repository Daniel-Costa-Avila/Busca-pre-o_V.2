from __future__ import annotations
from typing import Optional


def extrair_parcelamento(state: dict) -> Optional[str]:
    """
    Magalu — parcelamento REAL exibido ao cliente.
    Compatível com o schema novo baseado em métodos de pagamento.
    """

    # 1️⃣ Caso mais comum — bloco direto de installment
    inst = state.get("installment")
    if isinstance(inst, dict):
        q = inst.get("quantity")
        v = inst.get("amount") or inst.get("value")
        if _valid_installment(q, v):
            return f"{q}x de {_format_brl(v)}"

    # 2️⃣ Lista de parcelamentos por método de pagamento
    installments = state.get("installments")
    if isinstance(installments, list):
        for inst in installments:
            if not isinstance(inst, dict):
                continue

            # ignorar Pix
            if inst.get("paymentMethodId") == "pix":
                continue

            q = inst.get("quantity")
            v = inst.get("amount") or inst.get("value")
            if _valid_installment(q, v):
                return f"{q}x de {_format_brl(v)}"

    # 3️⃣ Fallback legado (casos raros)
    legacy = state.get("price", {}).get("installments")
    if isinstance(legacy, dict):
        q = legacy.get("quantity")
        v = legacy.get("value")
        if _valid_installment(q, v):
            return f"{q}x de {_format_brl(v)}"

    return None


# ---------------- helpers ----------------

def _valid_installment(q, v) -> bool:
    return isinstance(q, int) and isinstance(v, (int, float)) and q > 1 and v >= 10


def _format_brl(value: float) -> str:
    inteiro = int(value)
    centavos = int(round((value - inteiro) * 100))
    s = f"{inteiro:,}".replace(",", ".")
    return f"R$ {s},{centavos:02d}"
