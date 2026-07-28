# Brief para implementacao: pipeline resiliente (GitLab -> Supabase)

Documento para handoff a outro agente (ex.: Claude Opus). Objetivo: **finalizar sync e publicar**
sem timeouts, sem sobrescrever dados bons no Supabase, com um comando de publicacao claro.

## Contexto

Repositorio: `mgi-kpi-pipeline` (Python) + `mgi-kpi-dashboard` (Next.js) + `supabase/migrations`.

Problema de negocio: pivô **Mergeadas por periodo -> Por epico** no dashboard mostrava "Nao informado".
Causa raiz: no GitLab MGI, **epico = Parent do work item** (hierarquia), nao so `issue.epic` legado.

Ja implementado (nao reverter):

- `gitlab_epics.py`: Parent GraphQL via `namespace(fullPath).workItem`, batch 15, split em complexity error
- `backfill_epicos_mergeadas.py --escopo filhas` (padrao): preenche epico no Supabase para filhas de epicos
- `audit_epicos_grupo.py`: auditoria GitLab vs Supabase (51 epicos)
- `atualizar_gitlab_issues.py`: carrega `.env`, `GITLAB_TOKEN` global, retry HTTP, `--repo`, `--sem-merge-dates`
- `sync_supabase.py`: `--repo`, agrupamento PostgREST (PGRST102), omite campos vazios no upsert (`epico`, `mergeado_em`, etc.)
- Agendamento: `executar_pipeline_silent.bat` incremental + backfill filhas

## Sintomas atuais

1. **Timeouts** GitLab em:
   - `related_merge_requests` (20s antigo; parcialmente corrigido para 120s + retry)
   - GraphQL Parent em lotes grandes (802 issues)
   - `audit_epicos_grupo.py` epico #19 ocasional timeout
2. **`--full --repo contratos_v2`** ainda disparava merge dates do **contratos v1** (corrigido: filtra por repo)
3. **`atualizar_gitlab_issues`** mostra `0/X filhas enriquecidas` no JSON - esperado; epico no SB vem de `backfill --escopo filhas`
4. Carga **parcial** (so um repo) + sync **sem --repo** reprocessa tudo e demora

## Objetivo da entrega

1. **Comando unico de publicacao** (ex.: `python publicar_kpi.py` ou `executar_publicacao.bat`) que:
   - Valida `.env` (GITLAB_TOKEN, SUPABASE_*)
   - Opcional: sync GitLab JSON por repo (`--repo`) com `--sem-merge-dates` na carga full parcial
   - Sync Supabase por repo ou incremental
   - Backfill epicos `--escopo filhas`
   - Audit epicos com exit code != 0 se gap critico
   - Resumo final (issues sync, epicos ok/fora SB)
2. **Cliente HTTP GitLab centralizado** (`gitlab_http.py`):
   - `get_json(url, params)`, `post_graphql(query, variables)`
   - Timeout/retry/backoff via env: `MGI_GITLAB_HTTP_TIMEOUT`, `MGI_GITLAB_HTTP_RETRIES`, `MGI_GITLAB_HTTP_RETRY_DELAY`
   - Usado por: `atualizar_gitlab_issues`, `gitlab_epics`, `gitlab_merges`, `audit_epicos_grupo`, `backfill`
3. **Etapas opcionais / retomaveis**:
   - Estado em `logs/publicacao_state.json` (ultimo repo, ultima etapa ok)
   - `--resume` continua de onde parou
   - `--skip-gitlab` / `--skip-supabase` / `--skip-epicos`
4. **Nao degradar dados existentes**:
   - Manter `UPSERT_PRESERVE_IF_BLANK` em `gitlab_identities.py`
   - Sync por `--repo` como padrao em publicacao parcial
   - Nunca `--full` no agendamento
5. **Testes**:
   - HTTP retry mock
   - PostgREST key grouping
   - Publicacao dry-run

## Fluxo recomendado pos-implementacao

```powershell
cd D:\mgi-workspace\mgi-kpi-pipeline

# Publicacao completa (primeira vez ou recuperacao)
python publicar_kpi.py --full --sem-merge-dates

# Ou por etapas manuais (hoje):
python atualizar_gitlab_issues.py --full --repo contratos_v2 --sem-merge-dates
python atualizar_gitlab_issues.py --full --repo contratos --sem-merge-dates
python sync_supabase.py --repo contratos_v2
python sync_supabase.py --repo contratos
python backfill_epicos_mergeadas.py --escopo filhas
python audit_epicos_grupo.py
```

## Criterios de aceite

- [ ] `publicar_kpi.py` completa sem intervencao em rede instavel (retries)
- [ ] Nenhum PGRST102 no sync
- [ ] `audit_epicos_grupo`: 0 issues no SB com filha conhecida no GitLab sem epico (exceto fora do SB)
- [ ] Epico #45: 3/3 no SB; #17: 2/2 apos contratos_v2#1079 sincronizada
- [ ] Documentar em `docs/04-configuracao-execucao.md` variaveis HTTP e comando de publicacao
- [ ] Testes pytest passando

## Arquivos principais

| Arquivo | Papel |
|---------|-------|
| `atualizar_gitlab_issues.py` | GitLab REST -> JSON |
| `sync_supabase.py` | JSON -> Supabase |
| `gitlab_epics.py` | Parent, filhas REST, backfill |
| `backfill_epicos_mergeadas.py` | Epicos no SB |
| `audit_epicos_grupo.py` | Validacao |
| `gitlab_merges.py` | mergeado_em (opcional, lento) |
| `executar_pipeline_silent.bat` | Agendamento |

## Fora de escopo

- Nao commitar `.env`, tokens, `tmp_*`
- Nao abrir PR sem pedido do usuario
- Dashboard migration 065: verificar se aplicada no Supabase remoto
