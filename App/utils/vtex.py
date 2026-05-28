# utils/vtex.py
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional
from urllib.parse import urlparse

import requests


@dataclass
class VtexProduct:
    slug: str
    sku_id: str
    seller_id: str
    commercial_offer: dict[str, Any]  # commertialOffer
    raw: dict[str, Any]               # payload inteiro do produto (1o resultado)


class VtexError(Exception):
    """Erros internos do helper VTEX (não deixar subir pro main)."""


def _timeout() -> tuple[float, float]:
    return (8.0, 20.0)  # connect, read


def _to_brl(value: Decimal | int | float | str | None) -> Optional[str]:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except Exception:
        return None
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # formata 1234.56 -> "R$ 1.234,56"
    s = f"{d:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _to_reais_from_cents(cents: int | str | None) -> Optional[Decimal]:
    if cents is None:
        return None
    try:
        c = Decimal(str(cents))
        return (c / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


def parse_vtex_base_and_slug(product_url: str) -> tuple[str, str]:
    """
    Ex:
      https://www.webcontinental.com.br/produto-x-y/p -> base=https://www.webcontinental.com.br, slug=produto-x-y
      https://www.webcontinental.com.br/produto-x-y/p?skuId=123 -> slug=produto-x-y
    """
    u = urlparse(product_url)
    if not u.scheme or not u.netloc:
        raise VtexError("URL inválida.")

    base = f"{u.scheme}://{u.netloc}"
    path = (u.path or "").strip("/")

    # padrão VTEX comum: /<slug>/p
    m = re.match(r"^(?P<slug>.+?)/p/?$", path)
    if m:
        return base, m.group("slug")

    # fallback: pega o primeiro segmento como slug (menos confiável, mas útil)
    parts = [p for p in path.split("/") if p]
    if parts:
        return base, parts[0]

    raise VtexError("Não consegui extrair slug da URL.")


def fetch_product_by_slug(base: str, slug: str, session: Optional[requests.Session] = None) -> VtexProduct:
    """
    Endpoint clássico VTEX:
      GET {base}/api/catalog_system/pub/products/search/{slug}/p
    """
    s = session or requests.Session()
    url = f"{base}/api/catalog_system/pub/products/search/{slug}/p"
    r = s.get(url, timeout=_timeout(), headers={"accept": "application/json"})
    if r.status_code != 200:
        raise VtexError(f"VTEX search falhou (HTTP {r.status_code}).")

    data = r.json()
    if not isinstance(data, list) or not data:
        raise VtexError("Produto não encontrado na VTEX (search retornou vazio).")

    prod = data[0]

    # tenta achar 1o SKU/Item e 1o Seller
    items = prod.get("items") or []
    if not items:
        raise VtexError("Produto sem itens/SKU (items vazio).")

    item0 = items[0]
    sku_id = str(item0.get("itemId") or "").strip()
    if not sku_id:
        raise VtexError("SKU (itemId) não disponível.")

    sellers = item0.get("sellers") or []
    if not sellers:
        raise VtexError("Sem sellers no SKU.")

    seller0 = sellers[0]
    seller_id = str(seller0.get("sellerId") or "1").strip() or "1"

    offer = (seller0.get("commertialOffer") or {})  # (sim, VTEX escreve assim)
    if not offer:
        raise VtexError("commertialOffer não disponível.")

    return VtexProduct(
        slug=slug,
        sku_id=sku_id,
        seller_id=seller_id,
        commercial_offer=offer,
        raw=prod,
    )


def pick_avista_from_commercial_offer(offer: dict[str, Any]) -> Optional[Decimal]:
    """
    Regras práticas:
      - Price costuma ser o preço atual (promocional) na vitrine.
      - PriceWithoutDiscount pode aparecer em alguns casos (nem sempre).
      - Se Price existir, preferimos Price.
    """
    price = offer.get("Price")
    if price is None:
        return None
    try:
        return Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


def pick_installment_string_from_offer(offer: dict[str, Any]) -> Optional[str]:
    """
    offer["Installments"] geralmente vem com:
      [{"NumberOfInstallments": 10, "Value": 123.45, "InterestRate": 0, "TotalValuePlusInterestRate": ...}, ...]
    A gente escolhe o maior N e monta uma frase padrão.
    """
    inst = offer.get("Installments")
    if not isinstance(inst, list) or not inst:
        return None

    # maior número de parcelas
    best = None
    for it in inst:
        try:
            n = int(it.get("NumberOfInstallments") or 0)
            v = Decimal(str(it.get("Value")))
            ir = Decimal(str(it.get("InterestRate") or "0"))
        except Exception:
            continue
        rank = (n, 1 if ir > 0 else 0, v)
        if best is None or rank > best[0]:
            best = (rank, n, v, ir)

    if not best:
        return None

    _, n, v, ir = best
    v_brl = _to_brl(v)
    if not v_brl:
        return None
    if ir == 0:
        return f"{n}x de {v_brl} sem juros"
    return f"{n}x de {v_brl} (com juros)"


def simulate_checkout(
    base: str,
    sku_id: str,
    seller_id: str = "1",
    quantity: int = 1,
    postal_code: str = "01001000",  # default SP (apenas pra simulação)
    country: str = "BRA",
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    """
    Simulação de checkout (mais confiável pra preço por meio de pagamento):
      POST {base}/api/checkout/pub/orderForms/simulation

    Retorna JSON com paymentData.installmentOptions etc.
    """
    s = session or requests.Session()
    url = f"{base}/api/checkout/pub/orderForms/simulation"

    payload = {
        "items": [
            {
                "id": str(sku_id),
                "quantity": int(quantity),
                "seller": str(seller_id),
            }
        ],
        "country": country,
        "postalCode": postal_code,
    }

    r = s.post(url, json=payload, timeout=_timeout(), headers={"accept": "application/json"})
    if r.status_code != 200:
        raise VtexError(f"Checkout simulation falhou (HTTP {r.status_code}).")
    data = r.json()
    if not isinstance(data, dict):
        raise VtexError("Simulation retornou payload inválido.")
    return data


def extract_payment_value_by_name(sim: dict[str, Any], wanted_keywords: list[str]) -> Optional[Decimal]:
    """
    Procura em paymentData.installmentOptions algo como "Pix", "Boleto", etc.
    Tenta extrair o menor valor 'à vista' daquele método.
    """
    pd = sim.get("paymentData") or {}
    options = pd.get("installmentOptions") or []
    if not isinstance(options, list):
        return None

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())

    wanted = [norm(k) for k in wanted_keywords]

    best_value = None

    for opt in options:
        name = norm(str(opt.get("paymentName") or opt.get("paymentSystemName") or ""))
        if not name:
            continue
        if not any(k in name for k in wanted):
            continue

        # opt.installments: lista com (count, value, total)
        insts = opt.get("installments") or []
        if not isinstance(insts, list) or not insts:
            continue

        # pega a menor parcela (geralmente 1x)
        for ins in insts:
            v = _to_reais_from_cents(ins.get("value"))
            if v is None:
                continue
            if best_value is None or v < best_value:
                best_value = v

    return best_value


def brl_str_from_decimal(d: Optional[Decimal]) -> Optional[str]:
    return _to_brl(d)
