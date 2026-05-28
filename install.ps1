param(
  [switch]$RecreateVenv,
  [switch]$SkipPlaywrightBrowsers
)

$ErrorActionPreference = "Stop"

$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $root

$venvDir = Join-Path $root ".venv"
$venvPy = Join-Path $venvDir "Scripts\\python.exe"

function Ensure-Venv {
  if ($RecreateVenv -and (Test-Path -LiteralPath $venvDir)) {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $bak = ".venv.broken.$ts"
    Rename-Item -LiteralPath $venvDir -NewName $bak -ErrorAction Stop
    Write-Host "Venv anterior movido para: $bak"
  }

  if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Host "Criando venv em .venv..."
    py -m venv $venvDir
  }

  if (-not (Test-Path -LiteralPath $venvPy)) {
    throw "Nao foi possivel criar o venv. Verifique se o Python/py launcher esta instalado."
  }
}

function Disable-ProtobufUpbIfNeeded {
  $upb = Join-Path $venvDir "Lib\\site-packages\\google\\_upb"
  $disabled = Join-Path $venvDir "Lib\\site-packages\\google\\_upb.disabled"
  if ((Test-Path -LiteralPath $upb) -and -not (Test-Path -LiteralPath $disabled)) {
    try {
      Rename-Item -LiteralPath $upb -NewName "_upb.disabled" -ErrorAction Stop
      Write-Host "Info: desabilitei google._upb (protobuf binario) para compatibilidade."
    } catch {
      Write-Warning "Nao foi possivel desabilitar google._upb automaticamente: $($_.Exception.Message)"
    }
  }
}

Ensure-Venv

Write-Host "Atualizando pip..."
& $venvPy -m pip install --upgrade pip

Write-Host "Instalando dependencias (App + cloud_relay)..."
& $venvPy -m pip install -r "App\\requirements.txt" -r "cloud_relay\\requirements.txt"

Disable-ProtobufUpbIfNeeded

if (-not $SkipPlaywrightBrowsers) {
  Write-Host "Instalando navegadores do Playwright (chromium)..."
  & $venvPy -m playwright install chromium
} else {
  Write-Host "Playwright browsers: pulado (-SkipPlaywrightBrowsers)."
}

Write-Host ""
Write-Host "OK. Proximo passo: .\\run.ps1"
