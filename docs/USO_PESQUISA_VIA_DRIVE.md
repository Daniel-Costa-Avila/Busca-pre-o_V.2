# Manual - Pesquisa via Google Drive (Modo Automatico)

Este manual explica como usar a pesquisa via Google Drive, onde o usuario envia uma planilha para uma pasta e o sistema inicia a pesquisa automaticamente.

## 1. Visao geral (explicacao simples)
- O usuario envia uma planilha .xlsx para uma pasta do Google Drive.
- Um processo local (drive_watch.py) monitora essa pasta.
- Quando aparece um arquivo novo, ele baixa e inicia o job automaticamente.
- O resultado final e salvo na pasta local:
  C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS\Resultado Diario\Busca-Preco_DDMMYYYY.xlsx

## 2. O que o usuario precisa fazer
1. Abrir a pasta do Drive compartilhada com a empresa.
2. Enviar a planilha .xlsx (ela serve como gatilho).
3. Aguardar o processamento.
4. Pegar o resultado no caminho local acima.

Observacao:
- A planilha principal sempre vem de `C:\\Users\\daniel.avila\\Desktop\\AGENTE_DE_PRECOS\\input.xlsx`.
- A planilha secundaria sempre vem de `C:\\Users\\daniel.avila\\Desktop\\AGENTE_DE_PRECOS\\Planilha diaria\\Relatorio_Financeiro.xlsx`.

## 3. Onde o sistema busca a planilha
- Pasta do Drive (ID): 1WP4j7fCcd-idsEtXH2JxglVytP24vIx2
- O sistema processa somente arquivos .xlsx.
- Cada arquivo e processado uma unica vez.

## 4. Como ligar o monitoramento
No computador do servidor, execute:

```
.\.venv\Scripts\python tools\drive_watch.py
```

Se estiver tudo certo, voce vera no terminal:
"Drive watch ativo. Monitorando pasta: 1WP4j7fCcd-idsEtXH2JxglVytP24vIx2"

## 5. Onde o resultado e salvo
- Caminho fixo do resultado:
  C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS\Resultado Diario\Busca-Preco_DDMMYYYY.xlsx

## 6. Regras importantes
- O resultado sempre sobrescreve o arquivo anterior.
- Se a planilha secundaria nao estiver presente, o job nao inicia.
- A coluna A (id no Canal) e preservada exatamente como na entrada.
- Se a coluna A estiver vazia, o sistema preenche usando B + C.

## 7. Problemas comuns
1. Erro: "DRIVE_WATCH_FOLDER_ID nao configurado"
   - Verifique o arquivo .env.

2. Erro 403 (Google Drive API desativada)
   - Ative a Drive API no Google Cloud Console.

3. Nada acontece ao enviar arquivo
   - Confirme se o drive_watch.py esta rodando.
   - Confirme se o arquivo e .xlsx.

4. Resultado nao atualizado
   - Aguarde o tempo do poll (30s).
   - Verifique se o job foi criado em C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS\runs

## 8. Checklist rapido
- [ ] Drive API ativa
- [ ] Service Account com acesso a pasta do Drive
- [ ] drive_watch.py rodando
- [ ] Planilha enviada em .xlsx

Fim.
