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
2. Coleta Git + sync Supabase + **historico de status** + **snapshot diario** (`pipeline_maestro.py`)
   - `issue_status_events` — transicoes de coluna Kanban (GitLab `resource_label_events`)
   - `issue_status_snapshots` — foto diaria de etapa (`flow_capture_daily_snapshots`)

A etapa de status consulta no GitLab apenas as issues **alteradas** na etapa 0
(chaves em `gitlab_issues_sync_state.json`, ativado por `MGI_STATUS_EVENTS_INCREMENTAL=1`
em `executar_pipeline_silent.bat`). Upsert idempotente — nao duplica eventos.

O snapshot roda **apos** o sync, com `MGI_SYNC_DAILY_SNAPSHOT=1` (default).

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
- **WSL Ubuntu** com repos em `/root/MGI/contratos_v2` e `/root/MGI/contratos`.
- Rede disponivel (GitLab + Supabase).

O script `executar_pipeline_silent.bat` acorda o WSL antes do pipeline:

```bat
wsl -d Ubuntu -e true
timeout /t 2 /nobreak >nul
```

Isso evita falha na coleta Git quando a distribuicao esta parada (comum apos reboot).

## Verificar execucoes

- **Task Scheduler:** `taskschd.msc` → `MGI-Pipeline-Supabase` → Historico.
- **Logs:** pasta `D:\mgi-workspace\logs\`.
- **Snapshot no Supabase:**

```sql
select snapshot_date, count(*) as issues
from issue_status_snapshots
group by 1
order by 1 desc
limit 7;
```

## Ajustar horario

Remova e recrie com `-Time "09:30"`, ou edite o gatilho em `taskschd.msc`.

## Variaveis de ambiente (modo agendado)

| Variavel | Valor no agendamento | Efeito |
|----------|---------------------|--------|
| `MGI_SYNC_STATUS_EVENTS` | `1` | Coleta `issue_status_events` |
| `MGI_STATUS_EVENTS_INCREMENTAL` | `1` | So issues alteradas no GitLab |
| `MGI_SYNC_DAILY_SNAPSHOT` | `1` | Grava `issue_status_snapshots` apos sync |
