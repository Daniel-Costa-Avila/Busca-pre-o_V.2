from __future__ import annotations

import json
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def carregar_pagina(driver: WebDriver, link: str, timeout: int = 20) -> None:
    """Carrega a página da Magalu e aguarda o JSON do Next.js."""
    driver.get(link)
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.ID, "__NEXT_DATA__"))
    )


def extrair_estado_json(driver: WebDriver) -> Optional[dict]:
    """Retorna o nó do produto do __NEXT_DATA__ (bestPrice, payment methods, etc.)."""
    try:
        el = driver.find_element(By.ID, "__NEXT_DATA__")
        raw = el.get_attribute("textContent")
        if not raw:
            return None

        data = json.loads(raw)

        # caminho principal (mais comum)
        product = data.get("props", {}).get("pageProps", {}).get("product")
        if isinstance(product, dict):
            return product

        # fallback alternativo
        product = (
            data.get("props", {})
            .get("pageProps", {})
            .get("pdp", {})
            .get("product")
        )
        if isinstance(product, dict):
            return product

        return None
    except Exception:
        return None
