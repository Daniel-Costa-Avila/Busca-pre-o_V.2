"""Tela reutilizável na interface Streamlit: Central de Dados Públicos."""
import json

import streamlit as st

from integrations.brasilapi import BrasilAPIError, UFS, consultar, endpoint

# As consultas ficam agrupadas por finalidade, para o operador encontrar o que
# precisa sem percorrer uma lista longa.
CATEGORIES = {
    "⌖  Endereço e Localização": {"CEP": "cep", "Municípios": "municipios", "DDD": "ddd"},
    "◈  Empresas e Pessoas": {"CNPJ": "cnpj", "CPF": "cpf"},
    "▤  Fiscal e Comércio": {"NCM": "ncm", "CNAE": "cnae", "Versão IBPT": "ibpt_versao"},
}
FIELD_LABELS = {
    "ncm": "Código NCM", "cnae": "Classe CNAE", "ddd": "DDD",
}
NO_VALUE_RESOURCES = {"ibpt_versao"}
RESULT_FIELDS = {"cep": "CEP", "street": "Logradouro", "neighborhood": "Bairro", "city": "Cidade", "state": "UF", "razao_social": "Razão social", "nome_fantasia": "Nome fantasia", "cnpj": "CNPJ", "cpf": "CPF", "isValid": "CPF válido", "rf": "Região fiscal", "ufs": "UFs", "descricao_situacao_cadastral": "Situação cadastral", "municipio": "Município", "uf": "UF", "codigo": "Código", "descricao": "Descrição", "versao": "Versão IBPT", "cities": "Cidades", "id": "Código CNAE"}


@st.cache_data(ttl=3600, max_entries=256, show_spinner=False)
def _consulta(resource, value):
    return consultar(resource, value)


def _render_result(resource: str) -> None:
    result = st.session_state.get("brasilapi_result")
    if not result or result[0] != resource:
        return
    _, query, payload = result
    st.caption(f"Resultado de: {query or 'Consulta completa'}")
    if isinstance(payload, list):
        if payload:
            st.dataframe(payload, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum registro retornado.")
    else:
        rows = [{"Campo": title, "Valor": str(payload[key])} for key, title in RESULT_FIELDS.items() if payload.get(key) is not None]
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
    st.download_button("Baixar dados (JSON)", json.dumps(payload, ensure_ascii=False, indent=2), file_name=f"brasilapi-{resource}.json", mime="application/json", key=f"brasilapi_download_{resource}")


def _render_category(category: str, options: dict) -> None:
    label = st.selectbox("Tipo de consulta", list(options), key=f"brasilapi_type_{category}")
    resource = options[label]
    with st.form(f"brasilapi_{resource}"):
        if resource == "municipios":
            value = st.selectbox("Estado (UF)", UFS, index=UFS.index("SP"))
        elif resource in NO_VALUE_RESOURCES:
            value = ""
            st.caption("Consulta sem parâmetros.")
        else:
            title = FIELD_LABELS.get(resource, label)
            value = st.text_input(title, max_chars=24)
        submitted = st.form_submit_button("Consultar", type="primary", use_container_width=True)
    if submitted:
        st.session_state.pop("brasilapi_result", None)
        try:
            path = endpoint(resource, value)
            normalized = path.rsplit("/", 1)[-1]
            with st.spinner("Consultando BrasilAPI..."):
                payload = consultar(resource, normalized) if resource == "cpf" else _consulta(resource, normalized)
            st.session_state["brasilapi_result"] = (resource, value, payload)
        except BrasilAPIError as exc:
            st.error(str(exc))
    _render_result(resource)


def render():
    st.caption("Consulte dados públicos oficiais sem sair do painel. CPF não fica armazenado em cache; os demais resultados podem ser reutilizados por até 1 hora.")
    tabs = st.tabs(list(CATEGORIES))
    for tab, (category, options) in zip(tabs, CATEGORIES.items()):
        with tab:
            _render_category(category, options)
    st.caption("Fonte: BrasilAPI • As consultas não alteram as planilhas ou os cadastros do sistema.")
