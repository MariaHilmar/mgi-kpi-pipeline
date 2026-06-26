# Arquitetura

## Componentes

```
GitLab / repos Git (WSL)
        │
        ├── atualizar_gitlab_issues.py  → gitlab_issues_raw.json   (issues via API GitLab)
        └── coleta_git_contratos.py     → gitlab_git_data.json     (commits, branches, releases)
        │
        ▼
pipeline_maestro.py  (orquestrador / entry point)
        │
        ▼
sync_supabase.sync_issues_to_supabase()
        │
        ├── issue_filters         (data de corte + fechadas antigas)
        ├── processar_issues_memoria.build_issue_records()
        │        ├── issue_fields           (datas, lead time, idade, SLA, qualidade)
        │        ├── taxonomy                (módulo normalizado, qualidade)
        │        ├── detectar_area_funcional (Área Funcional via Git/título)
        │        ├── inferir_tipo_issue      (Tipo via labels/Git)
        │        └── enriquecer_dev_git      (branch, commits, MRs, mergeado)
        │
        ▼
Supabase (PostgREST)  →  tabelas public.issues / public.releases / public.sync_runs
        │
        ▼
mgi-kpi-dashboard (Next.js) consome views + RPCs
```

O código é **"flat"** (arquivos na raiz do projeto) por compatibilidade com os
scripts de orquestração/agendador que importam os módulos pelo nome.

## Fluxo de execução do `pipeline_maestro.py`

`PipelineMaestro.executar_pipeline()` segue estas etapas:

1. **Limpeza de logs** — remove logs/relatórios mais antigos que
   `MGI_LOG_RETENTION_DAYS` (padrão 5 dias).
2. **Validação do ambiente** — confere que o JSON de issues existe e cria o
   diretório de saída. (O repositório Git pode estar inacessível: a coleta Git
   falha graciosamente sem abortar o pipeline.)
3. **Etapa 1 — Coleta Git** (`executar_coleta_git`) — percorre `config.REPOS`
   (`contratos_v2` e `contratos`), extrai commits/branches/releases dos últimos
   `MGI_SINCE_DAYS` dias e grava o consolidado em `gitlab_git_data.json`.
4. **Validação do JSON local** — `atualizar_gitlab_issues.validar_json_local`
   emite aviso se o JSON parecer dados sintéticos/de teste.
5. **Etapa 2 — Carregamento de issues** (`carregar_issues_json`) — lê
   `gitlab_issues_raw.json` (lista ou objeto com chave `issues`).
6. **Etapa 3 — Processamento + sync** (`sincronizar_supabase`) — chama
   `sync_issues_to_supabase`, que filtra, processa em memória e faz upsert no
   Supabase. Os detectores Git ficam ativos por padrão (desligados se
   `MGI_FAST_REPO_SYNC=1`).
7. **Relatório final** — grava `logs/relatorio_<timestamp>.json` com totais de
   commits/branches/releases, issues carregadas e issues sincronizadas.

> A atualização do `gitlab_issues_raw.json` a partir da API GitLab acontece
> tipicamente em uma etapa anterior (script `.bat` que chama
> `atualizar_gitlab_issues.py`). Quando o pipeline roda sozinho, ele apenas
> valida o JSON local existente.

## Modos de execução

| Flag / variável | Efeito |
|-----------------|--------|
| (padrão) | Sync incremental: metadados GitLab só recalculados quando vazios. |
| `--full` / `MGI_REFRESH_MODE=full` | Reprocessa todos os metadados/enriquecimentos. |
| `--all-modules` / `MGI_ALL_MODULES=1` | Inclui issues de qualquer módulo (padrão). |
| `--initial-load` / `MGI_INITIAL_LOAD=1` | Carga histórica: não exclui fechadas antigas (a data de corte continua valendo). |
| `MGI_FAST_REPO_SYNC=1` | Desliga detectores Git (Área/Tipo/Dev) — usa só título/labels. |

## Filtros aplicados antes do sync

`sync_supabase._filter_issues_for_sync` aplica, na ordem:

1. **Fechadas antigas** — issues `closed` há mais de `MGI_CLOSED_EXCLUDE_DAYS`
   dias (padrão 60) são descartadas. Na carga inicial o filtro é desligado.
2. **Data de corte** — issues criadas antes de `DEFAULT_CUTOFF_DATE`
   (01/01/2024) são descartadas.

## Saídas e artefatos

| Arquivo | Conteúdo |
|---------|----------|
| `gitlab_issues_raw.json` | Issues cruas (entrada do processamento). |
| `gitlab_git_data.json` | Commits/branches/releases consolidados dos repos. |
| `logs/relatorio_<timestamp>.json` | Resumo de cada execução. |
| Tabelas Supabase | `issues`, `releases`, `sync_runs` (saída final consumida pelo dashboard). |
