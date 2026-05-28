from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait


def carregar_pagina(driver: WebDriver, url: str, timeout: int = 20) -> None:
    driver.get(url)

    # Espera estado minimo de carregamento.
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )
    WebDriverWait(driver, timeout).until(
        lambda d: bool(d.find_elements(By.TAG_NAME, "body"))
    )
    time.sleep(0.3)


def detectar_indisponivel(driver: WebDriver, state: dict | None = None) -> bool:
    """
    Mercado Livre:
    considera indisponivel quando JSON indicar quantidade/status invalido,
    e faz fallback best-effort por texto no HTML.
    """
    if isinstance(state, dict):
        try:
            item = state.get("item", {})
            qty = item.get("available_quantity")
            if isinstance(qty, int) and qty <= 0:
                return True
            status = item.get("status")
            if isinstance(status, str) and status.lower() != "active":
                return True
        except Exception:
            pass

    try:
        html = (driver.page_source or "").lower()
        sinais = [
            "produto indisponivel",
            "nao esta disponivel",
            "sem estoque",
            "publicacao finalizada",
        ]
        return any(s in html for s in sinais)
    except Exception:
        return False


def extrair_estado_json(driver: WebDriver) -> Optional[dict[str, Any]]:
    """
    Fonte primaria: window.__PRELOADED_STATE__ / window.__APOLLO_STATE__.
    Fallback: scripts JSON ou script inline contendo estado.
    """
    try:
        state = driver.execute_script("return window.__PRELOADED_STATE__ || null;")
        if isinstance(state, dict) and state:
            return state
    except Exception:
        pass

    try:
        apollo = driver.execute_script("return window.__APOLLO_STATE__ || null;")
        if isinstance(apollo, dict) and apollo:
            return {"__APOLLO_STATE__": apollo}
    except Exception:
        pass

    # JSON scripts.
    try:
        scripts = driver.find_elements(By.CSS_SELECTOR, 'script[type="application/json"], script[type="application/ld+json"]')
        candidatos = sorted(
            ((s.get_attribute("innerHTML") or "").strip() for s in scripts),
            key=len,
            reverse=True,
        )
        for txt in candidatos[:6]:
            if len(txt) < 80:
                continue
            try:
                parsed = json.loads(txt)
                if isinstance(parsed, dict) and parsed:
                    return {"__SCRIPT_JSON__": parsed}
            except Exception:
                continue
    except Exception:
        pass

    # Inline "__PRELOADED_STATE__ = {...};"
    try:
        html = driver.page_source or ""
        match = re.search(r"__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*;", html, flags=re.DOTALL)
        if match:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass

    return None


def extrair_titulo(driver: WebDriver, state: dict[str, Any]) -> Optional[str]:
    try:
        h1 = driver.find_elements(By.CSS_SELECTOR, "h1")
        if h1:
            txt = (h1[0].text or "").strip()
            if txt:
                return txt
    except Exception:
        pass

    return _find_first_str(state, keys=("title", "name", "product_title", "productName"))


def _find_first_str(obj: Any, keys: tuple[str, ...]) -> Optional[str]:
    try:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys and isinstance(v, str) and v.strip():
                    return v.strip()
                found = _find_first_str(v, keys)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = _find_first_str(item, keys)
                if found:
                    return found
    except Exception:
        return None
    return None

