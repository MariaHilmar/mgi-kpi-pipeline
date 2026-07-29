#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Agenda pull condicional nos repos contratos* (WSL): mensal, dia 1 as 09:00.

.PARAMETER Frequency
    "Monthly" (padrao) ou "Weekly".

.PARAMETER Time
    Horario (HH:mm). Padrao: 09:00.

.PARAMETER DayOfMonth
    Dia do mes (Frequency=Monthly). Padrao: 1.

.PARAMETER DaysOfWeek
    Dias da semana (Frequency=Weekly). Padrao: Tuesday, Thursday.

.PARAMETER Test
    Executa executar_pull_repos.bat apos criar/atualizar a tarefa.

.PARAMETER Force
    Substitui a tarefa existente sem perguntar.
#>
param(
    [ValidateSet("Monthly", "Weekly")]
    [string]$Frequency = "Monthly",
    [string]$Time = "09:00",
    [ValidateRange(1, 28)]
    [int]$DayOfMonth = 1,
    [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
    [System.DayOfWeek[]]$DaysOfWeek = @([System.DayOfWeek]::Tuesday, [System.DayOfWeek]::Thursday),
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
Write-Host " AGENDAMENTO - Pull condicional (contratos* / WSL)"
Write-Host "================================================================"
Write-Host ""

$admin = [Security.Principal.WindowsIdentity]::GetCurrent()
$principalCheck = New-Object Security.Principal.WindowsPrincipal($admin)
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERRO - Execute como Administrador" -ForegroundColor $colors.Error
    exit 1
}

$WORKSPACE_DIR = Split-Path -Parent $PSScriptRoot
$BATCH_FILE = Join-Path $WORKSPACE_DIR "executar_pull_repos.bat"
$TASK_NAME = "MGI-Pull-Repos-Main"
$RUN_AS_USER = "$env:USERDOMAIN\$env:USERNAME"
$dayLabels = if ($Frequency -eq "Monthly") { "dia $DayOfMonth de cada mes" } else { ($DaysOfWeek | ForEach-Object { $_.ToString() }) -join ", " }

Write-Host "Workspace:  $WORKSPACE_DIR"
Write-Host "Script:     executar_pull_repos.bat"
Write-Host "Tarefa:     $TASK_NAME"
Write-Host "Frequencia: $Frequency"
Write-Host "Horario:    $Time"
Write-Host "Dias:       $dayLabels"
Write-Host "Fluxo:      fetch + detecta branch (origin/HEAD / master) + pull --ff-only se remoto a frente"
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

$trigger = if ($Frequency -eq "Monthly") {
    New-ScheduledTaskTrigger -Monthly -DaysOfMonth $DayOfMonth -At $Time
} else {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DaysOfWeek -At $Time
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

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
    -Description "Pull condicional nos repos contratos* ($dayLabels $Time; branch origin/HEAD)" `
    -Force | Out-Null

Write-Host ""
Write-Host "OK - Tarefa criada!" -ForegroundColor $colors.Success

$taskInfo = Get-ScheduledTaskInfo -TaskName $TASK_NAME
Write-Host "Proxima execucao: $($taskInfo.NextRunTime)"
Write-Host "Logs:             $WORKSPACE_DIR\logs\pull_repos_*.log"
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
        Write-Host "Consulte o log mais recente em logs\pull_repos_*.log"
    }
}

Write-Host ""
Write-Host "Gerenciar: taskschd.msc -> $TASK_NAME"
Write-Host "Remover:   desagendar_pull_repos.bat"
Write-Host "Manual:    executar_pull_repos.bat"
Write-Host ""
