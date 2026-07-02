#!/usr/bin/env python3
"""
Atualiza gitlab_issues_raw.json com work items/issues reais do GitLab.

Modos:
  --incremental (padrao se o JSON local existir)
      Busca na API apenas issues novas ou alteradas desde a ultima sync
      (parametro updated_after). Faz merge no JSON local — nao baixa tudo.

  --full
      Carga completa de todas as issues (substitui o JSON).

IMPORTANTE: o campo 'id' no JSON deve ser o IID do projeto (#1289 na URL),
nao o ID global interno do GitLab. Issues de multiplos projetos usam
'gitlab_repo' (contratos_v2 | contratos) para evitar colisao de IID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
try:
    import config
except ImportError:
    config = None

from issue_filters import filtrar_issues_fechadas_antigas, parse_issue_datetime
from issue_keys import make_issue_key
from status_events import issue_key_from_raw_issue

# Padroes tipicos do JSON de teste/fabricado (nao vem do GitLab real)
MARCADORES_JSON_SINTETICO = (
    "Sincronizar dados com sistema externo",
    "Processo automático #",
    "Issue #1371",
    "Validar CNPJ automaticamente",
    "Gerar relatório consolidado de fiscalizações",
)

SYNC_STATE_FILENAME = "gitlab_issues_sync_state.json"
DEFAULT_OVERLAP_SECONDS = int(os.environ.get("MGI_SYNC_OVERLAP_SECONDS", "120"))
DEFAULT_BOOTSTRAP_DAYS = int(os.environ.get("MGI_SYNC_BOOTSTRAP_DAYS", "7"))


def _output_path(output_file: Optional[str] = None) -> Path:
    if output_file:
        return Path(output_file)
    if config:
        return config.ISSUES_JSON
    return Path(__file__).parent / "gitlab_issues_raw.json"


def _sync_state_path(issues_path: Path) -> Path:
    return issues_path.parent / SYNC_STATE_FILENAME


def _gitlab_projects() -> List[Tuple[str, str]]:
    if config and getattr(config, "GITLAB_PROJECTS", None):
        return list(config.GITLAB_PROJECTS)
    return [
        ("comprasnet%2Fcontratos_v2", "contratos_v2"),
        ("comprasnet%2Fcontratos", "contratos"),
    ]


def _issue_keys_from_fetched(fetched: List[Dict]) -> List[str]:
    keys: List[str] = []
    seen: set[str] = set()
    for issue in fetched:
        key = issue_key_from_raw_issue(issue)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


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
        "dueDate": issue.get("due_date") or "",
        "state": issue.get("state", ""),
        "author": {
            "id": author.get("id"),
            "username": author.get("username"),
            "name": author.get("name", "Unknown"),
        },
        "assignees": [
            {
                "id": assignee.get("id"),
                "username": assignee.get("username"),
                "name": assignee.get("name", ""),
            }
            for assignee in assignees
            if assignee.get("name") or assignee.get("id")
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


def format_gitlab_datetime(value: datetime) -> str:
    """Formata datetime para o parametro updated_after da API GitLab (UTC)."""
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_issues_list(path: Path) -> List[Dict]:
    """Carrega issues do JSON local (lista ou objeto com chave issues)."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("issues"), list):
        return data["issues"]
    return []


def index_issues_by_key(issues: List[Dict]) -> Dict[str, Dict]:
    """Indexa issues pela chave composta repositorio:iid."""
    indexed: Dict[str, Dict] = {}
    for issue in issues:
        key = make_issue_key(issue)
        if key:
            indexed[key] = issue
    return indexed


def compute_sync_watermark(
    indexed: Dict[str, Dict],
    state_path: Path,
    *,
    since_override: Optional[str] = None,
    overlap_seconds: int = DEFAULT_OVERLAP_SECONDS,
) -> datetime:
    """Calcula o instante updated_after para sync incremental."""
    if since_override:
        parsed = parse_issue_datetime(since_override)
        if parsed is None:
            raise ValueError(f"Data invalida em --since: {since_override!r}")
        return parsed - timedelta(seconds=overlap_seconds)

    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last_sync = parse_issue_datetime(state.get("last_sync_at"))
            if last_sync is not None:
                return last_sync - timedelta(seconds=overlap_seconds)
        except (json.JSONDecodeError, OSError):
            pass

    max_dt: Optional[datetime] = None
    for issue in indexed.values():
        for field in ("updatedDate", "createdDate"):
            parsed = parse_issue_datetime(issue.get(field, ""))
            if parsed is not None and (max_dt is None or parsed > max_dt):
                max_dt = parsed

    if max_dt is not None:
        return max_dt - timedelta(seconds=overlap_seconds)

    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=DEFAULT_BOOTSTRAP_DAYS)


def merge_issues_into_index(
    indexed: Dict[str, Dict],
    fetched: List[Dict],
) -> Tuple[int, int]:
    """Mescla issues buscadas no indice local. Retorna (novas, atualizadas)."""
    added = 0
    updated = 0
    for issue in fetched:
        key = make_issue_key(issue)
        if not key:
            continue
        if key in indexed:
            updated += 1
        else:
            added += 1
        indexed[key] = issue
    return added, updated


def _buscar_issues_projeto(
    project_id: str,
    gitlab_repo: str,
    gitlab_token: str,
    *,
    updated_after: Optional[datetime] = None,
) -> List[Dict]:
    """Busca issues de um projeto via API REST do GitLab."""
    import requests

    gitlab_url = config.GITLAB_URL if config else os.environ.get("GITLAB_URL", "https://gitlab.com")

    headers = {"PRIVATE-TOKEN": gitlab_token}
    url = f"{gitlab_url}/api/v4/projects/{project_id}/issues"
    params: Dict[str, object] = {"scope": "all", "state": "all", "per_page": 100, "page": 1}
    if updated_after is not None:
        params["updated_after"] = format_gitlab_datetime(updated_after)

    issues: List[Dict] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        for issue in data:
            issues.append(_mapear_issue_api(issue, gitlab_repo))
        params["page"] = int(params["page"]) + 1

    return issues


def buscar_issues_gitlab(*, updated_after: Optional[datetime] = None) -> List[Dict]:
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
        if updated_after is None:
            print(f"   -> Buscando {repo_name} ({project_id}) [completo]...")
        else:
            print(
                f"   -> Buscando {repo_name} ({project_id}) "
                f"[desde {format_gitlab_datetime(updated_after)}]..."
            )
        project_issues = _buscar_issues_projeto(
            project_id,
            repo_name,
            gitlab_token,
            updated_after=updated_after,
        )
        print(f"      {len(project_issues)} issues")
        all_issues.extend(project_issues)

    if not all_issues and updated_after is None:
        raise RuntimeError(
            "Nenhuma issue obtida. Verifique tokens e permissoes de leitura nos projetos."
        )

    return all_issues


def _aplicar_filtro_fechadas(issues: List[Dict]) -> Tuple[List[Dict], int]:
    exclude_days = config.closed_exclude_days() if config else 60
    if config and config.INITIAL_LOAD:
        print("OK - Carga inicial: filtro de issues fechadas DESATIVADO (todas incluidas)")
    filtered, excluidas = filtrar_issues_fechadas_antigas(issues, days=exclude_days)
    if excluidas:
        print(
            f"OK - {excluidas} issues fechadas ha mais de {exclude_days} dias "
            f"excluidas do JSON ({len(filtered)} restantes)"
        )
    elif exclude_days <= 0:
        print(f"OK - JSON com todas as {len(filtered)} issues (sem filtro de fechadas)")
    return filtered, excluidas


def _salvar_issues(
    destino: Path,
    issues: List[Dict],
    *,
    mode: str,
    stats: Optional[Dict[str, int]] = None,
    status_event_issue_keys: Optional[List[str]] = None,
) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as handle:
        json.dump(issues, handle, indent=2, ensure_ascii=False)

    state_path = _sync_state_path(destino)
    payload = {
        "last_sync_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "issue_count": len(issues),
    }
    if stats:
        payload["stats"] = stats
    if status_event_issue_keys is not None:
        payload["status_event_issue_keys"] = status_event_issue_keys
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    print(f"OK - Arquivo salvo: {destino}")
    print(f"OK - Estado de sync: {state_path}")
    print(f"OK - Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")


def _ensure_tokens(destino: Path) -> bool:
    configured = _tokens_configurados()
    if configured:
        print(f"OK - Tokens configurados para: {', '.join(configured)}")
        return True

    print("AVISO: Nenhum token GitLab definido.")
    print("        Global:  setx GITLAB_TOKEN \"<token>\"")
    print("        Por repo: setx GITLAB_TOKEN_CONTRATOS_V2 \"<token>\"")
    print("                  setx GITLAB_TOKEN_CONTRATOS \"<token>\"")
    print("        Continuando com gitlab_issues_raw.json existente.")
    validar_json_local(destino)
    return False


def atualizar_issues(
    output_file: Optional[str] = None,
    *,
    dry_run: bool = False,
) -> bool:
    """Carga completa: substitui gitlab_issues_raw.json a partir da API GitLab."""
    destino = _output_path(output_file)

    print("\n" + "=" * 70)
    print("ATUALIZADOR DE ISSUES - GitLab [MODO COMPLETO]")
    print("=" * 70)

    if not _ensure_tokens(destino):
        return False

    try:
        issues = buscar_issues_gitlab()
    except ImportError:
        print("Erro: requests nao instalado. Execute: pip install requests")
        validar_json_local(destino)
        return False
    except Exception as exc:
        print(f"Erro ao conectar ao GitLab: {exc}")
        validar_json_local(destino)
        return False

    by_repo: Dict[str, int] = {}
    for issue in issues:
        repo = issue.get("gitlab_repo", "?")
        by_repo[repo] = by_repo.get(repo, 0) + 1

    print(f"OK - {len(issues)} issues extraidas do GitLab (usando IID + repositorio)")
    for repo, count in sorted(by_repo.items()):
        print(f"     • {repo}: {count}")

    issues, _ = _aplicar_filtro_fechadas(issues)

    if dry_run:
        print(f"OK - Dry-run: {len(issues)} issues seriam gravadas (modo completo)")
        return True

    _salvar_issues(destino, issues, mode="full", stats={"fetched": len(issues)}, status_event_issue_keys=_issue_keys_from_fetched(issues))
    return True


def atualizar_issues_incremental(
    output_file: Optional[str] = None,
    *,
    since: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """Sync incremental: novas issues + alteracoes desde a ultima sync (merge local)."""
    destino = _output_path(output_file)
    state_path = _sync_state_path(destino)

    print("\n" + "=" * 70)
    print("ATUALIZADOR DE ISSUES - GitLab [MODO INCREMENTAL]")
    print("=" * 70)

    if not destino.exists():
        print(f"ERRO: JSON local nao encontrado: {destino}")
        print("       Rode primeiro: python atualizar_gitlab_issues.py --full")
        return False

    if not _ensure_tokens(destino):
        return False

    local_issues = load_issues_list(destino)
    indexed = index_issues_by_key(local_issues)
    print(f"OK - Issues locais carregadas: {len(indexed)}")

    try:
        watermark = compute_sync_watermark(indexed, state_path, since_override=since)
    except ValueError as exc:
        print(f"ERRO: {exc}")
        return False

    print(f"OK - Buscando alteracoes desde: {format_gitlab_datetime(watermark)}")

    try:
        fetched = buscar_issues_gitlab(updated_after=watermark)
    except ImportError:
        print("Erro: requests nao instalado. Execute: pip install requests")
        return False
    except Exception as exc:
        print(f"Erro ao conectar ao GitLab: {exc}")
        return False

    added, updated = merge_issues_into_index(indexed, fetched)
    unchanged = len(indexed) - added - updated
    merged = list(indexed.values())

    print(f"OK - API retornou {len(fetched)} issues")
    print(f"OK - Novas: {added} | Atualizadas: {updated} | Sem alteracao: {unchanged}")

    merged, removed_old_closed = _aplicar_filtro_fechadas(merged)
    if removed_old_closed:
        print(f"OK - {removed_old_closed} issues removidas do JSON por filtro de fechadas")

    if dry_run:
        print(
            f"OK - Dry-run: JSON final teria {len(merged)} issues "
            f"(+{added} novas, ~{updated} atualizadas)"
        )
        return True

    _salvar_issues(
        destino,
        merged,
        mode="incremental",
        stats={
            "fetched": len(fetched),
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
        },
        status_event_issue_keys=_issue_keys_from_fetched(fetched),
    )
    return True


def validar_json_local(json_path: Optional[Path] = None) -> None:
    """Emite aviso se o JSON local parecer dados de teste."""
    path = json_path or _output_path()
    if not path.exists():
        return
    issues = load_issues_list(path)
    if json_parece_sintetico(issues):
        print("\n" + "!" * 70)
        print("AVISO: gitlab_issues_raw.json parece conter DADOS DE TESTE,")
        print("       nao issues reais do GitLab!")
        print("       Defina GITLAB_TOKEN (ou tokens por repo) e rode:")
        print("       python atualizar_gitlab_issues.py --full")
        print("!" * 70 + "\n")
        amostra = next((i for i in issues if i.get("id") == "1289"), None)
        if amostra:
            print(f"   Exemplo #1289 no JSON local: {amostra.get('title', '')[:80]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sincroniza issues GitLab -> gitlab_issues_raw.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python atualizar_gitlab_issues.py              # incremental (se JSON existir)\n"
            "  python atualizar_gitlab_issues.py -i           # incremental explicito\n"
            "  python atualizar_gitlab_issues.py --full       # carga completa\n"
            "  python atualizar_gitlab_issues.py -i --since 2026-06-01T00:00:00Z\n"
            "  python atualizar_gitlab_issues.py -i --dry-run\n"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--incremental",
        "-i",
        action="store_true",
        help="busca apenas issues novas/alteradas e faz merge no JSON local",
    )
    mode.add_argument(
        "--full",
        "-f",
        action="store_true",
        help="carga completa de todas as issues (substitui o JSON)",
    )
    parser.add_argument(
        "--since",
        metavar="ISO8601",
        help="watermark manual para sync incremental (ex.: 2026-06-01T00:00:00Z)",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="PATH",
        help="caminho do JSON de saida (padrao: config.ISSUES_JSON)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="simula a sync sem gravar arquivos",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    destino = _output_path(args.output)

    if args.full:
        success = atualizar_issues(args.output, dry_run=args.dry_run)
    elif args.incremental or destino.exists():
        if args.since and not args.incremental and not destino.exists():
            parser.error("--since requer sync incremental e JSON local existente")
        success = atualizar_issues_incremental(
            args.output,
            since=args.since,
            dry_run=args.dry_run,
        )
    else:
        print("JSON local ausente — iniciando carga completa (--full)...")
        success = atualizar_issues(args.output, dry_run=args.dry_run)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
