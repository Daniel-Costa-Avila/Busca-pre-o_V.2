"""Cliente de consultas pontuais à BrasilAPI, sem credenciais do sistema."""
import re

import requests

BASE_URL = "https://brasilapi.com.br/api"
UFS = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


class BrasilAPIError(Exception):
    """Falha que pode ser exibida ao operador sem revelar dados internos."""


def endpoint(resource: str, value: str = "") -> str:
    value = str(value).strip().upper()
    if resource == "cep":
        value = re.sub(r"[.\-\s]", "", value)
        if not re.fullmatch(r"[0-9]{8}", value):
            raise BrasilAPIError("Informe um CEP com 8 dígitos.")
        return f"cep/v2/{value}"
    if resource == "cnpj":
        value = re.sub(r"[./\-\s]", "", value)
        if not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", value):
            raise BrasilAPIError("Informe um CNPJ com 14 caracteres, terminando em 2 dígitos.")
        return f"cnpj/v1/{value}"
    if resource == "cpf":
        value = re.sub(r"[.\-\s]", "", value)
        if not re.fullmatch(r"[0-9]{11}", value) or len(set(value)) == 1:
            raise BrasilAPIError("Informe um CPF com 11 dígitos válidos para consulta.")
        return f"cpf/v1/{value}"
    if resource == "ddd":
        if not re.fullmatch(r"[1-9][0-9]", value):
            raise BrasilAPIError("Informe um DDD brasileiro com 2 dígitos.")
        return f"ddd/v2/{value}"
    if resource == "ncm":
        value = re.sub(r"[.\-\s]", "", value)
        if not re.fullmatch(r"[0-9]{8}", value):
            raise BrasilAPIError("Informe um NCM com 8 dígitos.")
        return f"ncm/v1/{value}"
    if resource == "cnae":
        value = re.sub(r"[.\-\s]", "", value)
        if not re.fullmatch(r"[0-9]{5}", value):
            raise BrasilAPIError("Informe uma classe CNAE com 5 dígitos.")
        return f"ibge/cnae/v1/classes/{value}"
    if resource == "ibpt_versao":
        if value:
            raise BrasilAPIError("A consulta da versão IBPT não recebe parâmetros.")
        return "ibpt/versao/v1"
    if resource == "municipios":
        if value not in UFS:
            raise BrasilAPIError("Selecione uma UF válida.")
        return f"ibge/municipios/v1/{value}"
    raise BrasilAPIError("Consulta não disponível.")


def consultar(resource: str, value: str = "") -> dict | list:
    path = endpoint(resource, value)
    try:
        response = requests.get(
            f"{BASE_URL}/{path}",
            headers={"Accept": "application/json", "User-Agent": "BuscaPreco-BrasilAPI/1.0"},
            timeout=(5, 20),
            allow_redirects=False,
        )
        if response.status_code in (400, 422):
            raise BrasilAPIError("A BrasilAPI recusou os dados informados. Confira o campo e tente novamente.")
        if response.status_code == 404:
            raise BrasilAPIError("Nenhum registro encontrado para esta consulta.")
        if response.status_code == 429:
            raise BrasilAPIError("Limite de consultas atingido. Aguarde alguns minutos.")
        if response.status_code != 200:
            raise BrasilAPIError("BrasilAPI indisponível no momento. Tente novamente mais tarde.")
        payload = response.json()
        expected = list if resource in {"municipios", "ddd"} else dict
        if not isinstance(payload, expected) or (isinstance(payload, list) and any(not isinstance(row, dict) for row in payload)):
            raise BrasilAPIError("A BrasilAPI retornou um formato inesperado.")
        return payload
    except requests.Timeout as exc:
        raise BrasilAPIError("A consulta excedeu o tempo de espera. Tente novamente.") from exc
    except requests.RequestException as exc:
        raise BrasilAPIError("Não foi possível acessar a BrasilAPI. Verifique a conexão e tente novamente.") from exc
    except ValueError as exc:
        raise BrasilAPIError("A BrasilAPI retornou uma resposta inválida.") from exc
