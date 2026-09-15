# Integração BrasilAPI

Ativa na interface principal (`ui_streamlit/app.py`), no menu **Central de Dados Públicos**.

## Recursos implementados

- CEP v2: endereço e dados completos retornados pelo serviço.
- CNPJ v1: dados cadastrais e resposta completa, com suporte ao formato alfanumérico documentado no projeto fornecido.
- CPF v1: validação e região fiscal. O CPF não é colocado no cache da aplicação.
- DDD v2: UF e cidades atendidas por DDD.
- NCM: consulta de código fiscal com 8 dígitos.
- CNAE (IBGE): consulta de classe com 5 dígitos.
- IBPT: versão vigente da tabela tributária.
- IBGE municípios v1: municípios por UF.

O menu **Central de Dados Públicos** usa `integrations/brasilapi_panel.py` e `integrations/brasilapi.py`, com as consultas agrupadas em abas por assunto: Endereço e Localização, Empresas e Pessoas e Fiscal e Comércio. As consultas saem do servidor Streamlit para `https://brasilapi.com.br/api`, sem enviar o token interno do Busca Preço. Não é necessário executar o projeto Node da pasta `Api Brasil` para consumir o serviço público. Referência: https://brasilapi.com.br/docs e documentação local em `Api Brasil/pages/docs/doc`.

As requisições só acontecem ao clicar em Consultar; há timeout de conexão de 5 segundos e leitura de 20 segundos, sem repetição automática. Resultados ficam em cache de memória por até uma hora, limitado a 256 entradas. O cache é compartilhado pelo processo Streamlit e contém somente respostas públicas. Campos inválidos, registro não encontrado, limite de consultas e falhas do provedor têm mensagens próprias. A tela mostra os dados e permite baixar JSON; não grava dados nas planilhas nem altera rotinas de preços.

## Teste

Execute na raiz:

```powershell
.venv\Scripts\python.exe scripts\test_brasilapi.py
```

`scripts/prepare_brasilapi_test.py` e `scripts/start_brasilapi_test.py` foram usados apenas na fase de revisão em cópia isolada (antes da integração ser incorporada à UI principal) e não são mais necessários para este fluxo.
