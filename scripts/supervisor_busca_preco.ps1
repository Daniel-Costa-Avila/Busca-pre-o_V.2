[CmdletBinding()]
param([switch]$RunOnce, [switch]$NoRecovery)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$scriptsDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDirectory = Split-Path -Parent $scriptsDirectory
$envFile = Join-Path $appDirectory '.env'
$runtimeDirectory = Join-Path $appDirectory 'supervisor-runtime'
$stateFile = Join-Path $runtimeDirectory 'state.json'
$eventLog = Join-Path $runtimeDirectory 'events.jsonl'
$apiOutputLog = Join-Path $runtimeDirectory 'api-output.log'
$apiErrorLog = Join-Path $runtimeDirectory 'api-error.log'
$uiOutputLog = Join-Path $runtimeDirectory 'ui-output.log'
$uiErrorLog = Join-Path $runtimeDirectory 'ui-error.log'
$tunnelOutputLog = Join-Path $runtimeDirectory 'tunnel-output.log'
$tunnelErrorLog = Join-Path $runtimeDirectory 'tunnel-error.log'
$pythonExe = Join-Path $appDirectory '.venv\Scripts\python.exe'
$checkIntervalSeconds = 30
$recoveryDelays = @(10, 30, 60)
$recoveryWindowMinutes = 15
$maxRecoveriesInWindow = 3
$alertCooldownMinutes = 30
$apiPort = 8000
$uiPort = 8501
$localApiHealthUrl = 'http://127.0.0.1:8000/api/health'
$localUiHealthUrl = 'http://127.0.0.1:8501/_stcore/health'
$publicHealthUrl = 'https://buscapreco.promarketing.ind.br/_stcore/health'

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
Set-Location -LiteralPath $appDirectory

function Import-Environment {
  if (-not (Test-Path -LiteralPath $envFile)) { throw '.env nao encontrado.' }
  foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
      [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
    }
  }
  if (-not $env:CLOUDFLARE_TUNNEL_TOKEN) { throw 'CLOUDFLARE_TUNNEL_TOKEN nao definido no .env.' }
  if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Python do venv nao encontrado: $pythonExe" }
}

function Rotate-Log([string]$path) {
  if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 10MB) {
    $archive = "$path.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Move-Item -LiteralPath $path -Destination $archive
    Get-ChildItem -LiteralPath (Split-Path $path) -Filter "$(Split-Path $path -Leaf).*" |
      Sort-Object LastWriteTime -Descending | Select-Object -Skip 5 | Remove-Item -Force
  }
}

function Write-EventLog {
  param([string]$Event, [string]$Severity = 'info', [string]$Component = 'supervisor',
    [string]$Message = '', [Nullable[int]]$StatusCode = $null, [Nullable[int]]$Attempt = $null,
    [string]$Command = '', [string]$Result = '')
  Rotate-Log $eventLog
  $record = [ordered]@{ timestamp=(Get-Date).ToUniversalTime().ToString('o'); event=$Event;
    severity=$Severity; component=$Component; message=$Message; statusCode=$StatusCode;
    attempt=$Attempt; command=$Command; result=$Result }
  ($record | ConvertTo-Json -Compress) | Add-Content -LiteralPath $eventLog -Encoding UTF8
}

function New-State {
  [pscustomobject]@{ apiPid=0; uiPid=0; tunnelPid=0; outageStartedAt=$null; lastRecoveryAt=$null;
    lastAlertAt=$null; recoveryTimestamps=@() }
}

function Read-State {
  if (-not (Test-Path -LiteralPath $stateFile)) { return New-State }
  try {
    $loaded = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    if ($null -eq $loaded.recoveryTimestamps) { $loaded | Add-Member recoveryTimestamps @() -Force }
    return $loaded
  } catch {
    Write-EventLog -Event 'state_invalid' -Severity 'warning' -Message $_.Exception.Message
    return New-State
  }
}

function Save-State($state) {
  $temporary = "$stateFile.tmp"
  $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding UTF8
  Move-Item -LiteralPath $temporary -Destination $stateFile -Force
}

function Test-ExpectedProcess([int]$processId, [string]$name) {
  if ($processId -le 0) { return $false }
  $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
  return $null -ne $process -and $process.ProcessName -eq $name
}

function Get-PortOwnerPid([int]$port) {
  try { return [int](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -First 1 -ExpandProperty OwningProcess) }
  catch { return 0 }
}

function Test-ApiProcess([int]$processId) {
  if (-not (Test-ExpectedProcess $processId 'python')) { return $false }
  try {
    $instance = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop
    return $instance.CommandLine -match '(?i)uvicorn' -and $instance.CommandLine -match '(?i)ui\.server:app'
  } catch { return $false }
}

function Test-UiProcess([int]$processId) {
  if (-not (Test-ExpectedProcess $processId 'python')) { return $false }
  try {
    $instance = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop
    return $instance.CommandLine -match '(?i)streamlit' -and $instance.CommandLine -match '(?i)ui_streamlit[\\/]app\.py'
  } catch { return $false }
}

function Test-TcpPort([int]$port) {
  $client = [Net.Sockets.TcpClient]::new()
  try {
    $pending = $client.BeginConnect('127.0.0.1', $port, $null, $null)
    if (-not $pending.AsyncWaitHandle.WaitOne(5000)) { return $false }
    $client.EndConnect($pending); return $true
  } catch { return $false } finally { $client.Dispose() }
}

function Get-HttpHealth([string]$url, [int]$timeoutSeconds) {
  $timer = [Diagnostics.Stopwatch]::StartNew()
  try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec $timeoutSeconds
    return [pscustomobject]@{ ok=($response.StatusCode -eq 200); statusCode=[int]$response.StatusCode; elapsedMs=$timer.ElapsedMilliseconds; error='' }
  } catch {
    $status = $null
    if ($_.Exception.Response) { try { $status = [int]$_.Exception.Response.StatusCode } catch {} }
    return [pscustomobject]@{ ok=$false; statusCode=$status; elapsedMs=$timer.ElapsedMilliseconds; error=$_.Exception.Message }
  } finally { $timer.Stop() }
}

function Get-SystemHealth($state) {
  $apiOwnerPid = Get-PortOwnerPid $apiPort
  if ($apiOwnerPid -gt 0 -and (Test-ApiProcess $apiOwnerPid)) { $state.apiPid = $apiOwnerPid }
  $uiOwnerPid = Get-PortOwnerPid $uiPort
  if ($uiOwnerPid -gt 0 -and (Test-UiProcess $uiOwnerPid)) { $state.uiPid = $uiOwnerPid }

  $apiProcessOk = Test-ApiProcess ([int]$state.apiPid)
  $uiProcessOk = Test-UiProcess ([int]$state.uiPid)
  $tunnelProcessOk = Test-ExpectedProcess ([int]$state.tunnelPid) 'cloudflared'

  $apiPortOk = Test-TcpPort $apiPort
  $uiPortOk = Test-TcpPort $uiPort
  $apiLocal = Get-HttpHealth $localApiHealthUrl 8
  $uiLocal = Get-HttpHealth $localUiHealthUrl 8
  $public = Get-HttpHealth $publicHealthUrl 12

  $failureType =
    if (-not $apiProcessOk -or -not $uiProcessOk) { 'process_stopped' }
    elseif (-not $apiPortOk -or -not $uiPortOk) { 'port_unavailable' }
    elseif (-not $apiLocal.ok -or -not $uiLocal.ok) { 'local_health_failed' }
    elseif (-not $tunnelProcessOk) { 'tunnel_stopped' }
    elseif (-not $public.ok) { 'public_health_failed' }
    else { '' }

  [pscustomobject]@{
    ok = ($apiProcessOk -and $uiProcessOk -and $apiPortOk -and $uiPortOk -and $apiLocal.ok -and $uiLocal.ok -and $tunnelProcessOk -and $public.ok)
    apiProcessOk=$apiProcessOk; uiProcessOk=$uiProcessOk; tunnelProcessOk=$tunnelProcessOk
    apiPortOk=$apiPortOk; uiPortOk=$uiPortOk
    apiLocal=$apiLocal; uiLocal=$uiLocal; public=$public
    failureType=$failureType
  }
}

function Stop-ManagedProcess([int]$processId, [string]$name, [string]$component) {
  if (-not (Test-ExpectedProcess $processId $name)) { return }
  Write-EventLog -Event 'recovery_command' -Severity 'warning' -Component $component -Message "Encerrando PID $processId." -Command "Stop-Process $processId"
  Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
}

function Start-Api($state) {
  Stop-ManagedProcess ([int]$state.apiPid) 'python' 'api'
  Rotate-Log $apiOutputLog; Rotate-Log $apiErrorLog
  $apiArgs = @('-m', 'uvicorn', 'ui.server:app', '--host', '127.0.0.1', '--port', "$apiPort")
  $process = Start-Process -FilePath $pythonExe -ArgumentList $apiArgs -WorkingDirectory $appDirectory -WindowStyle Hidden -RedirectStandardOutput $apiOutputLog -RedirectStandardError $apiErrorLog -PassThru
  $state.apiPid = $process.Id
  Write-EventLog -Event 'recovery_command' -Severity 'warning' -Component 'api' -Message "API iniciada com PID $($process.Id)." -Command 'uvicorn ui.server:app' -Result 'started'
}

function Start-Ui($state) {
  Stop-ManagedProcess ([int]$state.uiPid) 'python' 'ui'
  Rotate-Log $uiOutputLog; Rotate-Log $uiErrorLog
  $env:UI_API_BASE = "http://127.0.0.1:$apiPort"
  $env:API_BASE = "http://127.0.0.1:$apiPort"
  $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = 'python'
  $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION = '3'
  $env:STREAMLIT_SERVER_FILE_WATCHER_TYPE = 'none'
  $uiArgs = @('-m', 'streamlit', 'run', 'ui_streamlit/app.py', '--server.address', '127.0.0.1', '--server.port', "$uiPort",
    '--server.enableWebsocketCompression', 'false', '--server.fileWatcherType', 'none', '--server.headless', 'true')
  $process = Start-Process -FilePath $pythonExe -ArgumentList $uiArgs -WorkingDirectory $appDirectory -WindowStyle Hidden -RedirectStandardOutput $uiOutputLog -RedirectStandardError $uiErrorLog -PassThru
  $state.uiPid = $process.Id
  Write-EventLog -Event 'recovery_command' -Severity 'warning' -Component 'ui' -Message "UI iniciada com PID $($process.Id)." -Command 'streamlit run ui_streamlit/app.py' -Result 'started'
}

function Find-CloudflaredExe {
  @($env:CLOUDFLARED_PATH, (Join-Path $appDirectory 'cloudflared.exe'), 'C:\Users\daniel.avila\AppData\Local\cloudflared\cloudflared.exe') |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}

function Start-Tunnel($state) {
  Stop-ManagedProcess ([int]$state.tunnelPid) 'cloudflared' 'tunnel'
  if (-not $env:CLOUDFLARE_TUNNEL_TOKEN) { throw 'CLOUDFLARE_TUNNEL_TOKEN nao definido no .env.' }
  $cloudflaredExe = Find-CloudflaredExe
  if (-not $cloudflaredExe) { throw 'cloudflared.exe nao encontrado.' }
  Rotate-Log $tunnelOutputLog; Rotate-Log $tunnelErrorLog
  $arguments = @('--no-autoupdate','tunnel','--protocol','http2','--edge-ip-version','4','run','--token',$env:CLOUDFLARE_TUNNEL_TOKEN)
  $process = Start-Process -FilePath $cloudflaredExe -ArgumentList $arguments -WorkingDirectory $appDirectory -WindowStyle Hidden -RedirectStandardOutput $tunnelOutputLog -RedirectStandardError $tunnelErrorLog -PassThru
  $state.tunnelPid = $process.Id
  Write-EventLog -Event 'recovery_command' -Severity 'warning' -Component 'tunnel' -Message "Tunel iniciado com PID $($process.Id)." -Command 'cloudflared tunnel run (credencial ocultada)' -Result 'started'
}

function Send-CriticalAlert([string]$message) {
  $sent = $false
  if ($env:SUPERVISOR_ALERT_WEBHOOK_URL) {
    try {
      Invoke-RestMethod -Method Post -Uri $env:SUPERVISOR_ALERT_WEBHOOK_URL -ContentType 'application/json' -Body (@{text=$message}|ConvertTo-Json) -TimeoutSec 15 | Out-Null
      Write-EventLog -Event 'critical_alert' -Severity 'critical' -Component 'alert' -Message 'Alerta enviado por webhook.' -Result 'sent'; $sent = $true
    } catch { Write-EventLog -Event 'alert_failed' -Severity 'critical' -Component 'alert' -Message $_.Exception.Message -Result 'failed' }
  }
  if ($env:SUPERVISOR_ALERT_EMAIL -and $env:SMTP_HOST -and $env:SMTP_USER -and $env:SMTP_PASSWORD) {
    try {
      $mail = [Net.Mail.MailMessage]::new(); $mail.From = $(if ($env:EMAIL_FROM) {$env:EMAIL_FROM} else {$env:SMTP_USER})
      $mail.To.Add($env:SUPERVISOR_ALERT_EMAIL); $mail.Subject = '[CRITICO] Busca Preco indisponivel'; $mail.Body = $message
      $smtp = [Net.Mail.SmtpClient]::new($env:SMTP_HOST, $(if ($env:SMTP_PORT) {[int]$env:SMTP_PORT} else {587}))
      # SMTP_SECURE segue a convencao Node/nodemailer (false = STARTTLS na 587), mas o
      # SmtpClient do .NET usa EnableSsl para decidir se emite STARTTLS: precisa ser true
      # para qualquer servidor real (Gmail inclusive), senao a autenticacao e recusada.
      $smtp.EnableSsl = $true; $smtp.Credentials = [Net.NetworkCredential]::new($env:SMTP_USER,$env:SMTP_PASSWORD)
      $smtp.Send($mail); $smtp.Dispose(); $mail.Dispose()
      Write-EventLog -Event 'critical_alert' -Severity 'critical' -Component 'alert' -Message 'Alerta enviado por e-mail.' -Result 'sent'; $sent = $true
    } catch { Write-EventLog -Event 'alert_failed' -Severity 'critical' -Component 'alert' -Message $_.Exception.Message -Result 'failed' }
  }
  if (-not $sent) { Write-EventLog -Event 'alert_not_configured' -Severity 'critical' -Component 'alert' -Message 'Defina SUPERVISOR_ALERT_EMAIL ou SUPERVISOR_ALERT_WEBHOOK_URL no .env.' -Result 'not_configured' }
  return $sent
}

function Invoke-Recovery($state, $initialHealth) {
  $cutoff = (Get-Date).AddMinutes(-$recoveryWindowMinutes)
  $recent = @($state.recoveryTimestamps | Where-Object { try {[datetime]$_ -ge $cutoff} catch {$false} })
  if ($recent.Count -ge $maxRecoveriesInWindow) {
    Write-EventLog -Event 'recovery_rate_limited' -Severity 'critical' -Message "Limite de $maxRecoveriesInWindow tentativas em $recoveryWindowMinutes minutos atingido." -Result 'blocked'; return $false
  }
  for ($index=0; $index -lt $recoveryDelays.Count; $index++) {
    $attempt=$index+1; $delay=$recoveryDelays[$index]
    Write-EventLog -Event 'recovery_scheduled' -Severity 'warning' -Component $initialHealth.failureType -Message "Tentativa $attempt agendada em $delay segundos." -StatusCode $initialHealth.public.statusCode -Attempt $attempt
    Start-Sleep -Seconds $delay
    $now=(Get-Date).ToUniversalTime().ToString('o'); $recent += $now; $state.recoveryTimestamps=@($recent); $state.lastRecoveryAt=$now
    try {
      if (-not $initialHealth.apiProcessOk -or -not $initialHealth.apiPortOk -or -not $initialHealth.apiLocal.ok) { Start-Api $state }
      if (-not $initialHealth.uiProcessOk -or -not $initialHealth.uiPortOk -or -not $initialHealth.uiLocal.ok) { Start-Ui $state }
      if (-not $initialHealth.tunnelProcessOk -or -not $initialHealth.public.ok) { Start-Tunnel $state }
      Save-State $state; Start-Sleep -Seconds 10; $health=Get-SystemHealth $state
      if ($health.ok) { Write-EventLog -Event 'recovery_succeeded' -Message 'API, UI, tunel e URL publica confirmados.' -Attempt $attempt -Result 'healthy'; return $true }
      Write-EventLog -Event 'recovery_attempt_failed' -Severity 'error' -Component $health.failureType -Message "Sistema ainda indisponivel apos a tentativa $attempt." -StatusCode $health.public.statusCode -Attempt $attempt -Result 'unhealthy'; $initialHealth=$health
    } catch { Write-EventLog -Event 'recovery_exception' -Severity 'error' -Message $_.Exception.Message -Attempt $attempt -Result 'failed' }
    if ($recent.Count -ge $maxRecoveriesInWindow) { break }
  }
  return $false
}

$mutex=[Threading.Mutex]::new($false,'Global\BuscaPrecoSupervisorV1'); $ownsMutex=$false
try {
  $ownsMutex=$mutex.WaitOne(0); if (-not $ownsMutex) { exit 0 }
  Import-Environment; $state=Read-State
  Write-EventLog -Event 'supervisor_started' -Message "Monitor iniciado; intervalo de $checkIntervalSeconds segundos."
  while ($true) {
    $health=Get-SystemHealth $state; Save-State $state
    if ($health.ok) {
      if ($state.outageStartedAt) { Write-EventLog -Event 'availability_restored' -Message "Disponibilidade restaurada; falha iniciada em $($state.outageStartedAt)." -Result 'healthy'; $state.outageStartedAt=$null; Save-State $state }
      Write-EventLog -Event 'health_check' -Component 'all' -Message "Saudavel; api=$($health.apiLocal.elapsedMs)ms ui=$($health.uiLocal.elapsedMs)ms public=$($health.public.elapsedMs)ms." -StatusCode $health.public.statusCode -Result 'healthy'
    } else {
      if (-not $state.outageStartedAt) { $state.outageStartedAt=(Get-Date).ToUniversalTime().ToString('o') }
      Write-EventLog -Event 'failure_detected' -Severity 'error' -Component $health.failureType -Message "api=$($health.apiProcessOk) ui=$($health.uiProcessOk) tunnel=$($health.tunnelProcessOk) apiLocal=$($health.apiLocal.ok) uiLocal=$($health.uiLocal.ok) public=$($health.public.ok)" -StatusCode $health.public.statusCode -Result 'unhealthy'
      if (-not $NoRecovery) {
        $recovered=Invoke-Recovery $state $health
        if ($recovered) { $state.outageStartedAt=$null } else {
          $canAlert=-not $state.lastAlertAt -or ([datetime]$state.lastAlertAt -lt (Get-Date).AddMinutes(-$alertCooldownMinutes))
          if ($canAlert) { [void](Send-CriticalAlert "O Busca Preco permanece indisponivel desde $($state.outageStartedAt). Falha: $($health.failureType). Consulte $eventLog."); $state.lastAlertAt=(Get-Date).ToUniversalTime().ToString('o') }
        }
        Save-State $state
      }
    }
    if ($RunOnce) { break }; Start-Sleep -Seconds $checkIntervalSeconds
  }
} catch { Write-EventLog -Event 'supervisor_fatal' -Severity 'critical' -Message $_.Exception.Message -Result 'stopped'; throw }
finally { if ($ownsMutex) {$mutex.ReleaseMutex()|Out-Null}; $mutex.Dispose() }
