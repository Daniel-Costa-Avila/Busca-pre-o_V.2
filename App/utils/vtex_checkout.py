import requests

def buscar_precos_checkout(base_url: str, sku_id: str):
    url = f"{base_url}/api/checkout/pub/orderForms/simulation"

    payload = {
        "items": [{
            "id": sku_id,
            "quantity": 1,
            "seller": "1"
        }],
        "country": "BRA"
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    r = requests.post(url, json=payload, headers=headers, timeout=15)
    r.raise_for_status()

    data = r.json()

    items = data.get("items", [])
    if not items:
        return None

    item = items[0]

    price = item.get("price")          # preço base (centavos)
    selling = item.get("sellingPrice") # preço com desconto (centavos)

    installments = item.get("installments", [])

    return {
        "avista": price / 100 if price else None,
        "pix": selling / 100 if selling else None,
        "parcelamento": installments
    }
