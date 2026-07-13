# Espelhamento GitHub → GitLab

O repositório canônico de desenvolvimento é o **GitHub** (`MariaHilmar/mgi-kpi-pipeline`).
A cada push em `main`, o workflow [`.github/workflows/mirror-gitlab.yml`](../.github/workflows/mirror-gitlab.yml)
espelha o código para o GitLab (`mariahilmar-group/mgi-kpi-pipeline`).

Se o check **Mirror to GitLab** falhar no GitHub, o commit mostra um **X vermelho** —
o código em si pode estar correto; o espelhamento é que não concluiu.

## Pré-requisitos

| Onde | O quê |
|------|--------|
| GitHub | Secrets `GITLAB_MIRROR_USER` e `GITLAB_MIRROR_TOKEN` |
| GitLab | Projeto `mariahilmar-group/mgi-kpi-pipeline` com branch `main` |
| Token | **Project Access Token** com permissão de escrita no repositório |

## Passo a passo — renovar o token (GitLab)

1. Abra o projeto no GitLab:  
   https://gitlab.com/mariahilmar-group/mgi-kpi-pipeline/-/settings/access_tokens

2. **Revogue** tokens antigos de espelhamento (ex.: `github-mirror`) se existirem.

3. Clique em **Add new token**:
   - **Name:** `github-mirror`
   - **Role:** `Maintainer` (ou `Developer` se o projeto permitir push na `main`)
   - **Scopes:** marque **`write_repository`**
   - **Expiration:** escolha uma data ou deixe sem expiração (conforme política do grupo)

4. Clique em **Create project access token**.

5. Copie imediatamente:
   - **Token** (só aparece uma vez) → será `GITLAB_MIRROR_TOKEN`
   - **Username** do bot (formato `project_<id>_bot`) → será `GITLAB_MIRROR_USER`

   Exemplo de username: `project_83796735_bot`

## Passo a passo — atualizar secrets (GitHub)

1. Abra:  
   https://github.com/MariaHilmar/mgi-kpi-pipeline/settings/secrets/actions

2. Atualize ou crie:
   - `GITLAB_MIRROR_USER` = username do bot (ex.: `project_83796735_bot`)
   - `GITLAB_MIRROR_TOKEN` = token copiado do GitLab

3. **Não** use Personal Access Token de usuário se o projeto exigir Project Access Token
   para push via HTTPS com bot.

## Validar

### Opção A — Reexecutar o workflow

1. https://github.com/MariaHilmar/mgi-kpi-pipeline/actions/workflows/mirror-gitlab.yml  
2. **Run workflow** → branch `main` → **Run workflow**  
3. O job `mirror` deve terminar em verde.

### Opção B — Teste local (PowerShell)

Substitua `USER` e `TOKEN` pelos valores reais (não commite):

```powershell
cd D:\mgi-workspace\mgi-kpi-pipeline
git fetch origin
git checkout main

$env:GITLAB_MIRROR_USER = "project_XXXXX_bot"
$env:GITLAB_MIRROR_TOKEN = "glpat-..."

$encoded = [uri]::EscapeDataString($env:GITLAB_MIRROR_TOKEN)
git ls-remote "https://${env:GITLAB_MIRROR_USER}:${encoded}@gitlab.com/mariahilmar-group/mgi-kpi-pipeline.git" HEAD
```

Se `ls-remote` listar um commit, a autenticação está ok.

## Erros comuns

| Mensagem no log | Causa provável | Correção |
|-----------------|----------------|----------|
| `defina GITLAB_MIRROR_USER e GITLAB_MIRROR_TOKEN` | Secrets ausentes no GitHub | Criar/atualizar secrets |
| `HTTP Basic: Access denied` | Token expirado, username errado ou scope insuficiente | Renovar token; usar username `project_*_bot` |
| `Authentication failed` | Token revogado ou URL do projeto incorreta | Recriar token; conferir path `mariahilmar-group/mgi-kpi-pipeline` |
| Push rejeitado (non-fast-forward) | Históricos GitHub/GitLab divergiram | Ver seção abaixo |

## Históricos divergentes

Se o GitLab tiver commits que o GitHub não tem, o espelhamento pode falhar após
a autenticação ser corrigida. Nesse caso, alinhe manualmente (somente se o GitHub
for a fonte da verdade):

```powershell
# Cuidado: sobrescreve main no GitLab com o estado do GitHub
git push "https://USER:TOKEN@gitlab.com/mariahilmar-group/mgi-kpi-pipeline.git" origin/main:main --force-with-lease
```

O workflow usa `--force-with-lease` apenas quando o push normal falha por
non-fast-forward (ver comentário no YAML).

## SonarCloud (check neutro)

O check **SonarCloud Code Analysis** pode aparecer como *Quality Gate not computed*
sem causar o X vermelho. Configure em https://sonarcloud.io se quiser quality gate
obrigatório; não bloqueia o espelhamento.

## Desativar o espelhamento

Se não precisar mais do GitLab espelhado, remova ou desabilite
`.github/workflows/mirror-gitlab.yml` — os pushes em `main` deixam de mostrar
falha de mirror.
