$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path (Split-Path -Parent $root) ".venv\Scripts\python.exe"
$scriptPath = Join-Path $root "html_para_pdf.py"
$pdfPath = Join-Path $root "DOCUMENTACAO_SISTEMA_COMPLETA_2026-03-18.pdf"

if (-not (Test-Path $pythonExe)) {
    throw "Python do ambiente virtual nao encontrado em: $pythonExe"
}

if (-not (Test-Path $scriptPath)) {
    throw "Script gerador nao encontrado em: $scriptPath"
}

& $pythonExe $scriptPath

if (-not (Test-Path $pdfPath)) {
    throw "Falha ao gerar PDF em: $pdfPath"
}

Write-Host "PDF gerado em: $pdfPath" -ForegroundColor Green
