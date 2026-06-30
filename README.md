# MGI KPI Pipeline

Pipeline que coleta dados de issues e commits dos repositórios GitLab do MGI,
processa tudo **em memória** (taxonomia, área funcional, tipo, enriquecimento
Dev/Git, qualidade) e sincroniza direto com o Supabase, que alimenta o dashboard
web `mgi-kpi-dashboard`. **O Excel não faz mais parte do fluxo.**

## Fluxo geral

```
GitLab / repos Git (WSL)
        │
        ▼
coleta_git_contratos.py        →  gitlab_git_data.json   (commits, branches, releases)
atualizar_gitlab_issues.py     →  gitlab_issues_raw.json  (issues via API GitLab)
        │
        ▼
pipeline_maestro.py  ──►  sync_supabase.sync_issues_to_supabase()
        │                        │
        │                        ▼
        │                 processar_issues_memoria.build_issue_records()
        │                        (issue crua → record Supabase, em memória:
        │                         taxonomia, área, tipo, Dev/Git, qualidade)
        ▼
Supabase (tabelas issues / releases / sync_runs / gitlab_users / issue_participants)
```

A derivação de cada campo (datas, lead time, idade, SLA, flags, módulo
normalizado, qualidade) vive em `issue_fields.py` — lógica pura, sem dependência
de Excel/openpyxl.

## Estrutura

O código é "flat" (arquivos na raiz) por compatibilidade com os scripts de
orquestração/agendador que chamam os módulos pelo nome. Principais módulos:

| Módulo | Responsabilidade |
|--------|------------------|
| `pipeline_maestro.py` | Orquestrador da execução (entry point). |
| `sync_supabase.py` | Carrega issues, filtra, processa em memória e faz upsert no Supabase. |
| `processar_issues_memoria.py` | Constrói os records do Supabase a partir das issues cruas (reaproveita os detectores). |
| `issue_fields.py` | Derivação pura de campos (datas, lead time, idade, SLA, qualidade) — sem Excel. |
| `config.py` | Configuração centralizada (paths, flags, tokens) via env vars. |
| `coleta_git_contratos.py` | Coleta commits/branches/releases dos repos Git. |
| `atualizar_gitlab_issues.py` | Baixa issues via API GitLab. |
| `taxonomy.py` | Normalização de módulos/áreas e regras de qualidade. |
| `detectar_area_funcional.py` / `inferir_tipo_issue.py` | Inferência de Área e Tipo (Git). |
| `enriquecer_dev_git.py` | Enriquecimento Dev/Git (branch, commits, MRs). |
| `issue_filters.py` / `issue_keys.py` | Filtros (data de corte, fechadas antigas) e chaves compostas. |
| `gitlab_identities.py` | Agrega usuários GitLab e participantes por issue para o sync. |
| `backfill_profile_gitlab_ids.py` | Vincula `profiles.gitlab_user_id` por e-mail (contas já existentes). |
| `provision_gitlab_users.py` | Cria contas Supabase a partir de membros GitLab (com `gitlab_user_id`). |

> Os módulos do antigo fluxo Excel (`process_gitlab_issues_v2.py`,
> `gerar_graficos_dashboard.py`, `excel_com_save.py`, etc.) permanecem no
> repositório como legado, mas **não são mais chamados pelo fluxo principal**.

Testes em `tests/` (`pytest`).

## Requisitos

- Python 3.11+ (CI roda em 3.12)
- Dependências de runtime: `requirements.txt` (apenas `requests`)
- Dependências de desenvolvimento/teste: `requirements-dev.txt`

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
```

## Variáveis de ambiente

Todas opcionais (têm default em `config.py`). Para o sync, use um `.env` na
raiz do workspace (`mgi-workspace/.env`).

| Variável | Default | Descrição |
|----------|---------|-----------|
| `MGI_BASE_DIR` | pasta do workspace | Base para logs/JSON. |
| `MGI_ISSUES_JSON` | `mgi-kpi-pipeline/gitlab_issues_raw.json` | Fonte das issues processadas. |
| `MGI_ALL_MODULES` | `1` | `1` = todos os módulos; `0` = só `Fiscalização`/`Fornecedor`. |
| `MGI_CLOSED_EXCLUDE_DAYS` | `60` | Exclui issues fechadas há mais de N dias. |
| `MGI_INITIAL_LOAD` | `0` | Carga inicial (inclui histórico, respeitando a data de corte). |
| `MGI_FAST_REPO_SYNC` | `0` | `1` desliga os detectores Git (área/tipo/Dev) — usa só título/labels. |
| `MGI_SINCE_DAYS` | `30` | Janela de coleta Git. |
| `GITLAB_URL` / `GITLAB_TOKEN` | `https://gitlab.com` / vazio | Integração GitLab (token nunca no código). |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | — | Necessárias para o sync com o Supabase. |

## Execução

```bash
# Sync incremental de issues (novas + alteradas — merge no JSON local)
python atualizar_gitlab_issues.py
python atualizar_gitlab_issues.py -i

# Carga completa de issues (substitui gitlab_issues_raw.json)
python atualizar_gitlab_issues.py --full

# Execução incremental padrão (data opcional via argumento ou stdin)
python pipeline_maestro.py

# Reprocessamento completo de metadados
python pipeline_maestro.py --full

# Incluir todos os módulos
python pipeline_maestro.py --all-modules

# Carga inicial (histórico)
python pipeline_maestro.py --initial-load

# Sincronizar issues para o Supabase (sem Git: só título/labels)
python sync_supabase.py
python sync_supabase.py --json "D:\caminho\gitlab_issues_raw.json"
python sync_supabase.py --sem-git --sem-releases

# Vincular perfis do dashboard ao GitLab (após migration 012)
python backfill_profile_gitlab_ids.py --dry-run
python backfill_profile_gitlab_ids.py
```

## Testes

```bash
pytest
```

A suíte cobre a derivação de campos (`issue_fields`), a construção de records
(`processar_issues_memoria`), os filtros e o cliente de sync (`sync_supabase`,
com `requests` mockado), além das funções puras de taxonomia, datas e chaves.
O CI (`.gitlab-ci.yml`) roda `pytest` a cada push/MR.

## Banco de dados (Supabase)

O schema versionado fica em `../supabase/migrations` (até **012** — identidades GitLab).
Aplicar via SQL Editor do Supabase ou `supabase db push`.
Contrato completo: [03-integracao-dashboard.md](docs/03-integracao-dashboard.md) e
`mgi-kpi-dashboard/docs/10-identidades-gitlab.md`.
