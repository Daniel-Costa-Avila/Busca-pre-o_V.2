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

def _should_embed_api_iframe() -> bool:
    raw = os.getenv("UI_EMBED_API_IFRAME")
    if raw is not None:
        return _parse_bool_env(raw, default=True)

    # Auto-detect: when accessed via a reverse proxy / Funnel, embedding the API UI iframe
    # (usually pointing at http://127.0.0.1:8000) fails on the client browser.
    try:
        host = str(st.context.headers.get("host") or "").lower()
        if host and not host.startswith(("127.0.0.1", "localhost")):
            return False
        url = str(getattr(st.context, "url", "") or "")
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname not in {"127.0.0.1", "localhost"}:
            return False
    except Exception:
        pass

    return True


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

        /* Redesign visual: limpo, profissional e com hierarquia clara */
        :root {
            --font-display: Arial, sans-serif !important;
            --font-body: Arial, sans-serif !important;
            --bg-base: #f6f8fb !important;
            --bg-muted: #eef2f7 !important;
            --surface: #ffffff !important;
            --surface-strong: #ffffff !important;
            --ink: #101828 !important;
            --muted: #475467 !important;
            --line-soft: #e4e7ec !important;
            --line: #d0d5dd !important;
            --radius-lg: 18px !important;
            --radius-md: 14px !important;
            --radius-sm: 10px !important;
            --shadow-card: 0 8px 24px rgba(16, 24, 40, 0.06) !important;
            --shadow-inner: inset 0 1px 0 rgba(255, 255, 255, 0.92) !important;
        }

        html, body, [data-testid="stAppViewContainer"] {
            font-family: Arial, sans-serif !important;
            color: var(--ink) !important;
            background: linear-gradient(180deg, var(--bg-base) 0%, var(--bg-muted) 100%) !important;
        }
        [data-testid="stAppViewContainer"]::after {
            display: none !important;
        }
        [data-testid="stAppViewContainer"] * {
            font-family: Arial, sans-serif !important;
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
            background: #ffffff !important;
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
        }
        .pm-sub {
            color: var(--muted) !important;
        }

        .pm-kpi p {
            color: #344054 !important;
            font-size: 0.76rem !important;
        }
        .pm-kpi strong {
            color: #101828 !important;
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
            color: #667085 !important;
            font-weight: 700 !important;
        }
        .pm-pathbar strong,
        .pm-card-title {
            color: #101828 !important;
            letter-spacing: -0.01em !important;
        }

        .pm-kv {
            background: #f9fafb !important;
            border: 1px solid #eaecf0 !important;
            border-radius: 10px !important;
        }
        .pm-kv span:first-child,
        .pm-mono {
            color: #344054 !important;
        }
        .pm-badge {
            background: #f2f4f7 !important;
            border-color: #d0d5dd !important;
            color: #344054 !important;
        }
        .pm-badge-ok {
            background: #ecfdf3 !important;
            border-color: #abefc6 !important;
            color: #067647 !important;
        }
        .pm-badge-warn {
            background: #fffaeb !important;
            border-color: #fedf89 !important;
            color: #b54708 !important;
        }
        .pm-badge-bad {
            background: #fef3f2 !important;
            border-color: #fecdca !important;
            color: #b42318 !important;
        }
        .pm-badge-info {
            background: #eff8ff !important;
            border-color: #b2ddff !important;
            color: #175cd3 !important;
        }

        .pm-sidebar [data-testid="stButton"] button {
            justify-content: flex-start !important;
            border-radius: 12px !important;
            border: 1px solid #d0d5dd !important;
            background: #ffffff !important;
            color: #101828 !important;
            box-shadow: none !important;
        }
        .pm-sidebar [data-testid="stButton"] button[kind="primary"] {
            background: linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%) !important;
            border-color: rgba(37, 99, 235, 0.34) !important;
            color: #ffffff !important;
            box-shadow: 0 8px 20px rgba(37, 99, 235, 0.28) !important;
        }

        .stButton > button {
            border-radius: 12px !important;
            font-weight: 600 !important;
        }
        .stButton > button[aria-label*="Executar"] {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
            border-color: rgba(37, 99, 235, 0.38) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Baixar"] {
            background: linear-gradient(135deg, #16a34a 0%, #15803d 100%) !important;
            border-color: rgba(22, 163, 74, 0.38) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Atualizar"] {
            background: linear-gradient(135deg, #0891b2 0%, #0e7490 100%) !important;
            border-color: rgba(8, 145, 178, 0.38) !important;
            color: #ffffff !important;
        }
        .stButton > button[aria-label*="Parar"] {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
            border-color: rgba(220, 38, 38, 0.38) !important;
            color: #ffffff !important;
        }

        .pm-auto-banner {
            border-radius: 16px !important;
            border: 1px solid #bfdbfe !important;
            background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 55%, #bfdbfe 100%) !important;
            box-shadow: 0 10px 24px rgba(37, 99, 235, 0.12) !important;
        }
        .pm-auto-banner__title {
            color: #1d4ed8 !important;
        }
        .pm-auto-banner__subtitle {
            color: #1e3a8a !important;
        }
        .pm-auto-banner__time,
        .pm-auto-banner__icon {
            background: linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%) !important;
            color: #ffffff !important;
            border-color: rgba(37, 99, 235, 0.35) !important;
        }

        /* Bloco de execução manual: melhorar contraste e legibilidade */
        [data-testid="stExpander"] details {
            border: 1px solid #e4e7ec !important;
            border-radius: 12px !important;
            background: #ffffff !important;
        }
        [data-testid="stExpander"] details summary::-webkit-details-marker {
            display: none !important;
        }
        [data-testid="stExpander"] summary {
            position: relative !important;
            padding-left: 2rem !important;
            background: #ffffff !important;
            color: #101828 !important;
        }
        [data-testid="stExpander"] summary::before {
            content: "▸";
            position: absolute;
            left: 0.75rem;
            top: 50%;
            transform: translateY(-50%);
            color: #475467;
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
            color: #101828 !important;
            font-weight: 600 !important;
            margin: 0 !important;
        }

        [data-testid="stFileUploaderDropzone"] {
            background: #f8fafc !important;
            border: 1px solid #d0d5dd !important;
            color: #344054 !important;
        }
        [data-testid="stFileUploaderDropzone"] * {
            color: #344054 !important;
        }
        [data-testid="stFileUploaderDropzone"] button {
            min-width: 132px !important;
            border-radius: 10px !important;
            border: 1px solid #1d4ed8 !important;
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
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
            color: #1f2937 !important;
            opacity: 1 !important;
        }

        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] span {
            color: #344054 !important;
            opacity: 1 !important;
        }
        [data-testid="stCheckbox"] p {
            color: #344054 !important;
            opacity: 1 !important;
            font-weight: 600 !important;
        }

        .stButton > button:disabled {
            background: #eaecf0 !important;
            border-color: #d0d5dd !important;
            color: #98a2b3 !important;
            opacity: 1 !important;
            box-shadow: none !important;
        }
        .stDownloadButton > button,
        [data-testid="stDownloadButton"] > button {
            border-radius: 12px !important;
            border: 1px solid rgba(22, 163, 74, 0.38) !important;
            background: linear-gradient(135deg, #16a34a 0%, #15803d 100%) !important;
            color: #ffffff !important;
            font-weight: 600 !important;
            box-shadow: 0 10px 24px rgba(22, 163, 74, 0.24) !important;
        }
        .stDownloadButton > button:disabled,
        [data-testid="stDownloadButton"] > button:disabled {
            background: #eaecf0 !important;
            border-color: #d0d5dd !important;
            color: #98a2b3 !important;
            box-shadow: none !important;
        }

        /* Correcao final da tela "Manual de Execucao" */
        [data-testid="stButton"] > button {
            color: #0f172a !important;
            background: linear-gradient(180deg, #ffffff 0%, #eef2f7 100%) !important;
            border: 1px solid #cbd5e1 !important;
        }
        [data-testid="stButton"] > button[aria-label*="Executar com base cadastrada"] {
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
            border-color: rgba(220, 38, 38, 0.36) !important;
            color: #ffffff !important;
        }
        [data-testid="stButton"] > button[aria-label*="Executar com sua planilha"] {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
            border-color: rgba(37, 99, 235, 0.36) !important;
            color: #ffffff !important;
        }
        [data-testid="stButton"] > button:disabled,
        [data-testid="stButton"] > button[aria-label*="Executar com sua planilha"]:disabled,
        [data-testid="stButton"] > button[aria-label*="Executar com base cadastrada"]:disabled {
            background: #e5e7eb !important;
            border-color: #cbd5e1 !important;
            color: #667085 !important;
            text-shadow: none !important;
            opacity: 1 !important;
            box-shadow: none !important;
        }

        [data-testid="stDownloadButton"] > button {
            background: linear-gradient(135deg, #16a34a 0%, #15803d 100%) !important;
            border-color: rgba(22, 163, 74, 0.36) !important;
            color: #ffffff !important;
        }
        [data-testid="stDownloadButton"] > button:disabled {
            background: #e5e7eb !important;
            border-color: #cbd5e1 !important;
            color: #667085 !important;
            opacity: 1 !important;
        }

        /* Funnel: correcao definitiva do uploader (evita "uploadcarregar" sobreposto) */
        [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] button {
            position: relative !important;
            min-width: 156px !important;
            height: 36px !important;
            padding: 0 14px !important;
            border-radius: 10px !important;
            border: 1px solid #1d4ed8 !important;
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
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
            color: #1f2937 !important;
            opacity: 1 !important;
        }

        /* Funnel: cor forte para o texto do checkbox acima do upload */
        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] label p,
        [data-testid="stCheckbox"] div,
        [data-testid="stCheckbox"] span {
            color: #374151 !important;
            opacity: 1 !important;
            font-weight: 600 !important;
        }

        /* Esconde texto de icone quebrado (ex.: keyboard_arrow_down) */
        [data-testid="stExpander"] summary [class*="material"],
        [data-testid="stExpander"] summary i {
            display: none !important;
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
    template_path = Path(r"C:\Users\daniel.avila\Desktop\modelo.xlsx")
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

    st.markdown(
        f"""
        <div class="pm-topbar">
          <div class="pm-brand">
            <div class="pm-mark">BP</div>
            <div style="min-width:0">
              <div class="pm-title">{UI_BRAND_NAME}</div>
            </div>
          </div>
          <div class="pm-actions"></div>
        </div>
        """,
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

    st.markdown(
        f"""
        <div class="pm-kpi-grid" style="margin-top: 12px;">
          <div class="pm-kpi pm-tone-wait"><p>Em fila</p><strong>{queued}</strong></div>
          <div class="pm-kpi pm-tone-run"><p>Em execução</p><strong>{running}</strong></div>
          <div class="pm-kpi pm-tone-done"><p>Concluídos</p><strong>{done}</strong></div>
          <div class="pm-kpi pm-tone-fail"><p>Falhas</p><strong>{failed}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="pm-layout">', unsafe_allow_html=True)

    nav_col, main_col = st.columns([0.25, 0.75], gap="large")

    with nav_col:
        st.markdown('<div class="pm-glass pm-sidebar">', unsafe_allow_html=True)
        st.markdown('<div class="pm-nav-title">Navegação</div>', unsafe_allow_html=True)

        def _nav_button(label: str, view: str) -> None:
            active = st.session_state.get("pm_view") == view
            if st.button(
                label,
                type="primary" if active else "secondary",
                use_container_width=True,
                key=f"pm_nav_{view}",
            ):
                st.session_state["pm_view"] = view
                st.rerun()

        _nav_button("Resumo", "overview")
        _nav_button("Execução Manual", "run")
        _nav_button("Status", "status")

        st.markdown('<div class="pm-help">', unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with main_col:
        view = str(st.session_state.get("pm_view") or "overview")

        path_title = "Painel / Resumo"
        if view == "run":
            path_title = "Painel / Execução Manual"
        elif view == "status":
            path_title = "Painel / Status"

        st.markdown(
            f"""
            <div class="pm-pathbar pm-glass">
              <p class="pm-kicker">Contexto</p>
              <strong>{path_title}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if view == "overview":
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

            st.markdown("</div>", unsafe_allow_html=True)

        elif view == "run":
            st.markdown('<div class="pm-glass pm-panel">', unsafe_allow_html=True)
            st.markdown('<p class="pm-kicker">Execução Manual</p>', unsafe_allow_html=True)
            st.subheader("Novo processamento")
            st.caption("Envie uma planilha ou use a base padrao do servidor.")

            st.markdown(
                """
                <div style="border:1px solid #e4e7ec;border-radius:12px;background:#ffffff;padding:14px 16px;margin:6px 0 12px 0;">
                  <p style="margin:0 0 8px 0;font-weight:700;color:#101828;">Manual rápido (como executar e baixar resultados)</p>
                  <p style="margin:0;color:#344054;line-height:1.55;">
                    1. Baixe a planilha modelo e preencha os produtos.<br/>
                    2. Faça upload da planilha.<br/>
                    3. Clique em <strong>Executar com sua planilha</strong>.<br/>
                    4. Acompanhe em <strong>Status</strong>.<br/>
                    5. Ao concluir, clique em <strong>Baixar resultado</strong>.
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
            use_default = st.checkbox(
                "Usar base padrão do servidor quando nenhum arquivo for enviado",
                value=has_default_input,
            )
            uploaded = st.file_uploader("Planilha (.xlsx)", type=["xlsx"])
            output_mode = "completa"

            run_col1, run_col2 = st.columns([1, 1])
            with run_col1:
                run_default = st.button(
                    "Executar com base cadastrada (padrão)",
                    type="primary",
                    use_container_width=True,
                    disabled=not use_default,
                    help="Inicia a coleta usando os produtos já cadastrados no servidor (base padrão).",
                )
                st.caption("Usa a base padrão já carregada. Ideal para rodar o processo completo rapidamente.")
            with run_col2:
                run_upload = st.button(
                    "Executar com sua planilha (personalizado)",
                    use_container_width=True,
                    disabled=uploaded is None,
                    help="Executa uma pesquisa personalizada usando a planilha que você enviou.",
                )
                st.caption("Permite testar novos produtos e critérios. Recomendado para validações e ajustes.")

            if run_default or run_upload:
                files = None
                if run_upload and uploaded is not None:
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

            st.markdown("</div>", unsafe_allow_html=True)

        else:
            st.markdown('<div class="pm-glass pm-panel">', unsafe_allow_html=True)
            st.markdown('<p class="pm-kicker">Status em tempo real</p>', unsafe_allow_html=True)
            st.subheader("Acompanhamento do job")

            job_id = str(st.session_state.get("last_job_id") or "").strip()
            if not job_id:
                latest_manual = overview.get("latest_manual_job") if isinstance(overview.get("latest_manual_job"), dict) else {}
                job_id = str(latest_manual.get("job_id") or "").strip()

            if not job_id:
                st.info("Nenhum job encontrado ainda.")
                st.markdown("</div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)
                return

            action_col1, action_col2, action_col3 = st.columns([1, 1, 2])
            with action_col1:
                refresh = st.button("Atualizar", use_container_width=True)
            with action_col2:
                stop = st.button("Parar execução", use_container_width=True)
            with action_col3:
                st.caption(f"Job atual: `{job_id}`")

            if stop:
                _request_json("POST", "/api/jobs/stop", timeout=8)

            if refresh or True:
                ok, _, status_payload, message = _request_json("GET", f"/api/status/{job_id}", timeout=8)
                if not ok:
                    st.error(message or "Falha ao buscar status do job.")
                    st.markdown("</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                    return

                if isinstance(status_payload, dict):
                    status_value = str(status_payload.get("status") or "").strip().upper() or "-"
                    created_at = str(status_payload.get("created_at") or "").strip() or "-"
                    started_at = str(status_payload.get("started_at") or "").strip() or "-"
                    finished_at = str(status_payload.get("finished_at") or "").strip() or "-"
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
                        f'<div class="pm-kv"><span>Estado</span><span class="pm-badge {badge_class}">{_esc(status_value)}</span></div>'
                        f'<div class="pm-kv"><span>Criado</span><span class="pm-mono">{_esc(created_at)}</span></div>'
                        f'<div class="pm-kv"><span>Iniciado</span><span class="pm-mono">{_esc(started_at)}</span></div>'
                        f'<div class="pm-kv"><span>Finalizado</span><span class="pm-mono">{_esc(finished_at)}</span></div>'
                        f"</div>"
                        f'<div class="pm-card">'
                        f'<div class="pm-card-title">Entregas</div>'
                        f"{deliveries_html}"
                        f"</div>"
                        f"</div>"
                    )
                    st.markdown(status_html, unsafe_allow_html=True)

                    if error_text:
                        st.error(error_text)

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

            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


_require_login()
_render_shell_css()

st.markdown(
    f"""
    <div class="pm-auto-banner" role="status" aria-live="polite">
      <div class="pm-auto-banner__left">
        <div class="pm-auto-banner__icon" aria-hidden="true">!</div>
        <div class="pm-auto-banner__text">
          <p class="pm-auto-banner__title">Atualização automática diária</p>
          <p class="pm-auto-banner__subtitle">O sistema atualiza todos os dias às <strong>{html.escape(AUTO_DAILY_UPDATE_TIME)}</strong> da manhã (horário de Brasília).</p>
        </div>
      </div>
      <div class="pm-auto-banner__time">{html.escape(AUTO_DAILY_UPDATE_TIME)}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

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
