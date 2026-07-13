# Repositório canônico — GitHub

O **código-fonte** do `mgi-kpi-pipeline` vive no GitHub:

**https://github.com/MariaHilmar/mgi-kpi-pipeline**

Commits, pull requests, issues e releases do **projeto** devem ser tratados apenas nesse repositório.

## GitLab neste contexto

| Uso | O que é |
|-----|---------|
| **API GitLab** (`comprasnet/contratos_v2`, etc.) | Fonte de **dados** (issues, commits) — configurada via `GITLAB_TOKEN` no `.env` |
| **GitLab `mariahilmar-group/mgi-kpi-pipeline`** | Cópia espelhada **opcional** — **não** é o repositório do projeto |

O workflow de espelhamento GitHub → GitLab foi **removido** para evitar checks falhos no GitHub e para deixar claro que o GitHub é a única origem do código.

Se ainda existir uma cópia no GitLab, pode ser arquivada ou ignorada; não é necessário manter tokens `GITLAB_MIRROR_*` no GitHub.

## CI e testes

- **GitHub:** não há workflow obrigatório de mirror; SonarCloud pode continuar como análise opcional.
- **Testes locais:** `pytest` (ver [04-configuracao-execucao.md](04-configuracao-execucao.md)).
- **`.gitlab-ci.yml`:** legado para quem eventualmente pushar o código em um fork GitLab; não faz parte do fluxo principal no GitHub.

## Remotes locais

Se o seu clone ainda aponta para o GitLab como `origin`, alinhe ao GitHub:

```powershell
cd D:\mgi-workspace\mgi-kpi-pipeline
git remote -v
git remote set-url origin https://github.com/MariaHilmar/mgi-kpi-pipeline.git
# Opcional: manter GitLab como remote secundário
git remote add gitlab https://gitlab.com/mariahilmar-group/mgi-kpi-pipeline.git 2>$null
```
