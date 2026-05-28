from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


class PriceMonitorClientError(RuntimeError):
    """Erro de comunicacao ou resposta inesperada da API."""


@dataclass
class PriceMonitorClient:
    """
    Cliente HTTP da API do Price Monitor.

    Funciona tanto para servidor local (ex.: http://127.0.0.1:8000)
    quanto para link remoto (ex.: HTTPS/Tailscale).
    """

    base_url: str
    api_token: str = ""
    timeout: int = 30

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {})
        merged_headers = {**self._headers(), **headers}
        timeout = kwargs.pop("timeout", self.timeout)

        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=merged_headers,
                timeout=timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise PriceMonitorClientError(f"Falha de conexao com {url}: {exc}") from exc

        if response.status_code >= 400:
            detail = None
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            raise PriceMonitorClientError(
                f"API retornou erro {response.status_code} em {path}: {detail}"
            )

        return response

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health").json()

    def overview(self) -> dict[str, Any]:
        return self._request("GET", "/api/overview").json()

    def run_job(self, file_path: str | Path | None = None) -> dict[str, Any]:
        if file_path is None:
            return self._request("POST", "/api/run").json()

        target = Path(file_path)
        if not target.exists():
            raise PriceMonitorClientError(f"Arquivo nao encontrado: {target}")

        with target.open("rb") as f:
            files = {
                "file": (
                    target.name,
                    f,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            }
            return self._request("POST", "/api/run", files=files).json()

    def status(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/status/{job_id}").json()

    def daily_latest(self) -> dict[str, Any]:
        return self._request("GET", "/api/daily/latest").json()

    def send_email(self, job_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/email/{job_id}/send").json()

    def download_output(self, job_id: str, target_path: str | Path | None = None) -> Path:
        destination = Path(target_path) if target_path else Path(f"output_{job_id}.xlsx")
        response = self._request("GET", f"/download/{job_id}", timeout=120)
        destination.write_bytes(response.content)
        return destination

