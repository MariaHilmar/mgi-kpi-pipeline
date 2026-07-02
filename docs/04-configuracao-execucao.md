# Configuração e execução

## Requisitos

- Python 3.11+ (CI roda em 3.12)
- **WSL 2** com Ubuntu e repos Git em `/root/MGI/contratos_v2` e `/root/MGI/contratos`
- Runtime: `requirements.txt` (apenas `requests`)
- Dev/testes: `requirements-dev.txt`

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
```

### Verificar WSL e repos

```powershell
wsl -d Ubuntu -e bash -lc "cd /root/MGI/contratos_v2 && git rev-parse --git-dir"
wsl -d Ubuntu -e bash -lc "cd /root/MGI/contratos && git rev-parse --git-dir"
```

## Variáveis de ambiente

Todas têm default em `config.py`. Para o sync com o Supabase, use um `.env` na
raiz do workspace (`mgi-workspace/.env`) — `sync_supabase._load_dotenv()` o
carrega automaticamente.

| Variável | Default | Descrição |
|----------|---------|-----------|
| `MGI_BASE_DIR` | pasta do workspace | Base para logs/JSON consolidado. |
| `MGI_ISSUES_JSON` | `mgi-kpi-pipeline/gitlab_issues_raw.json` | Fonte das issues processadas. |
| `MGI_GIT_DATA_JSON` | `<base>/gitlab_git_data.json` | Saída consolidada da coleta Git. |
| `MGI_ALL_MODULES` | `1` | `1` = todos os módulos; `0` = só `Fiscalização`/`Fornecedor`. |
| `MGI_CLOSED_EXCLUDE_DAYS` | `60` | Exclui issues fechadas há mais de N dias. |
| `MGI_INITIAL_LOAD` | `0` | Carga inicial (inclui histórico, respeitando a data de corte). |
| `MGI_FAST_REPO_SYNC` | `0` | `1` desliga os detectores Git (área/tipo/dev). |
| `MGI_REFRESH_MODE` | `normal` | `full` reprocessa todos os metadados. |
| `MGI_SINCE_DAYS` | `30` | Janela (dias) da coleta Git. |
| `MGI_LOG_RETENTION_DAYS` | `5` | Retenção de logs/relatórios. |
| `MGI_WSL_DISTRO` | `Ubuntu` | Distribuição WSL para coleta Git e detectores. |
| `MGI_SYNC_STATUS_EVENTS` | `1` | Coleta `issue_status_events` após cada sync. |
| `MGI_STATUS_EVENTS_INCREMENTAL` | `0` | `1` nos `.bat` diários — só issues alteradas no GitLab. |
| `MGI_SYNC_DAILY_SNAPSHOT` | `1` | Grava snapshot diário (`issue_status_snapshots`). |
| `MGI_STATUS_EVENTS_WORKERS` | `8` | Threads paralelas na API GitLab (status events). |
| `MGI_AREA_TITULO_ONLY` | `0` | `1` = área funcional só pelo título (sem Git). |
| `GITLAB_URL` | `https://gitlab.com` | Base da API GitLab. |
| `GITLAB_TOKEN` | vazio | Token global (fallback). |
| `GITLAB_TOKEN_CONTRATOS_V2` / `GITLAB_TOKEN_CONTRATOS` | vazio | Tokens por repositório. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | — | **Obrigatórias para o sync.** |

> A data de corte (`DEFAULT_CUTOFF_DATE = 01/01/2024`) e os repositórios
> (`REPOS`, `GITLAB_PROJECTS`) são definidos em `config.py`. Os paths em
> `REPOS` (UNC Windows) são referência legada; a coleta Git usa paths WSL em
> `issue_keys.WSL_REPO_PATHS`.

## Execução

```bash
# Atualizar issues a partir da API GitLab (requer token)
python atualizar_gitlab_issues.py

# Pipeline completo (coleta Git WSL + issues + sync + status events + snapshot)
python pipeline_maestro.py

# Reprocessamento completo de metadados
python pipeline_maestro.py --full

# Carga inicial (histórico)
python pipeline_maestro.py --initial-load

# Apenas sincronizar issues para o Supabase
python sync_supabase.py
python sync_supabase.py --json "D:\caminho\gitlab_issues_raw.json"
python sync_supabase.py --sem-git --sem-releases
python sync_supabase.py --sem-status-events

# Snapshot diário isolado
python snapshot_issue_status.py

# Backfill histórico de status (ver docs/06-status-events.md)
python backfill_status_events.py --dry-run

# Vincular perfis existentes (migration 012)
python backfill_profile_gitlab_ids.py --dry-run
python backfill_profile_gitlab_ids.py
```

### Configuração do Supabase (PowerShell)

```powershell
$env:SUPABASE_URL = "https://xxx.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY = "eyJ..."
cd D:\mgi-workspace\mgi-kpi-pipeline
python sync_supabase.py
```

## Testes

```bash
pytest
```

A suíte cobre derivação de campos (`issue_fields`), records em memória
(`processar_issues_memoria`), coleta Git WSL (`test_coleta_git_contratos`),
status events, flow stages, filtros, chaves compostas, taxonomia e sync
(`sync_supabase`, com `requests` mockado).

## CI

`.gitlab-ci.yml` roda `pytest` em `python:3.12-slim` a cada push e merge request
(instala `requirements-dev.txt`). `pywin32` é marcado como win32-only e ignorado
no runner Linux.

## Banco de dados

O schema versionado fica em `../supabase/migrations`. Migrations relevantes:

- **012** — identidades GitLab (`gitlab_users`, participantes)
- **027** — `issue_status_events`, snapshot CFD
- **028** — constraint upsert em `gitlab_event_id`

Aplicar via SQL Editor do Supabase ou `supabase db push`. Ver
[03-integracao-dashboard.md](03-integracao-dashboard.md) e
[06-status-events.md](06-status-events.md).

## Troubleshooting rápido

| Sintoma | Causa provável | Ação |
|---------|----------------|------|
| `Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY` | `.env` ausente/incompleto | Preencher `mgi-workspace/.env`. |
| `Nenhum token GitLab definido` | sem `GITLAB_TOKEN*` | Definir token; ou rodar só o sync com JSON existente. |
| `AVISO: ... DADOS DE TESTE` | JSON sintético no lugar do real | Rodar `atualizar_gitlab_issues.py` com token válido. |
| `repositorio inacessivel` / 0 commits | WSL parado ou repo ausente em `/root/MGI/...` | `wsl -d Ubuntu -e true`; verificar clones no WSL. |
| `WSL/Git indisponivel - detectores Git desativados` | WSL/repo inacessível ou `MGI_FAST_REPO_SYNC=1` | Acordar WSL; confirmar `git rev-parse` no WSL. |
| Issues carregadas >> sincronizadas | Filtros de corte/fechadas antigas | Esperado (~132 issues pré-2024 excluídas). |
| `Erro Supabase issues (4xx)` | schema desatualizado | Aplicar migrations pendentes (027/028). |
| Status events vazio no log diário | Nenhuma issue alterada no sync incremental | Normal; use backfill para carga inicial. |
