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

- **GitHub Actions:** workflow `tests.yml` — `pytest` em Python 3.11 e 3.12 em push/PR para `main`.
- **Testes locais:** `pytest` (ver [04-configuracao-execucao.md](04-configuracao-execucao.md)).
- **`.gitlab-ci.yml` na raiz:** removido; referência histórica em [legacy-gitlab-ci.yml](legacy-gitlab-ci.yml) para forks GitLab.

## Remotes locais

Se o seu clone ainda aponta para o GitLab como `origin`, alinhe ao GitHub:

```powershell
cd D:\mgi-workspace\mgi-kpi-pipeline
git remote -v
git remote set-url origin https://github.com/MariaHilmar/mgi-kpi-pipeline.git
# Opcional: manter GitLab como remote secundário
git remote add gitlab https://gitlab.com/mariahilmar-group/mgi-kpi-pipeline.git 2>$null
```
