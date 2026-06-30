# Agendamento automatico (Windows Task Scheduler)

## Resumo

| Item | Valor |
|------|-------|
| Script agendado | `executar_pipeline_silent.bat` (raiz do workspace) |
| Horario padrao | 08:10 (diario) |
| Tarefa | `MGI-Pipeline-Supabase` |
| Logs | `logs/scheduled_YYYYMMDD_HHMMSS.log` e `logs/pipeline.log` |

O modo silencioso roda o fluxo incremental completo:

1. Sync incremental de issues (`atualizar_gitlab_issues.py`)
2. Coleta Git + sync Supabase (`pipeline_maestro.py`)

Sem menu interativo, sem pausa no final.

## Configurar (uma vez)

1. Garanta `.env` na raiz do workspace com `GITLAB_TOKEN*`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
2. Duplo-clique em **`agendar.bat`** (pede admin).
3. Confirme horario e teste opcional.

Ou via PowerShell (admin):

```powershell
cd D:\mgi-workspace\mgi-kpi-pipeline
.\agendar_task_scheduler.ps1 -Time "08:10" -Force -Test
```

## Remover agendamento

Duplo-clique em **`desagendar.bat`** ou:

```powershell
.\desagendar_task_scheduler.ps1
```

## Requisitos

- PC ligado no horario (ou `StartWhenAvailable` executa ao voltar).
- Usuario logado (tarefa roda com sua conta — necessario para `.env` e WSL).
- Rede disponivel (GitLab + Supabase).

## Verificar execucoes

- **Task Scheduler:** `taskschd.msc` → `MGI-Pipeline-Supabase` → Historico.
- **Logs:** pasta `D:\mgi-workspace\logs\`.

## Ajustar horario

Remova e recrie com `-Time "09:30"`, ou edite o gatilho em `taskschd.msc`.
