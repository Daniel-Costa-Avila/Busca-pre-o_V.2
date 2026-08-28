from __future__ import annotations

import html
import hmac
import os
import re
import unicodedata
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import streamlit.components.v1 as components

API_BASE = (
    os.getenv("UI_API_BASE")
    or os.getenv("API_BASE", "http://127.0.0.1:8000")
).rstrip("/")
API_TOKEN = os.getenv("API_TOKEN", "").strip()
UI_BRAND_NAME = os.getenv("UI_BRAND_NAME", "Busca Preço").strip() or "Busca Preço"
RESULT_SYSTEM_NAME = (os.getenv("RESULT_SYSTEM_NAME") or UI_BRAND_NAME or "Busca-Preço").strip() or "Busca-Preço"
AUTO_DAILY_UPDATE_TIME = (os.getenv("AUTO_DAILY_UPDATE_TIME") or "06:00").strip() or "06:00"


def _slugify_filename(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "arquivo"
    normalized = unicodedata.normalize("NFKD", raw)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.replace(" ", "-")
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", normalized)
    normalized = re.sub(r"[-_]{2,}", "-", normalized)
    normalized = normalized.strip("-_")
    return normalized or "arquivo"


def _daily_result_filename(dt: datetime | None = None) -> str:
    return "resultados-agentes-de-precos.xlsx"


def _parse_bool_env(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    normalized = str(raw_value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


APP_AUTH_USER = os.getenv("APP_AUTH_USER", "").strip()
APP_AUTH_PASSWORD = os.getenv("APP_AUTH_PASSWORD", "").strip()
PASSWORD_AUTH_ENABLED = _parse_bool_env(os.getenv("PASSWORD_AUTH_ENABLED"), default=False)
AUTH_ENABLED = PASSWORD_AUTH_ENABLED and bool(APP_AUTH_USER and APP_AUTH_PASSWORD)
SHOW_SIDEBAR_USER_CARD = _parse_bool_env(
    os.getenv("SHOW_SIDEBAR_USER_CARD"),
    default=False,
)

EMBEDDED_HEIGHT = int(os.getenv("UI_EMBEDDED_HEIGHT", "1800"))
ADMIN_SESSION_HEADER = "X-User-Session"

st.set_page_config(
    page_title=UI_BRAND_NAME,
    layout="wide",
)

def _redirect_to_root_if_needed() -> None:
    """
    Evita o app ficar acessivel por caminhos alternativos (ex.: /frete) quando
    estiver atras de proxy/tunel. Mantem uma URL canonica no root.
    """
    try:
        base_path = (os.getenv("UI_BASE_PATH") or "").strip().strip("/")
        canonical = f"/{base_path}" if base_path else "/"
        url = str(getattr(st.context, "url", "") or "")
        parsed = urlparse(url)
        path = (parsed.path or "").strip()
        if path.lower().startswith("/frete"):
            st.markdown(
                f'<meta http-equiv="refresh" content="0;url={canonical}" />',
                unsafe_allow_html=True,
            )
            st.stop()
    except Exception:
        return


_redirect_to_root_if_needed()


def _install_dom_integrity_guard() -> None:
    """Protege o DOM do Streamlit contra tradutores e extensoes do navegador.

    Tradutores podem envolver ou mover nos de texto que ainda pertencem ao
    reconciliador React. Quando a tela muda, o React tenta remover o no da
    posicao original e o navegador dispara NotFoundError em removeChild.
    """

    components.html(
        """
        <script>
        (() => {
          try {
            const hostWindow = window.parent;
            const hostDocument = hostWindow.document;
            const root = hostDocument.documentElement;

            root.setAttribute("translate", "no");
            root.classList.add("notranslate");
            if (hostDocument.body) {
              hostDocument.body.setAttribute("translate", "no");
              hostDocument.body.classList.add("notranslate");
            }

            if (!hostDocument.head.querySelector('meta[name="google"][content="notranslate"]')) {
              const meta = hostDocument.createElement("meta");
              meta.name = "google";
              meta.content = "notranslate";
              hostDocument.head.appendChild(meta);
            }

            if (!hostWindow.__buscaPrecoDomIntegrityGuard) {
              const nodePrototype = hostWindow.Node.prototype;
              const nativeRemoveChild = nodePrototype.removeChild;
              const nativeInsertBefore = nodePrototype.insertBefore;

              Object.defineProperty(nodePrototype, "removeChild", {
                configurable: true,
                writable: true,
                value(child) {
                  if (child && child.parentNode !== this) {
                    return child;
                  }
                  return nativeRemoveChild.call(this, child);
                },
              });

              Object.defineProperty(nodePrototype, "insertBefore", {
                configurable: true,
                writable: true,
                value(newNode, referenceNode) {
                  if (referenceNode && referenceNode.parentNode !== this) {
                    return nativeInsertBefore.call(this, newNode, null);
                  }
                  return nativeInsertBefore.call(this, newNode, referenceNode);
                },
              });

              hostWindow.__buscaPrecoDomIntegrityGuard = true;
            }

            if (window.frameElement) {
              window.frameElement.setAttribute("aria-hidden", "true");
              window.frameElement.style.display = "none";
            }
          } catch (_) {
            // A interface continua funcionando mesmo se o navegador bloquear
            // o acesso do componente ao documento principal.
          }
        })();
        </script>
        """,
        height=0,
        width=0,
    )


def _should_embed_api_iframe() -> bool:
    raw = os.getenv("UI_EMBED_API_IFRAME")
    if raw is not None:
        return _parse_bool_env(raw, default=False)

    # Use o mesmo painel nativo em acessos locais e por proxy/túnel.
    return False


def _render_iframe(url: str, *, height: int) -> None:
    """
    Compatibilidade entre versões do Streamlit:
    - st.iframe() não aceita 'scrolling' em algumas versões.
    - components.iframe() aceita.
    """

    try:
        st.iframe(url, height=height)
    except TypeError:
        components.iframe(url, height=height, scrolling=True)


def _render_shell_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --font-display: "SF Pro Display", "SF Pro Text", "Avenir Next", "Manrope", "Segoe UI", sans-serif;
            --font-body: "SF Pro Text", "Avenir Next", "Public Sans", "Segoe UI", sans-serif;
            --bg-base: #050914;
            --bg-muted: #0b1220;
            --surface: rgba(15, 23, 42, 0.78);
            --surface-strong: rgba(15, 23, 42, 0.92);
            --ink: #e5e7eb;
            --muted: rgba(226, 232, 240, 0.72);
            --line-soft: rgba(148, 163, 184, 0.18);
            --accent: #3b82f6;
            --accent-strong: #60a5fa;
            --success: #22c55e;
            --warning: #f59e0b;
            --danger: #ef4444;
            --radius-lg: 24px;
            --radius-md: 16px;
            --radius-sm: 12px;
            --shadow-soft: 0 18px 42px rgba(0, 0, 0, 0.42);
            --btn-grad: linear-gradient(138deg, rgba(59, 130, 246, 0.96) 0%, rgba(37, 99, 235, 0.96) 100%);
            --shadow-card: 0 18px 50px rgba(0, 0, 0, 0.46);
            --shadow-inner: inset 0 1px 0 rgba(255, 255, 255, 0.06);
            --ring: 0 0 0 4px rgba(96, 165, 250, 0.16);
            --ring-strong: 0 0 0 5px rgba(96, 165, 250, 0.22);
        }

        [data-testid="stHeader"] {
            display: none;
        }
        [data-testid="stToolbar"] {
            display: none;
        }
        [data-testid="stDecoration"] {
            display: none;
        }
        [data-testid="stSidebar"] {
            display: none;
        }
        [data-testid="collapsedControl"] {
            display: none;
        }
        [data-testid="stStatusWidget"] {
            display: none;
        }
        #MainMenu, footer {
            display: none;
        }
        html, body {
            font-family: var(--font-body);
            color: var(--ink);
            font-size: 16px !important;
            line-height: 1.6;
        }
        /* Remove o grid de fundo para evitar "linhas soltas" entre blocos. */
        [data-testid="stAppViewContainer"]::before {
            display: none;
        }
        /* Remove divisores nativos (st.divider) que parecem linhas soltas. */
        div[data-testid="stDivider"] {
            display: none;
        }
        [data-testid="stAppViewContainer"]::after {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            opacity: 0.08;
            background-image:
                radial-gradient(circle at 30% 10%, rgba(59, 130, 246, 0.55), transparent 40%),
                radial-gradient(circle at 90% 0%, rgba(56, 189, 248, 0.40), transparent 44%),
                radial-gradient(circle at 65% 100%, rgba(34, 197, 94, 0.18), transparent 46%);
            filter: blur(40px);
        }
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 12% 0%, rgba(59, 130, 246, 0.20) 0%, transparent 36%),
                radial-gradient(circle at 100% 0%, rgba(56, 189, 248, 0.16) 0%, transparent 40%),
                linear-gradient(180deg, var(--bg-base) 0%, var(--bg-muted) 100%);
        }
        .block-container {
            padding-top: 0.5rem;
            padding-bottom: 0;
            padding-left: 0.75rem;
            padding-right: 0.75rem;
            max-width: none;
            position: relative;
            z-index: 1;
        }
        iframe {
            border-radius: 0.75rem;
        }

        .pm-topbar {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 12px;
            align-items: center;
            padding: 14px 16px;
            background: var(--surface);
            border: 1px solid var(--line-soft);
            border-radius: var(--radius-lg);
            box-shadow: var(--shadow-card);
            backdrop-filter: blur(10px);
            position: relative;
            overflow: hidden;
        }
        .pm-topbar::before {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            opacity: 0.9;
            background: linear-gradient(180deg, rgba(255,255,255,0.06) 0%, transparent 48%);
        }
        .pm-layout {
            display: grid;
            grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
            gap: 14px;
            margin-top: 12px;
        }
        .pm-sidebar {
            padding: 14px;
        }
        .pm-nav-title {
            margin: 0 0 10px 0;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.11em;
            text-transform: uppercase;
            color: var(--muted);
        }
        .pm-help {
            margin-top: 12px;
            color: var(--muted);
            font-size: 0.86rem;
            line-height: 1.4;
        }
        .pm-main {
            display: grid;
            gap: 12px;
        }
        .pm-pathbar {
            display: grid;
            gap: 4px;
            padding: 12px 14px;
            border-radius: var(--radius-lg);
            border: 1px solid var(--line-soft);
            background: rgba(2, 6, 23, 0.35);
            box-shadow: var(--shadow-inner);
        }
        .pm-pathbar strong {
            font-family: var(--font-display);
            font-size: 1.05rem;
            letter-spacing: -0.02em;
        }
        .pm-brand {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }
        .pm-mark {
            width: 48px;
            height: 48px;
            border-radius: 14px;
            background: var(--btn-grad);
            display: grid;
            place-items: center;
            color: white;
            font-weight: 800;
            font-family: var(--font-display);
            letter-spacing: -0.02em;
        }
        .pm-title {
            font-family: var(--font-display);
            font-weight: 800;
            letter-spacing: -0.02em;
            font-size: 1.15rem;
            margin: 0;
            line-height: 1.2;
        }
        .pm-sub {
            margin: 2px 0 0 0;
            color: var(--muted);
            font-size: 0.88rem;
            line-height: 1.4;
        }
        .pm-actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: flex-end;
        }
        .pm-glass {
            background: var(--surface);
            border: 1px solid var(--line-soft);
            border-radius: var(--radius-lg);
            box-shadow: var(--shadow-card);
            backdrop-filter: blur(10px);
            position: relative;
            overflow: hidden;
        }
        .pm-glass::before {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            background: linear-gradient(180deg, rgba(255,255,255,0.06), transparent 55%);
            opacity: 0.75;
        }

        /* Remove "linhas soltas" (sheen) em containers principais. */
        .pm-sidebar.pm-glass::before,
        .pm-pathbar.pm-glass::before,
        .pm-panel.pm-glass::before {
            display: none;
        }
        .pm-panel {
            padding: 16px;
            position: relative;
            z-index: 1;
        }
        .pm-kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
        }
        .pm-kpi {
            padding: 14px 14px 12px 14px;
            border-radius: var(--radius-md);
            border: 1px solid var(--line-soft);
            background: rgba(2, 6, 23, 0.35);
            box-shadow: var(--shadow-inner);
            position: relative;
            overflow: hidden;
        }
        .pm-kpi::after {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            opacity: 0.65;
            background: radial-gradient(circle at 20% 0%, rgba(59, 130, 246, 0.18), transparent 44%);
        }
        .pm-kpi p {
            margin: 0;
            color: var(--muted);
            font-size: 0.8rem;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            font-weight: 700;
            position: relative;
            z-index: 1;
        }
        .pm-kpi strong {
            display: block;
            margin-top: 8px;
            font-family: var(--font-display);
            font-size: 2rem;
            letter-spacing: -0.03em;
            position: relative;
            z-index: 1;
        }
        .pm-tone-wait strong { color: var(--warning); }
        .pm-tone-run strong { color: var(--accent-strong); }
        .pm-tone-done strong { color: var(--success); }
        .pm-tone-fail strong { color: var(--danger); }
        .pm-kicker {
            margin: 0 0 4px 0;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.11em;
            text-transform: uppercase;
            color: var(--muted);
        }

        .pm-info-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
        }
        .pm-card {
            padding: 14px;
            border-radius: var(--radius-md);
            border: 1px solid var(--line-soft);
            background: rgba(2, 6, 23, 0.35);
            box-shadow: var(--shadow-inner);
            position: relative;
            overflow: hidden;
        }
        .pm-card::after {
            content: "";
            position: absolute;
            inset: 0;
            pointer-events: none;
            opacity: 0.75;
            background:
              radial-gradient(circle at 25% 0%, rgba(59, 130, 246, 0.16), transparent 55%),
              radial-gradient(circle at 90% 10%, rgba(56, 189, 248, 0.12), transparent 55%);
        }
        .pm-card > * { position: relative; z-index: 1; }
        .pm-card-title {
            margin: 0 0 10px 0;
            font-family: var(--font-display);
            font-size: 0.98rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }
        .pm-kv {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 9px 10px;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.14);
            background: rgba(15, 23, 42, 0.46);
        }
        .pm-kv + .pm-kv { margin-top: 10px; }
        .pm-kv span:first-child {
            color: var(--muted);
            font-size: 0.86rem;
        }
        .pm-mono {
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
            font-size: 0.86rem;
            color: rgba(226, 232, 240, 0.9);
            word-break: break-word;
        }
        .pm-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 10px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.02em;
            border: 1px solid rgba(148, 163, 184, 0.18);
            background: rgba(2, 6, 23, 0.35);
            color: var(--ink);
            white-space: nowrap;
        }
        .pm-badge-ok { border-color: rgba(34, 197, 94, 0.25); color: rgba(34, 197, 94, 0.95); }
        .pm-badge-warn { border-color: rgba(245, 158, 11, 0.25); color: rgba(245, 158, 11, 0.95); }
        .pm-badge-bad { border-color: rgba(239, 68, 68, 0.25); color: rgba(239, 68, 68, 0.95); }
        .pm-badge-info { border-color: rgba(96, 165, 250, 0.25); color: rgba(96, 165, 250, 0.95); }

        /* Buttons */
        .stButton > button {
            border-radius: 14px !important;
            padding: 0.6rem 0.9rem !important;
            border: 1px solid rgba(148, 163, 184, 0.24) !important;
            box-shadow: var(--shadow-inner) !important;
            color: #0f172a !important;
            background: linear-gradient(180deg, #ffffff 0%, #f1f5f9 100%) !important;
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%) !important;
            border: 1px solid rgba(37, 99, 235, 0.35) !important;
            color: white !important;
            box-shadow: 0 16px 34px rgba(59, 130, 246, 0.28) !important;
        }
        .stButton > button[kind="secondary"] {
            background: linear-gradient(180deg, #ffffff 0%, #e5e7eb 100%) !important;
            color: #0f172a !important;
        }
        .stButton > button[aria-label*="Executar"] {
            background: linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%) !important;
            border-color: rgba(37, 99, 235, 0.35) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Baixar"] {
            background: linear-gradient(135deg, #16a34a 0%, #22c55e 100%) !important;
            border-color: rgba(22, 163, 74, 0.35) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Atualizar"] {
            background: linear-gradient(135deg, #0891b2 0%, #06b6d4 100%) !important;
            border-color: rgba(8, 145, 178, 0.35) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Parar"] {
            background: linear-gradient(135deg, #dc2626 0%, #f97316 100%) !important;
            border-color: rgba(220, 38, 38, 0.35) !important;
            color: #ffffff !important;
        }
        .stButton > button:hover { filter: brightness(1.04); }
        .stButton > button:focus { box-shadow: var(--ring-strong) !important; }

        /* Nav buttons (inside the faux-sidebar) */
        .pm-sidebar [data-testid="stButton"] button {
            justify-content: flex-start !important;
            gap: 10px !important;
            font-weight: 800 !important;
            letter-spacing: -0.01em !important;
            padding: 0.72rem 0.9rem !important;
        }

        [data-testid="stTabs"] button {
            color: var(--muted) !important;
        }
        [data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--ink) !important;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stSelectbox"] div,
        [data-testid="stFileUploaderDropzone"] {
            background: rgba(2, 6, 23, 0.40) !important;
            border-color: rgba(148, 163, 184, 0.22) !important;
            color: var(--ink) !important;
        }
        [data-testid="stForm"] {
            border: 1px solid rgba(148, 163, 184, 0.18) !important;
            border-radius: var(--radius-lg) !important;
            padding: 14px !important;
            background: rgba(2, 6, 23, 0.20) !important;
        }
        [data-testid="stJson"] {
            border-radius: var(--radius-md) !important;
            border: 1px solid rgba(148, 163, 184, 0.16) !important;
            background: rgba(2, 6, 23, 0.32) !important;
            box-shadow: var(--shadow-inner) !important;
        }
        pre, code {
            color: rgba(226, 232, 240, 0.92) !important;
        }

        @media (max-width: 980px) {
            .pm-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .pm-info-grid { grid-template-columns: 1fr; }
        }
        @media (max-width: 520px) {
            .pm-kpi-grid { grid-template-columns: 1fr; }
        }

        .pm-auto-banner {
            position: sticky;
            top: 0.75rem;
            z-index: 999;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.15rem 0 1rem 0;
            padding: 0.9rem 1.05rem;
            border-radius: 18px;
            border: 1px solid rgba(96, 165, 250, 0.38);
            background: linear-gradient(135deg, rgba(2, 132, 199, 0.26) 0%, rgba(30, 64, 175, 0.24) 45%, rgba(15, 23, 42, 0.74) 100%);
            box-shadow: 0 18px 48px rgba(2, 132, 199, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.06);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
        }

        .pm-auto-banner__left {
            display: flex;
            align-items: center;
            gap: 0.9rem;
            min-width: 0;
        }

        .pm-auto-banner__icon {
            width: 40px;
            height: 40px;
            border-radius: 14px;
            display: grid;
            place-items: center;
            font-family: var(--font-display);
            font-weight: 900;
            font-size: 1.05rem;
            color: rgba(255, 255, 255, 0.94);
            background: linear-gradient(152deg, rgba(59, 130, 246, 0.96) 0%, rgba(14, 165, 233, 0.96) 100%);
            box-shadow: 0 12px 26px rgba(37, 99, 235, 0.28);
            flex: 0 0 auto;
        }

        .pm-auto-banner__text { min-width: 0; }

        .pm-auto-banner__title {
            margin: 0;
            font-size: 1.06rem;
            font-weight: 900;
            letter-spacing: -0.01em;
            color: rgba(255, 255, 255, 0.96);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .pm-auto-banner__subtitle {
            margin: 0.2rem 0 0 0;
            font-size: 0.95rem;
            color: rgba(226, 232, 240, 0.82);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .pm-auto-banner__time {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.46rem 0.78rem;
            border-radius: 999px;
            font-weight: 900;
            font-size: 0.94rem;
            letter-spacing: 0.1em;
            border: 1px solid rgba(96, 165, 250, 0.38);
            background: rgba(2, 132, 199, 0.20);
            color: rgba(255, 255, 255, 0.94);
            flex: 0 0 auto;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }

        /* Redesign visual: tema escuro "Busca Preco", hierarquia clara */
        :root {
            --font-display: "SF Pro Display", "SF Pro Text", "Avenir Next", "Manrope", "Segoe UI", sans-serif !important;
            --font-body: "SF Pro Text", "Avenir Next", "Public Sans", "Segoe UI", sans-serif !important;
            --bg-base: #060a14 !important;
            --bg-muted: #0a0f1e !important;
            --surface: rgba(18, 26, 46, 0.72) !important;
            --surface-strong: rgba(22, 31, 53, 0.92) !important;
            --ink: #e7ecf7 !important;
            --muted: #8a97b3 !important;
            --line-soft: rgba(120, 150, 210, 0.16) !important;
            --line: rgba(120, 150, 210, 0.26) !important;
            --radius-lg: 18px !important;
            --radius-md: 14px !important;
            --radius-sm: 10px !important;
            --shadow-card: 0 18px 42px rgba(0, 0, 0, 0.4) !important;
            --shadow-inner: inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
        }

        html, body, [data-testid="stAppViewContainer"] {
            font-family: var(--font-body) !important;
            color: var(--ink) !important;
            background:
                radial-gradient(circle at 12% 0%, rgba(59, 109, 255, 0.16) 0%, transparent 38%),
                radial-gradient(circle at 100% 10%, rgba(109, 60, 220, 0.12) 0%, transparent 42%),
                linear-gradient(180deg, var(--bg-base) 0%, var(--bg-muted) 100%) !important;
        }
        [data-testid="stAppViewContainer"]::after {
            display: none !important;
        }
        [data-testid="stAppViewContainer"] * {
            font-family: var(--font-body) !important;
        }
        .block-container {
            max-width: 1340px !important;
            padding-top: 0.8rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            margin: 0 auto !important;
        }

        .pm-topbar,
        .pm-pathbar,
        .pm-panel,
        .pm-sidebar,
        .pm-kpi,
        .pm-card {
            background: var(--surface) !important;
            border-color: var(--line-soft) !important;
            box-shadow: var(--shadow-card) !important;
        }

        .pm-topbar {
            padding: 16px 18px !important;
            border-radius: 18px !important;
        }
        .pm-brand .pm-title {
            font-size: 1.28rem !important;
            font-weight: 700 !important;
            letter-spacing: -0.01em !important;
            color: var(--ink) !important;
        }
        .pm-sub {
            color: var(--muted) !important;
        }

        .pm-kpi p {
            color: var(--muted) !important;
            font-size: 0.76rem !important;
        }
        .pm-kpi strong {
            color: var(--ink) !important;
            font-size: 2.1rem !important;
        }
        .pm-tone-wait::before,
        .pm-tone-run::before,
        .pm-tone-done::before,
        .pm-tone-fail::before,
        .pm-kpi::after,
        .pm-card::after {
            display: none !important;
        }

        .pm-nav-title,
        .pm-kicker {
            color: var(--muted) !important;
            font-weight: 700 !important;
        }
        .pm-pathbar strong,
        .pm-card-title {
            color: var(--ink) !important;
            letter-spacing: -0.01em !important;
        }

        .pm-kv {
            background: rgba(120, 150, 220, 0.06) !important;
            border: 1px solid var(--line-soft) !important;
            border-radius: 10px !important;
        }
        .pm-kv span:first-child,
        .pm-mono {
            color: var(--muted) !important;
        }
        .pm-badge {
            background: rgba(138, 151, 179, 0.14) !important;
            border-color: var(--line) !important;
            color: var(--ink) !important;
        }
        .pm-badge-ok {
            background: rgba(52, 211, 153, 0.14) !important;
            border-color: rgba(52, 211, 153, 0.4) !important;
            color: #6ee7b7 !important;
        }
        .pm-badge-warn {
            background: rgba(251, 191, 36, 0.14) !important;
            border-color: rgba(251, 191, 36, 0.4) !important;
            color: #fcd34d !important;
        }
        .pm-badge-bad {
            background: rgba(239, 68, 68, 0.14) !important;
            border-color: rgba(239, 68, 68, 0.4) !important;
            color: #fca5a5 !important;
        }
        .pm-badge-info {
            background: rgba(59, 109, 255, 0.14) !important;
            border-color: rgba(59, 109, 255, 0.4) !important;
            color: #a9c2ff !important;
        }

        .pm-sidebar [data-testid="stButton"] button {
            justify-content: flex-start !important;
            border-radius: 12px !important;
            border: 1px solid transparent !important;
            background: transparent !important;
            color: var(--muted) !important;
            box-shadow: none !important;
        }
        .pm-sidebar [data-testid="stButton"] button:hover {
            background: rgba(120, 150, 220, 0.1) !important;
            color: var(--ink) !important;
        }
        .pm-sidebar [data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(135deg, #3b6dff 0%, #2447c9 100%) !important;
            border-color: rgba(59, 109, 255, 0.4) !important;
            color: #ffffff !important;
            box-shadow: 0 8px 20px rgba(36, 71, 201, 0.34) !important;
        }

        .stButton > button {
            border-radius: 12px !important;
            font-weight: 600 !important;
        }
        .stButton > button[aria-label*="Executar"] {
            background: linear-gradient(135deg, #3b6dff 0%, #2447c9 100%) !important;
            border-color: rgba(59, 109, 255, 0.4) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Baixar"] {
            background: linear-gradient(135deg, #e6394a 0%, #c81f30 100%) !important;
            border-color: rgba(230, 57, 74, 0.4) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Atualizar"] {
            background: linear-gradient(135deg, #0891b2 0%, #0e7490 100%) !important;
            border-color: rgba(8, 145, 178, 0.4) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Parar"] {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
            border-color: rgba(220, 38, 38, 0.4) !important;
            color: #ffffff !important;
        }

        .pm-auto-banner {
            border-radius: 16px !important;
            border: 1px solid rgba(96, 165, 250, 0.38) !important;
            background: linear-gradient(135deg, rgba(2, 132, 199, 0.26) 0%, rgba(30, 64, 175, 0.24) 45%, rgba(15, 23, 42, 0.74) 100%) !important;
            box-shadow: 0 18px 48px rgba(2, 132, 199, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
        }
        .pm-auto-banner__title {
            color: rgba(255, 255, 255, 0.96) !important;
        }
        .pm-auto-banner__subtitle {
            color: rgba(226, 232, 240, 0.82) !important;
        }
        .pm-auto-banner__time,
        .pm-auto-banner__icon {
            background: linear-gradient(135deg, #3b6dff 0%, #2447c9 100%) !important;
            color: #ffffff !important;
            border-color: rgba(59, 109, 255, 0.4) !important;
        }

        /* Bloco de execução manual: melhorar contraste e legibilidade */
        [data-testid="stExpander"] details {
            border: 1px solid var(--line-soft) !important;
            border-radius: 12px !important;
            background: var(--surface) !important;
        }
        [data-testid="stExpander"] details summary::-webkit-details-marker {
            display: none !important;
        }
        [data-testid="stExpander"] summary {
            position: relative !important;
            padding-left: 2rem !important;
            background: transparent !important;
            color: var(--ink) !important;
        }
        [data-testid="stExpander"] summary::before {
            content: "▸";
            position: absolute;
            left: 0.75rem;
            top: 50%;
            transform: translateY(-50%);
            color: var(--muted);
            font-size: 0.95rem;
            line-height: 1;
        }
        [data-testid="stExpander"] details[open] summary::before {
            content: "▾";
        }
        [data-testid="stExpanderToggleIcon"] {
            display: none !important;
        }
        [data-testid="stExpander"] summary p {
            color: var(--ink) !important;
            font-weight: 600 !important;
            margin: 0 !important;
        }

        [data-testid="stFileUploaderDropzone"] {
            background: rgba(2, 6, 23, 0.4) !important;
            border: 1px solid var(--line) !important;
            color: var(--muted) !important;
        }
        [data-testid="stFileUploaderDropzone"] * {
            color: var(--muted) !important;
        }
        [data-testid="stFileUploaderDropzone"] button {
            min-width: 132px !important;
            border-radius: 10px !important;
            border: 1px solid rgba(59, 109, 255, 0.4) !important;
            background: linear-gradient(135deg, #3b6dff 0%, #2447c9 100%) !important;
            color: #ffffff !important;
            font-weight: 700 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            box-shadow: none !important;
        }
        [data-testid="stFileUploaderDropzone"] button:hover {
            filter: brightness(1.04) !important;
        }
        [data-testid="stFileUploaderDropzone"] button p,
        [data-testid="stFileUploaderDropzone"] button span {
            color: #ffffff !important;
            margin: 0 !important;
            line-height: 1.2 !important;
        }
        [data-testid="stFileUploaderDropzone"] small,
        [data-testid="stFileUploaderDropzone"] [data-testid="stCaptionContainer"],
        [data-testid="stFileUploaderDropzone"] [data-testid="stMarkdownContainer"] p {
            color: var(--muted) !important;
            opacity: 1 !important;
        }

        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] span {
            color: var(--muted) !important;
            opacity: 1 !important;
        }
        [data-testid="stCheckbox"] p {
            color: var(--muted) !important;
            opacity: 1 !important;
            font-weight: 600 !important;
        }

        .stButton > button:disabled {
            background: rgba(120, 150, 220, 0.08) !important;
            border-color: var(--line-soft) !important;
            color: #64748b !important;
            opacity: 1 !important;
            box-shadow: none !important;
        }
        .stDownloadButton > button,
        [data-testid="stDownloadButton"] button {
            border-radius: 12px !important;
            border: 1px solid rgba(230, 57, 74, 0.4) !important;
            background: linear-gradient(135deg, #e6394a 0%, #c81f30 100%) !important;
            color: #ffffff !important;
            font-weight: 600 !important;
            box-shadow: 0 10px 24px rgba(200, 31, 48, 0.3) !important;
        }
        .stDownloadButton > button:disabled,
        [data-testid="stDownloadButton"] button:disabled {
            background: rgba(120, 150, 220, 0.08) !important;
            border-color: var(--line-soft) !important;
            color: #64748b !important;
            box-shadow: none !important;
        }

        /* Correcao final da tela "Manual de Execucao" */
        [data-testid="stButton"] button {
            color: var(--ink) !important;
            background: rgba(120, 150, 220, 0.1) !important;
            border: 1px solid var(--line) !important;
        }
        [data-testid="stButton"] button[aria-label*="Executar com base cadastrada"] {
            background: linear-gradient(135deg, #e6394a 0%, #c81f30 100%) !important;
            border-color: rgba(230, 57, 74, 0.4) !important;
            color: #ffffff !important;
        }
        [data-testid="stButton"] button[aria-label*="Executar com sua planilha"] {
            background: linear-gradient(135deg, #3b6dff 0%, #2447c9 100%) !important;
            border-color: rgba(59, 109, 255, 0.4) !important;
            color: #ffffff !important;
        }
        [data-testid="stButton"] button:disabled,
        [data-testid="stButton"] button[aria-label*="Executar com sua planilha"]:disabled,
        [data-testid="stButton"] button[aria-label*="Executar com base cadastrada"]:disabled {
            background: rgba(120, 150, 220, 0.08) !important;
            border-color: var(--line-soft) !important;
            color: #64748b !important;
            text-shadow: none !important;
            opacity: 1 !important;
            box-shadow: none !important;
        }

        [data-testid="stDownloadButton"] button {
            background: linear-gradient(135deg, #34d399 0%, #16a34a 100%) !important;
            border-color: rgba(22, 163, 74, 0.4) !important;
            color: #ffffff !important;
        }
        [data-testid="stDownloadButton"] button:disabled {
            background: rgba(120, 150, 220, 0.08) !important;
            border-color: var(--line-soft) !important;
            color: #64748b !important;
            opacity: 1 !important;
        }

        /* Funnel: correcao definitiva do uploader (evita "uploadcarregar" sobreposto) */
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] button {
            position: relative !important;
            min-width: 156px !important;
            height: 36px !important;
            padding: 0 14px !important;
            border-radius: 10px !important;
            border: 1px solid rgba(59, 109, 255, 0.4) !important;
            background: linear-gradient(135deg, #3b6dff 0%, #2447c9 100%) !important;
            box-shadow: none !important;
            color: transparent !important;
            overflow: hidden !important;
        }
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] button * {
            display: none !important;
        }
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] button::after {
            content: "Carregar arquivo";
            position: absolute;
            inset: 0;
            display: grid;
            place-items: center;
            color: #ffffff;
            font-weight: 700;
            font-size: 0.9rem;
            line-height: 1;
            white-space: nowrap;
        }
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] small,
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] p,
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] span {
            color: var(--muted) !important;
            opacity: 1 !important;
        }

        /* Funnel: cor forte para o texto do checkbox acima do upload */
        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] label p,
        [data-testid="stCheckbox"] div,
        [data-testid="stCheckbox"] span {
            color: var(--muted) !important;
            opacity: 1 !important;
            font-weight: 600 !important;
        }

        /* Esconde texto de icone quebrado (ex.: keyboard_arrow_down) */
        [data-testid="stExpander"] summary [class*="material"],
        [data-testid="stExpander"] summary i {
            display: none !important;
        }

        /* Layout de referência — dashboard Busca Preço */
        :root {
            --bp-bg: #020713;
            --bp-panel: #041022;
            --bp-panel-2: #061329;
            --bp-border: #10203b;
            --bp-border-soft: rgba(57, 91, 145, 0.22);
            --bp-blue: #1268ff;
            --bp-blue-2: #0848d8;
            --bp-text: #f5f7fb;
            --bp-muted: #98a4bb;
            --bp-green: #11c968;
            --bp-amber: #f5a524;
            --bp-red: #ef233c;
        }
        html, body, [data-testid="stAppViewContainer"] {
            background: var(--bp-bg) !important;
            color: var(--bp-text) !important;
        }
        [data-testid="stAppViewContainer"] {
            background:
              radial-gradient(circle at 72% -20%, rgba(16, 83, 210, 0.10), transparent 36%),
              linear-gradient(180deg, #020713 0%, #030a17 100%) !important;
        }
        .block-container {
            max-width: 1600px !important;
            padding: 0.8rem 0.8rem 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.pm-sidebar-brand) {
            align-items: stretch !important;
            gap: 14px !important;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) {
            min-width: 238px !important;
            max-width: 270px !important;
            flex: 0 0 255px !important;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) > div[data-testid="stVerticalBlock"] {
            min-height: calc(100vh - 26px);
            padding: 16px 13px 14px;
            border: 1px solid var(--bp-border);
            border-radius: 13px;
            background: rgba(2, 8, 20, 0.94);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.018);
            gap: 5px !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) {
            min-width: 0 !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) > div[data-testid="stVerticalBlock"] {
            gap: 13px !important;
        }
        .pm-sidebar-brand {
            display: flex;
            align-items: center;
            gap: 11px;
            min-height: 78px;
            padding: 4px 4px 14px;
            border-bottom: 1px solid rgba(19, 41, 75, 0.42);
            margin-bottom: 13px;
        }
        .pm-sidebar-logo {
            position: relative;
            width: 45px;
            height: 45px;
            flex: 0 0 45px;
            border: 3px solid #1472ff;
            border-radius: 50%;
            color: #1472ff;
            display: grid;
            place-items: center;
            font: 800 24px/1 var(--font-display);
            box-shadow: 0 0 18px rgba(20, 114, 255, 0.18);
        }
        .pm-sidebar-logo::after {
            content: "";
            position: absolute;
            width: 22px;
            height: 4px;
            right: -16px;
            bottom: -5px;
            border-radius: 4px;
            background: #1472ff;
            transform: rotate(47deg);
        }
        .pm-sidebar-name {
            color: #f6f7fb;
            font-size: 1.22rem;
            font-weight: 800;
            letter-spacing: -0.03em;
            white-space: nowrap;
        }
        .pm-sidebar-name span { color: #1472ff; }
        .pm-sidebar-tagline {
            margin-top: 1px;
            color: #c9d2e3;
            font-size: 0.57rem;
            font-weight: 700;
            letter-spacing: 0.18em;
            white-space: nowrap;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button {
            min-height: 50px !important;
            justify-content: flex-start !important;
            padding: 0 15px !important;
            border: 1px solid transparent !important;
            border-radius: 9px !important;
            background: transparent !important;
            color: #f1f4fa !important;
            box-shadow: none !important;
            font-size: 0.94rem !important;
            font-weight: 500 !important;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button:hover {
            background: rgba(18, 104, 255, 0.11) !important;
            border-color: rgba(18, 104, 255, 0.22) !important;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(180deg, #1472ff 0%, #0750db 100%) !important;
            border-color: #1c75ff !important;
            color: #ffffff !important;
            box-shadow: 0 8px 20px rgba(5, 72, 216, 0.27), inset 0 1px 0 rgba(255,255,255,0.16) !important;
            font-weight: 700 !important;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button p {
            width: 100%;
            margin: 0 !important;
            text-align: left;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stElementContainer"]:has(.pm-user-card) {
            margin-top: auto !important;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stElementContainer"]:has(.pm-version) {
            margin-top: auto !important;
        }
        .pm-sidebar-spacer { min-height: 0; }
        .pm-user-card {
            margin-top: auto;
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 13px 10px;
            border: 1px solid var(--bp-border);
            border-radius: 10px;
            background: rgba(5, 16, 35, 0.88);
        }
        .pm-user-avatar {
            width: 38px;
            height: 38px;
            border-radius: 50%;
            display: grid;
            place-items: center;
            background: linear-gradient(145deg, #31579b, #17305d);
            color: #fff;
            font-size: 1.1rem;
        }
        .pm-user-name { color: #fff; font-weight: 700; font-size: 0.87rem; }
        .pm-user-role { color: #2d7dff; font-size: 0.75rem; }
        .pm-version { color: #78859d; font-size: 0.69rem; padding: 6px 1px 0; }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button::before {
            width: 22px;
            flex: 0 0 22px;
            color: currentColor;
            font-size: 1.15rem;
            line-height: 1;
            text-align: center;
        }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[aria-label*="Resumo"]::before { content: "⌂"; }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[aria-label*="Execução Manual"]::before { content: "▷"; }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[aria-label="Status"]::before { content: "◉"; }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[aria-label*="Histórico"]::before { content: "◷"; }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[aria-label*="Downloads"]::before { content: "⇩"; }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[aria-label*="Configurações"]::before { content: "⚙"; }
        div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button[aria-label*="Ajuda"]::before { content: "?"; }

        .pm-main-marker { display: none; }
        .pm-dashboard-header {
            min-height: 98px;
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: center;
            gap: 24px;
            padding: 17px 26px;
            border: 1px solid var(--bp-border);
            border-radius: 13px;
            background: linear-gradient(110deg, rgba(4,16,34,0.98), rgba(3,12,27,0.97));
        }
        .pm-dashboard-title {
            color: #fff;
            font-size: 1.45rem;
            font-weight: 750;
            letter-spacing: -0.025em;
        }
        .pm-dashboard-subtitle { margin-top: 3px; color: var(--bp-muted); font-size: 0.91rem; }
        .pm-header-meta {
            min-width: 310px;
            display: grid;
            grid-template-columns: 48px 1fr;
            gap: 0 16px;
            align-items: center;
            padding-left: 22px;
            border-left: 1px solid rgba(40, 69, 111, 0.27);
            color: #aeb8ca;
            font-size: 0.84rem;
        }
        .pm-header-bell {
            grid-row: 1 / span 2;
            position: relative;
            font-size: 1.55rem;
            color: #dce5f4;
        }
        /* O ponto so acende quando existe alerta de verdade (ver alert_count). */
        .pm-header-bell.has-alert::after {
            content: attr(data-count);
            position: absolute;
            min-width: 17px;
            height: 17px;
            padding: 0 4px;
            display: grid;
            place-items: center;
            border-radius: 999px;
            background: var(--bp-amber);
            color: #1a1200;
            font-size: .62rem;
            font-weight: 800;
            line-height: 1;
            top: 0;
            right: 6px;
            box-shadow: 0 0 10px rgba(245,165,36,.45);
        }
        .pm-header-line { display: flex; align-items: center; gap: 11px; min-height: 28px; }
        .pm-header-line b { color: #8eb3ff; font-weight: 500; font-size: 1.1rem; }

        .pm-context-card {
            min-height: 180px;
            display: grid;
            grid-template-columns: minmax(360px, 0.95fr) minmax(360px, 1.05fr);
            align-items: center;
            gap: 20px;
            padding: 18px 28px;
            border: 1px solid var(--bp-border);
            border-radius: 13px;
            background: linear-gradient(105deg, rgba(3,13,29,.98), rgba(3,14,32,.94));
            overflow: hidden;
        }
        .pm-context-copy { display: grid; grid-template-columns: 42px 1fr; gap: 18px; align-items: start; }
        .pm-context-icon {
            width: 30px;
            height: 30px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background: #116cff;
            color: #07142d;
            font-weight: 900;
            box-shadow: 0 0 20px rgba(17,108,255,.35);
        }
        .pm-context-icon.ok { background: var(--bp-green); color: #04240f; box-shadow: 0 0 20px rgba(17,201,104,.32); }
        .pm-context-icon.warn { background: var(--bp-amber); color: #1a1200; box-shadow: 0 0 20px rgba(245,165,36,.32); }
        .pm-context-icon.bad { background: var(--bp-red); color: #2a0308; box-shadow: 0 0 20px rgba(239,35,60,.32); }
        .pm-context-name.big { font-size: 1.24rem; font-weight: 700; letter-spacing: -0.02em; }
        .pm-context-label { color: #1875ff; font-weight: 800; font-size: 1.05rem; letter-spacing: .02em; }
        .pm-context-name { margin-top: 21px; color: #fff; font-size: 1.04rem; font-weight: 650; }
        .pm-context-description { margin-top: 3px; color: var(--bp-muted); font-size: 0.86rem; }
        .pm-context-art { height: 140px; width: 100%; opacity: .96; }

        .pm-reference-grid {
            display: grid;
            grid-template-columns: .95fr 1.03fr 1.06fr;
            gap: 13px;
        }
        .pm-reference-card {
            min-height: 278px;
            padding: 20px 16px 16px;
            border: 1px solid var(--bp-border);
            border-radius: 13px;
            background: rgba(3, 13, 29, 0.95);
        }
        .pm-reference-heading {
            display: grid;
            grid-template-columns: 38px 1fr;
            gap: 10px;
            align-items: start;
            margin-bottom: 17px;
        }
        .pm-reference-icon {
            width: 34px;
            height: 34px;
            display: grid;
            place-items: center;
            border-radius: 7px;
            background: rgba(13, 84, 215, 0.12);
            color: #1472ff;
            font-size: 1.2rem;
            box-shadow: 0 0 20px rgba(20,114,255,.12);
        }
        .pm-reference-title { color: #fff; font-weight: 800; font-size: .91rem; text-transform: uppercase; }
        .pm-reference-subtitle { margin-top: 6px; color: var(--bp-muted); font-size: .78rem; line-height: 1.55; }
        .pm-reference-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            min-height: 60px;
            padding: 10px 12px;
            border: 1px solid var(--bp-border-soft);
            border-radius: 10px;
            background: rgba(5, 18, 39, 0.72);
        }
        .pm-reference-row + .pm-reference-row { margin-top: 10px; }
        .pm-reference-row-main { min-width: 0; color: #fff; font-size: .82rem; }
        .pm-reference-row-main small { display: block; margin-top: 3px; color: #7f8ca4; font-size: .69rem; }
        /* Selo de estado: a cor vem do valor, nao do CSS. Sem modificador fica neutro
           de proposito, para que um selo esquecido nunca afirme "esta tudo bem". */
        .pm-reference-status {
            flex: 0 0 auto;
            padding: 6px 12px;
            border: 1px solid rgba(148,163,184,.22);
            border-radius: 999px;
            background: rgba(148,163,184,.08);
            color: #b6c1d4;
            font-size: .72rem;
            font-weight: 700;
        }
        .pm-reference-status.ok {
            border-color: rgba(17,201,104,.24);
            background: rgba(17,201,104,.08);
            color: var(--bp-green);
        }
        .pm-reference-status.warn {
            border-color: rgba(245,165,36,.28);
            background: rgba(245,165,36,.09);
            color: var(--bp-amber);
        }
        .pm-reference-status.bad {
            border-color: rgba(239,35,60,.30);
            background: rgba(239,35,60,.09);
            color: #ff6b7d;
        }
        .pm-reference-note { margin-top: 14px; color: #7f8ca4; font-size: .72rem; }
        .pm-reference-note.ok::before { content: "●"; color: var(--bp-green); margin-right: 8px; }
        .pm-reference-link { margin-top: 14px; color: #1c76ff; font-size: .76rem; }

        .pm-system-overview,
        .pm-download-card {
            padding: 18px;
            border: 1px solid var(--bp-border);
            border-radius: 13px;
            background: rgba(3, 13, 29, 0.95);
        }
        .pm-section-title { display:flex; align-items:center; gap:12px; color:#fff; font-size:.91rem; font-weight:800; text-transform:uppercase; }
        .pm-section-title span { color:#1472ff; font-size:1.2rem; }
        .pm-metric-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); margin-top:14px; }
        .pm-metric { min-height:92px; padding: 4px 19px 2px; border-left:1px solid rgba(31,58,96,.34); }
        .pm-metric:first-child { border-left:0; }
        .pm-metric-label { color:#9aa6bb; font-size:.78rem; }
        .pm-metric-value { margin-top:3px; color:#fff; font-size:1.65rem; line-height:1.15; letter-spacing:-.035em; }
        .pm-metric-note { margin-top:7px; color:#8b97ad; font-size:.69rem; }
        .pm-metric-note.good { color:var(--bp-green); }
        .pm-metric-note.warn { color:var(--bp-amber); }
        .pm-metric-note.bad { color:#ff6b7d; }
        .pm-metric-value.bad { color:#ff6b7d; }
        .pm-metric-value small { margin-left:5px; color:#8b97ad; font-size:.62em; letter-spacing:0; }
        .pm-download-card { padding-bottom: 12px; }
        .pm-download-description { margin:5px 0 13px 38px; color:#8d99b0; font-size:.76rem; }
        /* Azul so no download que e a acao principal da tela (type="primary").
           O download da planilha modelo e apoio e herda o estilo discreto. */
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stDownloadButton"] button[kind="primary"],
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"] button[aria-label*="Baixar última diária"] {
            min-height: 52px !important;
            border-radius: 8px !important;
            background: linear-gradient(180deg, #1472ff 0%, #0750db 100%) !important;
            border: 1px solid #1c75ff !important;
            color: #fff !important;
            font-weight: 750 !important;
            box-shadow: 0 8px 20px rgba(5,72,216,.27), inset 0 1px 0 rgba(255,255,255,.16) !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stDownloadButton"] button:disabled,
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"] button[aria-label*="Baixar última diária"]:disabled {
            background: rgba(148,163,184,.10) !important;
            border-color: rgba(148,163,184,.20) !important;
            color: #7f8ca4 !important;
            box-shadow: none !important;
        }
        /* Marcadores sao invisiveis, mas o container do Streamlit continuava
           ocupando uma linha do flex (gap 13px) e empurrava o que vinha depois. */
        div[data-testid="stElementContainer"]:has(.pm-main-marker),
        div[data-testid="stElementContainer"]:has(.pm-sidebar-spacer) {
            display: none !important;
        }

        /* Botoes da area principal. Sem isto o Streamlit desenha o botao padrao
           (branco) no meio do painel escuro. */
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"] button,
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stFormSubmitButton"] button {
            min-height: 44px !important;
            border-radius: 8px !important;
            border: 1px solid var(--bp-border) !important;
            background: rgba(5, 18, 39, .82) !important;
            color: #dbe3f2 !important;
            font-weight: 650 !important;
            box-shadow: none !important;
            transition: border-color .16s ease, background .16s ease, color .16s ease;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"] button:hover:not(:disabled) {
            border-color: rgba(20, 114, 255, .45) !important;
            background: rgba(18, 104, 255, .12) !important;
            color: #ffffff !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"] button:disabled {
            background: rgba(148, 163, 184, .08) !important;
            border-color: rgba(148, 163, 184, .18) !important;
            color: #6f7c93 !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(180deg, #1472ff 0%, #0750db 100%) !important;
            border-color: #1c75ff !important;
            color: #ffffff !important;
            font-weight: 750 !important;
            box-shadow: 0 8px 20px rgba(5, 72, 216, .27), inset 0 1px 0 rgba(255, 255, 255, .16) !important;
        }
        /* Vermelho fica reservado para o que interrompe. Precisa da mesma
           ancoragem da regra generica acima para vencer por especificidade. */
        div[data-testid="stColumn"]:has(.pm-main-marker) .st-key-pm_status_stop [data-testid="stButton"] button {
            background: rgba(239, 35, 60, .10) !important;
            border-color: rgba(239, 35, 60, .45) !important;
            color: #ff6b7d !important;
            font-weight: 700 !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) .st-key-pm_status_stop [data-testid="stButton"] button:hover:not(:disabled) {
            background: rgba(239, 35, 60, .18) !important;
            border-color: rgba(239, 35, 60, .65) !important;
            color: #ffe3e6 !important;
        }

        /* Rotulos de widget e titulos da area principal: o padrao do Streamlit
           fica quase ilegivel sobre o fundo escuro, e o h3 do markdown saia
           maior que o titulo da propria tela. */
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stWidgetLabel"] p,
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stWidgetLabel"] label {
            color: #cfd8e8 !important;
            font-size: .86rem !important;
            font-weight: 600 !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stCaptionContainer"] p {
            color: #8d99b0 !important;
        }
        /* Radio e checkbox: o texto da opcao saia apagado e o marcador vinha no
           vermelho padrao do tema, a mesma cor usada para erro. */
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stRadio"] label p,
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stCheckbox"] label p {
            color: #e6ebf5 !important;
            font-size: .88rem !important;
        }
        /* A cor do marcador vem do primaryColor do tema (.streamlit/config.toml),
           nao de um seletor sobre a estrutura interna do BaseWeb. */

        /* Download de apoio (type="secondary") nao concorre com a acao principal. */
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stDownloadButton"] button[kind="secondary"] {
            min-height: 44px !important;
            border-radius: 8px !important;
            border: 1px solid var(--bp-border) !important;
            background: rgba(5, 18, 39, .82) !important;
            color: #dbe3f2 !important;
            font-weight: 650 !important;
            box-shadow: none !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stDownloadButton"] button[kind="secondary"]:hover {
            border-color: rgba(20, 114, 255, .45) !important;
            background: rgba(18, 104, 255, .12) !important;
            color: #ffffff !important;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) h1,
        div[data-testid="stColumn"]:has(.pm-main-marker) h2,
        div[data-testid="stColumn"]:has(.pm-main-marker) h3 {
            color: #ffffff;
            font-size: 1.02rem;
            font-weight: 800;
            letter-spacing: -.01em;
            padding: 0;
        }

        /* Cabecalho de secao: um bloco fechado, no lugar do wrapper que o
           Streamlit cortava ao meio. */
        .pm-view-head {
            padding: 16px 20px;
            border: 1px solid var(--bp-border);
            border-radius: 13px;
            background: rgba(3, 13, 29, .95);
        }
        .pm-view-kicker {
            color: #1875ff;
            font-size: .72rem;
            font-weight: 800;
            letter-spacing: .12em;
            text-transform: uppercase;
        }
        .pm-view-title {
            margin-top: 6px;
            color: #fff;
            font-size: 1.22rem;
            font-weight: 750;
            letter-spacing: -.02em;
        }
        .pm-view-note { margin-top: 4px; color: var(--bp-muted); font-size: .84rem; }
        .pm-job-chip {
            display: inline-flex;
            align-items: center;
            gap: 9px;
            padding: 7px 13px;
            border: 1px solid var(--bp-border-soft);
            border-radius: 999px;
            background: rgba(5, 18, 39, .72);
            color: var(--bp-muted);
            font-size: .78rem;
        }
        .pm-job-chip code {
            color: #cfe0ff;
            background: rgba(20, 114, 255, .12);
            border-radius: 5px;
            padding: 2px 7px;
            font-size: .76rem;
        }
        .pm-dashboard-footer { padding: 0 0 3px; color:#748198; font-size:.69rem; text-align:center; }

        /* Falha deixa de ser uma faixa vermelha com o texto cru do backend. */
        .pm-error-card {
            margin-top: 12px;
            padding: 16px 18px;
            border: 1px solid rgba(239,35,60,.34);
            border-radius: 13px;
            background: linear-gradient(105deg, rgba(40,8,16,.92), rgba(3,13,29,.95) 62%);
        }
        .pm-error-title { color:#fff; font-size:1rem; font-weight:700; }
        .pm-error-message { margin-top:5px; color:#d8b6bb; font-size:.86rem; }
        .pm-error-hint {
            margin-top:12px;
            padding:11px 13px;
            border:1px solid rgba(239,35,60,.20);
            border-radius:10px;
            background:rgba(3,10,23,.6);
            color:#e6ebf5;
            font-size:.84rem;
        }
        .pm-error-hint b {
            display:block;
            margin-bottom:4px;
            color:#7f8ca4;
            font-size:.68rem;
            font-weight:700;
            letter-spacing:.08em;
            text-transform:uppercase;
        }
        .pm-error-detail { margin-top:10px; color:#8b97ad; font-size:.74rem; font-family:"SF Mono","Cascadia Mono","Consolas",monospace; word-break:break-word; }

        @media (max-width: 1180px) {
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) { flex-basis: 220px !important; min-width: 205px !important; }
            .pm-sidebar-name { font-size: 1.02rem; }
            .pm-sidebar-tagline { font-size: .48rem; }
            .pm-context-card { grid-template-columns: 1fr .85fr; }
            .pm-reference-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }
            .pm-reference-card:last-child { grid-column:1 / -1; min-height:auto; }
            .pm-metric-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
            .pm-metric:nth-child(4) { border-left:0; }
        }
        @media (max-width: 850px) {
            div[data-testid="stHorizontalBlock"]:has(.pm-sidebar-brand) { flex-direction: column !important; }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) { min-width:100% !important; max-width:none !important; flex:1 1 auto !important; }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stVerticalBlock"]:has(.pm-sidebar-brand) {
                min-height:auto;
                display:grid !important;
                grid-template-columns:repeat(2,minmax(0,1fr));
                gap:6px !important;
            }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stElementContainer"]:has(.pm-sidebar-brand) { grid-column:1 / -1; }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stElementContainer"]:has(.pm-user-card),
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stElementContainer"]:has(.pm-version) { display:none !important; }
            .pm-sidebar-brand { min-height:auto; }
            .pm-sidebar-spacer, .pm-user-card, .pm-version { display:none; }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] { width:100%; }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button { min-height:42px !important; padding:0 9px !important; font-size:.78rem !important; }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button p { text-align:center; }
            .pm-dashboard-header { grid-template-columns:1fr; min-height:auto; }
            .pm-header-meta { min-width:0; padding:10px 0 0; border-left:0; border-top:1px solid rgba(40,69,111,.27); }
            .pm-context-card { grid-template-columns:1fr; min-height:auto; }
            .pm-context-art { height:105px; }
            .pm-reference-grid { grid-template-columns:1fr; }
            .pm-reference-card:last-child { grid-column:auto; }
            .pm-metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
            .pm-metric:nth-child(odd) { border-left:0; }
            .pm-metric:nth-child(4) { border-left:1px solid rgba(31,58,96,.34); }
        }
        @media (max-width: 540px) {
            .block-container { padding:.45rem !important; }
            .pm-dashboard-header { padding:15px; }
            .pm-dashboard-title { font-size:1.18rem; }
            .pm-context-card { padding:16px; }
            .pm-context-copy { grid-template-columns:30px 1fr; gap:10px; }
            .pm-context-name { margin-top:12px; }
            .pm-context-art { display:none; }
            .pm-reference-grid { gap:9px; }
            .pm-reference-card { min-height:auto; padding:15px 12px; }
            .pm-metric-grid { grid-template-columns:1fr; }
            .pm-metric, .pm-metric:nth-child(4) { border-left:0; border-top:1px solid rgba(31,58,96,.34); padding:12px 8px; }
            .pm-metric:first-child { border-top:0; }
            .pm-download-description { margin-left:0; }
        }

        /* ============================================================
           Responsividade
           Os breakpoints acima cuidavam so do HTML proprio (pm-*). Os widgets
           do Streamlit - colunas, botoes, uploader - continuavam com largura
           de desktop e espremiam ou estouravam a linha. Esta camada vem depois
           de proposito, para vencer as regras anteriores.
           ============================================================ */

        /* O Streamlit aplica margin-bottom: -1rem no stMarkdownContainer para
           compensar a margem que um <p> de markdown carrega. Nosso HTML nao tem
           essa margem, entao o -16px puxava o elemento seguinte para cima e ele
           encostava no bloco anterior (cartao colado no botao). */
        div[data-testid="stMarkdownContainer"]:has(> section),
        div[data-testid="stMarkdownContainer"]:has(> [class^="pm-"]) {
            margin-bottom: 0 !important;
        }

        /* A barra lateral e fixa em 255px, mas a coluna principal nascia com
           flex-basis: calc(82% - 16px). Somados, passavam de 100% da linha em
           qualquer tela abaixo de ~1500px: o flex quebrava, a barra ia para cima
           e o conteudo despencava para baixo dela, deixando meia tela vazia.
           Com basis 0 a coluna principal passa a ocupar exatamente o que sobra. */
        @media (min-width: 851px) {
            div[data-testid="stHorizontalBlock"]:has(.pm-sidebar-brand) {
                flex-wrap: nowrap !important;
            }
            div[data-testid="stColumn"]:has(.pm-main-marker) {
                flex: 1 1 0% !important;
                min-width: 0 !important;
            }
        }

        /* Nada deve poder empurrar a pagina na horizontal. */
        [data-testid="stAppViewContainer"] { overflow-x: hidden; }
        div[data-testid="stElementContainer"],
        div[data-testid="stVerticalBlock"],
        div[data-testid="stColumn"] { min-width: 0; }
        .pm-view-title,
        .pm-context-name,
        .pm-reference-row-main,
        .pm-metric-label,
        .pm-metric-value,
        .pm-error-message { overflow-wrap: anywhere; }

        /* Linhas de acao: colunas de mesma altura e botoes ocupando a coluna. */
        div[data-testid="stColumn"]:has(.pm-main-marker) div[data-testid="stHorizontalBlock"] {
            align-items: flex-end;
            gap: 10px;
        }
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"],
        div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stDownloadButton"] { width: 100%; }

        /* Notebooks e telas medias. */
        @media (max-width: 1180px) {
            .pm-info-grid { grid-template-columns: 1fr !important; }
            .pm-kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .pm-context-name.big { font-size: 1.12rem; }
        }

        /* Tablets e janelas estreitas: as colunas do Streamlit passam a empilhar.
           Sem isto elas so encolhem, e o texto do botao quebra no meio. */
        @media (max-width: 850px) {
            /* Empilhado, a coluna principal continuava presa em flex-basis 82%
               e deixava uma faixa morta a direita. */
            div[data-testid="stColumn"]:has(.pm-main-marker) {
                flex: 1 1 auto !important;
                width: 100% !important;
                min-width: 100% !important;
                max-width: none !important;
            }
            div[data-testid="stColumn"]:has(.pm-main-marker) div[data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
            }
            div[data-testid="stColumn"]:has(.pm-main-marker) div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                flex: 1 1 100% !important;
                width: 100% !important;
            }
            /* O menu vira uma grade que se ajusta a largura disponivel, em vez
               de duas colunas fixas empurrando o conteudo para baixo. */
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stVerticalBlock"]:has(.pm-sidebar-brand) {
                grid-template-columns: repeat(auto-fit, minmax(158px, 1fr)) !important;
            }
            .pm-view-head { padding: 14px 16px; }
            .pm-view-title { font-size: 1.1rem; }
            .pm-dashboard-title { font-size: 1.24rem; }
            .pm-context-name.big { font-size: 1.06rem; }
        }

        /* Celulares. */
        @media (max-width: 540px) {
            .pm-view-head { padding: 13px 14px; border-radius: 11px; }
            .pm-view-kicker { font-size: .66rem; letter-spacing: .1em; }
            .pm-view-title { font-size: 1.02rem; }
            .pm-view-note { font-size: .8rem; }
            .pm-job-chip { width: 100%; justify-content: space-between; }
            .pm-context-name.big { font-size: 1rem; }
            .pm-section-title { font-size: .84rem; }
            .pm-error-card { padding: 14px; }
            div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stButton"] button,
            div[data-testid="stColumn"]:has(.pm-main-marker) [data-testid="stDownloadButton"] button {
                min-height: 46px;
                font-size: .88rem;
            }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stVerticalBlock"]:has(.pm-sidebar-brand) {
                grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)) !important;
            }
        }

        /* Celular deitado: sobra largura e falta altura. Encolhe o vertical e
           devolve o menu para uma faixa unica. */
        @media (max-height: 520px) and (orientation: landscape) {
            .block-container { padding-top: .35rem !important; }
            .pm-dashboard-header { min-height: auto; padding: 11px 16px; }
            .pm-context-card { min-height: auto; padding: 13px 16px; }
            .pm-context-art { display: none; }
            .pm-context-name { margin-top: 10px; }
            .pm-reference-card { min-height: auto; }
            .pm-view-head { padding: 11px 14px; }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) div[data-testid="stVerticalBlock"]:has(.pm-sidebar-brand) {
                grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)) !important;
            }
            div[data-testid="stColumn"]:has(.pm-sidebar-brand) [data-testid="stButton"] button {
                min-height: 38px !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _admin_view_requested() -> bool:
    try:
        view = str(st.query_params.get("view", "")).strip().lower()
    except Exception:
        view = ""
    return view == "admin"


def _clear_auth_state() -> None:
    for key in ("app_authenticated", "current_user", "user_session_token", "session_expires_in"):
        if key in st.session_state:
            del st.session_state[key]


def _build_api_ui_url() -> str:
    parsed = urlparse(API_BASE)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if API_TOKEN:
        query["api_token"] = API_TOKEN
    query["embedded"] = "1"
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/",
            "",
            urlencode(query),
            "",
        )
    )


def _api_headers(include_user_session: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    if include_user_session:
        user_session_token = str(st.session_state.get("user_session_token") or "").strip()
        if user_session_token:
            headers[ADMIN_SESSION_HEADER] = user_session_token
    return headers


def _request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    include_user_session: bool = False,
    timeout: int = 8,
) -> tuple[bool, int, dict[str, object], str]:
    url = f"{API_BASE}{path}"
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=_api_headers(include_user_session=include_user_session),
            json=payload,
            timeout=timeout,
        )
    except Exception as exc:
        return False, 0, {}, f"Falha de conexao com {url}: {type(exc).__name__}: {exc}"

    data: dict[str, object] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}

    if response.status_code >= 400:
        message = str(data.get("error") or data.get("detail") or f"HTTP {response.status_code}")
        return False, response.status_code, data, message

    return True, response.status_code, data, ""

def _request_form(
    method: str,
    path: str,
    *,
    data: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: int = 60,
) -> tuple[bool, int, dict[str, object], str]:
    url = f"{API_BASE}{path}"
    try:
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=_api_headers(include_user_session=False),
            data=data,
            files=files,
            timeout=timeout,
        )
    except Exception as exc:
        return False, 0, {}, f"Falha de conexao com {url}: {type(exc).__name__}: {exc}"

    payload: dict[str, object] = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            payload = parsed
    except Exception:
        payload = {}

    if response.status_code >= 400:
        message = str(payload.get("error") or payload.get("detail") or f"HTTP {response.status_code}")
        return False, response.status_code, payload, message

    return True, response.status_code, payload, ""


def _download_bytes(path: str, timeout: int = 60) -> tuple[bool, bytes, str]:
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(url, headers=_api_headers(include_user_session=False), timeout=timeout)
    except Exception as exc:
        return False, b"", f"Falha de conexao com {url}: {type(exc).__name__}: {exc}"

    if resp.status_code >= 400:
        return False, b"", f"HTTP {resp.status_code}: {(resp.text or '').strip()[:400]}"

    return True, resp.content or b"", ""


def _build_template_xlsx_bytes() -> tuple[bool, bytes, str]:
    """Retorna a planilha modelo fixa para download."""
    template_path = Path(__file__).resolve().parent.parent / "Modelo.xlsx"
    if not template_path.is_file():
        return False, b"", f"Planilha modelo nao encontrada em: {template_path}"
    try:
        return True, template_path.read_bytes(), ""
    except Exception as exc:
        return False, b"", f"Nao foi possivel ler {template_path}: {type(exc).__name__}: {exc}"


def _prepare_download_for_job(job_id: str) -> tuple[bool, bytes, str]:
    job_id = str(job_id or "").strip()
    if not job_id:
        return False, b"", "Job inválido."
    return _download_bytes(f"/download/{job_id}", timeout=60)


def _prepare_download_by_path(path: str) -> tuple[bool, bytes, str]:
    path = str(path or "").strip()
    if not path:
        return False, b"", "Download inválido."
    if not path.startswith("/"):
        path = "/" + path
    return _download_bytes(path, timeout=180)


def _validate_api_base() -> tuple[bool, str]:
    health_url = f"{API_BASE}/api/health"
    try:
        health_response = requests.get(health_url, timeout=4)
    except Exception as exc:
        return (
            False,
            (
                f"Nao foi possivel conectar em {health_url}. "
                f"Detalhe: {type(exc).__name__}: {exc}"
            ),
        )

    if health_response.status_code != 200:
        return (
            False,
            (
                f"O endpoint {health_url} retornou HTTP {health_response.status_code}. "
                "Isso indica API errada nessa porta ou servico indisponivel."
            ),
        )

    try:
        health_payload = health_response.json()
    except Exception:
        return (
            False,
            (
                f"O endpoint {health_url} respondeu sem JSON valido. "
                "Isso indica API errada nessa porta."
            ),
        )

    if str(health_payload.get("status") or "").lower() != "ok":
        return (
            False,
            (
                f"O endpoint {health_url} nao retornou status=ok "
                f"(payload={health_payload})."
            ),
        )

    overview_url = f"{API_BASE}/api/overview"
    try:
        overview_response = requests.get(overview_url, headers=_api_headers(), timeout=4)
    except Exception as exc:
        return (
            False,
            (
                f"Nao foi possivel validar {overview_url}. "
                f"Detalhe: {type(exc).__name__}: {exc}"
            ),
        )

    if overview_response.status_code == 401:
        return (
            False,
            (
                "API online, mas token invalido/ausente para /api/overview. "
                "Defina API_TOKEN igual ao da API."
            ),
        )

    if overview_response.status_code >= 400:
        return (
            False,
            (
                f"Falha ao validar /api/overview (HTTP {overview_response.status_code}). "
                "A API nao esta pronta para a UI."
            ),
        )

    return True, ""


def _authenticate_platform_user(username: str, password: str) -> tuple[bool, str]:
    ok, status_code, data, message = _request_json(
        "POST",
        "/api/admin/users/authenticate",
        payload={
            "username": username,
            "password": password,
        },
        timeout=6,
    )
    if not ok:
        if status_code in (401, 403):
            return False, message or "Credenciais invalidas."
        return False, message or "Nao foi possivel autenticar na API."

    user_payload = data.get("user")
    session_token = str(data.get("session_token") or "").strip()
    expires_in = int(data.get("expires_in_seconds") or 0)
    if not isinstance(user_payload, dict) or not session_token:
        return False, "Resposta invalida da API de autenticacao."

    st.session_state.app_authenticated = True
    st.session_state.current_user = user_payload
    st.session_state.user_session_token = session_token
    st.session_state.session_expires_in = expires_in
    return True, ""


def _logout_platform_user() -> None:
    _request_json(
        "POST",
        "/api/admin/users/logout",
        include_user_session=True,
        timeout=4,
    )
    _clear_auth_state()


def _session_user() -> dict[str, object]:
    payload = st.session_state.get("current_user")
    if isinstance(payload, dict):
        return payload
    return {}


def _is_admin_user() -> bool:
    role = str(_session_user().get("role") or "").strip().lower()
    return role == "admin"


def _has_user_session_token() -> bool:
    token = str(st.session_state.get("user_session_token") or "").strip()
    return bool(token)


def _handle_admin_auth_failure(status_code: int, message: str) -> bool:
    if status_code not in (401, 403):
        return False
    if not _has_user_session_token():
        # Evita loop de rerun quando o painel esta sem sessao autenticada na API.
        return False
    st.warning(message or "Sessao administrativa invalida. Faca login novamente.")
    _clear_auth_state()
    st.rerun()
    return True


def _legacy_login_allowed(username: str, password: str) -> bool:
    if not AUTH_ENABLED:
        return False
    return (
        hmac.compare_digest(username, APP_AUTH_USER)
        and hmac.compare_digest(password, APP_AUTH_PASSWORD)
    )


def _require_login() -> None:
    if not PASSWORD_AUTH_ENABLED:
        if not st.session_state.get("app_authenticated") or not _session_user():
            st.session_state.app_authenticated = True
            st.session_state.current_user = {
                "username": "admin",
                "full_name": "Administrador (sem senha)",
                "role": "admin",
                "is_active": True,
                "created_at": "",
                "updated_at": "",
            }
            st.session_state.user_session_token = ""
            st.session_state.session_expires_in = 0
        with st.sidebar:
            st.caption("Sessao sem senha ativa")
            st.caption("Defina PASSWORD_AUTH_ENABLED=1 para reativar login.")
        return

    if st.session_state.get("app_authenticated") and _session_user():
        with st.sidebar:
            current = _session_user()
            role = str(current.get("role") or "operator")
            st.caption(f"Sessao autenticada: {current.get('username', '-')}")
            st.caption(f"Perfil: {role}")
            if st.button("Sair", key="logout_sidebar"):
                _logout_platform_user()
                st.rerun()
        return

    st.title("Login")
    st.caption("Acesso ao painel da plataforma")
    with st.form("login_form"):
        user = st.text_input("Usuario")
        password = st.text_input("Senha", type="password")
        submit = st.form_submit_button("Entrar")

    if submit:
        username = user.strip()
        success, error_message = _authenticate_platform_user(username, password)
        if success:
            st.rerun()

        if _legacy_login_allowed(username, password):
            st.session_state.app_authenticated = True
            st.session_state.current_user = {
                "username": APP_AUTH_USER,
                "full_name": "Administrador (legado)",
                "role": "admin",
                "is_active": True,
                "created_at": "",
                "updated_at": "",
            }
            st.session_state.user_session_token = ""
            st.session_state.session_expires_in = 0
            st.warning(
                "Login em modo legado habilitado. Configure usuarios no painel admin para usar autenticacao completa."
            )
            st.rerun()

        st.error(error_message or "Credenciais invalidas.")

    st.stop()


def _render_admin_panel() -> None:
    st.subheader("Painel Administrador")
    st.caption("Gerencie usuarios da plataforma: cadastro, alteracao e exclusao.")

    if not _has_user_session_token():
        if PASSWORD_AUTH_ENABLED:
            st.info("Faca login para carregar o painel de administracao.")
        else:
            st.info(
                "Sessao sem senha ativa. Para gerenciar usuarios, defina PASSWORD_AUTH_ENABLED=1 e faca login."
            )
        return

    ok, status_code, data, message = _request_json(
        "GET",
        "/api/admin/users",
        include_user_session=True,
        timeout=8,
    )
    if not ok:
        if _handle_admin_auth_failure(status_code, message):
            return
        st.error(f"Nao foi possivel carregar usuarios: {message}")
        return

    raw_users = data.get("users")
    if not isinstance(raw_users, list):
        st.error("Resposta invalida da API ao carregar usuarios.")
        return

    users: list[dict[str, object]] = []
    for item in raw_users:
        if isinstance(item, dict):
            users.append(item)
    users.sort(key=lambda item: str(item.get("username") or ""))

    st.write(f"Usuarios cadastrados: {len(users)}")
    if users:
        st.dataframe(
            [
                {
                    "usuario": str(user.get("username") or ""),
                    "nome": str(user.get("full_name") or ""),
                    "perfil": str(user.get("role") or ""),
                    "ativo": bool(user.get("is_active", True)),
                    "criado_em": str(user.get("created_at") or ""),
                    "atualizado_em": str(user.get("updated_at") or ""),
                }
                for user in users
            ],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Cadastrar novo usuario", expanded=True):
        with st.form("admin_create_user_form", clear_on_submit=True):
            create_username = st.text_input("Usuario")
            create_full_name = st.text_input("Nome completo")
            create_password = st.text_input("Senha", type="password")
            create_role = st.selectbox("Perfil", options=["admin", "operator"], index=1)
            create_active = st.checkbox("Ativo", value=True)
            create_submit = st.form_submit_button("Cadastrar usuario")

        if create_submit:
            ok, status_code, _, message = _request_json(
                "POST",
                "/api/admin/users",
                payload={
                    "username": create_username,
                    "full_name": create_full_name,
                    "password": create_password,
                    "role": create_role,
                    "is_active": create_active,
                },
                include_user_session=True,
                timeout=8,
            )
            if ok:
                st.success("Usuario cadastrado com sucesso.")
                st.rerun()
            if _handle_admin_auth_failure(status_code, message):
                return
            st.error(message or "Falha ao cadastrar usuario.")

    if not users:
        st.info("Cadastre ao menos um usuario para habilitar alteracao e exclusao.")
        return

    usernames = [str(user.get("username") or "") for user in users]
    user_map = {str(user.get("username") or ""): user for user in users}

    with st.expander("Alterar usuario", expanded=False):
        selected_to_edit = st.selectbox("Usuario para alterar", options=usernames, key="admin_user_edit")
        selected_user = user_map.get(selected_to_edit, {})
        role_options = ["admin", "operator"]
        selected_role = str(selected_user.get("role") or "operator")
        role_index = role_options.index(selected_role) if selected_role in role_options else 1

        with st.form("admin_update_user_form"):
            edit_username = st.text_input("Usuario", value=selected_to_edit)
            edit_full_name = st.text_input("Nome completo", value=str(selected_user.get("full_name") or ""))
            edit_role = st.selectbox("Perfil", options=role_options, index=role_index)
            edit_is_active = st.checkbox("Ativo", value=bool(selected_user.get("is_active", True)))
            edit_new_password = st.text_input("Nova senha (opcional)", type="password")
            edit_submit = st.form_submit_button("Salvar alteracoes")

        if edit_submit:
            payload: dict[str, object] = {
                "new_username": edit_username,
                "full_name": edit_full_name,
                "role": edit_role,
                "is_active": edit_is_active,
            }
            if edit_new_password.strip():
                payload["new_password"] = edit_new_password

            ok, status_code, response_data, message = _request_json(
                "PUT",
                f"/api/admin/users/{selected_to_edit}",
                payload=payload,
                include_user_session=True,
                timeout=8,
            )
            if ok:
                warning_message = str(response_data.get("warning") or "").strip()
                st.success("Usuario atualizado com sucesso.")
                if warning_message:
                    st.warning(warning_message)
                    _clear_auth_state()
                st.rerun()
            if _handle_admin_auth_failure(status_code, message):
                return
            st.error(message or "Falha ao atualizar usuario.")

    current_username = str(_session_user().get("username") or "").strip()
    deletable_usernames = [username for username in usernames if username != current_username]

    with st.expander("Excluir usuario", expanded=False):
        if not deletable_usernames:
            st.info("Nao ha usuarios elegiveis para exclusao.")
        else:
            with st.form("admin_delete_user_form"):
                selected_to_delete = st.selectbox("Usuario para excluir", options=deletable_usernames)
                confirmation = st.text_input("Digite o usuario acima para confirmar exclusao")
                delete_submit = st.form_submit_button("Excluir usuario")

            if delete_submit:
                if confirmation.strip() != selected_to_delete:
                    st.error("Confirmacao invalida. Digite exatamente o usuario selecionado.")
                else:
                    ok, status_code, _, message = _request_json(
                        "DELETE",
                        f"/api/admin/users/{selected_to_delete}",
                        include_user_session=True,
                        timeout=8,
                    )
                    if ok:
                        st.success("Usuario excluido com sucesso.")
                        st.rerun()
                    if _handle_admin_auth_failure(status_code, message):
                        return
                    st.error(message or "Falha ao excluir usuario.")


def _render_native_panel() -> None:
    if "pm_view" not in st.session_state:
        st.session_state["pm_view"] = "overview"

    def _esc(value: object) -> str:
        return html.escape(str(value or "").strip())

    def _fmt_timestamp(value: object) -> str:
        try:
            stamp = float(value or 0)
            if stamp <= 0:
                return "-"
            return datetime.fromtimestamp(stamp, tz=ZoneInfo("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
        except (TypeError, ValueError, OSError):
            return "-"

    def _job_duration_seconds(job: dict) -> float:
        try:
            start = float(job.get("started_at") or job.get("created_at") or 0)
            end = float(job.get("finished_at") or 0)
            return max(0.0, end - start) if start and end else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _fmt_clock(value) -> str:
        try:
            stamp = float(value or 0)
            if stamp <= 0:
                return "-"
            return datetime.fromtimestamp(stamp, tz=ZoneInfo("America/Sao_Paulo")).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            return "-"

    def _fmt_duration(seconds: float) -> str:
        total = int(seconds or 0)
        if total <= 0:
            return "-"
        if total < 60:
            return f"{total} s"
        minutes, rest = divmod(total, 60)
        return f"{minutes} min {rest:02d} s"

    def _fmt_bytes(size: int) -> str:
        value = float(size or 0)
        if value <= 0:
            return "-"
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return "-"

    # Tom do selo a partir do valor. Antes o verde estava fixo no CSS e um job
    # FAILED aparecia como se estivesse tudo certo.
    def _status_tone(value) -> str:
        normalized = str(value or "").strip().upper()
        if normalized in {"DONE", "SUCCESS", "COMPLETED", "OK"}:
            return "ok"
        if normalized in {"FAILED", "ERROR"}:
            return "bad"
        if normalized in {"RUNNING", "QUEUED", "PENDING", "STOPPED", "CANCELED"}:
            return "warn"
        return ""

    def _status_label(value) -> str:
        normalized = str(value or "").strip().upper()
        return {
            "DONE": "Concluído",
            "SUCCESS": "Concluído",
            "COMPLETED": "Concluído",
            "FAILED": "Falhou",
            "ERROR": "Falhou",
            "RUNNING": "Em execução",
            "QUEUED": "Na fila",
            "PENDING": "Pendente",
            "STOPPED": "Interrompido",
            "CANCELED": "Cancelado",
        }.get(normalized, str(value or "-").strip() or "-")

    def _section_head(kicker: str, title: str, note: str = "") -> None:
        """Cabecalho de secao em um unico bloco fechado.

        O padrao antigo abria '<div class="pm-glass pm-panel">' em uma chamada e
        fechava em outra. O Streamlit sanitiza cada bloco de markdown
        separadamente e fecha as tags soltas, entao o painel virava uma barra
        vazia e o conteudo caia fora dele.
        """
        note_html = f'<div class="pm-view-note">{_esc(note)}</div>' if note else ""
        st.markdown(
            f'<section class="pm-view-head">'
            f'<div class="pm-view-kicker">{_esc(kicker)}</div>'
            f'<div class="pm-view-title">{_esc(title)}</div>'
            f"{note_html}"
            f"</section>",
            unsafe_allow_html=True,
        )

    ok, _, overview, message = _request_json("GET", "/api/overview", timeout=8)
    if not ok:
        st.error(message or "Falha ao carregar overview da API.")
        return

    counts = overview.get("counts") if isinstance(overview.get("counts"), dict) else {}
    queued = int(counts.get("QUEUED") or 0)
    running = int(counts.get("RUNNING") or 0)
    done = int(counts.get("DONE") or 0)
    failed = int(counts.get("FAILED") or 0)
    schedule_ok, _, schedule, _ = _request_json("GET", "/api/daily/latest", timeout=8)
    if not schedule_ok or not isinstance(schedule, dict):
        schedule = {}

    nav_col, main_col = st.columns([0.18, 0.82], gap="small")

    with nav_col:
        st.markdown(
            """
            <div class="pm-sidebar-brand">
              <div class="pm-sidebar-logo">$</div>
              <div>
                <div class="pm-sidebar-name">BUSCA <span>PREÇO</span></div>
                <div class="pm-sidebar-tagline">INTELIGÊNCIA EM PREÇOS</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        def _set_view(target_view: str) -> None:
            st.session_state["pm_view"] = target_view

        def _nav_button(label: str, view: str) -> None:
            active = st.session_state.get("pm_view") == view
            st.button(
                label,
                type="primary" if active else "secondary",
                use_container_width=True,
                key=f"pm_nav_{view}",
                on_click=_set_view,
                args=(view,),
            )

        _nav_button("⌂  Resumo", "overview")
        _nav_button("▷  Execução Manual", "run")
        _nav_button("◉  Status", "status")
        _nav_button("◷  Histórico de Jobs", "history")
        _nav_button("⇩  Downloads", "downloads")
        _nav_button("⚙  Configurações", "settings")
        _nav_button("?  Ajuda", "help")

        if SHOW_SIDEBAR_USER_CARD:
            current_user = _session_user()
            username = str(current_user.get("username") or "").strip()
            display_name = _esc(
                current_user.get("display_name")
                or ("Daniel Avila" if username.lower() == "admin" else username)
                or "Daniel Avila"
            )
            raw_role = str(current_user.get("role") or "").strip()
            display_role = _esc(
                "Administrador"
                if raw_role.lower() in {"admin", "administrator"}
                else raw_role or "Administrador"
            )
            st.markdown(
                f"""
                <div class="pm-user-card">
                  <div class="pm-user-avatar">●</div>
                  <div><div class="pm-user-name">{display_name}</div><div class="pm-user-role">{display_role}</div></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown(
            '<div class="pm-version">Versão 1.0.0</div>',
            unsafe_allow_html=True,
        )

    with main_col:
        st.markdown('<span class="pm-main-marker"></span>', unsafe_allow_html=True)
        view = str(st.session_state.get("pm_view") or "overview")

        view_titles = {
            "overview": ("Painel / Resumo", "Visão geral do sistema Busca Preço"),
            "run": ("Painel / Execução Manual", "Inicie uma nova pesquisa de preços"),
            "status": ("Painel / Status", "Acompanhe o processamento em tempo real"),
            "history": ("Painel / Histórico de Jobs", "Consulte as execuções mais recentes"),
            "downloads": ("Painel / Downloads", "Baixe os resultados processados"),
            "settings": ("Painel / Configurações", "Preferências e integrações do sistema"),
            "help": ("Painel / Ajuda", "Orientações para utilizar o Busca Preço"),
        }
        path_title, path_subtitle = view_titles.get(view, view_titles["overview"])
        now_br = datetime.now(ZoneInfo("America/Sao_Paulo"))
        month_names = (
            "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        )
        date_label = f"{now_br.day:02d} de {month_names[now_br.month - 1].title()}, {now_br.year}"
        next_run_time = str(schedule.get("next_run_time") or AUTO_DAILY_UPDATE_TIME).strip()
        next_run_note = f"Próxima rotina às {next_run_time}"
        try:
            next_run_at = datetime.fromtimestamp(float(schedule.get("next_run_at") or 0), tz=ZoneInfo("America/Sao_Paulo"))
            day_label = "Hoje" if next_run_at.date() == now_br.date() else "Amanhã"
            next_run_note = f"{day_label} às {next_run_time}"
        except (TypeError, ValueError, OSError):
            pass

        # O sino so acende quando existe algo para o operador resolver. Um ponto
        # permanentemente aceso deixa de ser lido depois do segundo dia.
        alerts: list[str] = []
        if failed:
            alerts.append(f"{failed} execução(ões) com falha")
        if not bool(overview.get("has_default_input")):
            alerts.append("base de entrada ausente no servidor")
        if not bool(API_TOKEN):
            alerts.append("token de API não configurado")
        bell_class = "pm-header-bell has-alert" if alerts else "pm-header-bell"
        bell_title = _esc("; ".join(alerts)) if alerts else "Nenhum alerta"

        st.markdown(
            f"""
            <div class="pm-dashboard-header">
              <div>
                <div class="pm-dashboard-title">{_esc(path_title)}</div>
                <div class="pm-dashboard-subtitle">{_esc(path_subtitle)}</div>
              </div>
              <div class="pm-header-meta">
                <div class="{bell_class}" data-count="{len(alerts)}" title="{bell_title}">♧</div>
                <div class="pm-header-line"><b>□</b><span>{date_label}</span></div>
                <div class="pm-header-line"><b>◷</b><span>{now_br.strftime('%H:%M:%S')}</span></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if view == "overview":
            latest_manual = overview.get("latest_manual_job") if isinstance(overview.get("latest_manual_job"), dict) else {}
            latest_daily = overview.get("latest_daily_job") if isinstance(overview.get("latest_daily_job"), dict) else {}
            has_default_input = bool(overview.get("has_default_input"))
            latest_manual_id = str(latest_manual.get("job_id") or "").strip() or "-"
            latest_daily_id = str(latest_daily.get("job_id") or "").strip() or "-"
            latest_manual_time = _fmt_timestamp(latest_manual.get("created_at"))
            latest_daily_time = _fmt_timestamp(latest_daily.get("created_at"))
            latest_check = latest_manual_time if latest_manual_time != "-" else latest_daily_time
            total_jobs = queued + running + done + failed + int(counts.get("STOPPED") or 0)
            finished_jobs = done + failed
            success_rate = (done / finished_jobs * 100.0) if finished_jobs else 0.0
            durations = [
                duration
                for duration in (_job_duration_seconds(latest_manual), _job_duration_seconds(latest_daily))
                if duration > 0
            ]
            avg_seconds = int(sum(durations) / len(durations)) if durations else 0
            # Sem execucao concluida nao ha media: "00:00" dava a entender que a
            # coleta leva zero segundo.
            avg_duration = f"{avg_seconds // 60:02d}:{avg_seconds % 60:02d}" if avg_seconds else "-"
            avg_duration_note = "Por execução recente" if avg_seconds else "Nenhuma execução concluída ainda"

            # O arquivo do dia e preparado antes de desenhar o cartao para que o
            # carimbo (nome, horario e tamanho) apareca junto do botao de baixar.
            can_download_daily_job = latest_daily_id != "-"
            ok_dl, content, error = _prepare_download_by_path("/download/daily/fixed")
            filename = _daily_result_filename()
            if (not ok_dl or not content) and can_download_daily_job:
                ok_dl, content, error = _prepare_download_for_job(latest_daily_id)
                filename = _daily_result_filename()
            daily_file_ready = bool(ok_dl and content)
            daily_size_label = _fmt_bytes(len(content)) if daily_file_ready else "-"

            daily_status = str(latest_daily.get("status") or "").strip().upper()
            manual_status = str(latest_manual.get("status") or "").strip().upper()
            daily_tone = _status_tone(daily_status)
            daily_duration = _fmt_duration(_job_duration_seconds(latest_daily))
            manual_duration = _fmt_duration(_job_duration_seconds(latest_manual))
            daily_finished = _fmt_clock(latest_daily.get("finished_at"))
            daily_started = _fmt_clock(latest_daily.get("started_at") or latest_daily.get("created_at"))

            # O cartao de contexto repetia "Painel / Resumo", que ja esta no cabecalho
            # logo acima. Passa a carregar o resultado da coleta do dia.
            if not latest_daily:
                context_icon, context_tone = "i", ""
                context_headline = "Nenhuma coleta diária registrada ainda"
            elif daily_tone == "ok":
                context_icon, context_tone = "✓", "ok"
                context_headline = f"Concluída às {daily_finished}"
                if daily_duration != "-":
                    context_headline = f"{context_headline} · {daily_duration}"
            elif daily_tone == "bad":
                context_icon, context_tone = "!", "bad"
                context_headline = f"Falhou às {daily_finished}"
            elif daily_tone == "warn":
                context_icon, context_tone = "◷", "warn"
                context_headline = f"{_status_label(daily_status)} desde {daily_started}"
            else:
                context_icon, context_tone = "i", ""
                context_headline = _status_label(daily_status)

            context_parts = []
            if daily_file_ready:
                context_parts.append(f"{filename} · {daily_size_label}")
            if next_run_note:
                context_parts.append(f"Próxima rotina: {next_run_note}")
            context_description = " · ".join(context_parts) or "Resumo geral das informações e status do sistema."

            if daily_file_ready:
                # O horario so entra quando a diaria ja terminou; com o job ainda em
                # execucao o campo vinha vazio e saia como "gerado as -".
                download_parts = [filename]
                if daily_finished != "-":
                    download_parts.append(f"gerado às {daily_finished}")
                download_parts.append(daily_size_label)
                download_description = " · ".join(download_parts)
            else:
                download_description = "Nenhuma planilha diária disponível ainda."

            st.markdown(
                f"""
                <section class="pm-context-card">
                  <div class="pm-context-copy">
                    <div class="pm-context-icon {context_tone}">{context_icon}</div>
                    <div>
                      <div class="pm-context-label">COLETA DE HOJE</div>
                      <div class="pm-context-name big">{_esc(context_headline)}</div>
                      <div class="pm-context-description">{_esc(context_description)}</div>
                    </div>
                  </div>
                  <svg class="pm-context-art" viewBox="0 0 620 170" aria-hidden="true">
                    <defs>
                      <linearGradient id="bpBar" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#1268ff"/><stop offset="1" stop-color="#07328f"/></linearGradient>
                      <radialGradient id="bpGlow"><stop stop-color="#1268ff" stop-opacity=".38"/><stop offset="1" stop-color="#1268ff" stop-opacity="0"/></radialGradient>
                    </defs>
                    <ellipse cx="380" cy="90" rx="235" ry="84" fill="url(#bpGlow)" opacity=".34"/>
                    <g opacity=".38" stroke="#1268ff" fill="none"><path d="M300 131H590M320 111H570M342 91H552M365 71H530"/><path d="M335 45L405 145M390 35L450 145M445 31L495 145M500 42L540 145"/></g>
                    <g fill="url(#bpBar)" stroke="#2480ff"><path d="M50 122V82l26-8v48z"/><path d="M88 122V58l27-9v73z"/><path d="M128 122V31l27-10v101z"/></g>
                    <g transform="translate(184 28)"><circle cx="65" cy="61" r="48" fill="#07245e" stroke="#1268ff" stroke-width="8"/><circle cx="65" cy="61" r="35" fill="#06183b" stroke="#0b4fce"/><text x="65" y="78" text-anchor="middle" fill="#1675ff" font-size="50" font-weight="800">$</text><path d="M98 98l42 42" stroke="#0b3d9f" stroke-width="15" stroke-linecap="round"/></g>
                    <g transform="translate(352 17)" fill="none" stroke="#1268ff" stroke-width="1.2" opacity=".82"><path d="M23 19l31-10 31 12 25-8 33 15 18 24-19 13 8 25-23 8-13 28-31-6-20 9-25-17-16-35 11-24z"/><path d="M54 9l8 35 31 9 17-40M62 44L38 71l25 49M93 53l-10 35 31 38M110 53l32 12M83 88l47 2"/></g>
                    <g fill="#1472ff"><circle cx="516" cy="57" r="6"/><circle cx="564" cy="101" r="6"/><circle cx="470" cy="115" r="6"/><path d="M516 33c-11 0-19 8-19 19 0 15 19 32 19 32s19-17 19-32c0-11-8-19-19-19zm0 25a7 7 0 110-14 7 7 0 010 14z"/><path d="M577 74c-10 0-18 8-18 18 0 14 18 30 18 30s18-16 18-30c0-10-8-18-18-18zm0 23a6 6 0 110-12 6 6 0 010 12z"/></g>
                  </svg>
                </section>

                <section class="pm-download-card">
                  <div class="pm-section-title"><span>⇩</span> Downloads</div>
                  <div class="pm-download-description">{_esc(download_description)}</div>
                </section>
                """,
                unsafe_allow_html=True,
            )

            # O download da diaria e a acao mais usada do dia: fica logo abaixo do
            # resultado, e nao no rodape da pagina.
            if daily_file_ready:
                st.download_button(
                    "⇩  Baixar última diária (.xlsx)",
                    data=content,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )
            else:
                st.button(
                    "⇩  Baixar última diária (.xlsx)",
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                )
                if error:
                    st.caption("Arquivo diário indisponível no momento.")

            st.markdown(
                f"""
                <section class="pm-reference-grid">
                  <article class="pm-reference-card">
                    <div class="pm-reference-heading"><div class="pm-reference-icon">□</div><div><div class="pm-reference-title">Arquivos</div><div class="pm-reference-subtitle">Arquivo utilizado para a importação<br/>e processamento dos dados.</div></div></div>
                    <div class="pm-reference-row"><div class="pm-reference-row-main">Base de entrada<small>input.xlsx padrão</small></div><span class="pm-reference-status {'ok' if has_default_input else 'bad'}">{'Disponível' if has_default_input else 'Ausente'}</span></div>
                    <div class="pm-reference-row"><div class="pm-reference-row-main">Última planilha gerada<small>{_esc(daily_size_label)}</small></div><span class="pm-reference-status {'ok' if daily_file_ready else 'warn'}">{'Disponível' if daily_file_ready else 'Indisponível'}</span></div>
                    <div class="pm-reference-note">Última verificação: {_esc(latest_check)}</div>
                  </article>

                  <article class="pm-reference-card">
                    <div class="pm-reference-heading"><div class="pm-reference-icon">◷</div><div><div class="pm-reference-title">Últimos Jobs</div><div class="pm-reference-subtitle">Últimas execuções realizadas pelo sistema.</div></div></div>
                    <div class="pm-reference-row" title="{_esc(latest_daily_id)}"><div class="pm-reference-row-main">Diário<small>{_esc(latest_daily_time)} · {_esc(daily_duration)}</small></div><span class="pm-reference-status {_status_tone(daily_status)}">{_esc(_status_label(daily_status))}</span></div>
                    <div class="pm-reference-row" title="{_esc(latest_manual_id)}"><div class="pm-reference-row-main">Manual<small>{_esc(latest_manual_time)} · {_esc(manual_duration)}</small></div><span class="pm-reference-status {_status_tone(manual_status)}">{_esc(_status_label(manual_status))}</span></div>
                    <div class="pm-reference-link">Ver histórico completo &nbsp; →</div>
                  </article>

                  <article class="pm-reference-card">
                    <div class="pm-reference-heading"><div class="pm-reference-icon">◉</div><div><div class="pm-reference-title">Conexão</div><div class="pm-reference-subtitle">Status da conexão com API e tokens.</div></div></div>
                    <div class="pm-reference-row"><div class="pm-reference-row-main">API<small>respondeu à consulta do painel</small></div><span class="pm-reference-status ok">Ativa</span></div>
                    <div class="pm-reference-row"><div class="pm-reference-row-main">Token<small>{'configurado no servidor' if bool(API_TOKEN) else 'as chamadas seguem sem autenticação'}</small></div><span class="pm-reference-status {'ok' if bool(API_TOKEN) else 'bad'}">{'OK' if bool(API_TOKEN) else 'Ausente'}</span></div>
                    <div class="pm-reference-note ok">Conexão verificada: {_esc(now_br.strftime('%d/%m/%Y %H:%M'))}</div>
                  </article>
                </section>

                <section class="pm-system-overview">
                  <div class="pm-section-title"><span>◉</span> Visão geral do sistema</div>
                  <div class="pm-metric-grid">
                    <div class="pm-metric"><div class="pm-metric-label">Coletas concluídas</div><div class="pm-metric-value">{done}<small>de {total_jobs}</small></div><div class="pm-metric-note">{running} em execução · {queued} em fila</div></div>
                    <div class="pm-metric"><div class="pm-metric-label">Execuções com falha</div><div class="pm-metric-value{' bad' if failed else ''}">{failed}</div><div class="pm-metric-note{' bad' if failed else ' good'}">{'Verifique o Histórico de Jobs' if failed else 'Nenhuma falha registrada'}</div></div>
                    <div class="pm-metric"><div class="pm-metric-label">Tempo médio</div><div class="pm-metric-value">{avg_duration}</div><div class="pm-metric-note">{avg_duration_note}</div></div>
                    <div class="pm-metric"><div class="pm-metric-label">Taxa de sucesso</div><div class="pm-metric-value">{success_rate:.1f}%</div><div class="pm-metric-note{' good' if not failed else ' bad'}">{failed} falha(s) em {finished_jobs} execução(ões)</div></div>
                    <div class="pm-metric"><div class="pm-metric-label">Próxima execução</div><div class="pm-metric-value">Diária</div><div class="pm-metric-note">{_esc(next_run_note)}</div></div>
                  </div>
                </section>
                """,
                unsafe_allow_html=True,
            )

            st.markdown('<div class="pm-dashboard-footer">Busca Preço © 2026 · Todos os direitos reservados.</div>', unsafe_allow_html=True)

        elif view == "_legacy_overview":
            st.markdown('<div class="pm-glass pm-panel">', unsafe_allow_html=True)
            st.markdown('<p class="pm-kicker">Resumo</p>', unsafe_allow_html=True)
            latest_manual = overview.get("latest_manual_job") if isinstance(overview.get("latest_manual_job"), dict) else {}
            latest_daily = overview.get("latest_daily_job") if isinstance(overview.get("latest_daily_job"), dict) else {}
            has_default_input = bool(overview.get("has_default_input"))
            latest_manual_id = str(latest_manual.get("job_id") or "").strip() or "-"
            latest_daily_id = str(latest_daily.get("job_id") or "").strip() or "-"

            st.markdown(
                f"""
                <div class="pm-info-grid">
                  <div class="pm-card">
                    <div class="pm-card-title">Arquivos</div>
                    <div class="pm-kv">
                      <span>base padr?o do servidor</span>
                      <span class="pm-badge {'pm-badge-ok' if has_default_input else 'pm-badge-warn'}">
                        {'Disponível' if has_default_input else 'Ausente'}
                      </span>
                    </div>
                  </div>

                  <div class="pm-card">
                    <div class="pm-card-title">Últimos jobs</div>
                    <div class="pm-kv">
                      <span>Manual</span>
                      <span class="pm-mono">{_esc(latest_manual_id)}</span>
                    </div>
                    <div class="pm-kv">
                      <span>Diário</span>
                      <span class="pm-mono">{_esc(latest_daily_id)}</span>
                    </div>
                  </div>

                  <div class="pm-card">
                    <div class="pm-card-title">Conexão</div>
                    <div class="pm-kv">
                      <span>API</span>
                      <span class="pm-badge pm-badge-ok">Ativo</span>
                    </div>
                    <div class="pm-kv">
                      <span>Token</span>
                      <span class="pm-badge {'pm-badge-ok' if bool(API_TOKEN) else 'pm-badge-warn'}">
                        {'OK' if bool(API_TOKEN) else 'Ausente'}
                      </span>
                    </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown('<div style="height: 12px"></div>', unsafe_allow_html=True)
            st.markdown("### Downloads")
            st.caption("Disponibilize a última planilha diária já processada para testes e validações.")

            can_download_daily_job = latest_daily_id != "-"

            # Preferir arquivo diário fixo (persistido em disco). Se não existir, tenta o último job diário em memória.
            ok_dl, content, error = _prepare_download_by_path("/download/daily/fixed")
            filename = _daily_result_filename()
            if (not ok_dl or not content) and can_download_daily_job:
                ok_dl, content, error = _prepare_download_for_job(latest_daily_id)
                filename = _daily_result_filename()

            if ok_dl and content:
                st.download_button(
                    "Baixar última diária (.xlsx)",
                    data=content,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )
            else:
                st.button(
                    "Baixar última diária (.xlsx)",
                    type="primary",
                    use_container_width=True,
                    disabled=True,
                )
                if error:
                    st.caption("Arquivo diário indisponível no momento.")

        elif view == "run":
            _section_head(
                "Execução Manual",
                "Novo processamento",
                "Envie uma planilha ou use a base padrão do servidor.",
            )

            st.markdown(
                """
                <div style="border:1px solid var(--bp-border);border-radius:12px;background:rgba(5,18,39,.72);padding:14px 16px;margin:6px 0 12px 0;">
                  <p style="margin:0 0 8px 0;font-weight:700;color:#ffffff;">Manual rápido (como executar e baixar resultados)</p>
                  <p style="margin:0;color:#cfd8e8;line-height:1.55;">
                    1. Escolha a base: a cadastrada no servidor ou uma planilha sua.<br/>
                    2. Para usar a sua, baixe a planilha modelo, preencha e faça o upload.<br/>
                    3. Clique em <strong style="color:#ffffff;">Iniciar coleta</strong>.<br/>
                    4. Acompanhe em <strong style="color:#ffffff;">Status</strong>.<br/>
                    5. Ao concluir, clique em <strong style="color:#ffffff;">Baixar resultado</strong>.
                  </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("### Planilha modelo")
            st.caption("Baixe um modelo, preencha com seus próximos produtos e faça upload abaixo.")
            tpl_ok, tpl_bytes, tpl_error = _build_template_xlsx_bytes()
            if tpl_ok and tpl_bytes:
                st.download_button(
                    "Baixar planilha modelo (modelo.xlsx)",
                    data=tpl_bytes,
                    file_name="Busca_Preco_modelo.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="secondary",
                    use_container_width=True,
                )
            else:
                st.caption(tpl_error or "Modelo indisponível no momento.")

            st.markdown('<div style="height: 12px"></div>', unsafe_allow_html=True)

            has_default_input = bool(overview.get("has_default_input"))
            output_mode = "completa"

            # Antes eram dois botoes "Executar" com o mesmo peso, cada um habilitado
            # por um controle diferente. A escolha da base virou um seletor, e sobrou
            # um unico botao para iniciar.
            BASE_PADRAO = "Base cadastrada no servidor"
            BASE_UPLOAD = "Enviar a minha planilha"
            source = st.radio(
                "De onde vem a lista de produtos",
                options=[BASE_PADRAO, BASE_UPLOAD],
                index=0 if has_default_input else 1,
                horizontal=True,
            )

            uploaded = None
            if source == BASE_PADRAO:
                if has_default_input:
                    st.caption("Usa os produtos já cadastrados no servidor (input.xlsx padrão).")
                else:
                    st.warning("A base padrão não está disponível no servidor. Envie uma planilha para continuar.")
            else:
                uploaded = st.file_uploader("Planilha (.xlsx)", type=["xlsx"])
                st.caption("Use a planilha modelo acima — ela já vem com as colunas certas.")

            blocked = not has_default_input if source == BASE_PADRAO else uploaded is None
            start_run = st.button(
                "Iniciar coleta",
                type="primary",
                use_container_width=True,
                disabled=blocked,
                help="Você vai para a tela de Status assim que a coleta começar.",
            )

            if start_run:
                files = None
                if source == BASE_UPLOAD and uploaded is not None:
                    files = {
                        "file": (
                            uploaded.name or "input.xlsx",
                            uploaded.getvalue(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    }
                ok, _, data, message = _request_form(
                    "POST",
                    "/api/run",
                    data={"output_mode": str(output_mode)},
                    files=files,
                    timeout=60,
                )
                if not ok:
                    st.error(message or "Falha ao iniciar job.")
                else:
                    job_id = str(data.get("job_id") or "").strip()
                    if job_id:
                        st.session_state["last_job_id"] = job_id
                        st.success(f"Job iniciado: {job_id}")
                        st.session_state["pm_view"] = "status"
                        st.rerun()
                    else:
                        st.success("Job iniciado.")

        elif view == "history":
            latest_manual = overview.get("latest_manual_job") if isinstance(overview.get("latest_manual_job"), dict) else {}
            latest_daily = overview.get("latest_daily_job") if isinstance(overview.get("latest_daily_job"), dict) else {}
            history_rows = []
            for label, job in (("Manual", latest_manual), ("Diário", latest_daily)):
                if not job:
                    continue
                history_rows.append(
                    f'<div class="pm-reference-row"><div class="pm-reference-row-main">{label}'
                    f'<small>{_esc(_fmt_timestamp(job.get("created_at")))}</small></div>'
                    f'<div class="pm-reference-row-main">{_esc(job.get("job_id") or "-")} &nbsp; '
                    f'<span class="pm-reference-status {_status_tone(job.get("status"))}">'
                    f'{_esc(_status_label(job.get("status")))}</span></div></div>'
                )
            st.markdown(
                '<section class="pm-reference-card" style="min-height:260px">'
                '<div class="pm-reference-heading"><div class="pm-reference-icon">◷</div>'
                '<div><div class="pm-reference-title">Histórico de Jobs</div>'
                '<div class="pm-reference-subtitle">Execuções mais recentes registradas pelo sistema.</div></div></div>'
                + ("".join(history_rows) or '<div class="pm-reference-note">Nenhuma execução encontrada.</div>')
                + "</section>",
                unsafe_allow_html=True,
            )

        elif view == "downloads":
            latest_daily = overview.get("latest_daily_job") if isinstance(overview.get("latest_daily_job"), dict) else {}
            latest_daily_id = str(latest_daily.get("job_id") or "").strip() or "-"
            st.markdown(
                '<section class="pm-download-card"><div class="pm-section-title"><span>⇩</span> Downloads</div>'
                '<div class="pm-download-description">Baixe a última planilha diária processada pelo sistema.</div></section>',
                unsafe_allow_html=True,
            )
            ok_dl, content, error = _prepare_download_by_path("/download/daily/fixed")
            if (not ok_dl or not content) and latest_daily_id != "-":
                ok_dl, content, error = _prepare_download_for_job(latest_daily_id)
            if ok_dl and content:
                st.download_button(
                    "⇩  Baixar última diária (.xlsx)",
                    data=content,
                    file_name=_daily_result_filename(),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    use_container_width=True,
                )
            else:
                st.button("⇩  Baixar última diária (.xlsx)", disabled=True, use_container_width=True)
                st.caption(error or "Arquivo diário indisponível no momento.")

        elif view == "settings":
            st.markdown(
                '<section class="pm-reference-card" style="min-height:220px">'
                '<div class="pm-reference-heading"><div class="pm-reference-icon">⚙</div>'
                '<div><div class="pm-reference-title">Configurações</div>'
                '<div class="pm-reference-subtitle">A API, o token e a programação automática são administrados pelo servidor.</div></div></div>'
                f'<div class="pm-reference-row"><div class="pm-reference-row-main">API</div><span class="pm-reference-status ok">Ativa</span></div>'
                f'<div class="pm-reference-row"><div class="pm-reference-row-main">Token</div><span class="pm-reference-status {"ok" if API_TOKEN else "bad"}">{"Configurado" if API_TOKEN else "Ausente"}</span></div>'
                '</section>',
                unsafe_allow_html=True,
            )

        elif view == "help":
            st.markdown(
                '<section class="pm-reference-card" style="min-height:250px">'
                '<div class="pm-reference-heading"><div class="pm-reference-icon">?</div>'
                '<div><div class="pm-reference-title">Ajuda</div><div class="pm-reference-subtitle">Fluxo rápido para executar uma pesquisa.</div></div></div>'
                '<div class="pm-reference-row"><div class="pm-reference-row-main">1. Acesse Execução Manual e escolha a base padrão ou envie sua planilha.</div></div>'
                '<div class="pm-reference-row"><div class="pm-reference-row-main">2. Inicie o processamento e acompanhe a evolução em Status.</div></div>'
                '<div class="pm-reference-row"><div class="pm-reference-row-main">3. Ao finalizar, baixe o resultado em Downloads.</div></div>'
                '</section>',
                unsafe_allow_html=True,
            )

        elif view == "status":
            _section_head(
                "Status em tempo real",
                "Acompanhamento do job",
                "Estado, entregas e resultado da execução mais recente.",
            )

            job_id = str(st.session_state.get("last_job_id") or "").strip()
            if not job_id:
                latest_manual = overview.get("latest_manual_job") if isinstance(overview.get("latest_manual_job"), dict) else {}
                job_id = str(latest_manual.get("job_id") or "").strip()

            if not job_id:
                # A tela terminava aqui, sem caminho de saida. Agora oferece o proximo passo.
                st.info("Nenhuma coleta foi executada ainda nesta sessão.")
                if st.button(
                    "Ir para Execução Manual",
                    type="primary",
                    use_container_width=True,
                    key="pm_status_goto_run",
                ):
                    st.session_state["pm_view"] = "run"
                    st.rerun()
                return

            # As chaves viram classes st-key-* no container, e e por elas que o CSS
            # pinta cada botao. O marcador invisivel anterior empurrava o botao
            # para baixo e desalinhava a linha de acoes.
            st.markdown(
                f'<div class="pm-job-chip">Job atual <code>{_esc(job_id)}</code></div>',
                unsafe_allow_html=True,
            )
            action_col1, action_col2 = st.columns(2)
            with action_col1:
                refresh = st.button(
                    "Atualizar", use_container_width=True, key="pm_status_refresh"
                )
            with action_col2:
                stop = st.button(
                    "Parar execução", use_container_width=True, key="pm_status_stop"
                )

            if stop:
                _request_json("POST", "/api/jobs/stop", timeout=8)

            if refresh or True:
                ok, _, status_payload, message = _request_json("GET", f"/api/status/{job_id}", timeout=8)
                if not ok:
                    st.error(message or "Falha ao buscar status do job.")
                    return

                if isinstance(status_payload, dict):
                    status_value = str(status_payload.get("status") or "").strip().upper() or "-"
                    # A API devolve epoch em float: sem formatar, a tela mostrava
                    # "1756213448.1234". Agora sai como data e hora de Brasilia.
                    created_at = _fmt_timestamp(status_payload.get("created_at"))
                    started_at = _fmt_timestamp(status_payload.get("started_at"))
                    finished_at = _fmt_timestamp(status_payload.get("finished_at"))
                    job_duration = _fmt_duration(_job_duration_seconds(status_payload))
                    error_text = str(status_payload.get("error") or "").strip()

                    delivery = {
                        "Email": str(status_payload.get("email_status") or "").strip() or "-",
                        "WhatsApp": str(status_payload.get("whatsapp_status") or "").strip() or "-",
                        "Drive": str(status_payload.get("drive_status") or "").strip() or "-",
                    }

                    badge_class = "pm-badge-info"
                    if status_value in {"DONE", "SUCCESS", "COMPLETED"}:
                        badge_class = "pm-badge-ok"
                    elif status_value in {"FAILED", "ERROR"}:
                        badge_class = "pm-badge-bad"
                    elif status_value in {"QUEUED", "PENDING"}:
                        badge_class = "pm-badge-warn"

                    def _delivery_badge(value: str) -> str:
                        normalized = value.strip().upper()
                        if normalized in {"DONE", "SENT", "OK", "SUCCESS"}:
                            return "pm-badge-ok"
                        if normalized in {"SKIPPED", "DISABLED", "PENDING"}:
                            return "pm-badge-warn"
                        if normalized in {"FAILED", "ERROR"}:
                            return "pm-badge-bad"
                        return "pm-badge-info"

                    def _humanize_delivery_status(value: str) -> str:
                        normalized = value.strip().upper()
                        if normalized in {"DONE", "SENT", "OK", "SUCCESS", "COMPLETED"}:
                            return "Concluído"
                        if normalized in {"PENDING", "QUEUED"}:
                            return "Pendente"
                        if normalized in {"SKIPPED", "DISABLED"}:
                            return "Ignorado"
                        if normalized in {"FAILED", "ERROR"}:
                            return "Falhou"
                        if not normalized or normalized == "-":
                            return "-"
                        return value

                    deliveries_html = "\n".join(
                        (
                            f'<div class="pm-kv">'
                            f'<span>{_esc(label)}</span>'
                            f'<span class="pm-badge {_delivery_badge(value)}">{_esc(_humanize_delivery_status(value))}</span>'
                            f"</div>"
                        )
                        for label, value in delivery.items()
                    )

                    status_html = (
                        f'<div class="pm-info-grid" style="grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 6px;">'
                        f'<div class="pm-card">'
                        f'<div class="pm-card-title">Status do job</div>'
                        f'<div class="pm-kv"><span>Estado</span><span class="pm-badge {badge_class}">{_esc(_status_label(status_value))}</span></div>'
                        f'<div class="pm-kv"><span>Criado</span><span class="pm-mono">{_esc(created_at)}</span></div>'
                        f'<div class="pm-kv"><span>Iniciado</span><span class="pm-mono">{_esc(started_at)}</span></div>'
                        f'<div class="pm-kv"><span>Finalizado</span><span class="pm-mono">{_esc(finished_at)}</span></div>'
                        f'<div class="pm-kv"><span>Duração</span><span class="pm-mono">{_esc(job_duration)}</span></div>'
                        f"</div>"
                        f'<div class="pm-card">'
                        f'<div class="pm-card-title">Entregas</div>'
                        f"{deliveries_html}"
                        f"</div>"
                        f"</div>"
                    )
                    st.markdown(status_html, unsafe_allow_html=True)

                    if error_text:
                        lowered = error_text.lower()
                        if "401" in lowered or "403" in lowered or "unauthor" in lowered or "credenc" in lowered:
                            error_hint = (
                                "A credencial do marketplace foi recusada. Renove o token em "
                                "Configurações e execute a coleta novamente."
                            )
                        elif "timeout" in lowered or "timed out" in lowered or "conexão" in lowered or "connection" in lowered:
                            error_hint = (
                                "A coleta perdeu conexão com o site consultado. Costuma ser "
                                "instabilidade momentânea — tente novamente em alguns minutos."
                            )
                        elif "coluna" in lowered or "column" in lowered or "planilha" in lowered:
                            error_hint = (
                                "A planilha de entrada não tem o formato esperado. Baixe a "
                                "planilha modelo em Execução Manual e compare as colunas."
                            )
                        else:
                            error_hint = (
                                "Guarde a mensagem acima e tente novamente. Se repetir, "
                                "verifique o Histórico de Jobs para ver se é uma falha recorrente."
                            )
                        st.markdown(
                            f"""
                            <div class="pm-error-card">
                              <div class="pm-error-title">A coleta não foi concluída</div>
                              <div class="pm-error-message">{_esc(error_text)}</div>
                              <div class="pm-error-hint"><b>O que costuma resolver</b>{_esc(error_hint)}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if st.button("Tentar novamente", type="primary", use_container_width=True):
                            st.session_state["pm_view"] = "run"
                            st.rerun()

                download_path = str(status_payload.get("download_url") or "").strip() if isinstance(status_payload, dict) else ""
                if download_path:
                    dl_ok, content, dl_error = _download_bytes(download_path, timeout=60)
                    if dl_ok and content:
                        st.download_button(
                            label="Baixar resultado",
                            data=content,
                            file_name="resultado.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            type="primary",
                            use_container_width=True,
                        )
                    elif dl_error:
                        st.caption(f"Download indisponível: {dl_error}")

        else:
            st.session_state["pm_view"] = "overview"
            st.rerun()

_install_dom_integrity_guard()
_require_login()
_render_shell_css()

api_ok, api_error = _validate_api_base()
if not api_ok:
    st.error("Falha de conexao com a API configurada.")
    st.caption(api_error)
    st.warning(
        "Inicie o sistema por `run.ps1` para subir API+UI com portas corretas, "
        "ou ajuste `API_BASE` para a URL da API deste projeto."
    )
    st.stop()

ui_url = _build_api_ui_url()
current_user = _session_user()
is_admin = _is_admin_user()

if is_admin and _admin_view_requested():
    st.subheader("Administracao")
    st.caption(f"Usuario: {current_user.get('username', '-')} | Perfil: {current_user.get('role', '-')}")
    if st.button("Voltar ao painel", use_container_width=False):
        st.query_params.clear()
        st.rerun()
    _render_admin_panel()
else:
    if _should_embed_api_iframe():
        _render_iframe(ui_url, height=EMBEDDED_HEIGHT)
    else:
        _render_native_panel()
