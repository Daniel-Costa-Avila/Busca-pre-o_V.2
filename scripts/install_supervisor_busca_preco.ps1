#Requires -RunAsAdministrator
[CmdletBinding()]
param([switch]$DoNotStart)

$ErrorActionPreference = 'Stop'
$scriptsDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDirectory = Split-Path -Parent $scriptsDirectory
$supervisor = Join-Path $scriptsDirectory 'supervisor_busca_preco.ps1'
$taskName = 'Busca Preco Supervisor'
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

if (-not (Test-Path -LiteralPath $supervisor)) { throw 'supervisor_busca_preco.ps1 nao encontrado.' }

# Encerra somente inicializadores antigos deste projeto para impedir duplicidade.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -match '(?i)(^|[\\\s"''])(run|start_busca_preco|supervisor_busca_preco)\.ps1([\s"'']|$)' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# Libera as portas 8000 (API) e 8501 (UI) se ainda ocupadas por processos deste projeto.
foreach ($portInfo in @(@{Port=8000; Pattern='(?i)uvicorn'}, @{Port=8501; Pattern='(?i)streamlit'})) {
  $listenerPid = Get-NetTCPConnection -LocalPort $portInfo.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
  if ($listenerPid) {
    $listener = Get-CimInstance Win32_Process -Filter "ProcessId=$listenerPid" -ErrorAction SilentlyContinue
    if ($listener.Name -eq 'python.exe' -and $listener.CommandLine -match $portInfo.Pattern) {
      Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue
    }
  }
}

# Encerra tuneis cloudflared antigos com a mesma credencial (evita tunel duplicado).
$tokenLine = Get-Content -LiteralPath (Join-Path $appDirectory '.env') | Where-Object { $_ -match '^CLOUDFLARE_TUNNEL_TOKEN=' } | Select-Object -First 1
if ($tokenLine) {
  $tunnelToken = $tokenLine.Substring($tokenLine.IndexOf('=') + 1).Trim()
  Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $tunnelToken -and $_.CommandLine -and $_.CommandLine.Contains($tunnelToken) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

$action = New-ScheduledTaskAction -Execute $powerShell -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisor`"" -WorkingDirectory $appDirectory
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Inicializa, monitora e recupera a API, a UI e o tunel Cloudflare do Busca Preco.' -Force | Out-Null

if (-not $DoNotStart) { Start-ScheduledTask -TaskName $taskName }
Write-Output "Tarefa '$taskName' instalada para iniciar no boot como SYSTEM."
