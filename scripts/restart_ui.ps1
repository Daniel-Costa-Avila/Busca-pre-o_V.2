<#
.SYNOPSIS
  Reinicia apenas a UI (Streamlit) do Busca Preco, sem tocar na API nem no tunel.

.DESCRIPTION
  A UI sobe com --server.fileWatcherType none, entao alteracoes em
  ui_streamlit/app.py so aparecem depois de reiniciar o processo. Este script
  para o processo que ocupa a porta 8501 e sobe outro com exatamente os mesmos
  parametros usados por Start-Ui em scripts/supervisor_busca_preco.ps1.

  Precisa de PowerShell elevado: a UI costuma rodar sob outra conta.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\restart_ui.ps1
#>
[CmdletBinding()]
param([int]$UiPort = 8501, [int]$ApiPort = 8000, [int]$TimeoutSeconds = 90)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$scriptsDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDirectory = Split-Path -Parent $scriptsDirectory
$runtimeDirectory = Join-Path $appDirectory 'supervisor-runtime'
$pythonExe = Join-Path $appDirectory '.venv\Scripts\python.exe'
$uiOutputLog = Join-Path $runtimeDirectory 'ui-output.log'
$uiErrorLog = Join-Path $runtimeDirectory 'ui-error.log'
$healthUrl = "http://127.0.0.1:$UiPort/_stcore/health"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Warning 'Sessao nao elevada. Se o processo da UI pertencer a outra conta, o Stop-Process vai falhar com "Access is denied".'
}

if (-not (Test-Path $pythonExe)) { throw "Python do projeto nao encontrado em $pythonExe" }
if (-not (Test-Path $runtimeDirectory)) { New-Item -ItemType Directory -Force $runtimeDirectory | Out-Null }

# 1. Descobre quem ocupa a porta da UI (o PID muda a cada reinicio).
$owners = @(Get-NetTCPConnection -LocalPort $UiPort -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique)

foreach ($processId in $owners) {
  Write-Host "Parando UI (PID $processId)..."
  Stop-Process -Id $processId -Force
}
if (-not $owners) { Write-Host "Nada escutando na porta $UiPort; seguindo para a subida." }

# Espera a porta liberar antes de subir a nova instancia.
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
  if (-not (Get-NetTCPConnection -LocalPort $UiPort -State Listen -ErrorAction SilentlyContinue)) { break }
  Start-Sleep -Milliseconds 500
}

# 2. Rotaciona os logs agora que ninguem os mantem abertos.
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
foreach ($logPath in @($uiOutputLog, $uiErrorLog)) {
  if (Test-Path $logPath) {
    try { Move-Item $logPath "$logPath.$stamp.bak" -Force } catch { Write-Warning "Log em uso, mantido: $logPath" }
  }
}

# 3. Sobe com os mesmos parametros de Start-Ui.
$env:UI_API_BASE = "http://127.0.0.1:$ApiPort"
$env:API_BASE = "http://127.0.0.1:$ApiPort"
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = 'python'
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION = '3'
$env:STREAMLIT_SERVER_FILE_WATCHER_TYPE = 'none'

$uiArgs = @(
  '-m', 'streamlit', 'run', 'ui_streamlit/app.py',
  '--server.address', '127.0.0.1',
  '--server.port', "$UiPort",
  '--server.enableWebsocketCompression', 'false',
  '--server.fileWatcherType', 'none',
  '--server.headless', 'true'
)

$process = Start-Process -FilePath $pythonExe -ArgumentList $uiArgs -WorkingDirectory $appDirectory `
  -WindowStyle Hidden -RedirectStandardOutput $uiOutputLog -RedirectStandardError $uiErrorLog -PassThru
Write-Host "UI iniciada com PID $($process.Id)."

# 4. Espera ficar saudavel antes de devolver o controle.
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$healthy = $false
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  if ($process.HasExited) { throw "O processo da UI encerrou logo apos subir. Veja $uiErrorLog" }
  try {
    $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 5 -UseBasicParsing
    if ($response.StatusCode -eq 200) { $healthy = $true; break }
  } catch { }
}

if (-not $healthy) { throw "UI nao respondeu em $healthUrl dentro de $TimeoutSeconds s. Veja $uiErrorLog" }

Write-Host "UI saudavel em $healthUrl"
try {
  $public = Invoke-WebRequest -Uri 'https://buscapreco.promarketing.ind.br/_stcore/health' -TimeoutSec 15 -UseBasicParsing
  Write-Host "URL publica respondeu $($public.StatusCode)."
} catch {
  Write-Warning "URL publica ainda nao respondeu: $($_.Exception.Message). O tunel pode levar alguns segundos."
}
