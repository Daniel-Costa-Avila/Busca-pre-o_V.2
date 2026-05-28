# Migracao para servidor Linux

Este projeto fica mais previsivel em servidor usando `venv` + `systemd`.
O fluxo abaixo evita depender de janela interativa, `run.ps1` ou sessao SSH aberta.

## 1. Escolha do ambiente

- Use Ubuntu 22.04/24.04 ou outra distro Linux equivalente.
- Use Python `3.11` ou `3.13`.
- Evite Python `3.14+` para este deploy: o coletor Magalu desabilita Playwright nessa faixa por compatibilidade.
- Mantenha a aplicacao em um caminho fixo, por exemplo `/opt/price-monitor`.

## 2. Dependencias do sistema

Instale pelo menos:

```bash
sudo apt-get update
sudo apt-get install -y \
  python3.11 python3.11-venv python3-pip \
  curl ca-certificates unzip \
  libnss3 libatk-bridge2.0-0 libxcomposite1 libxdamage1 libxrandr2 \
  libgbm1 libasound2 libgtk-3-0 fonts-liberation
```

Se for usar Chrome/Chromium local com Selenium, deixe um navegador instalado no servidor.

## 3. Instalacao do projeto

```bash
sudo mkdir -p /opt/price-monitor
sudo chown -R $USER:$USER /opt/price-monitor
git clone <repo> /opt/price-monitor
cd /opt/price-monitor
python3.11 install.py --playwright-browsers chromium,firefox
```

## 4. Arquivo de ambiente

Copie o exemplo e preencha os valores reais:

```bash
cp deploy/server/server.env.example deploy/server/server.env
```

Pontos obrigatorios:

- `API_TOKEN`: precisa ser fixo e forte.
- `PASSWORD_AUTH_ENABLED=1`: nao exponha a UI sem login.
- `ADMIN_DEFAULT_PASSWORD`: troque a senha inicial antes de subir.
- `API_BASE`: URL publica da API.
- `APP_PUBLIC_BASE_URL`: URL publica usada para links de download/WhatsApp.

## 5. Arquivos persistentes

Antes de habilitar agendamento automatico, garanta estes itens no servidor:

- `input.xlsx` na raiz do projeto: o job diario usa esse arquivo quando nao ha upload manual.
- `runs/`: contem jobs, token persistido e configuracoes salvas em runtime.
- `runs/admin_users.json`: usuarios da plataforma.
- `chrome_profile_magalu/`: preserve apenas se voce realmente precisar manter sessao/perfil.

Para backup, preserve no minimo:

- `deploy/server/server.env`
- `input.xlsx`
- `runs/`

## 6. Subindo como servico

Os arquivos de exemplo estao em:

- `deploy/server/price-monitor-api.service`
- `deploy/server/price-monitor-ui.service`

Copie para o `systemd`, ajustando `User`, `Group`, `WorkingDirectory` e `EnvironmentFile` se o caminho nao for `/opt/price-monitor`:

```bash
sudo cp deploy/server/price-monitor-api.service /etc/systemd/system/
sudo cp deploy/server/price-monitor-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now price-monitor-api.service
sudo systemctl enable --now price-monitor-ui.service
```

Logs:

```bash
sudo journalctl -u price-monitor-api.service -f
sudo journalctl -u price-monitor-ui.service -f
```

## 7. Reverse proxy

O exemplo Nginx esta em `deploy/server/nginx-price-monitor.conf`.

Recomendacao:

- `api.seudominio.com` apontando para `127.0.0.1:8000`
- `app.seudominio.com` apontando para `127.0.0.1:8501`

Importante:

- A API precisa ficar publicada na raiz do hostname dela.
- Nao publique a API em subpath do tipo `/backend`, porque a UI Streamlit embute o painel da API a partir da raiz de `API_BASE`.

Depois do proxy HTTP funcionar, adicione TLS com Certbot ou no seu proxy de borda.

## 8. Validacao

Checagens locais:

```bash
bash deploy/server/healthcheck.sh
curl -fsS http://127.0.0.1:8501
```

Checagens do sistema:

```bash
systemctl status price-monitor-api.service --no-pager
systemctl status price-monitor-ui.service --no-pager
```

Checagens funcionais:

1. Abrir a UI.
2. Fazer login com o admin bootstrap.
3. Alterar a senha imediatamente.
4. Rodar um job manual.
5. Confirmar download do arquivo de output.
6. Confirmar que `input.xlsx` existe para o scheduler diario.

## 9. Observacoes operacionais

- O scheduler diario roda dentro da API. Se a API cair, o agendamento para.
- O servidor deve subir com os servicos habilitados no boot; nao use `run.sh` ou `run.ps1` como mecanismo de producao.
- Se quiser isolar Selenium do host, configure `SELENIUM_REMOTE_URL` para Selenoid/Grid e mantenha `HEADLESS=1`.
- Se o servidor ficar sem internet na primeira execucao, o Selenium pode falhar ao baixar driver automaticamente. Nesse caso, preinstale o driver e use `CHROMEDRIVER_PATH`, `GECKODRIVER_PATH` ou `EDGEDRIVER_PATH`.
