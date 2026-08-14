from __future__ import annotations

from functools import lru_cache
from os import cpu_count
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------- CONFIG ----------------

INPUT_FILE = "input.xlsx"
INPUT_MERCADO_LIVRE_FILE = (
    r"C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS\Planilha diaria\Relatorio_Financeiro.xlsx"
)
INPUT_MERCADO_LIVRE_COTIA_FILE = (
    r"C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS\Planilha diaria Cotia\Relatorio_Financeiro_Cotia.xlsx"
)
OUTPUT_FILE = "output.xlsx"
DEFAULT_BACKUP_OUTPUT_DIR = Path(r"C:\Users\daniel.avila\Desktop\Planilhas\Backup de Planilhas")
OUTPUT_HEADERS = [
    "id no Canal",
    "CODIGO INTERNO",
    "Canal",
    "Titulo",
    "Preco",
    "Link",
]

SUMMARY_CHANNEL_COLUMNS = [
    "Magazine Luiza",
    "Casas Bahia",
    "Web Continental",
    "Casa e Video",
    "Madeiramadeira",
    "Zema",
    "Mercado Livre",
    "Carrefour",
]

SUMMARY_HEADERS = [
    "CODIGO INTERNO",
    "CODIGO LOJISTA",
    "PRODUTO",
    "Probel (oficial)",
    "LOJA MENOR PREÇO",
    "SELLER MENOR PREÇO",
    "MENOR PRECO",
    "PREÇO MÉDIO",
    "QUANTIDADE DE LOJAS",
    *SUMMARY_CHANNEL_COLUMNS,
]


class ScraperSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    input_file: str = "input.xlsx"
    output_file: str = "output.xlsx"

    enable_parallel_scraping: bool = True
    max_workers: int = cpu_count() or 4
    max_selenium_sessions: int = 3
    selenium_driver_max_tasks: int = 15
    selenium_page_load_timeout: int = 35
    selenium_open_retry_attempts: int = 3
    selenium_open_retry_min_seconds: float = 1.0
    selenium_open_retry_max_seconds: float = 6.0

    clear_browser_cache_on_finish: bool = False
    headless: bool | None = None

    @field_validator("max_workers")
    @classmethod
    def _clamp_max_workers(cls, value: int) -> int:
        return min(32, max(1, value))

    @field_validator("max_selenium_sessions")
    @classmethod
    def _clamp_max_selenium_sessions(cls, value: int) -> int:
        return min(32, max(1, value))

    @field_validator("selenium_driver_max_tasks")
    @classmethod
    def _clamp_selenium_driver_max_tasks(cls, value: int) -> int:
        return min(200, max(1, value))

    @field_validator("selenium_page_load_timeout")
    @classmethod
    def _clamp_page_load_timeout(cls, value: int) -> int:
        return min(300, max(5, value))

    @field_validator("selenium_open_retry_attempts")
    @classmethod
    def _clamp_open_retry_attempts(cls, value: int) -> int:
        return min(10, max(1, value))

    @field_validator("selenium_open_retry_min_seconds")
    @classmethod
    def _clamp_open_retry_min(cls, value: float) -> float:
        return min(20.0, max(0.2, value))

    @field_validator("selenium_open_retry_max_seconds")
    @classmethod
    def _clamp_open_retry_max(cls, value: float) -> float:
        return min(60.0, max(0.5, value))


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_token: str = ""
    max_active_jobs: int = 5

    daily_auto_enabled: bool = True
    daily_run_times: str = "02:00,12:00,18:00"
    daily_run_hour: int | None = None
    daily_run_minute: int | None = None

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    gmail_user: str = ""
    gmail_address: str = ""
    gmail_app_password: str = ""
    gmail_sender: str = ""
    email_recipients: str = ""
    email_send_on: str = "AUTO_DIARIO,MANUAL"
    email_subject_prefix: str = "[Price Monitor]"
    email_delivery_mode: str = "auto"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    whatsapp_recipients: str = ""
    whatsapp_send_on: str = "AUTO_DIARIO"
    whatsapp_message_prefix: str = "[Price Monitor]"
    whatsapp_media_enabled: bool = False
    app_public_base_url: str = ""

    google_drive_credentials_file: str = ""
    google_drive_folder_id: str = ""
    google_drive_send_on: str = ""

    smtp_retry_attempts: int = 3
    smtp_retry_min_seconds: float = 1.0
    smtp_retry_max_seconds: float = 8.0

    ui_events_interval_seconds: int = 2

    @field_validator("max_active_jobs")
    @classmethod
    def _clamp_max_active_jobs(cls, value: int) -> int:
        return min(20, max(1, value))

    @field_validator("smtp_port")
    @classmethod
    def _clamp_smtp_port(cls, value: int) -> int:
        return min(65535, max(1, value))

    @field_validator("smtp_retry_attempts")
    @classmethod
    def _clamp_smtp_retry_attempts(cls, value: int) -> int:
        return min(10, max(1, value))

    @field_validator("smtp_retry_min_seconds")
    @classmethod
    def _clamp_smtp_retry_min(cls, value: float) -> float:
        return min(20.0, max(0.2, value))

    @field_validator("smtp_retry_max_seconds")
    @classmethod
    def _clamp_smtp_retry_max(cls, value: float) -> float:
        return min(60.0, max(0.5, value))

    @field_validator("ui_events_interval_seconds")
    @classmethod
    def _clamp_ui_events_interval(cls, value: int) -> int:
        return min(30, max(1, value))


@lru_cache(maxsize=1)
def get_scraper_settings() -> ScraperSettings:
    return ScraperSettings()


@lru_cache(maxsize=1)
def get_server_settings() -> ServerSettings:
    return ServerSettings()
