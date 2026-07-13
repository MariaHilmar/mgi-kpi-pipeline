# Configuração e execução

## Requisitos

- Python 3.11+ (CI roda em 3.12)
- Runtime: `requirements.txt` (apenas `requests`)
- Dev/testes: `requirements-dev.txt`

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
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
| `GITLAB_URL` | `https://gitlab.com` | Base da API GitLab. |
| `GITLAB_TOKEN` | vazio | Token global (fallback). |
| `GITLAB_TOKEN_CONTRATOS_V2` / `GITLAB_TOKEN_CONTRATOS` | vazio | Tokens por repositório. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | — | **Obrigatórias para o sync.** |

> A data de corte (`DEFAULT_CUTOFF_DATE = 01/01/2024`) e os repositórios
> (`REPOS`, `GITLAB_PROJECTS`) são definidos em `config.py`.

## Execução

```bash
# Atualizar issues a partir da API GitLab (requer token)
python atualizar_gitlab_issues.py

# Pipeline completo (coleta Git + carga issues + sync Supabase)
python pipeline_maestro.py

# Reprocessamento completo de metadados
python pipeline_maestro.py --full

# Incluir todos os módulos
python pipeline_maestro.py --all-modules

# Carga inicial (histórico)
python pipeline_maestro.py --initial-load

# Apenas sincronizar issues para o Supabase
python sync_supabase.py
python sync_supabase.py --json "D:\caminho\gitlab_issues_raw.json"
python sync_supabase.py --sem-git --sem-releases

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

A suíte cobre a derivação de campos (`issue_fields`), a construção de records
(`processar_issues_memoria`), os filtros, as chaves compostas, a taxonomia e o
cliente de sync (`sync_supabase`, com `requests` mockado).

## CI

Repositório canônico no **GitHub** — ver [08-repositorio-github.md](08-repositorio-github.md).

`pytest` localmente (`requirements-dev.txt`). O `.gitlab-ci.yml` no repositório é legado para runners GitLab opcionais; não há espelhamento automático para o GitLab.

## Banco de dados

O schema versionado fica em `../supabase/migrations`. Aplicar via SQL Editor do
Supabase ou `supabase db push`. Ver detalhes do contrato em
[03-integracao-dashboard.md](03-integracao-dashboard.md).

## Troubleshooting rápido

| Sintoma | Causa provável | Ação |
|---------|----------------|------|
| `Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY` | `.env` ausente/incompleto | Preencher `mgi-workspace/.env`. |
| `Nenhum token GitLab definido` | sem `GITLAB_TOKEN*` | Definir token; ou rodar só o sync com JSON existente. |
| `AVISO: ... DADOS DE TESTE` | JSON sintético no lugar do real | Rodar `atualizar_gitlab_issues.py` com token válido. |
| Coleta Git vazia | repo WSL inacessível | Verificar `\\wsl.localhost\Ubuntu\root\MGI\...`; o pipeline segue sem Git. |
| `Erro Supabase issues (4xx)` | schema desatualizado | Aplicar migrations pendentes. |
