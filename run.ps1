param(
  [switch]$ApiOnly,
  [switch]$UiOnly,
  [switch]$Wait,
  [switch]$PowershellWindows,
  [switch]$KeepOpenWindows,
  [string]$BindHost = "127.0.0.1",
  [int]$ApiPort = 8000,
  [int]$UiPort = 8501,
  # Opcional: publica a UI em um caminho base (ex.: "busca-preco"),
  # útil quando a URL externa precisa ser https://host/busca-preco
  [string]$UiBasePath = ""
)

$ErrorActionPreference = "Stop"

$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $root

# Se abrir janelas separadas, mantenha este processo supervisor ativo para conseguir encerrar tudo junto.
if ($PowershellWindows -and -not $Wait) { $Wait = $true }

$venvPython = Join-Path $root ".venv\\Scripts\\python.exe"
$pythonExe = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }

function Import-DotEnvIfPresent {
  $envPath = Join-Path $root ".env"
  if (-not (Test-Path -LiteralPath $envPath)) {
    return
  }

  Get-Content -LiteralPath $envPath -ErrorAction Stop | ForEach-Object {
    $line = ($_ -as [string]).Trim()
    if (-not $line -or $line.StartsWith("#")) { return }

    $m = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$')
    if (-not $m.Success) { return }

    $name = $m.Groups[1].Value
    $value = $m.Groups[2].Value.Trim()

    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      if ($value.Length -ge 2) { $value = $value.Substring(1, $value.Length - 2) }
    }

    $current = (Get-Item -Path ("Env:{0}" -f $name) -ErrorAction SilentlyContinue).Value

    # Para evitar UI/API desincronizada, sempre force settings sensiveis quando existirem no .env
    if ($name -in @(
        "API_TOKEN", "API_BASE", "UI_API_BASE",
        "MAGALU_SELENIUM_BROWSER", "MAGALU_SELENIUM_BROWSERS",
        "GMAIL_USER", "GMAIL_APP_PASSWORD", "GMAIL_SENDER",
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_SENDER", "SMTP_USE_SSL", "SMTP_USE_TLS",
        "EMAIL_DELIVERY_MODE", "OUTLOOK_FALLBACK_ENABLED"
      )) {
      Set-Item -Path ("Env:{0}" -f $name) -Value $value
      return
    }

    if (-not $current) { Set-Item -Path ("Env:{0}" -f $name) -Value $value }
  }
}

function Disable-ProtobufUpbIfNeeded {
  $upb = Join-Path $root ".venv\\Lib\\site-packages\\google\\_upb"
  $disabled = Join-Path $root ".venv\\Lib\\site-packages\\google\\_upb.disabled"
  if ((Test-Path -LiteralPath $upb) -and -not (Test-Path -LiteralPath $disabled)) {
    try {
      Rename-Item -LiteralPath $upb -NewName "_upb.disabled" -ErrorAction Stop
      Write-Host "Info: desabilitei google._upb (protobuf binario) para compatibilidade."
    } catch {
      Write-Warning "Nao foi possivel desabilitar google._upb automaticamente: $($_.Exception.Message)"
    }
  }
}

function Get-LanIPv4 {
  try {
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop `
      | Where-Object {
        $_.IPAddress -and
        $_.IPAddress -ne "127.0.0.1" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.PrefixOrigin -ne "WellKnown"
      } `
      | Select-Object -First 1 -ExpandProperty IPAddress
    return $ip
  } catch {
    return $null
  }
}

function Get-ListeningPidsForPort([int]$port) {
  try {
    $lines = netstat -ano | Select-String -Pattern (":$port\\s") -ErrorAction Stop | ForEach-Object { $_.Line }
    $pids = @()
    foreach ($line in $lines) {
      if ($line -match "\\sLISTENING\\s+(\\d+)\\s*$") {
        $pids += [int]$Matches[1]
      }
    }
    return $pids | Select-Object -Unique
  } catch {
    return @()
  }
}

function Assert-PortFree([int]$port, [string]$name) {
  $pids = Get-ListeningPidsForPort $port
  if ($pids.Count -gt 0) {
    Write-Error ("{0}: porta {1} em uso (PID(s): {2}). Feche o processo ou mude a porta (ApiPort/UiPort)." -f $name, $port, ($pids -join ", "))
    return $false
  }
  return $true
}

function Start-Api {
  Import-DotEnvIfPresent
  Disable-ProtobufUpbIfNeeded
  if (-not (Assert-PortFree $ApiPort "API")) { return $null }
  $apiArgs = @(
    "-m", "uvicorn",
    "ui.server:app",
    "--host", $BindHost,
    "--port", "$ApiPort"
  )
  Write-Host "API: $pythonExe $($apiArgs -join ' ')"
  if ($PowershellWindows) {
    # Abre um novo terminal com o processo da API. Ao encerrar o sistema, o PID sera finalizado.
    # Se KeepOpenWindows estiver ativo, mantem a janela aberta apos o processo encerrar (debug).
    $cmd = @(
      "& '$pythonExe' -m uvicorn ui.server:app --host '$BindHost' --port '$ApiPort'"
    ) -join " "
    $psArgs = @("-ExecutionPolicy", "Bypass", "-NoProfile", "-Command", $cmd)
    if ($KeepOpenWindows) { $psArgs = @("-ExecutionPolicy", "Bypass", "-NoProfile", "-NoExit", "-Command", $cmd) }
    return Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $root -PassThru
  }
  if ($Wait) {
    New-Item -ItemType Directory -Force (Join-Path $root "runs") | Out-Null
    $out = Join-Path $root "runs\\api.out.log"
    $err = Join-Path $root "runs\\api.err.log"
    return Start-Process -FilePath $pythonExe -ArgumentList $apiArgs -WorkingDirectory $root -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
  }
  Start-Process -FilePath $pythonExe -ArgumentList $apiArgs -WorkingDirectory $root | Out-Null
  return $null
}

function Start-Ui {
  Import-DotEnvIfPresent
  Disable-ProtobufUpbIfNeeded
  if (-not (Assert-PortFree $UiPort "UI")) { return $null }
  # Streamlit roda no servidor e chama a API server-side.
  # Mesmo com bind 0.0.0.0 para acesso interno, usar 127.0.0.1 evita URL inválida (0.0.0.0) dentro do servidor.
  # Sempre configure a base da API para a UI conforme a porta atual do run.ps1.
  # (UI lê UI_API_BASE primeiro; assim evitamos cair no default hardcoded 127.0.0.1:8000.)
  # Nao preserve valores antigos no mesmo terminal: sempre sobrescreva para refletir ApiPort atual.
  $env:UI_API_BASE = "http://127.0.0.1`:$ApiPort"
  $env:API_BASE = "http://127.0.0.1`:$ApiPort"
  if ($UiBasePath) {
    $env:UI_BASE_PATH = $UiBasePath
  }
  # Python 3.14 + protobuf binary extension (upb) can crash in some envs.
  # Force the pure-Python protobuf runtime so Streamlit can start.
  $oldProtoImpl = $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION
  $oldProtoVer = $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION
  $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = "python"
  $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION = "3"
  # Python 3.14 no Windows + watchdog pode causar crash fatal (semaphore). Desative o file watcher.
  $env:STREAMLIT_SERVER_FILE_WATCHER_TYPE = "none"
  $uiArgs = @(
    "-m", "streamlit", "run",
    "ui_streamlit/app.py",
    "--server.address", $BindHost,
    "--server.port", "$UiPort",
    # Evita falhas intermitentes em proxies/tuneis (ex.: Tailscale Serve/Funnel) por compressao de WebSocket.
    "--server.enableWebsocketCompression", "false",
    "--server.fileWatcherType", "none"
  )
  if ($UiBasePath) {
    $uiArgs += @("--server.baseUrlPath", $UiBasePath)
  }
  Write-Host "UI:  $pythonExe $($uiArgs -join ' ')"
  if ($PowershellWindows) {
    $basePathArg = ""
    if ($UiBasePath) { $basePathArg = " --server.baseUrlPath '$UiBasePath'" }
    $cmd = @(
      # A UI chama a API server-side: use 127.0.0.1 mesmo com bind 0.0.0.0.
      "`$env:API_BASE='http://127.0.0.1`:$ApiPort';",
      "`$env:UI_API_BASE='http://127.0.0.1`:$ApiPort';",
      (if ($UiBasePath) { "`$env:UI_BASE_PATH='$UiBasePath';" } else { "" }),
      "`$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION='python';",
      "`$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION='3';",
      "`$env:STREAMLIT_SERVER_FILE_WATCHER_TYPE='none';",
      "& '$pythonExe' -m streamlit run 'ui_streamlit/app.py' --server.address '$BindHost' --server.port '$UiPort' --server.enableWebsocketCompression 'false' --server.fileWatcherType 'none'$basePathArg"
    ) -join " "
    $psArgs = @("-ExecutionPolicy", "Bypass", "-NoProfile", "-Command", $cmd)
    if ($KeepOpenWindows) { $psArgs = @("-ExecutionPolicy", "Bypass", "-NoProfile", "-NoExit", "-Command", $cmd) }
    return Start-Process -FilePath "powershell.exe" -ArgumentList $psArgs -WorkingDirectory $root -PassThru
  }
  if ($Wait) {
    New-Item -ItemType Directory -Force (Join-Path $root "runs") | Out-Null
    $out = Join-Path $root "runs\\ui.out.log"
    $err = Join-Path $root "runs\\ui.err.log"
    return Start-Process -FilePath $pythonExe -ArgumentList $uiArgs -WorkingDirectory $root -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
  }
  Start-Process -FilePath $pythonExe -ArgumentList $uiArgs -WorkingDirectory $root | Out-Null
  return $null
  $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION = $oldProtoImpl
  $env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION_VERSION = $oldProtoVer
}

function Get-ChildPids([int]$ParentPid) {
  try {
    # Win32_Process via CIM: rapido e disponivel no Windows.
    return @(Get-CimInstance Win32_Process -Filter ("ParentProcessId={0}" -f $ParentPid) -ErrorAction Stop | Select-Object -ExpandProperty ProcessId)
  } catch {
    return @()
  }
}

function Stop-ProcessTree([int]$Pid) {
  if (-not $Pid) { return }
  $children = Get-ChildPids $Pid
  foreach ($c in $children) {
    Stop-ProcessTree $c
  }
  try {
    Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue
  } catch {
    # ignore
  }
}

if ($Wait) {
  $started = @()

  $stopping = $false
  $cleanup = {
    if ($script:stopping) { return }
    $script:stopping = $true
    foreach ($proc in $script:started) {
      try {
        if ($proc -and -not $proc.HasExited) {
          Stop-ProcessTree $proc.Id
        }
      } catch {
        # ignore
      }
    }
  }

  try {
    if (-not $UiOnly) { $p = Start-Api; if ($p) { $started += $p } }
    if (-not $ApiOnly) { $p = Start-Ui; if ($p) { $started += $p } }

    $lanIp = Get-LanIPv4
    Write-Host ""
    if (-not $PowershellWindows) {
      Write-Host "Logs:"
      Write-Host "  runs\\api.out.log / runs\\api.err.log"
      Write-Host "  runs\\ui.out.log  / runs\\ui.err.log"
      Write-Host ""
    }
    Write-Host "Pronto."
    Write-Host "API health (local): http://127.0.0.1`:$ApiPort/api/health"
    Write-Host "UI (local):         http://127.0.0.1`:$UiPort"
    if ($lanIp) {
      Write-Host "API health (rede):  http://$lanIp`:$ApiPort/api/health"
      Write-Host "UI (rede):          http://$lanIp`:$UiPort"
    } else {
      Write-Host "Info: nao consegui detectar IP interno automaticamente."
    }
    Write-Host ""
    Write-Host "Para encerrar, pressione Ctrl+C."

    while ($true) {
      $alive = @()
      foreach ($proc in $started) {
        try {
          if ($proc) {
            $proc.Refresh()
            if (-not $proc.HasExited) { $alive += $proc }
          }
        } catch {
          # Ignorar falhas de refresh
        }
      }
      if ($started.Count -gt 0 -and $alive.Count -eq 0) {
        Write-Warning "API/UI encerraram. Verifique os logs em runs\\*.err.log."
        try {
          if (Test-Path -LiteralPath (Join-Path $root "runs\\api.err.log")) {
            Write-Host "--- runs\\api.err.log (tail) ---"
            Get-Content -LiteralPath (Join-Path $root "runs\\api.err.log") -Tail 50 | Write-Host
          }
          if (Test-Path -LiteralPath (Join-Path $root "runs\\ui.err.log")) {
            Write-Host "--- runs\\ui.err.log (tail) ---"
            Get-Content -LiteralPath (Join-Path $root "runs\\ui.err.log") -Tail 50 | Write-Host
          }
        } catch {
          # ignore
        }
        break
      }
      Start-Sleep -Seconds 2
    }
  } finally {
    & $cleanup
  }
  exit 0
}

if (-not $UiOnly) {
  Start-Api
}

if (-not $ApiOnly) {
  Start-Ui
}

$lanIp = Get-LanIPv4
Write-Host ""
Write-Host "Pronto."
Write-Host "API health (local): http://127.0.0.1`:$ApiPort/api/health"
Write-Host "UI (local):         http://127.0.0.1`:$UiPort"
if ($lanIp) {
  Write-Host "API health (rede):  http://$lanIp`:$ApiPort/api/health"
  Write-Host "UI (rede):          http://$lanIp`:$UiPort"
} else {
  Write-Host "Info: nao consegui detectar IP interno automaticamente."
}
