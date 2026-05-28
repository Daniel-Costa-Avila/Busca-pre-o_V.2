# collectors/madeiramadeira.py
from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any, Optional

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from App.utils.dom_prices import extract_struck_prices


_MONEY_RE = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})")
_INSTALLMENT_RE = re.compile(
    r"(?P<qty>\d{1,2})\s*[xX\u00D7]\s*de\s*(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))",
    re.IGNORECASE,
)
_OU_TOTAL_INSTALLMENT_RE = re.compile(
    r"ou\s*(?P<total>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))\s*"
    r"(?:em\s*(?:ate|at\u00e9)?\s*)?"
    r"(?P<qty>\d{1,2})\s*[xX\u00D7]\s*de\s*"
    r"(?P<price>R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2}))"
    r"(?:\s*(?P<label>sem juros|com juros))?",
    re.IGNORECASE,
)


def _first_money(text: str) -> Optional[str]:
    if not text:
        return None
    m = _MONEY_RE.search(text)
    return m.group(0).strip() if m else None


def _all_money(text: str, ignored_prices: Optional[set[str]] = None) -> list[str]:
    if not text:
        return []
    ignored = ignored_prices or set()
    return [m.group(0).strip() for m in _MONEY_RE.finditer(text) if m.group(0).strip() not in ignored]


def _money_to_float(price: str) -> float:
    raw = (price or "").replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return 0.0


def _format_brl(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        match = _MONEY_RE.search(value)
        if match:
            return match.group(0).strip()
        raw = value.strip()
        if not raw:
            return None
        try:
            value = float(raw.replace(".", "").replace(",", "."))
        except Exception:
            return None
    try:
        number = float(value)
    except Exception:
        return None
    if number <= 0:
        return None
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.lower().split())


def _extract_meta_content(page_source: str, field: str) -> Optional[str]:
    if not page_source:
        return None
    pattern = rf'<meta[^>]+(?:property|name)=["\']{re.escape(field)}["\'][^>]+content=["\']([^"\']+)["\']'
    match = re.search(pattern, page_source, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()


def _extract_from_meta(page_source: str) -> Optional[str]:
    for key in ("product:price:amount", "og:price:amount", "price"):
        content = _extract_meta_content(page_source, key)
        formatted = _format_brl(content)
        if formatted:
            return formatted
    return None


def _extract_offer_price(offers: Any) -> Optional[str]:
    if isinstance(offers, dict):
        for key in ("price", "lowPrice", "highPrice"):
            formatted = _format_brl(offers.get(key))
            if formatted:
                return formatted
    elif isinstance(offers, list):
        for item in offers:
            formatted = _extract_offer_price(item)
            if formatted:
                return formatted
    return None


def _extract_from_jsonld(page_source: str) -> dict[str, Optional[str]]:
    result = {"a_prazo": None, "avista": None}
    if not page_source:
        return result

    for raw_json in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_source,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            payload = json.loads(raw_json.strip())
        except Exception:
            continue

        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            formatted = _extract_offer_price(node.get("offers"))
            if formatted:
                result["a_prazo"] = result["a_prazo"] or formatted
                result["avista"] = result["avista"] or formatted
                return result
    return result


def _walk_price_candidates(node: Any) -> list[float]:
    found: list[float] = []
    if isinstance(node, dict):
        for key, value in node.items():
            key_norm = _norm(str(key))
            if key_norm in {
                "price",
                "saleprice",
                "sellingprice",
                "spotprice",
                "cashprice",
                "bestprice",
                "currentprice",
                "fullprice",
                "promotionalprice",
                "pricevalue",
            }:
                try:
                    num = float(value)
                    if num > 0:
                        found.append(num)
                except Exception:
                    formatted = _format_brl(value)
                    if formatted:
                        found.append(_money_to_float(formatted))
            found.extend(_walk_price_candidates(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_price_candidates(item))
    return found


def _extract_from_next_data(page_source: str) -> dict[str, Optional[str]]:
    result = {"a_prazo": None, "avista": None}
    if not page_source:
        return result

    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page_source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return result

    try:
        payload = json.loads(match.group(1))
    except Exception:
        return result

    prices = [price for price in _walk_price_candidates(payload) if price > 0]
    if not prices:
        return result

    best_price = min(prices)
    formatted = _format_brl(best_price)
    result["a_prazo"] = formatted
    result["avista"] = formatted
    return result


def _clean_lines(body_text: str) -> list[str]:
    return [ln.strip() for ln in body_text.splitlines() if ln.strip()]


def _is_noise_line(line_norm: str) -> bool:
    if not line_norm:
        return False
    return any(token in line_norm for token in ("economizando", "% off", "desconto", "acumule", "pontos"))


def _money_around_index(
    lines: list[str],
    idx: int,
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    for pos in (idx, idx - 1, idx + 1):
        if pos < 0 or pos >= len(lines):
            continue
        line_norm = _norm(lines[pos])
        if "x de r$" in line_norm or _is_noise_line(line_norm):
            continue
        money = _first_money(lines[pos])
        if money and money not in (ignored_prices or set()):
            return money
    return None


def _find_pix_avista_from_lines(
    body_text: str,
    ignored_prices: Optional[set[str]] = None,
) -> tuple[Optional[str], Optional[str]]:
    lines = _clean_lines(body_text)
    avista = None
    pix = None

    for i, ln in enumerate(lines):
        ln_norm = _norm(ln)
        if "x de r$" in ln_norm or _is_noise_line(ln_norm):
            continue

        has_pix = "pix" in ln_norm
        has_avista = ("a vista" in ln_norm) or ("avista" in ln_norm)

        if has_pix and not pix:
            pix = _money_around_index(lines, i, ignored_prices=ignored_prices) or pix

        if has_avista and (not has_pix) and not avista:
            candidate = _money_around_index(lines, i, ignored_prices=ignored_prices)
            if candidate and candidate != pix:
                avista = candidate

    if not avista:
        for ln in lines:
            ln_norm = _norm(ln)
            if "x de r$" in ln_norm or _is_noise_line(ln_norm):
                continue
            if "pix" in ln_norm:
                continue
            candidate = _first_money(ln)
            if candidate and candidate != pix and candidate not in (ignored_prices or set()):
                avista = candidate
                break

    return avista, pix


def _extract_ou_bundle(
    text: str,
    pix: Optional[str] = None,
    ignored_prices: Optional[set[str]] = None,
) -> tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None

    compact = re.sub(r"\s+", " ", text).strip()
    best: tuple[tuple[float, int], tuple[str, str]] | None = None
    pix_num = _money_to_float(pix) if pix else 0.0

    for match in _OU_TOTAL_INSTALLMENT_RE.finditer(compact):
        total = match.group("total").strip()
        price = match.group("price").strip()
        if total in (ignored_prices or set()):
            continue

        try:
            qty = int(match.group("qty"))
        except Exception:
            continue

        total_num = _money_to_float(total)
        unit_num = _money_to_float(price)
        delta = abs((qty * unit_num) - total_num)
        if total_num <= 0 or unit_num <= 0:
            continue
        if pix_num > 0 and total_num < pix_num:
            continue

        label_raw = (match.group("label") or "").lower()
        suffix = " sem juros" if "sem juros" in label_raw else (" com juros" if "com juros" in label_raw else "")
        formatted = f"{qty}x de {price}{suffix}"
        rank = (delta, match.start())
        if best is None or rank < best[0]:
            best = (rank, (total, formatted))

    if not best:
        return None, None
    return best[1]


def _extract_best_installment(
    text: str,
    reference_value: Optional[float] = None,
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    if not text:
        return None

    best: tuple[tuple[float, int, int], str] | None = None
    ref = float(reference_value or 0.0)
    for match in _INSTALLMENT_RE.finditer(text):
        qty_raw = match.group("qty")
        price_raw = match.group("price").strip()
        if price_raw in (ignored_prices or set()):
            continue
        try:
            qty = int(qty_raw)
        except Exception:
            continue

        total_num = qty * _money_to_float(price_raw)
        if total_num <= 0:
            continue
        around = text[max(0, match.start() - 24) : min(len(text), match.end() + 32)].lower()
        has_sem = "sem juros" in around
        has_com = ("com juros" in around) or ("juros" in around and not has_sem)
        interest_rank = 0 if has_sem else (2 if has_com else 1)
        ratio_delta = abs((total_num / ref) - 1.0) if ref > 0 else 0.0

        # Com referencia, prioriza o parcelamento cujo total bate com o valor a prazo.
        rank = (ratio_delta, interest_rank, -qty) if ref > 0 else (0.0, interest_rank, -qty)
        label = " com juros" if has_com else (" sem juros" if has_sem else "")
        formatted = f"{qty}x de {price_raw}{label}"

        if best is None or rank < best[0]:
            best = (rank, formatted)

    return best[1] if best else None


def _is_checked(value: str | None) -> bool:
    return _norm(value or "") == "true"


def _is_probel_seller_line(line: str) -> bool:
    n = _norm(line)
    if "probel" not in n:
        return False
    if "vendido e entregue por" in n:
        return True
    return ("vendido por" in n) and ("entregue por" in n)


def _find_probel_context(lines: list[str]) -> Optional[list[str]]:
    for i, line in enumerate(lines):
        if _is_probel_seller_line(line):
            return lines[i : min(len(lines), i + 70)]

    # fallback para layout em duas linhas:
    # linha N = "Vendido e entregue por", linha N+1 = "Probel"
    for i in range(0, len(lines) - 1):
        cur = _norm(lines[i])
        nxt = _norm(lines[i + 1])
        if ("vendido e entregue por" in cur) and ("probel" in nxt):
            return lines[i : min(len(lines), i + 70)]

    return None


def _best_money_from_lines(
    lines: list[str],
    ignored_prices: Optional[set[str]] = None,
) -> Optional[str]:
    if not lines:
        return None

    # Prioriza valor "limpo": sem percentual e sem linha de parcelamento.
    for ln in lines:
        n = _norm(ln)
        if "%" in ln or _is_noise_line(n):
            continue
        if "x de r$" in n:
            continue
        money = _first_money(ln)
        if money and money not in (ignored_prices or set()):
            return money

    # Fallback final: qualquer dinheiro fora de parcelamento.
    for ln in lines:
        n = _norm(ln)
        if "x de r$" in n or _is_noise_line(n):
            continue
        money = _first_money(ln)
        if money and money not in (ignored_prices or set()):
            return money

    return None


def _extract_display_prices_from_body(
    body_text: str,
    ignored_prices: Optional[set[str]] = None,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    avista, pix = _find_pix_avista_from_lines(body_text, ignored_prices=ignored_prices)
    a_prazo, prazo_bundle = _extract_ou_bundle(body_text, pix=pix, ignored_prices=ignored_prices)
    ref_value = _money_to_float(a_prazo) if a_prazo else (_money_to_float(avista) or _money_to_float(pix) or None)
    prazo = prazo_bundle or _extract_best_installment(
        body_text,
        reference_value=ref_value,
        ignored_prices=ignored_prices,
    )

    if not avista:
        non_pix_lines = [ln for ln in _clean_lines(body_text) if "pix" not in _norm(ln)]
        avista = _best_money_from_lines(non_pix_lines, ignored_prices=ignored_prices)

    if pix and avista:
        px = _money_to_float(pix)
        av = _money_to_float(avista)
        if px > 0 and av > 0 and av < px:
            avista = None

    return a_prazo, avista, pix, prazo


def _extract_probel_prices_from_body(
    body_text: str,
    ignored_prices: Optional[set[str]] = None,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[list[str]]]:
    all_lines = _clean_lines(body_text)
    probel_context = _find_probel_context(all_lines)
    if not probel_context:
        return None, None, None, None, None

    context_text = "\n".join(probel_context)
    a_prazo, avista, pix, prazo = _extract_display_prices_from_body(
        context_text,
        ignored_prices=ignored_prices,
    )

    if not avista:
        non_pix_context = [ln for ln in probel_context if "pix" not in _norm(ln)]
        avista = _best_money_from_lines(non_pix_context, ignored_prices=ignored_prices)

    return a_prazo, avista, pix, prazo, probel_context


def _get_offer_labels(driver) -> list[str]:
    try:
        labels = driver.find_elements(By.XPATH, "//div[@role='radiogroup']//label")
    except Exception:
        return []

    out: list[str] = []
    for label in labels:
        text = " ".join((label.text or "").split())
        if text:
            out.append(text)
    return out


def _select_probel_offer(driver) -> tuple[bool, bool, Optional[str]]:
    """
    Procura a opcao de marketplace da PROBEL no radiogroup e tenta seleciona-la.
    Retorna:
    - se encontrou opcao PROBEL
    - se conseguiu deixar a opcao marcada
    - texto da oferta PROBEL (label)
    """
    labels = driver.find_elements(By.XPATH, "//div[@role='radiogroup']//label")
    for label in labels:
        label_text = " ".join((label.text or "").split())
        if "probel" not in _norm(label_text):
            continue

        checked = False
        radio = None
        radio_id = None

        try:
            radio = label.find_element(
                By.XPATH,
                "./preceding-sibling::button[@role='radio'][1]",
            )
            radio_id = radio.get_attribute("id")
            checked = _is_checked(radio.get_attribute("aria-checked"))
        except Exception:
            radio = None

        if not checked:
            try:
                # JS click evita bloqueio por overlay/tooltip flutuante.
                driver.execute_script("arguments[0].click();", radio or label)
            except Exception:
                try:
                    (radio or label).click()
                except Exception:
                    pass

            if radio_id:
                try:
                    WebDriverWait(driver, 6).until(
                        lambda d: _is_checked(
                            d.find_element(By.ID, radio_id).get_attribute("aria-checked")
                        )
                    )
                except Exception:
                    pass

            try:
                if radio_id:
                    checked = _is_checked(
                        driver.find_element(By.ID, radio_id).get_attribute("aria-checked")
                    )
                elif radio is not None:
                    checked = _is_checked(radio.get_attribute("aria-checked"))
                else:
                    checked = True
            except Exception:
                checked = False

        return True, checked, label_text

    return False, False, None


def coletar(driver, link: str | None = None) -> dict:
    if not link:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "LINK AUSENTE"}

    if driver is None:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "ERRO DE COLETA"}

    try:
        driver.set_page_load_timeout(25)
        last_nav_error: Exception | None = None
        for attempt in range(2):
            try:
                driver.get(link)
                last_nav_error = None
                break
            except WebDriverException as exc:
                last_nav_error = exc
                if attempt >= 1:
                    raise
                time.sleep(1.0)
        if last_nav_error is not None:
            raise last_nav_error

        wait = WebDriverWait(driver, 15)
        try:
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except TimeoutException:
            pass

        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        except Exception:
            pass

        try:
            page_source = driver.page_source or ""
        except Exception:
            page_source = ""

        offer_labels = _get_offer_labels(driver)
        multiple_offers = len(offer_labels) > 1

        option_found = False
        option_selected = False
        option_text = None
        if multiple_offers:
            option_found, option_selected, option_text = _select_probel_offer(driver)

        a_prazo = None
        avista = None
        pix = None
        prazo = None
        probel_context = None
        ignored_prices: set[str] = set()

        # Com mais de uma oferta, aceita apenas PROBEL.
        # Com oferta unica, usa o destaque atual da pagina.
        attempts = 7 if multiple_offers else 3
        for _ in range(attempts):
            ignored_prices = extract_struck_prices(driver)
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text or ""
            except Exception:
                body_text = ""

            if multiple_offers:
                a_prazo, avista, pix, prazo, probel_context = _extract_probel_prices_from_body(
                    body_text,
                    ignored_prices=ignored_prices,
                )
                if probel_context:
                    break

                if option_found and not option_selected:
                    _, option_selected, option_text = _select_probel_offer(driver)
            else:
                a_prazo, avista, pix, prazo = _extract_display_prices_from_body(
                    body_text,
                    ignored_prices=ignored_prices,
                )
                if a_prazo or avista or pix or prazo:
                    break

            try:
                driver.execute_script("window.scrollTo(0, 0);")
            except Exception:
                pass
            time.sleep(0.5)

        if multiple_offers and option_selected and option_text:
            option_a_prazo, option_avista, option_pix, option_prazo = _extract_display_prices_from_body(
                option_text,
                ignored_prices=ignored_prices,
            )
            a_prazo = a_prazo or option_a_prazo
            avista = avista or option_avista
            pix = pix or option_pix
            prazo = prazo or option_prazo

        meta_prices = _extract_from_jsonld(page_source)
        if not meta_prices["a_prazo"] and not meta_prices["avista"]:
            meta_prices = _extract_from_next_data(page_source)
        if not meta_prices["a_prazo"] and not meta_prices["avista"]:
            fallback_price = _extract_from_meta(page_source)
            if fallback_price:
                meta_prices = {"a_prazo": fallback_price, "avista": fallback_price}

        if not a_prazo and not avista and not pix:
            a_prazo = a_prazo or meta_prices.get("a_prazo")
            avista = avista or meta_prices.get("avista")

        if pix:
            avista = pix
        elif avista and a_prazo:
            av_num = _money_to_float(avista)
            ap_num = _money_to_float(a_prazo)
            if av_num > 0 and ap_num > 0 and abs(av_num - ap_num) < 0.01:
                candidate = meta_prices.get("avista")
                if candidate and _money_to_float(candidate) != ap_num:
                    avista = candidate
        elif not avista:
            avista = meta_prices.get("avista") or avista

        # Sem contexto PROBEL e sem opcao PROBEL selecionada -> nao confiar no destaque.
        if multiple_offers and not probel_context and not option_selected:
            return {
                "a_prazo": None,
                "avista": None,
                "pix": None,
                "prazo": None,
                "status": "OFERTA PROBEL NAO ENCONTRADA",
            }

        if a_prazo and pix and prazo:
            status = "OK"
        elif a_prazo and pix and not prazo:
            status = "OK (SEM PARCELAMENTO)"
        elif pix and not avista:
            status = "OK (SOMENTE PIX)"
        elif a_prazo and not pix and prazo:
            status = "OK (SEM PIX)"
        elif avista and not pix and not prazo:
            status = "OK (SOMENTE A VISTA)"
        elif a_prazo and not pix:
            status = "OK (SOMENTE A PRAZO)"
        elif multiple_offers and option_found and not avista and not pix and not a_prazo:
            status = "OFERTA PROBEL SEM PRECO"
        elif not multiple_offers and (avista or pix or a_prazo):
            status = "OK"
        else:
            status = "OFERTA PROBEL NAO ENCONTRADA" if multiple_offers else "DADO NAO DISPONIVEL"

        return {"a_prazo": a_prazo, "avista": avista, "pix": pix, "prazo": prazo, "status": status}

    except WebDriverException:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "ERRO DE COLETA"}
    except Exception:
        return {"a_prazo": None, "avista": None, "pix": None, "prazo": None, "status": "ERRO DE COLETA"}
