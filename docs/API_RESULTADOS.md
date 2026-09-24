# API de resultados

Ao final de cada coleta bem-sucedida, a API importa a aba `Output` do XLSX para
`data/resultados.sqlite3`. O arquivo e local ao servidor: os sistemas externos
devem consultar a API HTTP, e nao acessar o SQLite diretamente.

Os registros sao apagados automaticamente depois de sete dias. Cada item
preserva os campos principais (`id no Canal`, `CODIGO INTERNO`, `Canal`,
`Titulo`, `Preco` e `Link`) e tambem o objeto `payload` com todas as colunas
originais da planilha.

Se `API_TOKEN` estiver configurado, inclua-o em todas as chamadas:

```powershell
$headers = @{ Authorization = "Bearer $env:API_TOKEN" }
Invoke-RestMethod 'http://127.0.0.1:8000/api/resultados/ultimos?dias=7&canal=Mercado%20Livre' -Headers $headers
```

Endpoints:

- `GET /api/resultados/ultimos`: itens dos ultimos 1 a 7 dias. Aceita `dias`,
  `canal`, `codigo_interno`, `id_no_canal`, `busca`, `pagina` e
  `tamanho_pagina` (maximo 500).
- `GET /api/resultados/ultima-coleta`: metadados da coleta mais recente.
- `GET /api/resultados/coletas?dias=7`: coletas armazenadas no periodo.
- `GET /api/resultados/resumo?dias=7`: totais por coleta e canal.

O historico comeca na primeira coleta executada apos esta versao. O arquivo
diario existente e sobrescrito e, por isso, nao e usado para inventar coletas
historicas que nao estejam preservadas.
