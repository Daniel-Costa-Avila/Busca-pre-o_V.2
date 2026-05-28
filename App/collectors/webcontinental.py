# collectors/webcontinental.py
from __future__ import annotations

import requests

from App.utils.vtex import (
    VtexError,
    brl_str_from_decimal,
    extract_payment_value_by_name,
    fetch_product_by_slug,
    parse_vtex_base_and_slug,
    pick_avista_from_commercial_offer,
    pick_installment_string_from_offer,
    simulate_checkout,
)


def coletar(driver, link: str | None = None) -> dict:
    """
    Web Continental (VTEX) — NÃO usa Selenium para preço.

    Contrato de retorno (inviolável):
    {
        "avista": str | None,   # preço base (cartão / 1x)
        "pix": str | None,      # preço com desconto Pix/Boleto (checkout)
        "prazo": str | None,    # melhor parcelamento disponível
        "status": str
    }
    """

    if not link:
        return {
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": "LINK AUSENTE",
        }

    session = requests.Session()

    try:
        # 1) Descoberta do produto via VTEX Search API
        base, slug = parse_vtex_base_and_slug(link)
        product = fetch_product_by_slug(base, slug, session=session)
        offer = product.commercial_offer

        # 2) Preço base (cartão / 1x)
        avista_dec = pick_avista_from_commercial_offer(offer)
        avista = brl_str_from_decimal(avista_dec)

        # 3) Parcelamento (calculado sobre o preço base)
        prazo = pick_installment_string_from_offer(offer)

        # 4) Pix / Boleto via Checkout Simulation
        pix = None
        try:
            sim = simulate_checkout(
                base=base,
                sku_id=product.sku_id,
                seller_id=product.seller_id,
                session=session,
            )
            pix_dec = extract_payment_value_by_name(
                sim,
                wanted_keywords=["pix", "boleto"],
            )
            pix = brl_str_from_decimal(pix_dec)
        except VtexError:
            # Pix pode não existir — isso NÃO é erro fatal
            pix = None

        # 5) Validação final (sem inventar dados)
        if avista or pix or prazo:
            return {
                "avista": avista,
                "pix": pix,
                "prazo": prazo,
                "status": "OK",
            }

        return {
            "avista": avista,
            "pix": pix,
            "prazo": prazo,
            "status": "DADO NÃO DISPONÍVEL",
        }

    except VtexError as e:
        return {
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": f"DADO NÃO DISPONÍVEL: {e}",
        }

    except Exception:
        # Nunca deixar exceção subir para o main.py
        return {
            "avista": None,
            "pix": None,
            "prazo": None,
            "status": "ERRO INESPERADO",
        }
