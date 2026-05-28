from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

import requests


class MercadoLivreAPI:
    """
    Cliente para API do Mercado Livre com renovacao automatica de Token.
    """

    BASE_URL = "https://api.mercadolibre.com"

    def __init__(self) -> None:
        self.app_id = os.getenv("ML_APP_ID", "")
        self.client_secret = os.getenv("ML_CLIENT_SECRET", "")
        self.access_token = os.getenv("ML_ACCESS_TOKEN", "")
        self.refresh_token = os.getenv("ML_REFRESH_TOKEN", "")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "PriceMonitor/1.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def is_configured(self) -> bool:
        """Verifica se as credenciais minimas estao presentes."""
        return bool(self.access_token)

    def _get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _refresh_access_token(self) -> bool:
        """
        Tenta renovar o access_token usando o refresh_token.
        Atualiza as variaveis de instancia em caso de sucesso.
        Nota: Em producao, o ideal e salvar os novos tokens no .env ou banco.
        """
        if not self.app_id or not self.client_secret or not self.refresh_token:
            print("ML API: Credenciais de refresh (App ID/Secret) nao configuradas.")
            return False

        url = f"{self.BASE_URL}/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.app_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        }

        try:
            resp = self.session.post(url, data=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self.access_token = data.get("access_token", "")
                self.refresh_token = data.get("refresh_token", "")
                # Aqui voce poderia implementar uma logica para persistir os novos tokens
                print("ML API: Token renovado com sucesso.")
                return True
            else:
                print(f"ML API: Falha ao renovar token. HTTP {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"ML API: Erro de conexao ao renovar token: {e}")

        return False

    def get_item(self, item_id: str) -> Optional[dict[str, Any]]:
        """
        Busca dados publicos de um item (ex: MLB12345678).
        Tenta renovar token 1 vez se receber 401 (Unauthorized).
        """
        if not self.is_configured():
            return None

        # Limpeza do ID (garantir apenas MLB...)
        clean_id = re.sub(r"[^A-Z0-9]", "", item_id.upper())
        if not clean_id.startswith("MLB"):
            # Tenta extrair de URL se for o caso, ou retorna None
            return None

        url = f"{self.BASE_URL}/items/{clean_id}"
        
        # Tentativa 1
        resp = self.session.get(url, headers=self._get_auth_headers(), timeout=10)

        # Se der erro de auth, tenta renovar e chama de novo
        if resp.status_code == 401:
            print("ML API: Token expirado (401). Tentando renovar...")
            if self._refresh_access_token():
                resp = self.session.get(url, headers=self._get_auth_headers(), timeout=10)
            else:
                return None

        if resp.status_code == 200:
            return resp.json()
        
        if resp.status_code == 404:
            print(f"ML API: Item {clean_id} nao encontrado (404).")
            return None

        print(f"ML API: Erro ao buscar item {clean_id}. HTTP {resp.status_code}")
        return None

    @staticmethod
    def extract_mlb_from_url(url: str) -> Optional[str]:
        """
        Extrai o ID do item (MLB...) a partir de um link.
        Ex: https://produto.mercadolivre.com.br/MLB-123456-produto...
        """
        # Padrao comum na URL: MLB-12345 ou MLB12345
        match = re.search(r"(MLB)[-]?(\d+)", url, re.IGNORECASE)
        if match:
            return f"{match.group(1).upper()}{match.group(2)}"
        return None

    def parse_price(self, item_data: dict) -> Optional[str]:
        """
        Formata o preco vindo do JSON da API para o padrao do sistema (R$ 1.000,00).
        """
        if not item_data:
            return None
        
        price = item_data.get("price")
        currency = item_data.get("currency_id", "BRL")
        
        if price is None:
            return None
            
        try:
            val = float(price)
            # Formata para padrao brasileiro
            formatted = f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return f"R$ {formatted}"
        except ValueError:
            return None

    def get_status(self, item_data: dict) -> str:
        if not item_data:
            return "Erro API"
        return item_data.get("status", "unknown")