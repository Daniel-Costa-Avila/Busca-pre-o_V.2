# Apps Script - Portal Interno (Envio Manual de Planilha)

Este exemplo permite que um usuario do Google Workspace envie uma planilha .xlsx para iniciar uma pesquisa manual no sistema via endpoint HTTP publico.

## Arquivos
- Code.gs
- index.html

## Configuracao rapida
1. Crie um projeto no Google Apps Script.
2. Cole os arquivos `Code.gs` e `index.html`.
3. Em **Propriedades do Script**, crie:
   - BASE_URL (URL publica do seu sistema, ex.: https://seu-endereco)
   - API_TOKEN (token de acesso, se existir)
4. Publique como Web App:
   - Executar como: voce
   - Quem tem acesso: apenas usuarios do dominio

## Endpoint esperado
- POST /api/run (multipart/form-data com campo `file`)

## Observacoes
- Ajuste `ALLOWED_DOMAIN` e `ALLOWED_EMAILS` no `Code.gs`.
- Se nao usar token, deixe `API_TOKEN` vazio.
