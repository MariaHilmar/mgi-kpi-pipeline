# =====================================================================
# REMOVER AGENDAMENTO - Task Scheduler
# =====================================================================
# Script PowerShell para remover a tarefa agendada do Pipeline
# =====================================================================

# Requer privilégios de administrador
#Requires -RunAsAdministrator

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════════════╗"
Write-Host "║      REMOVER AGENDAMENTO - PIPELINE MAESTRO                       ║"
Write-Host "╚════════════════════════════════════════════════════════════════════╝"
Write-Host ""

# Cores
$colors = @{
    Success = 'Green'
    Error   = 'Red'
    Warning = 'Yellow'
    Info    = 'Cyan'
}

# Verificar privilégios
$admin = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($admin)

if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "❌ Este script requer privilégios de Administrador" -ForegroundColor $colors.Error
    Write-Host "   Execute novamente com: Run as administrator"
    Write-Host ""
    pause
    exit 1
}

Write-Host "✓ Privilégios: OK" -ForegroundColor $colors.Success
Write-Host ""

$TASK_NAME = "MGI-Pipeline-Dashboard"

# =====================================================================
# VERIFICAR TAREFA
# =====================================================================

Write-Host "[VERIFICAÇÃO]"
Write-Host ""

try {
    $task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction Stop
    Write-Host "✓ Tarefa encontrada: $TASK_NAME" -ForegroundColor $colors.Success
    Write-Host ""
} catch {
    Write-Host "❌ Tarefa não encontrada: $TASK_NAME" -ForegroundColor $colors.Error
    Write-Host ""
    pause
    exit 1
}

# =====================================================================
# CONFIRMAR REMOÇÃO
# =====================================================================

Write-Host "⚠️  CUIDADO: Esta ação é irreversível" -ForegroundColor $colors.Warning
Write-Host ""
Write-Host "Informações da tarefa:"
Write-Host "  Nome: $($task.TaskName)"
Write-Host "  Status: $($task.State)"
Write-Host ""

$confirm = Read-Host "Tem certeza que deseja remover? Digite 'SIM' para confirmar"

if ($confirm -ne "SIM") {
    Write-Host ""
    Write-Host "[CANCELADO]"
    pause
    exit 0
}

# =====================================================================
# REMOVER TAREFA
# =====================================================================

Write-Host ""
Write-Host "[REMOVENDO TAREFA]"
Write-Host ""

try {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
    Write-Host "✓ Tarefa removida com sucesso!" -ForegroundColor $colors.Success
    Write-Host ""
} catch {
    Write-Host "❌ Erro ao remover tarefa:" -ForegroundColor $colors.Error
    Write-Host $_.Exception.Message
    Write-Host ""
    pause
    exit 1
}

# =====================================================================
# RESULTADO FINAL
# =====================================================================

Write-Host "═══════════════════════════════════════════════════════════════════"
Write-Host ""
Write-Host "✅ AGENDAMENTO REMOVIDO!" -ForegroundColor $colors.Success
Write-Host ""
Write-Host "O pipeline não será mais executado automaticamente."
Write-Host ""
Write-Host "Você ainda pode executar manualmente com:"
Write-Host "  📂 Duplo-clique: D:\MGI-Relatorios\executar_pipeline.bat"
Write-Host ""

pause
