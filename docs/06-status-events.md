# Coleta de histórico de status (GitLab → Supabase)

A pipeline registra **quando** cada issue entrou/saiu de colunas `status::`
do board GitLab, via API **Resource Label Events**, e captura um **snapshot
diário** de etapa/status para CFD histórico.

## Fluxo

1. `atualizar_gitlab_issues.py` — baixa issues (labels atuais) e grava
   `status_event_issue_keys` em `gitlab_issues_sync_state.json` (modo incremental).
2. `sync_supabase.py` — upsert em `issues` e, em seguida:
   - Para cada issue alvo: `GET /projects/:id/issues/:iid/resource_label_events`
   - Filtra labels `status::`
   - Mapeia etapa gerencial via `flow_stages.flow_map_etapa`
   - Grava em `public.issue_status_events` (upsert idempotente por `gitlab_event_id`)
3. `snapshot_issue_status.py` — RPC `flow_capture_daily_snapshots` →
   `public.issue_status_snapshots`

## Tabela `issue_status_events`

| Coluna | Exemplo |
|---|---|
| `issue_key` | `Contratos v2:2706` |
| `event_at` | `2026-02-15T09:31:00Z` |
| `event_type` | `status_add` / `status_remove` |
| `status_novo` | `Doing` (em add) |
| `status_anterior` | `Backlog` (em remove) |
| `etapa_nova` / `etapa_anterior` | Mapeamento Kanban gerencial |
| `gitlab_event_id` | ID único do evento GitLab (upsert idempotente) |

## Pipeline diário

`executar_pipeline.bat` / `executar_pipeline_silent.bat` (raiz do workspace) incluem:

1. `atualizar_gitlab_issues.py` — sync incremental GitLab → JSON
2. `pipeline_maestro.py` → `sync_supabase.py` — upsert issues + status events
3. `pipeline_maestro.py` → `snapshot_issue_status.py` — snapshot diário

Variáveis no agendamento silencioso:

| Variável | Valor | Efeito |
|---|---|---|
| `MGI_SYNC_STATUS_EVENTS` | `1` | Coleta status events |
| `MGI_STATUS_EVENTS_INCREMENTAL` | `1` | Só issues alteradas na etapa 0 |
| `MGI_SYNC_DAILY_SNAPSHOT` | `1` | Grava snapshot após sync |

Para sync manual de **todas** as issues do lote (sem filtro incremental):

```bash
python sync_supabase.py
# ou desligar incremental:
MGI_STATUS_EVENTS_INCREMENTAL=0 python sync_supabase.py
```

Para desligar a coleta:

```bash
python sync_supabase.py --sem-status-events
# ou MGI_SYNC_STATUS_EVENTS=0
```

## Scripts de backfill

```bash
# Backfill completo (default: lista em public.issues, gravação incremental)
python backfill_status_events.py

# Com 12 workers paralelos
python backfill_status_events.py --workers 12

# Usar JSON local (comportamento antigo; aplica filtros do sync)
python backfill_status_events.py --source json

# Supabase sem filtros de corte (default) ou com filtros do sync
python backfill_status_events.py --filtrar

# Apenas simular (não grava)
python backfill_status_events.py --dry-run
```

**Importante:** gravação incremental a cada 50 issues. Logs com `[HH:MM:SS]`.

## Snapshot diário (CFD)

```bash
python snapshot_issue_status.py
python snapshot_issue_status.py --date 2026-06-30
```

Desligar: `MGI_SYNC_DAILY_SNAPSHOT=0`.

Conferir no Supabase:

```sql
select snapshot_date, count(*) as issues
from issue_status_snapshots
group by 1
order by 1 desc
limit 7;
```

## Conferir eventos no Supabase

```sql
select count(distinct issue_key) as issues_com_historico,
       count(*) as total_eventos
from issue_status_events;
```

Exemplo por issue:

```sql
select event_at, event_type, status_anterior, status_novo, etapa_nova
from issue_status_events
where issue_key = 'Contratos v2:2706'
order by event_at;
```

## Variáveis de ambiente

| Variável | Default | Descrição |
|---|---|---|
| `MGI_SYNC_STATUS_EVENTS` | `1` | `0` desliga a coleta no sync/backfill |
| `MGI_STATUS_EVENTS_INCREMENTAL` | `0` | `1` = só issues alteradas no GitLab (pipeline diário) |
| `MGI_SYNC_DAILY_SNAPSHOT` | `1` | `0` = não grava snapshot diário após sync |
| `MGI_STATUS_EVENTS_ISSUE_LIMIT` | `0` | Máx. issues por execução (`0` = todas) |
| `MGI_STATUS_EVENTS_WORKERS` | `8` | Threads paralelas na API GitLab |
| `GITLAB_TOKEN` / `GITLAB_TOKEN_CONTRATOS_V2` | — | Token com escopo `read_api` |

## Origem da lista de issues (backfill)

| Modo | Comando | Issues típicas |
|---|---|---|
| **Supabase** (default) | `python backfill_status_events.py` | Todas em `public.issues` |
| JSON local | `--source json` | Apenas `gitlab_issues_raw.json` |

O JSON local pode ficar desatualizado; o modo Supabase evita depender de
`atualizar_gitlab_issues.py --full`. Use `--filtrar` para aplicar o mesmo corte
do sync (issues antes de 2024 + fechadas há >60 dias).

## Migrations

Aplicar `027_issue_status_events_pipeline.sql` e
`028_issue_status_events_upsert_constraint.sql` (UNIQUE em `gitlab_event_id` —
obrigatório para o upsert da pipeline).

## Performance

- Coleta **paralela** (`MGI_STATUS_EVENTS_WORKERS`, default 8) com `requests.Session` por thread.
- Timeout por request: 30s.
- Retry automático em HTTP 429 (rate limit GitLab).
- Gravação Supabase a cada **50 issues** coletadas.

Estimativa **~2.800 issues** (Supabase): ~15–45 min com 12 workers (depende do rate limit GitLab).

## Limitações

- Histórico **só existe no GitLab** enquanto a instância retém `resource_label_events`.
- Primeira carga completa = **1 chamada API por issue** (usar `--limit` ou backfill incremental).
- Troca de coluna no board = remove label antiga + add nova (dois eventos).
