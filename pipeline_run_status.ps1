# Atualiza logs/pipeline_run_status.json (acompanhar_pipeline.bat e execucao agendada).
param(
    [switch]$SetFromEnv
)

$workspace = Split-Path -Parent $PSScriptRoot
$statusPath = Join-Path $workspace 'logs\pipeline_run_status.json'
$logsDir = Split-Path -Parent $statusPath
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

if ($SetFromEnv) {
    $now = Get-Date -Format 'o'
    $payload = [ordered]@{
        state      = $env:MGI_PIPELINE_STATE
        stage      = $env:MGI_PIPELINE_STAGE
        message    = $env:MGI_STATUS_MSG
        pid        = $PID
        log_file   = $env:MGI_PIPELINE_LOG
        updated_at = $now
    }
    if ($env:MGI_EXIT_CODE) {
        $payload.exit_code = [int]$env:MGI_EXIT_CODE
    }
    if ($env:MGI_PIPELINE_STATE -in @('completed', 'failed')) {
        $payload.finished_at = $now
    }
    $payload | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    exit 0
}

if (-not (Test-Path $statusPath)) {
    Write-Host 'Nenhuma execucao registrada.'
    exit 0
}

$data = Get-Content -LiteralPath $statusPath -Raw -Encoding utf8 | ConvertFrom-Json
Write-Host "Estado:  $($data.state)"
Write-Host "Etapa:   $($data.stage)"
Write-Host "Mensagem: $($data.message)"
if ($data.log_file) { Write-Host "Log:     $($data.log_file)" }
if ($data.updated_at) { Write-Host "Atualizado: $($data.updated_at)" }
if ($null -ne $data.exit_code) { Write-Host "Codigo:  $($data.exit_code)" }
