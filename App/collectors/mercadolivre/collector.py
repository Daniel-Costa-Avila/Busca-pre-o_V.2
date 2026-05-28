from __future__ import annotations

from typing import Any, Optional

from App.utils.mercadolivre_api import MercadoLivreAPI

from . import dom


def coletar(driver: Any, link: str, sku: Optional[str] = None) -> dict:
    """
    Coletor Hibrido para Mercado Livre.
    1. Tenta usar a API oficial (se configurada).
    2. Se falhar, usa o coletor DOM (Selenium) como fallback.
    """
    # --- Estrategia 1: API First ---
    api = MercadoLivreAPI()
    mlb_id = None
    id_source = None

    # Estrategia de ID: 1. SKU (id no Canal), 2. Link
    if sku and isinstance(sku, str) and sku.strip().upper().startswith("MLB"):
        mlb_id = sku.strip()
        id_source = "SKU"
    elif link:
        mlb_id = api.extract_mlb_from_url(link)
        if mlb_id:
            id_source = "Link"

    if mlb_id and api.is_configured():
        print(f"ML API: Buscando ID '{mlb_id}' (fonte: {id_source})...")
        item_data = api.get_item(mlb_id)
        if item_data:
            price = api.parse_price(item_data)
            status = item_data.get("status", "unknown")

            return {
                "avista": price,
                "pix": price,  # Na API do ML, o preco principal e unico.
                "prazo": None,  # A API publica de itens nao fornece parcelamento.
                "status": f"OK (API) - {status}",
            }
        else:
            # A API esta configurada, mas falhou. Avisa e segue para o fallback.
            print(f"ML API: Falha ao buscar {mlb_id}. Usando fallback DOM.")

    # --- Estrategia 2: Fallback para DOM (Selenium) ---
    if not link:
        return {
            "avista": None, "pix": None, "prazo": None,
            "status": "ERRO: API falhou e nao ha link para fallback via DOM."
        }

    if not driver:
        return {
            "avista": None, "pix": None, "prazo": None,
            "status": "ERRO: Coletor DOM requer um driver Selenium, mas nenhum foi fornecido."
        }

    try:
        # A navegacao e necessaria aqui para garantir que a pagina correta seja raspada.
        driver.get(link)
        if dom.pagina_login_detectada(driver):
            return {
                "avista": None, "pix": None, "prazo": None,
                "status": "ERRO (DOM): Pagina de login/captcha detectada."
            }

        avista = dom.extrair_avista_dom(driver)
        prazo = dom.extrair_parcelamento_dom(driver)

        status = "OK (DOM)"
        if not avista and not prazo:
            status = "ERRO (DOM): Preco nao encontrado."

        return {
            "avista": avista,
            "pix": avista,  # No DOM, o preco a vista e o principal.
            "prazo": prazo,
            "status": status,
        }
    except Exception as e:
        return {
            "avista": None, "pix": None, "prazo": None,
            "status": f"ERRO (DOM): {type(e).__name__}"
        }