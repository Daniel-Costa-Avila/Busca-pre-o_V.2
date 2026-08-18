from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
import requests
import random
import time
import json
import multiprocessing as mp
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from openpyxl import load_workbook, Workbook
from openpyxl.worksheet.worksheet import Worksheet

from App.config import (
    DEFAULT_BACKUP_OUTPUT_DIR,
    INPUT_FILE,
    INPUT_MERCADO_LIVRE_COTIA_FILE,
    INPUT_MERCADO_LIVRE_FILE,
    OUTPUT_FILE,
    OUTPUT_HEADERS,
    SUMMARY_CHANNEL_COLUMNS,
    SUMMARY_HEADERS,
)
from App.collectors.webcontinental import coletar as coletar_webcontinental
from App.collectors.magalu import coletar as coletar_magalu, close_magalu_selenium_driver
from App.collectors.zema import coletar as coletar_zema
from App.collectors.madeiramadeira import coletar as coletar_madeiramadeira
from App.collectors.probel import coletar as coletar_probel
from App.collectors.carrefour import coletar as coletar_carrefour
from App.collectors.mercadolivre import coletar as coletar_mercadolivre
from App.collectors.casasbahia import coletar as coletar_casasbahia
from App.utils.browser import get_driver, resolve_browser_pool
from App.workbook_style import style_result_workbook


def _magalu_collect_worker(url: str, headless: bool, queue) -> None:
    try:
        queue.put(coletar_magalu(url, headless=headless))
    except Exception as e:
        queue.put({"status": f"MAGALU - ERRO NO COLETOR: {type(e).__name__} | {e}"})
    finally:
        # Evita deixar navegadores Selenium Ã³rfÃ£os quando o worker termina.
        try:
            from App.collectors.magalu import collector as magalu_collector  # type: ignore

            drv = getattr(magalu_collector, "_SELENIUM_DRIVER", None)
            if drv is not None:
                try:
                    drv.quit()
                except Exception:
                    pass
                try:
                    setattr(magalu_collector, "_SELENIUM_DRIVER", None)
                    setattr(magalu_collector, "_SELENIUM_BROWSER_NAME", None)
                except Exception:
                    pass
        except Exception:
            pass


def coletar_magalu_com_timeout(url: str, headless: bool, timeout_seconds: int) -> dict:
    """
    Executa a coleta da Magalu em subprocesso para permitir timeout real em Windows
    (se o navegador/driver travar, o processo pode ser encerrado).
    """
    if timeout_seconds <= 0:
        return coletar_magalu(url, headless=headless)

    worker_python = str(os.getenv("MAGALU_WORKER_PYTHON") or "").strip()
    if worker_python:
        worker_entry = Path(__file__).resolve().parent / "collectors" / "magalu" / "worker_entry.py"
        if not worker_entry.exists():
            return {"status": "MAGALU - WORKER ENTRY NAO ENCONTRADO"}
        try:
            cmd = [worker_python, str(worker_entry), str(url), "1" if headless else "0"]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=float(timeout_seconds),
                cwd=str(Path(__file__).resolve().parent.parent),
                env=os.environ.copy(),
            )
            stdout = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            if proc.returncode != 0 and not stdout:
                detail = (stderr or f"exit={proc.returncode}")[-260:]
                return {"status": f"MAGALU - WORKER EXTERNO FALHOU: {detail}"}
            if stdout:
                last_line = stdout.splitlines()[-1].strip()
                try:
                    parsed = json.loads(last_line)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
            detail = ((stderr or stdout) or "sem retorno")[-260:]
            return {"status": f"MAGALU - WORKER EXTERNO RETORNO INVALIDO: {detail}"}
        except subprocess.TimeoutExpired:
            return {"status": f"MAGALU - TIMEOUT ({timeout_seconds}s)"}
        except Exception as e:
            return {"status": f"MAGALU - ERRO NO WORKER EXTERNO: {type(e).__name__} | {e}"}

    ctx = mp.get_context("spawn")
    q = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_magalu_collect_worker, args=(url, headless, q), daemon=True)
    proc.start()
    proc.join(timeout=float(timeout_seconds))

    if proc.is_alive():
        # Em Windows, matar apenas o processo Python pode deixar geckodriver/firefox Ã³rfÃ£os.
        # Use taskkill /T para encerrar a Ã¡rvore inteira.
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:
                pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.join(timeout=2.0)
        except Exception:
            pass
        return {"status": f"MAGALU - TIMEOUT ({timeout_seconds}s)"}

    try:
        if not q.empty():
            result = q.get_nowait()
            return result if isinstance(result, dict) else {"status": "MAGALU - RETORNO INVALIDO"}
    except Exception:
        pass

    return {"status": "MAGALU - SEM RETORNO (TIMEOUT/CRASH)"}


def _should_use_magalu_subprocess_timeout(headless: bool, timeout_seconds: int) -> bool:
    """
    Em modo visivel, preserve o comportamento antigo para facilitar diagnostico
    e evitar a janela abrindo/fechando instantaneamente a cada item.
    """
    if timeout_seconds <= 0:
        return False
    if not headless:
        return False
    if not _env_bool("MAGALU_USE_SUBPROCESS_TIMEOUT", True):
        return False
    return True


CollectorFn = Callable[..., dict]


# ---------------- RESOLVER COLETOR ----------------

def resolve_collector(link: str) -> Optional[CollectorFn]:
    if not link:
        return None

    l = link.lower().strip()

    if "magazineluiza.com.br" in l or "magalu" in l:
        return coletar_magalu

    if "mercadolivre.com.br" in l:
        return coletar_mercadolivre
    if "casasbahia.com.br" in l:
        return coletar_casasbahia

    if "webcontinental" in l:
        return coletar_webcontinental

    if "zema.com" in l:
        return coletar_zema

    if "madeiramadeira" in l:
        return coletar_madeiramadeira

    if "carrefour" in l:
        return coletar_carrefour

    if "probel" in l:
        return coletar_probel

    return None


# ---------------- HELPERS EXCEL ----------------

def find_col(ws: Worksheet, names: set[str]) -> Optional[int]:
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=col).value
        if v and str(v).strip().lower() in names:
            return col
    return None


def extract_url_from_cell(cell) -> str:
    def _extract_url_from_text(raw: object) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""

        formula_match = re.search(r'HYPERLINK\(\s*"([^"]+)"', text, re.IGNORECASE)
        if formula_match:
            return formula_match.group(1).strip()

        inline_match = re.search(r"https?://[^\s\"'<>]+", text, re.IGNORECASE)
        if inline_match:
            return inline_match.group(0).rstrip(".,;)")

        return ""

    # Algumas planilhas exibem uma URL no texto da celula, mas mantem um hyperlink
    # antigo/apagado apontando para outro dominio. A URL visivel deve vencer.
    visible_url = _extract_url_from_text(cell.value)
    if visible_url:
        return visible_url

    if getattr(cell, "hyperlink", None) and cell.hyperlink.target:
        return str(cell.hyperlink.target).strip()

    return ""


def _normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", normalized)


def find_col_flexible(ws: Worksheet, names: set[str]) -> Optional[int]:
    normalized_names = {_normalize_text(name) for name in names if _normalize_text(name)}
    if not normalized_names:
        return None
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=col).value
        if _normalize_text(v) in normalized_names:
            return col
    return None


def _map_output_columns(ws: Worksheet) -> dict[str, Optional[int]]:
    return {
        "id_no_canal": find_col_flexible(ws, {
            "id no canal",
            "id_no_canal",
            "id canal",
            "id_canal",
            "codigo lojista",
            "codigo_lojista",
            "sku canal",
            "sku",
        }),
        "codigo_interno": find_col_flexible(ws, {
            "codigo interno",
            "codigo_interno",
            "id_produto",
            "produto",
            "id",
            "codigo",
            "codigo_produto",
            "product_id",
        }),
        "canal": find_col_flexible(ws, {"canal", "loja", "marketplace", "seller"}),
        "titulo": find_col_flexible(ws, {"titulo", "tÃƒÂ­tulo", "nome", "descricao", "descriÃƒÂ§ÃƒÂ£o"}),
        "a_prazo": find_col_flexible(ws, {"a prazo", "a_prazo"}),
        "a_vista": find_col_flexible(ws, {"a vista", "a_vista", "avista"}),
        "parcelamento": find_col_flexible(ws, {"parcelamento", "prazo"}),
        "status": find_col_flexible(ws, {"status"}),
        "data_pesquisa": find_col_flexible(ws, {"data_pesquisa", "data pesquisa", "data"}),
        "hora_pesquisa": find_col_flexible(ws, {"hora_pesquisa", "hora pesquisa", "hora"}),
        "origem_execucao": find_col_flexible(ws, {"origem_execucao", "origem execucao"}),
        "origem_dados": find_col_flexible(ws, {"origem_dados", "origem dados", "source"}),
        "link": find_col_flexible(ws, {"link", "url", "href"}),
    }


def _normalize_key_part(value: object) -> str:
    return _normalize_text(value)


def _build_import_key(
    id_no_canal: object,
    codigo_interno: object,
    titulo: object,
    link: object,
) -> Optional[tuple[str, str, str]]:
    id_key = _normalize_key_part(id_no_canal)
    cod_key = _normalize_key_part(codigo_interno)
    title_key = _normalize_key_part(titulo)
    link_key = _normalize_key_part(link)

    if id_key or cod_key:
        # Identidade principal pelo cÃ³digo interno / id do canal.
        return ("id", id_key or "", cod_key or "")

    if link_key:
        # Fallback por link quando nÃ£o hÃ¡ cÃ³digos.
        return ("link", link_key, "")

    if title_key:
        # Ãšltimo fallback por tÃ­tulo.
        return ("title", title_key, "")

    return None


def _append_precollected_rows(
    ws_src: Worksheet,
    ws_out: Worksheet,
    source_name: str,
    only_ids: set[str] | None,
    max_rows: int | None,
    summary: dict[str, dict] | None = None,
    seen_rows: set[tuple[str, str, str]] | None = None,
    seen_ids: set[str] | None = None,
) -> int:
    col_map = _map_output_columns(ws_src)

    is_ml = source_name.strip().lower() == "mercado_livre"
    if is_ml:
        # Mapeamento fixo da planilha Mercado Livre:
        # A: id no canal | B: codigo interno | C: canal | D: titulo | E: prazo | F: link
        col_id_canal = 1
        col_codigo_interno = 2
        col_canal = 3
        col_titulo = 4
        col_a_prazo = 5
        col_a_vista = None
        col_parcelamento = None
        col_status = None
        col_data = None
        col_hora = None
        col_origem_execucao = None
        col_origem_dados = None
        col_link = 6
    else:
        col_codigo_interno = col_map["codigo_interno"] or 1
        col_id_canal = col_map["id_no_canal"] or col_codigo_interno
        col_canal = col_map["canal"]
        col_titulo = col_map["titulo"]
        col_a_prazo = col_map["a_prazo"]
        col_a_vista = col_map["a_vista"]
        col_parcelamento = col_map["parcelamento"]
        col_status = col_map["status"]
        col_data = col_map["data_pesquisa"]
        col_hora = col_map["hora_pesquisa"]
        col_origem_execucao = col_map["origem_execucao"]
        col_origem_dados = col_map["origem_dados"]
        col_link = col_map["link"]

        if col_link is None:
            for c in range(1, ws_src.max_column + 1):
                if extract_url_from_cell(ws_src.cell(row=2, column=c)):
                    col_link = c
                    break

    processed = 0

    for row in range(2, ws_src.max_row + 1):
        codigo_interno = ws_src.cell(row=row, column=col_codigo_interno).value
        id_no_canal = ws_src.cell(row=row, column=col_id_canal).value if col_id_canal else None
        id_key = str(codigo_interno).strip() if codigo_interno is not None else ""
        if only_ids and id_key not in only_ids:
            continue
        if max_rows is not None and processed >= max_rows:
            break

        titulo = ws_src.cell(row=row, column=col_titulo).value if col_titulo else None
        link = extract_url_from_cell(ws_src.cell(row=row, column=col_link)) if col_link else ""
        canal_raw = ws_src.cell(row=row, column=col_canal).value if col_canal else None
        canal = _resolve_output_channel(canal_raw, link)
        if not str(id_no_canal or "").strip():
            id_no_canal = _build_missing_channel_id_from_raw(codigo_interno, canal_raw)

        if seen_ids is not None:
            id_unique = str(id_no_canal or "").strip()
            if id_unique:
                if id_unique in seen_ids:
                    continue
                seen_ids.add(id_unique)

        if seen_rows is not None:
            key = _build_import_key(id_no_canal, codigo_interno, titulo, link)
            if key is not None:
                if key in seen_rows:
                    continue
                seen_rows.add(key)

        a_prazo = ws_src.cell(row=row, column=col_a_prazo).value if col_a_prazo else None
        a_vista = ws_src.cell(row=row, column=col_a_vista).value if col_a_vista else None
        parcelamento = ws_src.cell(row=row, column=col_parcelamento).value if col_parcelamento else None
        status = ws_src.cell(row=row, column=col_status).value if col_status else None
        data_pesquisa = ws_src.cell(row=row, column=col_data).value if col_data else None
        hora_pesquisa = ws_src.cell(row=row, column=col_hora).value if col_hora else None
        origem_execucao = (
            ws_src.cell(row=row, column=col_origem_execucao).value
            if col_origem_execucao
            else None
        )
        origem_dados = (
            ws_src.cell(row=row, column=col_origem_dados).value
            if col_origem_dados
            else None
        )

        ws_out.append([
            id_no_canal,
            codigo_interno,
            canal,
            titulo,
            a_prazo,
            _sanitize_output_link(link),
        ])

        if summary is not None:
            _update_summary(
                summary,
                codigo_interno,
                id_no_canal,
                titulo,
                str(canal_raw or "").strip() or (canal or None),
                canal,
                _to_float(a_prazo),
            )

        processed += 1

    return processed


def _resolve_channel_column(channel_raw: object, link: str) -> Optional[str]:
    channel = _normalize_text(channel_raw)
    link_l = (link or "").lower()

    if "probel" in channel:
        return "Probel (oficial)"
    if "magazine luiza" in channel or "magalu" in channel:
        return "Magazine Luiza"
    if "casas bahia" in channel:
        return "Casas Bahia"
    if "web continental" in channel or "webcontinental" in channel:
        return "Web Continental"
    if "casa e video" in channel or "casavideo" in channel:
        return "Casa e Video"
    if "madeira madeira" in channel or "madeiramadeira" in channel:
        return "Madeiramadeira"
    if "zema" in channel:
        return "Zema"
    if "mercado livre" in channel or "mercadolivre" in channel:
        return "Mercado Livre"
    if "carrefour" in channel:
        return "Carrefour"

    if "probel.com.br" in link_l:
        return "Probel (oficial)"
    if "magazineluiza.com.br" in link_l or "magalu" in link_l:
        return "Magazine Luiza"
    if "casasbahia.com.br" in link_l:
        return "Casas Bahia"
    if "webcontinental" in link_l:
        return "Web Continental"
    if "casaevideo.com.br" in link_l:
        return "Casa e Video"
    if "madeiramadeira.com.br" in link_l:
        return "Madeiramadeira"
    if "zema.com" in link_l:
        return "Zema"
    if "mercadolivre.com.br" in link_l:
        return "Mercado Livre"
    if "carrefour" in link_l:
        return "Carrefour"

    return None


def _resolve_output_channel(channel_raw: object, link: str) -> Optional[str]:
    raw = str(channel_raw or "").strip()
    if raw:
        return raw
    return _resolve_channel_column(channel_raw, link)


def _build_missing_channel_id_from_raw(codigo_interno: object, canal_raw: object) -> Optional[str]:
    codigo = str(codigo_interno) if codigo_interno is not None else ""
    canal_txt = str(canal_raw) if canal_raw is not None else ""
    if not codigo.strip():
        return None
    if canal_txt.strip():
        return f"{codigo}-{canal_txt}"
    return codigo



def _build_runtime_row_key(
    id_no_canal: object,
    codigo_interno: object,
    canal: object,
    titulo: object,
    link: object,
) -> Optional[tuple[str, str, str]]:
    # Deduplica apenas linhas realmente equivalentes (evita colidir canais diferentes).
    id_key = _normalize_key_part(id_no_canal)
    cod_key = _normalize_key_part(codigo_interno)
    channel_key = _normalize_key_part(canal)
    title_key = _normalize_key_part(titulo)
    link_key = _normalize_key_part(link)

    if link_key:
        return ("link", link_key, channel_key or cod_key or id_key)
    if id_key and channel_key:
        return ("id_canal", id_key, channel_key)
    if cod_key and channel_key:
        return ("cod_canal", cod_key, channel_key)
    if id_key:
        return ("id", id_key, "")
    if cod_key:
        return ("cod", cod_key, "")
    if title_key:
        return ("title", title_key, channel_key)
    return None


def _sanitize_output_link(link: object) -> str:
    text = str(link or "").strip()
    if not text:
        return ""
    lower = text.lower()
    # Nao exibir links de lista do Mercado Livre no output final.
    if "lista.mercadolivre.com.br" in lower:
        return ""
    return text


def _resolve_ml_listing_to_product_url(link: str) -> str:
    raw = str(link or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    if "lista.mercadolivre.com.br" not in lower:
        return raw
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(raw, timeout=15, headers=headers)
        if resp.status_code >= 400:
            return raw
        html = resp.text or ""
        # Preferir URL de produto direto.
        m = re.search(r"https://produto\\.mercadolivre\\.com\\.br/MLB-\\d+[^\"'\\s<>#]*", html, re.IGNORECASE)
        if m:
            return m.group(0).strip()
        # Fallback para URL canônica /p/MLB...
        m2 = re.search(r"https://www\\.mercadolivre\\.com\\.br/[^\"'\\s<>]*/p/MLB\\d+[^\"'\\s<>#]*", html, re.IGNORECASE)
        if m2:
            return m2.group(0).strip()
    except Exception:
        return raw
    return raw
def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    # Prioriza o primeiro valor monetario BRL quando o texto contem
    # informacoes compostas (ex.: "10x de R$ 199,90 sem juros").
    match_brl = re.search(r"R\$\s*([\d\.]+,\d{2})", text, re.IGNORECASE)
    if match_brl:
        raw = match_brl.group(1).replace(".", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            pass

    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not cleaned:
        return None

    # "1.234,56" -> "1234.56"
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    # "1234,56" -> "1234.56"
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_number(value) -> Optional[float | int]:
    num = _to_float(value)
    if num is None:
        return None
    if float(num).is_integer():
        return int(num)
    return num


def _normalize_collector_prices(result: dict) -> dict:
    """
    Regra global para todos os canais:
    - quando houver avista e pix, PIX deve ser <= avista.
    - se vier invertido no coletor, corrige no pipeline central.
    """
    out = dict(result or {})
    avista_raw = out.get("avista")
    pix_raw = out.get("pix")

    avista_num = _to_float(avista_raw)
    pix_num = _to_float(pix_raw)
    if avista_num is None or pix_num is None:
        return out

    if pix_num > avista_num:
        out["avista"], out["pix"] = pix_raw, avista_raw
    return out


def _resolve_output_prices(result: dict) -> tuple[object, object, object]:
    """
    Normaliza campos para a planilha:
    - A prazo: usa o campo explicito `a_prazo` quando o coletor informar.
    - A vista: prioriza Pix; sem Pix, usa `avista`.
    - Parcelamento: campo prazo original.

    Sem `a_prazo`, mantem o fallback historico por menor/maior valor.
    """
    normalized = _normalize_collector_prices(result)
    status_text = " ".join(str(normalized.get("status") or "").lower().split())
    if status_text and any(token in status_text for token in ("bloqueado", "erro 403", "http 403", "forbidden")):
        # Exibe bloqueio na coluna "Preco" para ficar visivel na planilha.
        return "BLOQUEADO (403)", None, None
    raw_a_prazo = normalized.get("a_prazo")
    raw_avista = normalized.get("avista")
    raw_pix = normalized.get("pix")
    raw_prazo = normalized.get("prazo")

    if raw_a_prazo is not None and str(raw_a_prazo).strip():
        a_prazo = raw_a_prazo
        if raw_pix is not None and str(raw_pix).strip():
            a_vista = raw_pix
        elif raw_avista is not None and str(raw_avista).strip():
            a_vista = raw_avista
        else:
            a_vista = raw_a_prazo
        return a_prazo, a_vista, raw_prazo

    avista_num = _to_float(raw_avista)
    pix_num = _to_float(raw_pix)

    if avista_num is not None and pix_num is not None:
        if avista_num >= pix_num:
            a_prazo = raw_avista
            a_vista = raw_pix
        else:
            a_prazo = raw_pix
            a_vista = raw_avista
    elif raw_avista is not None and str(raw_avista).strip():
        a_prazo = raw_avista
        a_vista = raw_avista
    elif raw_pix is not None and str(raw_pix).strip():
        a_prazo = raw_pix
        a_vista = raw_pix
    else:
        a_prazo = None
        a_vista = None

    # Evita celula vazia: quando falhar, sinaliza que nao houve preco.
    if a_prazo is None and status_text and not status_text.startswith("ok"):
        tokens_no_price = (
            "preco nao disponivel",
            "preco nao encontrado",
            "falha",
            "erro",
            "blocked",
        )
        if any(t in status_text for t in tokens_no_price):
            a_prazo = "SEM PRECO"

    return a_prazo, a_vista, raw_prazo


def _select_reference_price(result: dict) -> Optional[float]:
    # Consolidado deve refletir menor preco instantaneo consistente.
    normalized = _normalize_collector_prices(result)
    for key in ("pix", "avista"):
        value = _to_float(normalized.get(key))
        if value is not None and value >= 0:
            return value
    return None


def _resolve_output_seller(result: dict, channel_raw: object, link: str) -> str:
    for key in ("seller", "seller_name", "seller_id", "loja", "store"):
        value = result.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    channel_name = _resolve_channel_column(channel_raw, link)
    if channel_name:
        return channel_name

    raw_channel = str(channel_raw or "").strip()
    if raw_channel:
        return raw_channel

    return "DESCONHECIDO"


def _update_summary(
    summary: dict[str, dict],
    codigo_interno,
    codigo_lojista,
    produto,
    seller_name,
    channel_column: Optional[str],
    price: Optional[float],
) -> None:
    key = str(codigo_interno).strip() if codigo_interno is not None else ""
    if not key:
        key = "<SEM_CODIGO_INTERNO>"

    item = summary.get(key)
    if item is None:
        item = {
            "codigo_interno": codigo_interno,
            "codigo_lojista": codigo_lojista,
            "produto": produto,
            "probel_oficial": None,
            "channel_prices": {name: None for name in SUMMARY_CHANNEL_COLUMNS},
            "channel_sellers": {name: None for name in SUMMARY_CHANNEL_COLUMNS},
            "probel_seller": None,
        }
        summary[key] = item
    else:
        if not item["codigo_lojista"] and codigo_lojista:
            item["codigo_lojista"] = codigo_lojista
        if not item["produto"] and produto:
            item["produto"] = produto

    if price is None or channel_column is None:
        return

    if channel_column == "Probel (oficial)":
        current = item["probel_oficial"]
        item["probel_oficial"] = price if current is None else min(current, price)
        if seller_name and not item["probel_seller"]:
            item["probel_seller"] = seller_name
        return

    if channel_column in item["channel_prices"]:
        current = item["channel_prices"][channel_column]
        item["channel_prices"][channel_column] = price if current is None else min(current, price)
        if seller_name and not item["channel_sellers"].get(channel_column):
            item["channel_sellers"][channel_column] = seller_name


def _normalize_summary_label(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _append_summary_sheet(wb_out: Workbook, summary: dict[str, dict]) -> None:
    ws_summary = wb_out.create_sheet(title="Consolidado")
    ws_summary.append(SUMMARY_HEADERS)

    for item in summary.values():
        channel_prices: dict[str, Optional[float]] = item["channel_prices"]
        channel_sellers: dict[str, Optional[str]] = item.get("channel_sellers", {})
        ranked_prices: list[tuple[str, float, str]] = []

        probel_price = item["probel_oficial"]
        if probel_price is not None:
            ranked_prices.append(
                (
                    "Probel (oficial)",
                    probel_price,
                    _normalize_summary_label(item.get("probel_seller"), "Probel (oficial)"),
                )
            )

        for channel_name in SUMMARY_CHANNEL_COLUMNS:
            value = channel_prices.get(channel_name)
            if value is not None:
                ranked_prices.append(
                    (
                        channel_name,
                        value,
                        _normalize_summary_label(channel_sellers.get(channel_name), channel_name),
                    )
                )

        if ranked_prices:
            ranked_prices.sort(key=lambda pair: pair[1])
            loja_menor_preco = ranked_prices[0][0]
            seller_menor_preco = ranked_prices[0][2]
            menor_preco = ranked_prices[0][1]
            preco_medio = sum(price for _, price, _ in ranked_prices) / len(ranked_prices)
            quantidade_lojas = len(ranked_prices)
        else:
            loja_menor_preco = None
            seller_menor_preco = None
            menor_preco = None
            preco_medio = None
            quantidade_lojas = 0

        ws_summary.append(
            [
                item["codigo_interno"],
                item["codigo_lojista"],
                item["produto"],
                probel_price,
                loja_menor_preco,
                seller_menor_preco,
                menor_preco,
                preco_medio,
                quantidade_lojas,
                channel_prices.get("Magazine Luiza"),
                channel_prices.get("Casas Bahia"),
                channel_prices.get("Web Continental"),
                channel_prices.get("Casa e Video"),
                channel_prices.get("Madeiramadeira"),
                channel_prices.get("Zema"),
                channel_prices.get("Mercado Livre"),
                channel_prices.get("Carrefour"),
            ]
        )


def _parse_ids(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    ids = {v.strip() for v in raw.split(",") if v.strip()}
    return ids or None


def _get_run_filters() -> tuple[int | None, set[str] | None]:
    max_rows = None
    only_ids = None

    # ENV overrides
    env_limit = os.getenv("LIMIT_ROWS")
    env_ids = os.getenv("ONLY_IDS")
    if env_limit:
        try:
            max_rows = int(env_limit)
        except ValueError:
            max_rows = None
    only_ids = _parse_ids(env_ids)

    # CLI flags: --limit N | --ids A,B
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg in {"--limit", "-l"} and i + 1 < len(args):
            try:
                max_rows = int(args[i + 1])
            except ValueError:
                pass
        if arg in {"--ids", "-i"} and i + 1 < len(args):
            only_ids = _parse_ids(args[i + 1]) or only_ids

    return max_rows, only_ids


def _get_io_paths() -> tuple[Path, Path, Optional[Path], Optional[Path]]:
    input_file = os.getenv("INPUT_FILE") or INPUT_FILE
    input_ml_file = os.getenv("INPUT_MERCADO_LIVRE_FILE") or INPUT_MERCADO_LIVRE_FILE
    input_ml_cotia_file = (
        os.getenv("INPUT_MERCADO_LIVRE_COTIA_FILE") or INPUT_MERCADO_LIVRE_COTIA_FILE
    )
    output_file = os.getenv("OUTPUT_FILE") or OUTPUT_FILE

    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg in {"--input", "-in"} and i + 1 < len(args):
            input_file = args[i + 1]
        if arg in {"--input-ml", "--input-mercado-livre"} and i + 1 < len(args):
            input_ml_file = args[i + 1]
        if arg in {"--input-ml-cotia", "--input-mercado-livre-cotia"} and i + 1 < len(args):
            input_ml_cotia_file = args[i + 1]
        if arg in {"--output", "-out"} and i + 1 < len(args):
            output_file = args[i + 1]

    input_ml_path = Path(input_ml_file) if str(input_ml_file).strip() else None
    input_ml_cotia_path = (
        Path(input_ml_cotia_file) if str(input_ml_cotia_file).strip() else None
    )
    return Path(input_file), Path(output_file), input_ml_path, input_ml_cotia_path


def _resolve_backup_output_dir() -> Path:
    raw_dir = str(os.getenv("OUTPUT_BACKUP_DIR") or "").strip()
    if raw_dir:
        return Path(raw_dir).expanduser()
    return DEFAULT_BACKUP_OUTPUT_DIR


def _backup_output_file(output_path: Path) -> Path:
    backup_dir = _resolve_backup_output_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{output_path.stem}_backup_{timestamp}{output_path.suffix}"
    backup_path = backup_dir / backup_name
    shutil.copy2(output_path, backup_path)
    return backup_path


def _should_headless() -> bool:
    env_headless = os.getenv("HEADLESS")
    if env_headless is not None:
        return env_headless.strip().lower() not in {"0", "false", "no", "off"}

    if sys.platform.startswith("linux") and not os.getenv("DISPLAY"):
        return True

    return False


# ---------------- MAIN ----------------

def main():
    input_path, output_path, input_ml_path, input_ml_cotia_path = _get_io_paths()
    if not input_path.exists():
        raise FileNotFoundError(f"Arquivo {input_path} nao encontrado.")
    if input_ml_path is not None and not input_ml_path.exists():
        print(f"Aviso: arquivo {input_ml_path} nao encontrado. Importacao Mercado Livre sera ignorada.")
        input_ml_path = None
    if input_ml_cotia_path is not None and not input_ml_cotia_path.exists():
        print(
            f"Aviso: arquivo {input_ml_cotia_path} nao encontrado. "
            "Importacao Mercado Livre Cotia sera ignorada."
        )
        input_ml_cotia_path = None

    wb_in = load_workbook(input_path)
    ws_in = wb_in.active

    col_codigo_interno = find_col_flexible(ws_in, {
        "codigo interno",
        "codigo_interno",
        "id_produto",
        "produto",
        "id",
        "codigo",
        "codigo_produto",
        "product_id",
    }) or 1

    col_id_canal = find_col_flexible(ws_in, {
        "id no canal",
        "id_no_canal",
        "id canal",
        "id_canal",
        "codigo lojista",
        "codigo_lojista",
        "sku canal",
        "sku",
    })
    if col_id_canal is None:
        col_id_canal = col_codigo_interno

    col_canal = find_col_flexible(ws_in, {"canal", "loja", "marketplace", "seller"})
    col_titulo = find_col_flexible(ws_in, {"titulo", "tÃ­tulo", "nome", "descricao", "descriÃ§Ã£o"})
    col_link = find_col_flexible(ws_in, {"link", "url", "href"})

    if col_link is None:
        for c in range(1, ws_in.max_column + 1):
            if extract_url_from_cell(ws_in.cell(row=2, column=c)):
                col_link = c
                break

    if col_link is None:
        raise RuntimeError("Nao foi possivel localizar a coluna de LINK.")

    wb_out = Workbook()
    ws_out = wb_out.active
    ws_out.title = "Output"

    ws_out.append(OUTPUT_HEADERS)

    headless = _should_headless()
    driver = None
    browser_pool = resolve_browser_pool()
    drivers: dict[str, object] = {}
    run_dt = datetime.now()
    data_pesquisa = run_dt.strftime("%Y-%m-%d")
    hora_pesquisa = run_dt.strftime("%H:%M:%S")
    origem_execucao = (os.getenv("ORIGEM_EXECUCAO") or "CLI").strip() or "CLI"
    origem_dados = (os.getenv("ORIGEM_DADOS") or "principal").strip() or "principal"

    # -------- Processar produtos --------
    max_rows, only_ids = _get_run_filters()
    processed = 0
    imported = 0
    seen_main_rows: set[tuple[str, str, str]] = set()
    summary: dict[str, dict] = {}

    def _status_ok(result: dict) -> bool:
        return str(result.get("status") or "").startswith("OK")

    def _status_blocked(result: dict) -> bool:
        status = " ".join(str((result or {}).get("status") or "").lower().split())
        if not status:
            return False
        return any(token in status for token in ("bloqueado", "erro 403", "http 403", "forbidden", "access denied"))

    def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            value = int(str(raw).strip())
        except ValueError:
            return default
        if value < minimum or value > maximum:
            return default
        return value

    def _get_driver_for(browser_name: str):
        if browser_name in drivers:
            return drivers[browser_name]
        new_driver = get_driver(headless=headless, browser_name=browser_name)
        drivers[browser_name] = new_driver
        return new_driver

    try:
        run_started_at = time.time()
        last_progress_at = run_started_at
        abort_reason: str | None = None
        # Watchdogs (0 = desativado)
        run_max_seconds = _env_int("RUN_MAX_SECONDS", 0, 0, 24 * 60 * 60)
        run_max_idle_seconds = _env_int("RUN_MAX_IDLE_SECONDS", 0, 0, 24 * 60 * 60)

        def _check_abort() -> bool:
            nonlocal abort_reason
            now = time.time()
            if abort_reason:
                return True
            if run_max_seconds and (now - run_started_at) >= run_max_seconds:
                abort_reason = f"tempo total excedido ({run_max_seconds}s)"
                return True
            if run_max_idle_seconds and (now - last_progress_at) >= run_max_idle_seconds:
                abort_reason = f"inatividade excedida ({run_max_idle_seconds}s)"
                return True
            return False

        def _sleep_with_abort(seconds: int | float) -> bool:
            """
            Dorme em pequenos intervalos para permitir abortar a fila com seguranca.
            Retorna True se abortou durante o sono.
            """
            try:
                remaining = float(seconds)
            except Exception:
                remaining = 0.0
            if remaining <= 0:
                return _check_abort()
            while remaining > 0:
                if _check_abort():
                    return True
                step = 0.5 if remaining > 0.5 else remaining
                time.sleep(step)
                remaining -= step
            return _check_abort()

        blocked_items: list[dict] = []
        magalu_throttle_seconds = _env_int("MAGALU_THROTTLE_SECONDS", 0, 0, 60)
        # Default: sem throttle para nao deixar a execucao lenta.
        # Ajuste via env quando a Magalu estiver bloqueando (403/rate limit).
        magalu_throttle_min = _env_int("MAGALU_THROTTLE_MIN_SECONDS", 0, 0, 60)
        magalu_throttle_max = _env_int("MAGALU_THROTTLE_MAX_SECONDS", 0, 0, 60)
        if magalu_throttle_max < magalu_throttle_min:
            magalu_throttle_max = magalu_throttle_min
        magalu_blocked_streak_threshold = _env_int("MAGALU_BLOCKED_STREAK_THRESHOLD", 3, 1, 50)
        magalu_blocked_cooldown_seconds = _env_int("MAGALU_BLOCKED_COOLDOWN_SECONDS", 70, 5, 600)
        magalu_blocked_streak = 0
        magalu_circuit_open_until = 0.0
        magalu_retry_max_items = _env_int("MAGALU_RETRY_MAX_ITEMS", 60, 0, 5000)
        # Evita travar indefinidamente em um item da Magalu (browser/driver preso).
        # Default propositalmente >0 para garantir progresso; ajuste via .env.
        magalu_item_timeout_seconds = _env_int("MAGALU_ITEM_TIMEOUT_SECONDS", 180, 0, 600)

        for row in range(2, ws_in.max_row + 1):
            if _check_abort():
                print(
                    f"Watchdog: encerrando fila e salvando parcial (motivo: {abort_reason})."
                )
                break
            coletor = None
            codigo_interno = ws_in.cell(row=row, column=col_codigo_interno).value
            id_no_canal = ws_in.cell(row=row, column=col_id_canal).value if col_id_canal else None
            id_key = str(codigo_interno).strip() if codigo_interno is not None else ""
            if only_ids and id_key not in only_ids:
                continue
            if max_rows is not None and processed >= max_rows:
                break

            titulo = ws_in.cell(row=row, column=col_titulo).value if col_titulo else None
            link = extract_url_from_cell(ws_in.cell(row=row, column=col_link))
            canal_raw = ws_in.cell(row=row, column=col_canal).value if col_canal else None
            canal = _resolve_output_channel(canal_raw, link)
            if not str(id_no_canal or "").strip():
                id_no_canal = _build_missing_channel_id_from_raw(codigo_interno, canal_raw)

            dedupe_key = _build_runtime_row_key(
                id_no_canal=id_no_canal,
                codigo_interno=codigo_interno,
                canal=canal,
                titulo=titulo,
                link=link,
            )
            if dedupe_key is not None:
                if dedupe_key in seen_main_rows:
                    continue
                seen_main_rows.add(dedupe_key)

            if not link:
                if canal == "Casas Bahia" and str(id_no_canal or "").strip():
                    try:
                        result = coletar_casasbahia(
                            None,
                            None,
                            sku=str(id_no_canal or "").strip(),
                        )
                    except Exception as e:
                        result = {
                            "avista": None,
                            "pix": None,
                            "prazo": None,
                            "status": f"ERRO NO COLETOR: {type(e).__name__} | {e}",
                        }
                else:
                    result = {
                        "avista": None,
                        "pix": None,
                        "prazo": None,
                        "status": "LINK AUSENTE"
                    }
            else:
                coletor = resolve_collector(link)

                if not coletor:
                    result = {
                        "avista": None,
                        "pix": None,
                        "prazo": None,
                        "status": "CANAL NAO SUPORTADO"
                    }
                else:
                    try:
                        if coletor is coletar_magalu:
                            # Circuit breaker: se estiver em cooldown, nao tenta coletar agora.
                            now = time.time()
                            if now < magalu_circuit_open_until:
                                result = {"status": "MAGALU - BLOQUEADO (COOLDOWN)"}
                            else:
                                # Throttle com jitter para reduzir chance de bloqueio (403/rate limit).
                                if magalu_throttle_seconds:
                                    if _sleep_with_abort(magalu_throttle_seconds):
                                        print(
                                            f"Watchdog: encerrando fila e salvando parcial (motivo: {abort_reason})."
                                        )
                                        break
                                elif magalu_throttle_max:
                                    jitter = random.randint(magalu_throttle_min, magalu_throttle_max)
                                    if jitter:
                                        if _sleep_with_abort(jitter):
                                            print(
                                                f"Watchdog: encerrando fila e salvando parcial (motivo: {abort_reason})."
                                            )
                                            break
                                # Timeout real (subprocesso) para evitar travar se o browser ficar preso.
                                if _should_use_magalu_subprocess_timeout(headless, magalu_item_timeout_seconds):
                                    result = coletar_magalu_com_timeout(
                                        link,
                                        headless=headless,
                                        timeout_seconds=magalu_item_timeout_seconds,
                                    )
                                else:
                                    result = coletor(link, headless=headless)
                        elif coletor is coletar_casasbahia:
                            result = coletor(driver, link, sku=str(id_no_canal or "").strip())
                        else:
                            primary_browser = browser_pool[0] if browser_pool else "edge"
                            if driver is None:
                                driver = _get_driver_for(primary_browser)
                            result = coletor(driver, link)

                            # Fallback: se Zema nao retornar dados validos, tenta em outro navegador.
                            if coletor is coletar_zema and not _status_ok(result):
                                if browser_pool[1:]:
                                    print(
                                        f"ZEMA fallback: status primario='{result.get('status')}' "
                                        f"-> tentando navegadores {browser_pool[1:]}"
                                    )
                                for alt_browser in browser_pool[1:]:
                                    try:
                                        alt_driver = _get_driver_for(alt_browser)
                                        alt_result = coletor(alt_driver, link)
                                        if isinstance(alt_result, dict) and _status_ok(alt_result):
                                            print(f"ZEMA fallback: sucesso com {alt_browser}")
                                            result = alt_result
                                            break
                                    except Exception:
                                        print(f"ZEMA fallback: erro ao tentar {alt_browser}")
                                        continue

                        if not isinstance(result, dict):
                            raise ValueError("Coletor nao retornou dict")

                    except Exception as e:
                        result = {
                            "avista": None,
                            "pix": None,
                            "prazo": None,
                            "status": f"ERRO NO COLETOR: {type(e).__name__} | {e}"
                        }

            a_prazo, a_vista, parcelamento = _resolve_output_prices(result)
            seller_name = _resolve_output_seller(result, canal_raw, link)
            reference_price = _select_reference_price(result)
            channel_column = _resolve_channel_column(canal_raw, link)

            _update_summary(
                summary,
                codigo_interno,
                id_no_canal,
                titulo,
                seller_name,
                channel_column,
                reference_price,
            )

            ws_out.append([
                id_no_canal,
                codigo_interno,
                canal,
                titulo,
                a_prazo,
                _sanitize_output_link(link),
            ])
            last_progress_at = time.time()

            # Se a Magalu bloquear (403/captcha), pula agora e tenta novamente depois do tempo de espera.
            if coletor is coletar_magalu and _status_blocked(result):
                magalu_blocked_streak += 1
                blocked_items.append(
                    {
                        "out_row": ws_out.max_row,
                        "link": link,
                        "id_no_canal": id_no_canal,
                        "codigo_interno": codigo_interno,
                    }
                )
                # Circuit breaker: se muitos bloqueios em sequencia, espera antes de continuar.
                if magalu_blocked_streak >= magalu_blocked_streak_threshold:
                    print(
                        "MAGALU bloqueado em sequencia "
                        f"({magalu_blocked_streak}/{magalu_blocked_streak_threshold}). "
                        f"Aguardando {magalu_blocked_cooldown_seconds}s para reduzir bloqueio..."
                    )
                    magalu_circuit_open_until = time.time() + float(magalu_blocked_cooldown_seconds)
                    magalu_blocked_streak = 0
            elif coletor is coletar_magalu:
                magalu_blocked_streak = 0

            processed += 1

        # Retry de itens bloqueados (Magalu): espera e tenta de novo.
        if blocked_items:
            # Importante: retry com sleep pode fazer a execucao "parecer travada".
            # Por padrao deixamos DESLIGADO (MAGALU_BLOCKED_RETRIES=0) e o usuario
            # habilita manualmente quando fizer sentido (ex.: bloqueio temporario).
            wait_seconds = int(os.getenv("MAGALU_BLOCKED_WAIT_SECONDS") or "65")
            max_retries = int(os.getenv("MAGALU_BLOCKED_RETRIES") or "0")
            wait_seconds = 65 if wait_seconds < 5 else wait_seconds
            max_retries = 0 if max_retries < 0 else max_retries

            if max_retries <= 0:
                print(
                    "MAGALU retry: desativado (MAGALU_BLOCKED_RETRIES=0). "
                    f"Ignorando {len(blocked_items)} itens bloqueados."
                )
                blocked_items = []

            if magalu_retry_max_items and len(blocked_items) > magalu_retry_max_items:
                print(
                    f"MAGALU retry: {len(blocked_items)} itens bloqueados; "
                    f"limitando a {magalu_retry_max_items} para evitar demora excessiva."
                )
                blocked_items = blocked_items[:magalu_retry_max_items]

            if blocked_items and max_retries > 0 and not _check_abort():
                for attempt in range(1, max_retries + 1):
                    print(f"MAGALU retry: aguardando {wait_seconds}s (tentativa {attempt}/{max_retries})...")
                    if _sleep_with_abort(wait_seconds):
                        print(
                            f"Watchdog: encerrando fila e salvando parcial (motivo: {abort_reason})."
                        )
                        break

                    remaining: list[dict] = []
                    for item in blocked_items:
                        if _check_abort():
                            print(
                                f"Watchdog: encerrando fila e salvando parcial (motivo: {abort_reason})."
                            )
                            break

                        try:
                            retry_link = str(item["link"])
                            if _should_use_magalu_subprocess_timeout(headless, magalu_item_timeout_seconds):
                                retry_result = coletar_magalu_com_timeout(
                                    retry_link,
                                    headless=headless,
                                    timeout_seconds=magalu_item_timeout_seconds,
                                )
                            else:
                                retry_result = coletar_magalu(retry_link, headless=headless)
                        except Exception as e:
                            retry_result = {"status": f"ERRO NO COLETOR: {type(e).__name__} | {e}"}

                        if isinstance(retry_result, dict) and _status_blocked(retry_result):
                            remaining.append(item)
                            continue

                        retry_price, _, _ = _resolve_output_prices(retry_result if isinstance(retry_result, dict) else {})
                        if retry_price is not None and str(retry_price).strip():
                            ws_out.cell(row=int(item["out_row"]), column=5).value = retry_price
                        else:
                            # Mantem marcador de bloqueio/indisponivel.
                            ws_out.cell(row=int(item["out_row"]), column=5).value = "INDISPONIVEL"

                        last_progress_at = time.time()

                    if abort_reason:
                        break
                    blocked_items = remaining
                    if not blocked_items:
                        break

        seen_import_rows: set[tuple[str, str, str]] = set()
        seen_import_ids: set[str] = set()

        if input_ml_path is not None:
            wb_ml = load_workbook(input_ml_path)
            ws_ml = wb_ml.active
            imported += _append_precollected_rows(
                ws_ml,
                ws_out,
                source_name="mercado_livre",
                only_ids=only_ids,
                max_rows=max_rows,
                summary=summary,
                seen_rows=seen_import_rows,
                seen_ids=seen_import_ids,
            )
        if input_ml_cotia_path is not None:
            same_as_main = False
            if input_ml_path is not None:
                try:
                    same_as_main = input_ml_cotia_path.resolve() == input_ml_path.resolve()
                except Exception:
                    same_as_main = str(input_ml_cotia_path) == str(input_ml_path)

            if same_as_main:
                print(
                    "Aviso: planilha Mercado Livre Cotia aponta para o mesmo arquivo "
                    "da planilha Mercado Livre principal. Importacao duplicada ignorada."
                )
            else:
                wb_ml_cotia = load_workbook(input_ml_cotia_path)
                ws_ml_cotia = wb_ml_cotia.active
                imported += _append_precollected_rows(
                    ws_ml_cotia,
                    ws_out,
                    source_name="mercado_livre",
                    only_ids=only_ids,
                    max_rows=max_rows,
                    summary=summary,
                    seen_rows=seen_import_rows,
                    seen_ids=seen_import_ids,
                )

        _append_summary_sheet(wb_out, summary)
        style_result_workbook(wb_out)
        wb_out.save(output_path)
        backup_path = _backup_output_file(output_path)
    finally:
        # Encerra todos os drivers criados
        for drv in drivers.values():
            try:
                drv.quit()
            except Exception:
                pass
        try:
            close_magalu_selenium_driver()
        except Exception:
            pass

    total = ws_in.max_row - 1
    if max_rows is not None or only_ids:
        print(
            f"OK - {processed} produtos processados (filtro aplicado). "
            f"Arquivo gerado: {output_path} | Backup: {backup_path}"
        )
    else:
        if imported:
            print(
                f"OK - {total} produtos processados + {imported} importados. "
                f"Arquivo gerado: {output_path} | Backup: {backup_path}"
            )
        else:
            print(f"OK - {total} produtos processados. Arquivo gerado: {output_path} | Backup: {backup_path}")


# ---------------- STATUS ----------------

def write_status(status: str):
    try:
        Path("run_status.txt").write_text(status, encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    write_status("RUNNING")
    try:
        main()
        write_status("FINISHED")
    except Exception:
        write_status("FAILED")
        raise


