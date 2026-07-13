# Documentação — mgi-kpi-pipeline

Pipeline Python que coleta dados de issues e commits dos repositórios GitLab do
MGI (`contratos_v2` e `contratos`), processa tudo **em memória** e sincroniza
direto com o **Supabase**, que por sua vez alimenta o dashboard web
[`mgi-kpi-dashboard`](https://github.com/MariaHilmar/mgi-kpi-dashboard).

> **O Excel não faz mais parte do fluxo.** O processamento é feito em memória
> (`processar_issues_memoria.py`) e sincronizado direto com o Supabase.

## Visão de alto nível

```
GitLab (issues / commits)
        │
        ▼
mgi-kpi-pipeline  ──►  processamento em memória  ──►  sync_supabase.py
                                                              │
                                                              ▼
                                                       Supabase (Postgres)
                                                              │
                                                              ▼
                                                     mgi-kpi-dashboard (web)
```

O dashboard é **somente leitura**: ele nunca altera issues no GitLab nem grava
no Supabase. Toda a escrita no banco é feita por este pipeline, usando a
`service_role` key. O frontend consome apenas views/RPCs com a `anon` key.

## Índice

| Documento | Conteúdo |
|-----------|----------|
| [01-arquitetura.md](01-arquitetura.md) | Componentes, fluxo de execução, etapas do pipeline. |
| [02-modulos.md](02-modulos.md) | Responsabilidade de cada módulo Python. |
| [03-integracao-dashboard.md](03-integracao-dashboard.md) | Contrato de dados Supabase ↔ dashboard, campos derivados e KPIs. |
| [04-configuracao-execucao.md](04-configuracao-execucao.md) | Variáveis de ambiente, execução, testes e CI. |
| [05-agendamento.md](05-agendamento.md) | Task Scheduler — execução automática diária. |
| [08-repositorio-github.md](08-repositorio-github.md) | Repositório canônico no GitHub (não espelhar para GitLab). |
| [../mgi-kpi-dashboard/docs/10-identidades-gitlab.md](../mgi-kpi-dashboard/docs/10-identidades-gitlab.md) | Vínculo issue ↔ usuário GitLab, backfill de perfis. |

## Atalhos

```bash
# Execução incremental padrão
python pipeline_maestro.py

# Apenas sincronizar issues para o Supabase (sem detectores Git)
python sync_supabase.py --sem-git

# Testes
pytest
```

Detalhes de cada comando em [04-configuracao-execucao.md](04-configuracao-execucao.md).
