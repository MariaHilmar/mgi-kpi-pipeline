# Integração com o dashboard

O pipeline e o [`mgi-kpi-dashboard`](https://github.com/MariaHilmar/mgi-kpi-dashboard)
**não se comunicam diretamente**: o contrato entre eles é o **schema do Supabase**
(versionado em `../supabase/migrations`). O pipeline escreve; o dashboard lê.

```
pipeline (service_role)  ──►  Supabase  ──►  dashboard (anon, somente leitura)
```

## Tabelas escritas pelo pipeline

### `public.issues`
Espelho de cada issue processada. O record produzido por
`processar_issues_memoria.build_issue_record` mapeia 1:1 nas colunas da tabela.
Grupos de colunas:

- **Identidade:** `issue_key` (único, `on_conflict`), `gitlab_repo`, `gitlab_iid`,
  `repositorio`, `titulo`.
- **Taxonomia:** `modulo`, `modulo_normalizado`, `area_funcional`, `tipo`.
- **Estado/labels:** `estado`, `status`, `prioridade`, `equipe`, `parceria`,
  `sprint`, `assignee`, `autor`, `solicitante`, `alteracao_escopo`.
- **Datas/SLA:** `criado_em`, `fechado_em`, `lead_time_dias`, `ano_mes_criacao`,
  `ano_criacao`, `mes_criacao`, `ano_mes_fechamento`, `mes_fechamento`, `aberto`,
  `fechado`, `idade_dias`, `sla_mais_90_dias`, `faixa_idade`.
- **Dev/Git:** `dev_tem_branch`, `dev_branch`, `dev_commits`,
  `dev_ultimo_commit`, `dev_autor_dev`, `gitlab_mrs`, `dev_mergeado`,
  `desenvolvedor`.
- **Qualidade:** `categoria`, `modulo_ok`, `area_ok`, `padrao_titulo`,
  `padrao_completo`, `confianca_area`.
- **Manuais (NÃO enviados pelo sync):** `situacao_analise`,
  `desenvolvedor_futuro`, `observacao_geral`, `chamado`, `priorizar`, `epico` —
  preenchidos diretamente no Supabase e preservados pelo upsert.

### `public.releases`
`repositorio` + `versao` (chave única), `data_release`, `rotulo`. Origem:
`gitlab_git_data.json`.

### `public.sync_runs`
Telemetria de cada execução do sync: `source`, `status`, `rows_upserted`,
`releases_upserted`, `started_at`, `finished_at`, `message`.

## Camada consumida pelo dashboard (views + RPCs)

O frontend nunca varre a tabela bruta; usa objetos versionados nas migrations:

| Objeto | Migration | Uso no dashboard |
|--------|-----------|------------------|
| `v_kpis` | 001 | KPIs consolidados (total, abertas, fechadas, SLA > 90, lead time médio). |
| `v_filter_options` | 001 | Opções dos filtros globais (parceria, sprint, ano). |
| `dashboard_aggregate(...)` | 001 | Agregações por dimensão (parceria, repositório, área, dev, módulo, tipo, qualidade…) com filtros. |
| `dashboard_kpis(...)` | 001 | KPIs com filtros aplicados. |
| `_issues_filtered(...)` + RPCs de KPI | 003 | KPIs completos do "Dashboard Executivo" com todos os filtros globais. |
| busca de issues | 004 | Página `/issues` (busca livre, paginação). |
| pares módulo/área | 005 | Coerência de filtros dependentes. |

> **Convenção de filtros:** `NULL` ou `'Todos'` = sem filtro; `'Não informado'`
> casa com valores vazios/em branco. Sempre há corte `ano_criacao >= 2024`.

## Hardening (migrations 006 / 007)

- **006** — passa a calcular `idade_dias` / `sla_mais_90_dias` / `faixa_idade`
  **no banco** (colunas/funções `STABLE` baseadas em `current_date`), evitando a
  defasagem de valores congelados no momento do sync; tipa a confiança da área
  como número. Aditiva: não muda assinaturas nem remove colunas em uso.
- **007** — menor privilégio para o papel `anon` (somente leitura do necessário).

## Mapa de gráficos (paridade Excel → Web)

| Excel (legado) | Web |
|----------------|-----|
| Parcerias | BarChart Parcerias |
| Issues por Repositório | BarChart Repositório |
| Área Funcional (top 14) | BarChart Área |
| Top Desenvolvedores (top 12) | BarChart horizontal |
| Merge em master | BarChart Dev mergeado |
| Qualidade dos Dados | BarChart Qualidade |
| Releases Git | BarChart Releases |

## Segurança do contrato

- O pipeline usa **`SUPABASE_SERVICE_ROLE_KEY`** (bypassa RLS) — apenas no
  backend, nunca exposta no frontend.
- O dashboard usa **`NEXT_PUBLIC_SUPABASE_ANON_KEY`** (somente leitura via RLS +
  grants).
- Tokens GitLab e chaves do Supabase ficam em variáveis de ambiente / `.env`,
  nunca hardcoded.
