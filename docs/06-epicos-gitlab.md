# Épicos no GitLab MGI

Este documento registra como o grupo **comprasnet** define épicos no GitLab e
como o pipeline resolve o campo `issues.epico` no Supabase. Serve de referência
para evitar regressões no pivô "Por épico" do dashboard e em alertas de issues
sem épico.

## Como o time define épico no GitLab (fonte de verdade)

No GitLab do MGI, o vínculo de uma issue/task com o épico aparece no painel
lateral do work item como **Parent** (hierarquia de work items), **não** como
campo legado "Epic" da API antiga.

Exemplo real: issue **#1053** em `comprasnet/contratos_v2` ("[Fiscalização]
Incluir análise do Plano de Fiscalização na visualização do TRP e TRD.") tem
como Parent o work item **"[Fiscalização] Checklist de fiscalização..."**.

Na interface:

```
Issue (task)
  └── Parent  →  work item de nível superior (épico do time)
```

Esse Parent é exposto pela API GraphQL em `namespace(fullPath).workItem`
(widget `WorkItemWidgetHierarchy.parent`) ou, em fallback, pela REST
`GET /projects/:id/work_items/:iid?features=hierarchy`.

## O que o pipeline faz (implementação)

Ordem de resolução em `issue_fields.extract_epico` (após enriquecimento no sync):

1. **Filhas do épico no grupo** (`GET /groups/.../epics/:iid/issues`) - 1 request
   traz todas as issues do épico (ex.: work item #30 → 29 filhas).
2. **Parent** do work item (`namespace.workItem` + GraphQL em lote).
3. Label `Épico::` / `Epico::` / variantes.
4. Objeto `epic` da REST de issues (`issue.epic.title`).

### Módulos envolvidos

| Módulo | Papel |
|--------|-------|
| `gitlab_epics.enriquecer_epicos_via_parent_hierarchy` | GraphQL em lote (15 issues/request, split auto) |
| `gitlab_epics.resolver_epico_issue_api` | Parent + REST (backfill issue a issue) |
| `issue_fields.extract_epico` | Parent > label > `epic` REST |
| `sync_supabase.py` | Chama `aplicar_epicos_em_issues` antes do upsert |
| `backfill_epicos_mergeadas.py` | Usa `resolver_epico_issue_api` nas mergeadas sem épico |

### Fluxo no sync

```
aplicar_epicos_em_issues
  ├── vinculos do JSON local (label / epic ja no arquivo)
  ├── enriquecer_epicos_via_filhas_grupo   (REST epics/:iid/issues)
  ├── enriquecer_epicos_via_parent_hierarchy  (GraphQL, lotes de 15)
  └── enriquecer_epicos_via_projetos          (REST issue.epic, restantes)
```

Requer `GITLAB_TOKEN` (ou token por repo) com escopo **read_api** e acesso aos
projetos `comprasnet/contratos_v2` e `comprasnet/contratos`.

## Validação

Após `python sync_supabase.py` ou backfill:

```sql
SELECT count(*) FILTER (WHERE coalesce(trim(epico), '') <> '') AS com_epico,
       count(*) AS total
FROM issues
WHERE mergeado_em IS NOT NULL;
```

Backfill só das mergeadas sem épico:

```powershell
cd mgi-kpi-pipeline
python backfill_epicos_mergeadas.py --dry-run --limit 50
python backfill_epicos_mergeadas.py
```

Por padrao ordena por `mergeado_em` desc (mais recentes primeiro). O backfill
usa filhas dos epicos do grupo + Parent GraphQL; REST legado so com
`--rest-fallback` (lento, raramente util).

## Referências cruzadas

- Contrato Supabase ↔ dashboard: [03-integracao-dashboard.md](03-integracao-dashboard.md)
- Coluna `epico` e pivôs: `mgi-kpi-dashboard/docs/04-dados-supabase.md`
- Migrations do pivô por épico: `061`–`065` em `mgi-kpi-dashboard/supabase/migrations/`
