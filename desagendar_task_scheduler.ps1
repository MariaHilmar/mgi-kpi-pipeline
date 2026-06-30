#Requires -RunAsAdministrator
param(
    [string]$TaskName = "MGI-Pipeline-Supabase"
)

$colors = @{ Success = "Green"; Error = "Red"; Warning = "Yellow" }

Write-Host ""
Write-Host "REMOVER AGENDAMENTO - $TaskName"
Write-Host ""

$admin = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($admin)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERRO - Execute como Administrador" -ForegroundColor $colors.Error
    exit 1
}

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
} catch {
    # Tenta nome legado
    $TaskName = "MGI-Pipeline-Dashboard"
    try {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } catch {
        Write-Host "AVISO - Nenhuma tarefa encontrada" -ForegroundColor $colors.Warning
        exit 0
    }
}

Write-Host "Tarefa encontrada: $($task.TaskName) [$($task.State)]"
$confirm = Read-Host "Remover? Digite SIM"
if ($confirm -ne "SIM") {
    Write-Host "Cancelado."
    exit 0
}

Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false
Write-Host "OK - Tarefa removida" -ForegroundColor $colors.Success
Write-Host ""
Write-Host "Execucao manual: executar_pipeline.bat"
