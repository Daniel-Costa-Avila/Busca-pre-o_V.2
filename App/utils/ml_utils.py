import re

def extrair_item_id_ml(url: str) -> str | None:
    if not url:
        return None

    m = re.search(r"(MLB-?\d+)", url.upper())
    if not m:
        return None

    return m.group(1).replace("-", "")
