#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Agenda execucao diaria do pipeline MGI no Task Scheduler:
    GitLab incremental, sync Supabase, issue_status_events (historico Kanban)
    e snapshot diario (issue_status_snapshots para CFD).

.PARAMETER Time
    Horario diario no formato HH:mm (padrao 08:10).

.PARAMETER Test
    Executa executar_pipeline_silent.bat apos criar/atualizar a tarefa.

.PARAMETER Force
    Substitui a tarefa existente sem perguntar.
#>
param(
    [string]$Time = "08:10",
    [switch]$Test,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$colors = @{
    Success = "Green"
    Error   = "Red"
    Warning = "Yellow"
}

Write-Host ""
Write-Host "================================================================"
Write-Host " AGENDAMENTO - MGI KPI Pipeline (GitLab -> Supabase + status Kanban)"
Write-Host "================================================================"
Write-Host ""

$admin = [Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = New-Object Security.Principal.WindowsPrincipal($admin)
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERRO - Execute como Administrador" -ForegroundColor $colors.Error
    exit 1
}

$WORKSPACE_DIR = Split-Path -Parent $PSScriptRoot
$BATCH_FILE = Join-Path $WORKSPACE_DIR "executar_pipeline_silent.bat"
$TASK_NAME = "MGI-Pipeline-Supabase"
$RUN_AS_USER = "$env:USERDOMAIN\$env:USERNAME"

Write-Host "Workspace:  $WORKSPACE_DIR"
Write-Host "Script:     executar_pipeline_silent.bat"
Write-Host "Tarefa:     $TASK_NAME"
Write-Host "Horario:    $Time (diario)"
Write-Host "Fluxo:      GitLab incremental + Supabase + status_events + snapshot diario"
Write-Host "Usuario:    $RUN_AS_USER"
Write-Host ""

if (-not (Test-Path $BATCH_FILE)) {
    Write-Host "ERRO - Arquivo nao encontrado: $BATCH_FILE" -ForegroundColor $colors.Error
    exit 1
}

$existingTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($existingTask) {
    if ($Force) {
        Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
        Write-Host "OK - Tarefa anterior removida" -ForegroundColor $colors.Success
    } else {
        $choice = Read-Host "Tarefa ja existe. Atualizar? (S/N)"
        if ($choice -notmatch "^[Ss]") {
            Write-Host "Cancelado."
            exit 0
        }
        Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    }
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BATCH_FILE`"" `
    -WorkingDirectory $WORKSPACE_DIR

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# Usuario atual (acessa .env, tokens e WSL do perfil logado)
$principal = New-ScheduledTaskPrincipal `
    -UserId $RUN_AS_USER `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Sync diario GitLab -> Supabase + status_events + snapshot Kanban" `
    -Force | Out-Null

Write-Host ""
Write-Host "OK - Tarefa criada!" -ForegroundColor $colors.Success

$taskInfo = Get-ScheduledTaskInfo -TaskName $TASK_NAME
Write-Host "Proxima execucao: $($taskInfo.NextRunTime)"
Write-Host ""
Write-Host "Logs: $WORKSPACE_DIR\logs\scheduled_*.log"
Write-Host "      $WORKSPACE_DIR\logs\pipeline.log"
Write-Host ""

if ($Test -or ((Read-Host "Testar agora? (S/N)") -match "^[Ss]")) {
    Write-Host "Executando teste..."
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c `"$BATCH_FILE`"" `
        -WorkingDirectory $WORKSPACE_DIR `
        -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -eq 0) {
        Write-Host "OK - Teste concluido com sucesso" -ForegroundColor $colors.Success
    } else {
        Write-Host "AVISO - Teste retornou codigo $($proc.ExitCode)" -ForegroundColor $colors.Warning
        Write-Host "Consulte o log mais recente em logs\scheduled_*.log"
    }
}

Write-Host ""
Write-Host "Gerenciar: taskschd.msc -> $TASK_NAME"
Write-Host "Remover:   desagendar.bat"
Write-Host ""
