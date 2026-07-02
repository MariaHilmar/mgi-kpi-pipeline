# Módulos

## Orquestração e sync

### `pipeline_maestro.py`
Entry point. Classe `PipelineMaestro` orquestra validação → coleta Git (WSL) →
carregamento de issues → processamento/sync no Supabase → status events →
snapshot diário → relatório. Lê flags de CLI (`--full`, `--all-modules`,
`--initial-load`) e variáveis de ambiente.

### `sync_supabase.py`
Coração do sync. Funções principais:

- `sync_issues_to_supabase(issues, include_releases, enable_git)` — carrega o
  `.env`, valida `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`, filtra as issues,
  monta os records (`build_issue_records`) e faz upsert.
- `SupabaseSync` — cliente PostgREST:
  - `upsert_gitlab_users` — `POST /gitlab_users?on_conflict=id`.
  - `upsert_issues` — `POST /issues?on_conflict=issue_key` em lotes de 200.
  - `replace_issue_participants` — substitui papéis (`author`, `assignee`, `developer`) por issue.
  - `upsert_releases` — `POST /releases?on_conflict=repositorio,versao`.
  - `start_sync_run` / `finish_sync_run` — registra cada execução em
    `public.sync_runs` (status `running` → `success`/`error`).
- Header `Prefer: resolution=merge-duplicates,return=minimal` garante **upsert**
  (preservando campos não enviados).

### `processar_issues_memoria.py`
Converte cada issue crua em um **record com as colunas exatas de
`public.issues`**. `build_issue_records` deduplica por `issue_key` (última
ocorrência vence). Reaproveita os detectores Git e a taxonomia. Campos manuais
(`situacao_analise`, `desenvolvedor_futuro`, `observacao_geral`, `chamado`,
`priorizar`, `epico`) são **omitidos de propósito** para o upsert não
sobrescrever o que foi preenchido à mão no Supabase.

Campos de identidade GitLab (`gitlab_author_id`, `gitlab_assignee_ids`,
`gitlab_developer_id`) e metadados internos `_participants` / `_gitlab_user_meta`
são montados em cada record; o sync remove campos `_*` antes do upsert em
`issues` e grava participantes via `gitlab_identities.py`.

### `gitlab_identities.py`
- `collect_gitlab_users_from_records` — usuários únicos para `public.gitlab_users`.
- `build_participant_rows` — linhas de `public.issue_participants`.
- `enrich_records_with_developer_ids` — resolve dev por e-mail Git ou assignee.
- `prepare_issue_rows_for_upsert` — remove campos internos antes do POST.

### `backfill_profile_gitlab_ids.py`
Vincula `profiles.gitlab_user_id` em contas **já existentes**, cruzando e-mail
do perfil com membros GitLab (API) e `gitlab_users`. Use `--dry-run` antes de
aplicar.

### `provision_gitlab_users.py`
Lista membros ativos dos projetos, cria contas no Supabase Auth e preenche
`profiles.gitlab_user_id` + upsert em `gitlab_users` para usuários novos.

## Derivação de campos

### `issue_fields.py`
Lógica pura (sem Excel/openpyxl). Deriva:

- Datas: `parse_date`, `derive_date_fields` (criado/fechado, ano/mês, lead time,
  idade em dias, `sla_mais_90_dias`).
- `parse_due_date` / campo `entrega_prevista` a partir de `dueDate` GitLab.
- Taxonomia de título: `extract_module`, `normalized_module`,
  `extract_functional_area`.
- Labels GitLab → colunas: `parse_labels` (tipo, status, equipe, parceria,
  prioridade, solicitante, alteração de escopo).
- `faixa_idade` (0-30 / 31-60 / 61-90 / 91-120 / +120 dias).
- `quality_fields` (delega à `taxonomy.assess_row_quality`).

### `taxonomy.py`
Normalização de módulos/áreas (canônicos e buckets) e regras de qualidade dos
dados (`assess_row_quality`: categoria, módulo_ok, área_ok, padrão de título,
confiança da área).

### `issue_keys.py`
Chaves compostas para issues de múltiplos projetos. Define `issue_key =
"<repo_display>:<iid>"`, slugs/aliases de repositório (`contratos_v2` → "Contratos
v2", `contratos` → "Contratos v1"), URLs de work item e paths WSL.

### `issue_filters.py`
`filtrar_issues_fechadas_antigas` (corte por dias desde fechamento) e
`parse_issue_datetime` (datas ISO 8601 ou humanizadas).

## Coleta de dados

### `atualizar_gitlab_issues.py`
Baixa issues via **API REST do GitLab** (`/projects/:id/issues`, paginado) para
todos os projetos em `config.GITLAB_PROJECTS`. Mapeia a resposta para o formato
do pipeline — inclui **`author.id`**, **`author.username`** e **`assignees[].id`**
(além dos nomes) — usa o **IID** do projeto (`#1289`), não o ID global — e
grava `gitlab_issues_raw.json`. Requer `GITLAB_TOKEN` (global) ou tokens por
repo. Detecta JSON sintético/de teste.

### `coleta_git_contratos.py`
Classe `GitColeta`: executa `git log` / `git branch` / `git tag` **via WSL**
(`wsl -d Ubuntu bash -lc "cd /root/MGI/... && git ..."`), extrai commits
(últimos N dias), branches e releases (tags, ordenadas por versão semântica) e
consolida tudo em `gitlab_git_data.json`. Paths WSL definidos em
`issue_keys.WSL_REPO_PATHS`. Distribuição WSL: `MGI_WSL_DISTRO` (default
`Ubuntu`). As releases viram linhas em `public.releases`.

### `status_events.py`
Coleta `resource_label_events` da API GitLab, filtra labels `status::`, mapeia
etapas via `flow_stages` e faz upsert em `public.issue_status_events`. Suporta
modo incremental (`MGI_STATUS_EVENTS_INCREMENTAL=1`) e workers paralelos.

### `snapshot_issue_status.py`
Chama RPC Supabase `flow_capture_daily_snapshots` para gravar snapshot diário
de status/etapa em `issue_status_snapshots` (base do CFD histórico no dashboard).

### `flow_stages.py`
Mapeamento puro `status::` GitLab → etapa Kanban gerencial (`flow_map_etapa`),
espelhando a lógica SQL do Supabase.

### `backfill_status_events.py`
Backfill histórico de status events a partir de `public.issues` (default) ou
JSON local. Gravação incremental a cada 50 issues; flags `--workers`, `--dry-run`,
`--filtrar`, `--source json`.

## Detectores (enriquecimento via Git)

| Módulo | Papel |
|--------|-------|
| `detectar_area_funcional.py` | Infere a **Área Funcional** combinando título e sinais do repositório Git. |
| `inferir_tipo_issue.py` | Infere o **Tipo** da issue (quando não há label `tipo::`). |
| `enriquecer_dev_git.py` | Enriquecimento **Dev/Git**: branch, commits, e-mail do autor (`%ae`), MRs, mergeado e desenvolvedor resolvido. |

Todos são opcionais: com `MGI_FAST_REPO_SYNC=1` (ou `--sem-git` no
`sync_supabase.py`) o processamento usa apenas título e labels.

## Infraestrutura

| Módulo | Papel |
|--------|-------|
| `config.py` | Configuração centralizada via env vars (paths, repos, filtros, tokens, modos). |
| `logging_utils.py` | `configure_logging` / `get_logger` (console + arquivo rotacionado). |
| `log_maintenance.py` | Remove logs/relatórios além da retenção. |

## Legado (não usado no fluxo atual)

`process_gitlab_issues_v2.py`, geradores de gráfico/Excel e `excel_com_save.py`
permanecem no repositório por histórico, mas **não são chamados** pelo
`pipeline_maestro.py`.
