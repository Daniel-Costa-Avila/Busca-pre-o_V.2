param(
  # Busca-Preço (Streamlit) - publicado em https://<host>/busca-preco
  [string]$BuscaPrecoUrlPath = "busca-preco",
  [int]$BuscaPrecoUiPort = 8630,
  [int]$BuscaPrecoHttpsPort = 443,

  # Frete - publicado em https://<host>:10000/
  [int]$FreteLocalPort = 5100,
  [int]$FreteHttpsPort = 10000,

  # Se quiser também desligar caminhos antigos (ex.: /frete no 443), ligue este switch.
  [switch]$CleanupLegacyPaths
)

$ErrorActionPreference = "Stop"

$script:ScriptPath = $PSCommandPath

function Quote-Arg([string]$value) {
  if ($null -eq $value) { return "" }
  $v = [string]$value
  if ($v -match '[\s"]') {
    return '"' + ($v -replace '"', '""') + '"'
  }
  return $v
}

function Build-ArgsFromBoundParameters([hashtable]$bound) {
  $argsOut = @()
  foreach ($key in ($bound.Keys | Sort-Object)) {
    $val = $bound[$key]
    if ($val -is [switch] -or $val -is [bool]) {
      if ($val) { $argsOut += "-$key" }
      continue
    }
    $argsOut += "-$key"
    $argsOut += (Quote-Arg "$val")
  }
  return $argsOut
}

function Ensure-Admin([hashtable]$bound) {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { return }

  if (-not $script:ScriptPath) {
    throw "Este script precisa rodar como Administrador para configurar o Tailscale."
  }

  $argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Quote-Arg $script:ScriptPath)
  ) + (Build-ArgsFromBoundParameters $bound)
  Write-Host "Reabrindo PowerShell como Administrador..."
  Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argList | Out-Null
  exit 0
}

function Invoke-Tailscale([string[]]$Args) {
  $cmd = "tailscale " + ($Args -join " ")
  Write-Host ">> $cmd"
  & tailscale @Args
}

Ensure-Admin $PSBoundParameters

Write-Host ""
Write-Host "Aplicando tuneis (Tailscale Funnel)..."
Write-Host "  - Busca-Preço: /$BuscaPrecoUrlPath -> http://127.0.0.1:$BuscaPrecoUiPort/$BuscaPrecoUrlPath (HTTPS $BuscaPrecoHttpsPort)"
Write-Host "                 + /_stcore, /static e /media -> http://127.0.0.1:$BuscaPrecoUiPort"
Write-Host "  - Frete:       / -> http://127.0.0.1:$FreteLocalPort (HTTPS $FreteHttpsPort)"
Write-Host ""

if ($CleanupLegacyPaths) {
  # Remove caminhos antigos comuns sem resetar tudo.
  # (Se não existirem, o Tailscale pode apenas ignorar/erro leve.)
  try { Invoke-Tailscale @("serve", "--https=$BuscaPrecoHttpsPort", "--set-path=/frete", "off") } catch { }
  try { Invoke-Tailscale @("serve", "--http=80", "--set-path=/frete", "off") } catch { }
}

# Publica Busca-Preço no 443 em /busca-preco
Invoke-Tailscale @(
  "funnel",
  "--bg",
  "--https=$BuscaPrecoHttpsPort",
  "--set-path=/$BuscaPrecoUrlPath",
  # Importante: o Tailscale encaminha /<path> para o alvo sem o prefixo.
  # Como o Streamlit roda com baseUrlPath=<path>, apontamos para .../<path>.
  "http://127.0.0.1:$BuscaPrecoUiPort/$BuscaPrecoUrlPath"
)

# Compatibilidade do Streamlit quando websocket/assets usam caminhos raiz.
Invoke-Tailscale @(
  "funnel",
  "--bg",
  "--https=$BuscaPrecoHttpsPort",
  "--set-path=/_stcore",
  "http://127.0.0.1:$BuscaPrecoUiPort/_stcore"
)

Invoke-Tailscale @(
  "funnel",
  "--bg",
  "--https=$BuscaPrecoHttpsPort",
  "--set-path=/static",
  "http://127.0.0.1:$BuscaPrecoUiPort/static"
)

Invoke-Tailscale @(
  "funnel",
  "--bg",
  "--https=$BuscaPrecoHttpsPort",
  "--set-path=/media",
  "http://127.0.0.1:$BuscaPrecoUiPort/media"
)

# Publica Frete em :10000 na raiz
Invoke-Tailscale @(
  "funnel",
  "--bg",
  "--https=$FreteHttpsPort",
  "http://127.0.0.1:$FreteLocalPort"
)

Write-Host ""
Write-Host "Status atual:"
Invoke-Tailscale @("funnel", "status")
Write-Host ""
Write-Host "Pronto."
