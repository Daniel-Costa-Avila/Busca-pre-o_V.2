def format_br_money(valor):
    """
    Formata float para moeda BR.
    Retorna None se o valor for inválido.
    """
    if valor is None:
        return None

    try:
        s = f"{float(valor):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"
    except Exception:
        return None
