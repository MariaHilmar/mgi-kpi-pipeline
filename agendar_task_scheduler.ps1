# =====================================================================
# CONFIGURAR TASK SCHEDULER - Pipeline MGI Dashboard
# =====================================================================
# Script PowerShell para agendar execução automática diária
# Executa: executar_pipeline.bat (modo silencioso)
# Horário: 08:10 (personalizável)
# =====================================================================

# Requer privilégios de administrador
#Requires -RunAsAdministrator

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════════════╗"
Write-Host "║         CONFIGURAR AGENDAMENTO - PIPELINE MAESTRO                ║"
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

# =====================================================================
# CONFIGURAÇÕES
# =====================================================================

$WORKSPACE_DIR = Split-Path -Parent $PSScriptRoot
$PROJECT_DIR = $WORKSPACE_DIR
$BATCH_FILE = Join-Path $WORKSPACE_DIR "executar_pipeline.bat"
$TASK_NAME = "MGI-Pipeline-Dashboard"
$TASK_FOLDER = "\"  # Raiz do Task Scheduler
$TRIGGER_TIME = "08:10"

Write-Host "[CONFIGURAÇÃO]"
Write-Host "  Diretório: $PROJECT_DIR"
Write-Host "  Script: executar_pipeline.bat"
Write-Host "  Tarefa: $TASK_NAME"
Write-Host "  Horário: $TRIGGER_TIME (diário)"
Write-Host ""

# =====================================================================
# VALIDAÇÕES
# =====================================================================

Write-Host "[VALIDAÇÃO] Verificando pré-requisitos..."
Write-Host ""

# Verificar se arquivo .bat existe
if (-not (Test-Path $BATCH_FILE)) {
    Write-Host "❌ Arquivo não encontrado: $BATCH_FILE" -ForegroundColor $colors.Error
    Write-Host ""
    pause
    exit 1
}
Write-Host "✓ executar_pipeline.bat encontrado" -ForegroundColor $colors.Success

# Verificar se tarefa já existe
try {
    $existingTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
    if ($existingTask) {
        Write-Host "⚠️  Tarefa já existe: $TASK_NAME" -ForegroundColor $colors.Warning
        Write-Host ""

        $choice = Read-Host "Deseja (1) Atualizar ou (2) Cancelar? (1/2)"

        if ($choice -eq "1") {
            Write-Host "Removendo tarefa existente..."
            Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
            Write-Host "✓ Tarefa removida" -ForegroundColor $colors.Success
        } else {
            Write-Host "[CANCELADO]"
            exit 0
        }
    }
} catch {
    # Tarefa não existe, continuar
}

Write-Host ""

# =====================================================================
# CRIAR TAREFA
# =====================================================================

Write-Host "[CRIANDO TAREFA]"
Write-Host ""

try {
    # Criar ação para executar o batch
    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/c `"$BATCH_FILE`"" `
        -WorkingDirectory $PROJECT_DIR

    # Criar trigger diário
    $trigger = New-ScheduledTaskTrigger `
        -Daily `
        -At $TRIGGER_TIME

    # Definir settings
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -Compatibility Win8 `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable

    # Registrar tarefa
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TASK_NAME `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Host "✓ Tarefa criada com sucesso!" -ForegroundColor $colors.Success
    Write-Host ""

} catch {
    Write-Host "❌ Erro ao criar tarefa:" -ForegroundColor $colors.Error
    Write-Host $_.Exception.Message
    Write-Host ""
    pause
    exit 1
}

# =====================================================================
# VERIFICAR TAREFA
# =====================================================================

Write-Host "[VERIFICAÇÃO]"
Write-Host ""

try {
    $task = Get-ScheduledTask -TaskName $TASK_NAME
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TASK_NAME

    Write-Host "✓ Tarefa registrada" -ForegroundColor $colors.Success
    Write-Host ""
    Write-Host "📋 DETALHES:"
    Write-Host "  Nome da Tarefa: $($task.TaskName)"
    Write-Host "  Status: $($task.State)"
    Write-Host "  Acionador: Diário às $TRIGGER_TIME"
    Write-Host "  Última execução: $($taskInfo.LastRunTime)"
    Write-Host "  Próxima execução: $($taskInfo.NextRunTime)"
    Write-Host ""

} catch {
    Write-Host "❌ Erro ao verificar tarefa:" -ForegroundColor $colors.Error
    Write-Host $_.Exception.Message
}

# =====================================================================
# MODO MANUAL
# =====================================================================

Write-Host "[OPÇÕES]"
Write-Host ""

$final = Read-Host "Deseja (1) Testar agora ou (2) Apenas agendar? (1/2)"

if ($final -eq "1") {
    Write-Host ""
    Write-Host "Executando teste..."
    Write-Host ""

    # Executar em modo silencioso (choice 2)
    $process = Start-Process cmd.exe `
        -ArgumentList "/c `"$BATCH_FILE`" && echo 2 | exit" `
        -WorkingDirectory $PROJECT_DIR `
        -NoNewWindow `
        -PassThru `
        -Wait

    if ($process.ExitCode -eq 0) {
        Write-Host ""
        Write-Host "✓ Teste executado com sucesso!" -ForegroundColor $colors.Success
    } else {
        Write-Host ""
        Write-Host "⚠️  Teste retornou código de erro: $($process.ExitCode)" -ForegroundColor $colors.Warning
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════"
Write-Host ""
Write-Host "✅ AGENDAMENTO CONCLUÍDO!" -ForegroundColor $colors.Success
Write-Host ""
Write-Host "O pipeline será executado automaticamente às 08:10 todos os dias"
Write-Host ""
Write-Host "📍 Para gerenciar manualmente:"
Write-Host "   1. Abra: taskschd.msc (Task Scheduler)"
Write-Host "   2. Procure por: $TASK_NAME"
Write-Host ""
Write-Host "🔍 Para ver logs das execuções:"
Write-Host "   • Automáticas: D:\MGI-Relatorios\pipeline_*.log"
Write-Host "   • Task Scheduler: Event Viewer → Windows Logs → System"
Write-Host ""
Write-Host "⚠️  Notas importantes:"
Write-Host "   • Computador precisa estar ligado às 08:10"
Write-Host "   • WSL e Git devem estar configurados (executar setup-ambiente.bat)"
Write-Host "   • Será executado em modo silencioso (sem saída visual)"
Write-Host ""

pause
