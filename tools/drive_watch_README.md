# Monitoramento de pasta Google Drive (opcao B)

Este script monitora uma pasta do Google Drive e dispara o processamento automaticamente sempre que um novo .xlsx for enviado.

## Requisitos
- Credencial de Service Account do Google Drive (arquivo .json)
- A pasta do Drive deve estar compartilhada com o e-mail da service account

## Variaveis de ambiente
- DRIVE_WATCH_FOLDER_ID
- GOOGLE_DRIVE_CREDENTIALS_FILE
- DRIVE_WATCH_POLL_SECONDS (opcional, default 30)

## Como rodar
```
.\.venv\Scripts\python tools\drive_watch.py
```

## Observacoes
- Somente arquivos .xlsx sao processados.
- Cada arquivo e processado uma unica vez.
- O estado fica em `runs\drive_watch_state.json`.
