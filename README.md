# MGI KPI Pipeline

Pipeline que coleta dados de issues e commits dos repositórios GitLab do MGI,
consolida tudo em um dashboard Excel (`MGI_Dashboard.xlsx`) e, opcionalmente,
sincroniza com o Supabase (que alimenta o dashboard web `mgi-kpi-dashboard`).

## Fluxo geral

```
GitLab / repos Git (WSL)
        │
        ▼
coleta_git_contratos.py        →  gitlab_git_data.json   (commits, branches, releases)
atualizar_gitlab_issues.py     →  gitlab_issues_raw.json  (issues via API GitLab)
        │
        ▼
pipeline_maestro.py  ──►  process_gitlab_issues_v2.process_issues()
        │                        (upsert na aba "Dados", enriquecimento,
        │                         taxonomia, qualidade, gráficos, KPIs)
        ▼
MGI_Dashboard.xlsx
        │
        ▼ (opcional)
sync_supabase.py               →  Supabase (tabelas issues / releases / sync_runs)
```

## Estrutura

O código é "flat" (arquivos na raiz) por compatibilidade com os scripts de
orquestração/agendador que chamam os módulos pelo nome. Principais módulos:

| Módulo | Responsabilidade |
|--------|------------------|
| `pipeline_maestro.py` | Orquestrador da execução (entry point). |
| `process_gitlab_issues_v2.py` | Núcleo: lê/escreve a aba `Dados` e aplica todo o processamento. |
| `config.py` | Configuração centralizada (paths, flags, tokens) via env vars. |
| `coleta_git_contratos.py` | Coleta commits/branches/releases dos repos Git. |
| `atualizar_gitlab_issues.py` | Baixa issues via API GitLab. |
| `taxonomy.py` | Normalização de módulos/áreas e regras de qualidade. |
| `detectar_area_funcional.py` / `inferir_tipo_issue.py` | Inferência de Área e Tipo. |
| `enriquecer_dev_git.py` | Enriquecimento Dev/Git (branch, commits, MRs). |
| `qualidade_dados.py` / `relatorio_excecoes.py` | Métricas de qualidade e exceções. |
| `sync_supabase.py` | Sincroniza a aba `Dados` + releases para o Supabase. |
| `excel_com_save.py` | Save via COM (Windows) preservando filtros. |

Testes em `tests/` (`pytest`).

## Requisitos

- Python 3.11+ (CI roda em 3.12)
- Dependências de runtime: `requirements.txt`
- Dependências de desenvolvimento/teste: `requirements-dev.txt`
- `pywin32` só é necessário no Windows (save COM do Excel).

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
| `MGI_BASE_DIR` | pasta do workspace | Base para Excel/logs/JSON. |
| `MGI_EXCEL_OUTPUT` | `BASE_DIR/MGI_Dashboard.xlsx` | Caminho do dashboard Excel. |
| `MGI_ALL_MODULES` | `1` | `1` = todos os módulos; `0` = só `Fiscalização`/`Fornecedor`. |
| `MGI_ALLOW_NEW_ISSUES` | `1` | `0` = só atualiza issues já na planilha. |
| `MGI_PRESERVE_TAXONOMY` | `1` | Não sobrescreve Módulo/Área já preenchidos. |
| `MGI_CLOSED_EXCLUDE_DAYS` | `60` | Exclui issues fechadas há mais de N dias. |
| `MGI_INITIAL_LOAD` | `0` | Carga inicial (inclui histórico, respeitando a data de corte). |
| `MGI_REFRESH_MODE` | `normal` | `full` reprocessa metadados/labels/tipo/Dev-Git. |
| `MGI_SINCE_DAYS` | `30` | Janela de coleta Git. |
| `GITLAB_URL` / `GITLAB_TOKEN` | `https://gitlab.com` / vazio | Integração GitLab (token nunca no código). |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | — | Necessárias para `sync_supabase.py`. |

## Execução

```bash
# Execução incremental padrão (data opcional via argumento ou stdin)
python pipeline_maestro.py

# Reprocessamento completo de metadados
python pipeline_maestro.py --full

# Incluir todos os módulos
python pipeline_maestro.py --all-modules

# Carga inicial (histórico)
python pipeline_maestro.py --initial-load

# Sincronizar o Excel para o Supabase
python sync_supabase.py
python sync_supabase.py --excel "D:\MGI-Relatórios\MGI_Dashboard.xlsx"
```

## Testes

```bash
pytest
```

A suíte cobre funções puras (taxonomia, datas, filtros, chaves de issue) e um
teste de integração de `process_issues` (workbook temporário, hooks pesados
mockados). O CI (`.gitlab-ci.yml`) roda `pytest` a cada push/MR.

## Banco de dados (Supabase)

O schema versionado fica em `../supabase/migrations`. As migrations `006`/`007`
endurecem o schema (idade/SLA calculados no banco, tipos, menor privilégio para
`anon`). Aplicar via SQL Editor do Supabase ou `supabase db push`.
