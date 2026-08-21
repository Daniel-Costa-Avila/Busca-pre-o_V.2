# Uso interno (operação) — Busca‑Preço / Agente de Frete

Este documento é para uso interno e descreve **como iniciar**, **como publicar via Tailscale Funnel** e **como o sistema funciona** (componentes + fluxo).

---

## 1) Visão geral do sistema (Busca‑Preço)

O Busca‑Preço é composto por:

- **API (FastAPI/Uvicorn)**: `ui/server.py` (porta configurável, ex.: `8040`)
- **UI (Streamlit)**: `ui_streamlit/app.py` (porta configurável, ex.: `8630`)
- **Runner**: `run.ps1` (sobe API + UI com variáveis coerentes)
- **Watch do Drive (opcional)**: `tools/drive_watch.py` (processo em loop; gera planilhas e faz upload)

Fluxo típico:
1. Usuário acessa a UI (Streamlit).
2. UI chama a API (`/api/*`) para iniciar job, acompanhar status e baixar arquivos.
3. API executa o job e gera um `.xlsx` de saída.
4. O resultado diário é copiado para a pasta **Resultado Diario** com nome padronizado.

---

## 2) Portas e “conflitos” (regra de ouro)

O maior problema operacional é **porta ocupada** por outro processo/sistema.

Regras recomendadas:
- **Frete**: fixo em `127.0.0.1:5100`
- **Busca‑Preço**: API/UI em faixas **altas e separadas**, e sempre configuradas juntas
  - API: `8040–8099`
  - UI: `8630–8699`

Comando para ver o que está usando uma porta:
```powershell
netstat -ano | Select-String -Pattern ":8630\\s|:8040\\s"
```

Para identificar o processo (PID):
```powershell
Get-Process -Id <PID> | Select-Object Id,ProcessName,Path
```

---

## 3) Como iniciar o Busca‑Preço (recomendado)

Use o script que escolhe portas livres automaticamente e mantém API/UI sincronizadas:

```powershell
cd C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_busca_preco.ps1 -Wait
```

Opções úteis:
- Forçar portas (se necessário):
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_busca_preco.ps1 -Wait -ApiPort 8040 -UiPort 8630
  ```
- Alterar base path da UI (quando publicar no `/busca-preco`):
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_busca_preco.ps1 -Wait -UiBasePath busca-preco
  ```

Alternativa “manual” (quando você quer controlar tudo):
```powershell
.\run.ps1 -Wait -BindHost 127.0.0.1 -ApiPort 8040 -UiPort 8630 -UiBasePath busca-preco
```

Observações importantes:
- O `run.ps1` sempre sobrescreve `API_BASE` e `UI_API_BASE` para a UI falar com a API na porta correta.
- A UI inicia com `--server.enableWebsocketCompression false` para reduzir erros em proxies/túneis.

---

## 4) Como iniciar o Agente de Frete

O Frete é um projeto separado (fora desta pasta). O requisito para os túneis é:

- Serviço HTTP respondendo em `http://127.0.0.1:5100/`
- E também em `http://127.0.0.1:5100/frete`

Teste local:
```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5100/ | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5100/frete | Select-Object StatusCode
```

---

## 5) Tailscale Funnel: URLs fixas sem conflito

Meta: publicar os dois sistemas **no mesmo host** sem sobrescrever regras.

Padrão recomendado:
- **Frete**: `https://madri.tailfaad49.ts.net/frete` → `http://127.0.0.1:5100/frete`
- **Busca‑Preço**: `https://madri.tailfaad49.ts.net/busca-preco` → `http://127.0.0.1:<UI_PORT>/busca-preco`

### 5.1) Aplicar túneis (script)

Use o script `scripts/tunnels.ps1` (ele pede admin; se não estiver admin ele tenta reabrir):

```powershell
cd C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\tunnels.ps1
```

Se você mudou a porta da UI do Busca‑Preço:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\tunnels.ps1 -BuscaPrecoUiPort 8630
```

### 5.2) Aplicar túneis (comandos diretos)

Requer PowerShell **Administrador**:
```powershell
tailscale funnel reset

tailscale funnel --bg --https=443 --set-path=/frete http://127.0.0.1:5100/frete
tailscale funnel --bg --https=443 --set-path=/busca-preco http://127.0.0.1:8630/busca-preco

tailscale funnel status
```

### 5.3) Por que o destino do Busca‑Preço inclui `/busca-preco`?

Quando a UI do Streamlit roda com:
```text
--server.baseUrlPath busca-preco
```
ela passa a responder em **`/busca-preco`** e o root `/` tende a dar **404**.

Por isso o Funnel aponta para:
```text
http://127.0.0.1:<UI_PORT>/busca-preco
```
para não ocorrer “404: Not Found” externamente.

---

## 6) Arquivos de resultado (nome + data)

O resultado diário é salvo em:
```text
C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS\Resultado Diario\
```

Padrão do nome:
```text
Busca-Preco_DDMMYYYY.xlsx
```

O nome base pode ser ajustado no `.env`:
```ini
RESULT_SYSTEM_NAME=Busca-Preço
```

---

## 7) Variáveis importantes (.env)

Arquivo: `.env` (não commitar)

- `API_TOKEN`: token da API (autenticação quando habilitada)
- `RESULT_SYSTEM_NAME`: base do nome da planilha diária

### 7.1) Magalu (navegador / fallback)

Quando a Magalu bloquear ou não retornar preço no Playwright, o sistema pode tentar **Selenium (Firefox/Edge)** como fallback.

- `MAGALU_SELENIUM_BROWSER=firefox` (recomendado no ambiente atual)
- `MAGALU_SELENIUM_BROWSER=chrome` (use só se o Firefox não abrir corretamente no PC)
- `MAGALU_HEADLESS=0` (recomendado no ambiente atual; preserva o modo visivel e evita a janela fechar instantaneamente)
- `MAGALU_FALLBACK_SELENIUM_ON_EMPTY=1` (tenta Selenium quando o Playwright não encontra preço)
- `WEBDRIVER_MANAGER_ENABLED=0` (opcional; usa Selenium Manager/driver no PATH em vez de baixar via webdriver_manager)
- `MAGALU_ITEM_TIMEOUT_SECONDS=0` (default `0` = desativado; recomendado `90`-`180`): timeout por item da Magalu. Se travar, marca como timeout e segue.
- `MAGALU_USE_SUBPROCESS_TIMEOUT=1` (default ligado; quando `MAGALU_HEADLESS=0`, o timeout em subprocesso nao e usado para nao abrir/fechar a janela visual rapidamente)
- `MAGALU_MANUAL_UNLOCK_ON_BLOCK=1` (recomendado em modo visivel): quando cair na tela da Akamai, mantem a pagina aberta e aguarda a liberacao da sessao.
- `MAGALU_MANUAL_UNLOCK_TIMEOUT_SECONDS=120` (tempo maximo para resolver o challenge e reaproveitar a mesma sessao)

Diagnóstico Magalu:
- Em caso de bloqueio/captcha ou preço não encontrado, o sistema salva HTML + screenshot em `debug_magalu\\` para análise.
- Se aparecer “Não é possível acessar a página (Erro 403)”, é bloqueio do site (anti-bot/rate limit). Nesse caso, o coletor não consegue obter preços de forma confiável; reduza o volume/velocidade, aguarde e tente novamente, ou use outra fonte/canal para o preço.
- Estratégia implementada: quando detectar bloqueio (403), o sistema **marca como BLOQUEADO (403)** na planilha, **pula para o próximo item** e faz uma nova tentativa depois de aguardar (`MAGALU_BLOCKED_WAIT_SECONDS`, `MAGALU_BLOCKED_RETRIES`).
  - Opcional: throttling/circuit breaker no fluxo (`MAGALU_THROTTLE_SECONDS`, `MAGALU_BLOCKED_STREAK_THRESHOLD`, `MAGALU_BLOCKED_COOLDOWN_SECONDS`) para reduzir bloqueio durante execuções grandes.
  - Recomendado: usar jitter em vez de delay fixo (`MAGALU_THROTTLE_MIN_SECONDS`, `MAGALU_THROTTLE_MAX_SECONDS`).
  - Avançado: tentar Selenium quando o Playwright dá 403 (`MAGALU_TRY_SELENIUM_ON_403=1`) e rotacionar navegadores no bloqueio (`MAGALU_TRY_OTHER_BROWSERS_ON_BLOCK=1`). Isso pode aumentar o volume e piorar o bloqueio.
  - Observação: a Magalu pode retornar uma **página de bloqueio** com status 200. O coletor detecta textos como “Não é possível acessar a página / tente novamente em 1 minuto” e marca como bloqueado.

---

### 7.1.1) Zema (mesma estratégia anti-bloqueio da Magalu)

A Zema reaproveita o kit anti-bloqueio da Magalu: throttle com jitter, circuit breaker e fila de retentativa após a execução. O coletor já detecta captcha/challenge/cloudflare e faz fallback automático para outro navegador do pool antes de marcar como bloqueado.

- `ZEMA_THROTTLE_SECONDS=0` (default `0` = sem throttle fixo)
- `ZEMA_THROTTLE_MIN_SECONDS` / `ZEMA_THROTTLE_MAX_SECONDS` (recomendado: jitter em vez de delay fixo)
- `ZEMA_BLOCKED_STREAK_THRESHOLD=3` (bloqueios seguidos até abrir o circuit breaker)
- `ZEMA_BLOCKED_COOLDOWN_SECONDS=70` (tempo de espera com o circuito aberto)
- `ZEMA_BLOCKED_WAIT_SECONDS=65` / `ZEMA_BLOCKED_RETRIES=0` (retentativa após a fila principal; desativada por padrão, igual à Magalu)
- `ZEMA_RETRY_MAX_ITEMS=60` (limite de itens reprocessados na fila de retentativa)

Diagnóstico Zema:
- Em caso de bloqueio/challenge, o sistema salva HTML + screenshot em `debug_zema\\` para análise.
- Estratégia implementada: quando detectar bloqueio, o item é marcado, a fila segue para o próximo produto e uma nova tentativa ocorre depois de aguardar (`ZEMA_BLOCKED_WAIT_SECONDS`, `ZEMA_BLOCKED_RETRIES`), igual ao fluxo da Magalu.

---

### 7.2) Watchdog (evitar travar a fila)

Para evitar que a execução fique **pausada por muito tempo** (ex.: bloqueio do site, navegador travado, rede lenta),
você pode configurar um watchdog que **encerra a fila com segurança** e salva a planilha parcial com o que já foi coletado.

- `RUN_MAX_SECONDS` (default `0` = desativado): tempo máximo total da execução em segundos.
- `RUN_MAX_IDLE_SECONDS` (default `0` = desativado): tempo máximo sem progresso (sem escrever linhas na planilha) em segundos.

Exemplo (encerra em 30 min ou 5 min sem progresso):
```ini
RUN_MAX_SECONDS=1800
RUN_MAX_IDLE_SECONDS=300
```

---

## 8) Diagnóstico rápido

### 8.1) Ver se a API está no ar
```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8040/api/health
```

### 8.2) Ver status do Funnel
```powershell
tailscale funnel status --json
```

### 8.3) Erros comuns
- **WinError 10048 / “Port is not available”**: porta ocupada → troque portas ou pare o PID.
- **UI tentando API na porta errada**: sempre iniciar por `run.ps1` ou `scripts/start_busca_preco.ps1` (não subir Streamlit “na mão” sem configurar API_BASE/UI_API_BASE).
- **404 no `/busca-preco`**: Funnel apontando para `http://127.0.0.1:<UI_PORT>` (sem `/busca-preco`) ou UI não foi iniciada com `-UiBasePath busca-preco`.
- **App.main falhou: planilha Cotia não encontrada**: o caminho padrão é `Planilha diaria Cotia\\Relatorio_Financeiro_Cotia.xlsx`. Se o arquivo não existir, a importação do Mercado Livre Cotia é ignorada (o restante roda normal). Para usar essa importação, garanta o arquivo no caminho correto ou defina `INPUT_MERCADO_LIVRE_COTIA_FILE`.
