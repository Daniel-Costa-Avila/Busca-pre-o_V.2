from __future__ import annotations

import re
from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver


def pagina_login_detectada(driver: WebDriver) -> bool:
    """
    Detecta login/challenge do Mercado Livre por URL e sinais de tela.
    """
    try:
        current_url = (driver.current_url or "").lower()
        url_markers = ["login", "autentic", "registration", "challenge", "captcha"]
        if any(marker in current_url for marker in url_markers):
            return True
    except Exception:
        pass

    try:
        html = (driver.page_source or "").lower()
        text_markers = [
            "acesse sua conta",
            "entrar na sua conta",
            "ja tenho conta",
            "sou novo",
            "conta mercado livre",
            "verificacao de seguranca",
            "confirmar identidade",
            "captcha",
        ]
        return any(marker in html for marker in text_markers)
    except Exception:
        return False


def produto_disponivel_dom(driver: WebDriver) -> bool:
    """
    Produto disponivel se existir CTA de compra ativo.
    """
    try:
        botoes_compra = driver.find_elements(
            By.XPATH,
            (
                "//button["
                "contains(., 'Comprar agora') "
                "or contains(., 'Adicionar ao carrinho') "
                "or contains(., 'Comprar')"
                "]"
            ),
        )
        if botoes_compra:
            return True

        avisos_indisponivel = driver.find_elements(
            By.XPATH,
            (
                "//*[contains(., 'Produto indisponivel') "
                "or contains(., 'Publicacao finalizada') "
                "or contains(., 'Avise-me') "
                "or contains(., 'Sem estoque')]"
            ),
        )
        if avisos_indisponivel:
            return False
    except Exception:
        return True

    return True


def extrair_avista_dom(driver: WebDriver) -> Optional[str]:
    """
    Preco principal exibido ao cliente (DOM estruturado + meta tags).
    """
    # Meta tags comuns.
    meta_selectors = [
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
    ]
    for sel in meta_selectors:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                raw = (el.get_attribute("content") or "").strip()
                if not raw:
                    continue
                normalized = _normalize_raw_decimal(raw)
                if normalized:
                    return normalized
        except Exception:
            continue

    # Seletores de preco no bloco principal.
    selectors = [
        '[data-testid="price-part"]',
        '[data-testid="price"]',
        '.ui-pdp-price__second-line',
        '.ui-pdp-price__main-container',
        '.andes-money-amount',
    ]
    for sel in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                txt = (el.text or "").strip()
                parsed = _extract_brl_from_text(txt)
                if parsed:
                    return parsed
        except Exception:
            continue

    # Fallback para fragmentos fracao + centavos.
    try:
        amount_blocks = driver.find_elements(By.CSS_SELECTOR, ".andes-money-amount")
        for block in amount_blocks:
            frac_nodes = block.find_elements(By.CSS_SELECTOR, ".andes-money-amount__fraction")
            if not frac_nodes:
                continue
            frac = re.sub(r"[^\d]", "", frac_nodes[0].text or "")
            if not frac:
                continue
            cents_nodes = block.find_elements(By.CSS_SELECTOR, ".andes-money-amount__cents")
            cents = re.sub(r"[^\d]", "", cents_nodes[0].text or "") if cents_nodes else "00"
            cents = (cents + "00")[:2]
            inteiro = f"{int(frac):,}".replace(",", ".")
            return f"R$ {inteiro},{cents}"
    except Exception:
        pass

    return None


def extrair_parcelamento_dom(driver: WebDriver) -> Optional[str]:
    """
    Parcelamento exibido ao cliente.
    """
    selectors = [
        '[data-testid="installments"]',
        '.ui-pdp-installments',
        '.ui-pdp-price__subtitles',
        '.ui-pdp-price__subtitles-container',
    ]
    pattern = re.compile(r"(\d+\s*x\s*de\s*R\$\s*[\d\.]+,\d{2}(?:\s*sem juros)?)", re.IGNORECASE)

    for sel in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in elements:
                txt = " ".join((el.text or "").split())
                match = pattern.search(txt)
                if match:
                    return " ".join(match.group(1).split())
        except Exception:
            continue

    return None


def extrair_seller_dom(driver: WebDriver) -> Optional[str]:
    """
    Identifica o seller ativo exibido ao cliente.
    """
    try:
        elements = driver.find_elements(
            By.XPATH,
            (
                "//*[contains(text(), 'Vendido por') "
                "or contains(text(), 'Vendido e entregue por')]"
            ),
        )
        for el in elements:
            txt = " ".join((el.text or "").split())
            lower = txt.lower()
            if "vendido" not in lower:
                continue
            parts = re.split(r"\bpor\b", txt, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                seller = parts[1].strip(" :-")
                if seller:
                    return seller
    except Exception:
        pass

    return None


def _extract_brl_from_text(txt: str) -> Optional[str]:
    if not txt:
        return None
    match = re.search(r"R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}", txt)
    if match:
        return _normalize_brl(match.group(0))

    # Fallback quando o "R$" nao aparece no texto do container.
    match = re.search(r"\d{1,3}(?:\.\d{3})*,\d{2}", txt)
    if match:
        return _normalize_brl(match.group(0))
    return None


def _normalize_brl(raw: str) -> Optional[str]:
    match = re.search(r"\d{1,3}(?:\.\d{3})*,\d{2}", raw or "")
    if not match:
        return None
    value = match.group(0)
    return f"R$ {value}"


def _normalize_raw_decimal(raw: str) -> Optional[str]:
    value = (raw or "").strip()
    if not value:
        return None

    # Ex.: "1234.56" -> "R$ 1.234,56"
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
        number = float(value)
        inteiro = int(number)
        cents = int(round((number - inteiro) * 100))
        return f"R$ {inteiro:,}".replace(",", ".") + f",{cents:02d}"

    return _normalize_brl(value)

