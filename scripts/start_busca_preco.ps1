param(
  [string]$BindHost = "127.0.0.1",
  [string]$UiBasePath = "busca-preco",

  # Se informado (!=0), tenta usar exatamente essa porta.
  [int]$ApiPort = 0,
  [int]$UiPort = 0,

  # Faixas padrão para evitar conflito com outros sistemas.
  [int]$ApiPortStart = 8040,
  [int]$ApiPortEnd = 8099,
  [int]$UiPortStart = 8630,
  [int]$UiPortEnd = 8699,

  # Se ligado, mantém este processo em execução e mostra logs (equivalente ao -Wait do run.ps1)
  [switch]$Wait,

  # Se ligado, tenta atualizar o Funnel automaticamente (abre UAC se necessário).
  [switch]$ConfigureTunnel,

  # Parâmetros do tunnel (443 em /busca-preco por padrão).
  [int]$TunnelHttpsPort = 443,
  [string]$TunnelPath = "busca-preco"
)

$ErrorActionPreference = "Stop"

$root = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
Set-Location $root

function Test-PortFree([int]$port) {
  try {
    $hit = netstat -ano | Select-String -Pattern (":$port\\s") -ErrorAction SilentlyContinue
    return -not $hit
  } catch {
    return $true
  }
}

function Pick-FreePort([int]$preferred, [int]$start, [int]$end, [string]$name) {
  if ($preferred -gt 0) {
    if (Test-PortFree $preferred) { return $preferred }
    Write-Warning ("{0}: porta {1} já está em uso. Vou procurar outra disponível." -f $name, $preferred)
  }
  for ($p = $start; $p -le $end; $p++) {
    if (Test-PortFree $p) { return $p }
  }
  throw ("{0}: não encontrei porta livre no intervalo {1}-{2}." -f $name, $start, $end)
}

$pickedApiPort = Pick-FreePort $ApiPort $ApiPortStart $ApiPortEnd "API"
$pickedUiPort = Pick-FreePort $UiPort $UiPortStart $UiPortEnd "UI"

Write-Host ""
Write-Host "Iniciando Busca-Preço..."
Write-Host "  API: http://127.0.0.1:$pickedApiPort"
Write-Host "  UI:  http://127.0.0.1:$pickedUiPort/$UiBasePath"
Write-Host ""

$runParams = @{
  BindHost   = $BindHost
  ApiPort    = $pickedApiPort
  UiPort     = $pickedUiPort
  UiBasePath = $UiBasePath
}
if ($Wait) { $runParams.Wait = $true }

if ($ConfigureTunnel) {
  $tunnelScript = Join-Path $root "scripts\\tunnels.ps1"
  if (-not (Test-Path -LiteralPath $tunnelScript)) {
    throw "Não encontrei $tunnelScript"
  }
  Write-Host "Atualizando tunnel para /$TunnelPath -> http://127.0.0.1:$pickedUiPort (HTTPS $TunnelHttpsPort)..."
  & powershell -NoProfile -ExecutionPolicy Bypass -File $tunnelScript `
    -BuscaPrecoUiPort $pickedUiPort `
    -BuscaPrecoUrlPath $TunnelPath `
    -BuscaPrecoHttpsPort $TunnelHttpsPort | Out-Host
  Write-Host ""
}

& (Join-Path $root "run.ps1") @runParams
