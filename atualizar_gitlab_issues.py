#!/usr/bin/env python3
"""
Atualiza gitlab_issues_raw.json com work items/issues reais do GitLab.

IMPORTANTE: o campo 'id' no JSON deve ser o IID do projeto (#1289 na URL),
nao o ID global interno do GitLab. Issues de multiplos projetos usam
'gitlab_repo' (contratos_v2 | contratos) para evitar colisao de IID.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
try:
    import config
except ImportError:
    config = None

from issue_filters import filtrar_issues_fechadas_antigas

# Padroes tipicos do JSON de teste/fabricado (nao vem do GitLab real)
MARCADORES_JSON_SINTETICO = (
    "Sincronizar dados com sistema externo",
    "Processo automático #",
    "Issue #1371",
    "Validar CNPJ automaticamente",
    "Gerar relatório consolidado de fiscalizações",
)


def _output_path(output_file: Optional[str] = None) -> Path:
    if output_file:
        return Path(output_file)
    if config:
        return config.ISSUES_JSON
    return Path(__file__).parent / "gitlab_issues_raw.json"


def _gitlab_projects() -> List[Tuple[str, str]]:
    if config and getattr(config, "GITLAB_PROJECTS", None):
        return list(config.GITLAB_PROJECTS)
    return [
        ("comprasnet%2Fcontratos_v2", "contratos_v2"),
        ("comprasnet%2Fcontratos", "contratos"),
    ]


def _mapear_issue_api(issue: Dict, gitlab_repo: str) -> Dict:
    """Mapeia resposta da API GitLab para o formato do pipeline."""
    author = issue.get("author") or {}
    assignees = issue.get("assignees") or []
    milestone = issue.get("milestone") or {}
    return {
        # IID = numero visivel no GitLab (#1289). NAO usar issue['id'] global.
        "id": str(issue["iid"]),
        "gitlab_repo": gitlab_repo,
        "gitlab_id": str(issue["id"]),
        "title": issue.get("title", ""),
        "description": issue.get("description", "") or "",
        "createdDate": issue.get("created_at", ""),
        "updatedDate": issue.get("updated_at", ""),
        "closedDate": issue.get("closed_at", "") or "",
        "state": issue.get("state", ""),
        "author": {"name": author.get("name", "Unknown")},
        "assignees": [
            {"name": assignee.get("name", "")}
            for assignee in assignees
            if assignee.get("name")
        ],
        "milestone": {"title": milestone.get("title", "") if milestone else ""},
        "labels": issue.get("labels", []) or [],
        "merge_requests_count": issue.get("merge_requests_count", 0) or 0,
    }


def json_parece_sintetico(issues: List[Dict]) -> bool:
    """Detecta se o JSON parece dados de teste, nao exportacao real do GitLab."""
    if not issues:
        return False
    titulos = " ".join(i.get("title", "") for i in issues[:50])
    return any(m in titulos for m in MARCADORES_JSON_SINTETICO)


def _gitlab_token_for_repo(gitlab_repo: str) -> str:
    if config and hasattr(config, "gitlab_token_for_repo"):
        return config.gitlab_token_for_repo(gitlab_repo)
    by_repo = {
        "contratos_v2": os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", ""),
        "contratos": os.environ.get("GITLAB_TOKEN_CONTRATOS", ""),
    }
    return by_repo.get(gitlab_repo, "") or os.environ.get("GITLAB_TOKEN", "")


def _tokens_configurados() -> List[str]:
    if config and hasattr(config, "gitlab_tokens_configurados"):
        return config.gitlab_tokens_configurados()
    repos = [repo for _, repo in _gitlab_projects()]
    return [repo for repo in repos if _gitlab_token_for_repo(repo)]


def _buscar_issues_projeto(project_id: str, gitlab_repo: str, gitlab_token: str) -> List[Dict]:
    """Busca todas as issues de um projeto via API REST do GitLab."""
    import requests

    gitlab_url = config.GITLAB_URL if config else os.environ.get("GITLAB_URL", "https://gitlab.com")

    headers = {"PRIVATE-TOKEN": gitlab_token}
    url = f"{gitlab_url}/api/v4/projects/{project_id}/issues"
    params = {"scope": "all", "state": "all", "per_page": 100, "page": 1}

    issues: List[Dict] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        for issue in data:
            issues.append(_mapear_issue_api(issue, gitlab_repo))
        params["page"] += 1

    return issues


def buscar_issues_gitlab() -> List[Dict]:
    """Busca issues de todos os projetos configurados (contratos_v2 + contratos)."""
    configured = _tokens_configurados()
    if not configured:
        raise RuntimeError(
            "Nenhum token GitLab definido. Use GITLAB_TOKEN (global) ou, por repositorio:\n"
            "  GITLAB_TOKEN_CONTRATOS_V2\n"
            "  GITLAB_TOKEN_CONTRATOS\n"
            "Gere tokens em https://gitlab.com/-/user_settings/personal_access_tokens"
        )

    all_issues: List[Dict] = []
    for project_id, repo_name in _gitlab_projects():
        gitlab_token = _gitlab_token_for_repo(repo_name)
        if not gitlab_token:
            print(
                f"   -> Pulando {repo_name}: sem token "
                f"(defina GITLAB_TOKEN_{repo_name.upper()} ou GITLAB_TOKEN)"
            )
            continue
        print(f"   -> Buscando {repo_name} ({project_id})...")
        project_issues = _buscar_issues_projeto(project_id, repo_name, gitlab_token)
        print(f"      {len(project_issues)} issues")
        all_issues.extend(project_issues)

    if not all_issues:
        raise RuntimeError(
            "Nenhuma issue obtida. Verifique tokens e permissoes de leitura nos projetos."
        )

    return all_issues


def atualizar_issues(output_file: Optional[str] = None) -> bool:
    """Atualiza gitlab_issues_raw.json a partir da API GitLab."""
    destino = _output_path(output_file)

    print("\n" + "=" * 70)
    print("ATUALIZADOR DE ISSUES - GitLab (contratos_v2 + contratos)")
    print("=" * 70)

    configured = _tokens_configurados()
    if not configured:
        print("AVISO: Nenhum token GitLab definido.")
        print("        Global:  setx GITLAB_TOKEN \"<token>\"")
        print("        Por repo: setx GITLAB_TOKEN_CONTRATOS_V2 \"<token>\"")
        print("                  setx GITLAB_TOKEN_CONTRATOS \"<token>\"")
        print("        Continuando com gitlab_issues_raw.json existente.")
        validar_json_local(destino)
        return False

    print(f"OK - Tokens configurados para: {', '.join(configured)}")

    try:
        issues = buscar_issues_gitlab()
    except ImportError:
        print("Erro: requests nao instalado. Execute: pip install requests")
        validar_json_local(destino)
        return False
    except Exception as e:
        print(f"Erro ao conectar ao GitLab: {e}")
        validar_json_local(destino)
        return False

    by_repo: Dict[str, int] = {}
    for issue in issues:
        repo = issue.get("gitlab_repo", "?")
        by_repo[repo] = by_repo.get(repo, 0) + 1

    print(f"OK - {len(issues)} issues extraidas do GitLab (usando IID + repositorio)")
    for repo, count in sorted(by_repo.items()):
        print(f"     • {repo}: {count}")

    exclude_days = config.closed_exclude_days() if config else 60
    if config and config.INITIAL_LOAD:
        print("OK - Carga inicial: filtro de issues fechadas DESATIVADO (todas incluidas)")

    issues, excluidas = filtrar_issues_fechadas_antigas(issues, days=exclude_days)
    if excluidas:
        print(
            f"OK - {excluidas} issues fechadas ha mais de {exclude_days} dias "
            f"excluidas do JSON ({len(issues)} restantes)"
        )
    elif exclude_days <= 0:
        print(f"OK - JSON com todas as {len(issues)} issues (sem filtro de fechadas)")

    amostra = next(
        (i for i in issues if i["id"] == "1289" and i.get("gitlab_repo") == "contratos_v2"),
        None,
    )
    if amostra:
        print(f"   Amostra contratos_v2 #1289: {amostra['title'][:80]}")

    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(issues, f, indent=2, ensure_ascii=False)

    print(f"OK - Arquivo salvo: {destino}")
    print(f"OK - Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    return True


def validar_json_local(json_path: Optional[Path] = None) -> None:
    """Emite aviso se o JSON local parecer dados de teste."""
    path = json_path or _output_path()
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        issues = json.load(f)
    if json_parece_sintetico(issues):
        print("\n" + "!" * 70)
        print("AVISO: gitlab_issues_raw.json parece conter DADOS DE TESTE,")
        print("       nao issues reais do GitLab!")
        print("       Defina GITLAB_TOKEN (ou tokens por repo) e rode:")
        print("       python atualizar_gitlab_issues.py")
        print("!" * 70 + "\n")
        amostra = next((i for i in issues if i.get("id") == "1289"), None)
        if amostra:
            print(f"   Exemplo #1289 no JSON local: {amostra.get('title', '')[:80]}")


if __name__ == "__main__":
    success = atualizar_issues()
    sys.exit(0 if success else 1)
