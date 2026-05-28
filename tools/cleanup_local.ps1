param(
  [switch]$Safe,
  [switch]$IncludeProfiles,
  [switch]$IncludeRuns,
  [switch]$RemoveFirebasePublic,
  [switch]$ListAll,
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  if ($PSScriptRoot) {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  }
  return (Get-Location).Path
}

function Assert-InRepo([string]$repoRoot, [string]$targetPath) {
  $resolved = (Resolve-Path -LiteralPath $targetPath -ErrorAction Stop).Path
  if (-not $resolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Caminho fora do repo: $resolved"
  }
  return $resolved
}

function Get-DirSizeBytes([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) { return 0 }
  try {
    return (Get-ChildItem -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
  } catch {
    return 0
  }
}

function Format-Size([double]$bytes) {
  if ($bytes -ge 1TB) { return ("{0:N2} TB" -f ($bytes / 1TB)) }
  if ($bytes -ge 1GB) { return ("{0:N2} GB" -f ($bytes / 1GB)) }
  if ($bytes -ge 1MB) { return ("{0:N2} MB" -f ($bytes / 1MB)) }
  if ($bytes -ge 1KB) { return ("{0:N2} KB" -f ($bytes / 1KB)) }
  return ("{0:N0} B" -f $bytes)
}

function Remove-PathSafe([string]$repoRoot, [string]$relativePath) {
  $full = Join-Path $repoRoot $relativePath
  if (-not (Test-Path -LiteralPath $full)) {
    Write-Host "OK (nao existe): $relativePath"
    return
  }
  $resolved = Assert-InRepo $repoRoot $full
  if ($WhatIf) {
    Write-Host "WHATIF: remover $relativePath ($resolved)"
    return
  }
  try {
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
    Write-Host "REMOVIDO: $relativePath"
  } catch {
    $msg = $_.Exception.Message
    Write-Warning "NAO FOI POSSIVEL remover: $relativePath | $msg"
    Write-Warning "Dica: feche processos Python/servidor (uvicorn/streamlit) ou reinicie a maquina e rode novamente."
  }
}

function Remove-PyCache([string]$repoRoot) {
  $excludedRoots = @(
    (Join-Path $repoRoot ".venv"),
    (Join-Path $repoRoot "venv"),
    (Join-Path $repoRoot "env")
  )

  function Is-UnderExcludedRoot([string]$path) {
    foreach ($root in $excludedRoots) {
      if (-not $root) { continue }
      if ($path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
      }
    }
    return $false
  }

  $folders = Get-ChildItem -LiteralPath $repoRoot -Recurse -Force -Directory -ErrorAction SilentlyContinue `
    | Where-Object { $_.Name -eq "__pycache__" -and -not (Is-UnderExcludedRoot $_.FullName) }

  $pycFiles = Get-ChildItem -LiteralPath $repoRoot -Recurse -Force -File -ErrorAction SilentlyContinue `
    | Where-Object { ($_.Extension -in @(".pyc", ".pyo")) -and -not (Is-UnderExcludedRoot $_.FullName) }

  if ($WhatIf -and -not $ListAll) {
    Write-Host ("WHATIF: remover {0} pastas __pycache__ e {1} arquivos *.pyc/*.pyo (use -ListAll para detalhar)" -f $folders.Count, $pycFiles.Count)
    return
  }

  foreach ($f in $folders) {
    $rel = $f.FullName.Substring($repoRoot.Length).TrimStart("\", "/")
    Remove-PathSafe $repoRoot $rel
  }
  foreach ($file in $pycFiles) {
    $resolved = Assert-InRepo $repoRoot $file.FullName
    $rel = $resolved.Substring($repoRoot.Length).TrimStart("\", "/")
    if ($WhatIf) {
      Write-Host "WHATIF: remover $rel"
      continue
    }
    try {
      Remove-Item -LiteralPath $resolved -Force -ErrorAction Stop
      if ($ListAll) { Write-Host "REMOVIDO: $rel" }
    } catch {
      $msg = $_.Exception.Message
      Write-Warning "NAO FOI POSSIVEL remover arquivo: $rel | $msg"
    }
  }
}

$repoRoot = Resolve-RepoRoot

if (-not ($Safe -or $IncludeProfiles -or $IncludeRuns -or $RemoveFirebasePublic)) {
  $Safe = $true
}

Write-Host "Repo: $repoRoot"
Write-Host ""
Write-Host "Itens grandes (top):"

$candidates = @(
  "debug_zema",
  "chrome_profile_magalu",
  "chrome_profile_mercadolivre",
  ".venv",
  "venv",
  ".venv.broken.20260317_075831",
  ".selenium",
  ".firebase",
  "runs",
  "firebase_public"
)

$sizes = foreach ($c in $candidates) {
  $p = Join-Path $repoRoot $c
  if (Test-Path -LiteralPath $p) {
    [pscustomobject]@{ Path = $c; Size = (Get-DirSizeBytes $p) }
  }
}

$sizes | Sort-Object Size -Descending | Select-Object -First 12 `
  | ForEach-Object { "{0,-28} {1,12}" -f $_.Path, (Format-Size $_.Size) } | Write-Host

Write-Host ""
Write-Host "Modo: " -NoNewline
if ($WhatIf) { Write-Host "WHATIF (nao remove nada)" } else { Write-Host "APLICAR (remove)" }
Write-Host ""

if ($Safe) {
  Write-Host "Limpando (SAFE): venvs, caches e debug..."
  Remove-PathSafe $repoRoot ".venv"
  Remove-PathSafe $repoRoot "venv"
  Get-ChildItem -LiteralPath $repoRoot -Directory -Force -Filter ".venv.broken*" -ErrorAction SilentlyContinue | ForEach-Object {
    $rel = $_.FullName.Substring($repoRoot.Length).TrimStart("\", "/")
    Remove-PathSafe $repoRoot $rel
  }
  Remove-PathSafe $repoRoot ".selenium"
  Remove-PathSafe $repoRoot ".firebase"
  Remove-PathSafe $repoRoot "debug_magalu"
  Remove-PathSafe $repoRoot "debug_zema"
  Remove-PyCache $repoRoot
}

if ($RemoveFirebasePublic) {
  Write-Host "Limpando: firebase_public (somente se nao usa Firebase Hosting pra UI)..."
  Remove-PathSafe $repoRoot "firebase_public"
}

if ($IncludeProfiles) {
  Write-Host "ATENCAO: remover perfis pode exigir novo login/captcha."
  Remove-PathSafe $repoRoot "chrome_profile_magalu"
  Remove-PathSafe $repoRoot "chrome_profile_mercadolivre"
}

if ($IncludeRuns) {
  Write-Host "ATENCAO: remover runs/ apaga estado (usuarios/token/config/jobs)."
  Remove-PathSafe $repoRoot "runs"
}

Write-Host ""
Write-Host "Concluido."
