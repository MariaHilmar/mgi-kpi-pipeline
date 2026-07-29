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

sys.path.insert(0, str(Path(__file__).parent))


def _load_dotenv_early() -> None:
    """Carrega .env antes de importar modulos que leem config."""
    for path in (
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
    ):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ[key] = value
        return


_load_dotenv_early()

try:
    import config
except ImportError:
    config = None

from sync_supabase import _load_dotenv

_load_dotenv()

from gitlab_epics import coletar_e_salvar_epicos, mapear_epic_api
from gitlab_merges import enriquecer_issues_com_merge_dates
from issue_filters import filtrar_issues_fechadas_antigas, parse_issue_datetime
from issue_keys import make_issue_key
from logging_utils import get_logger

log = get_logger(__name__)

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
DEFAULT_GITLAB_HTTP_TIMEOUT = int(os.environ.get("MGI_GITLAB_HTTP_TIMEOUT", "120"))
DEFAULT_GITLAB_HTTP_RETRIES = int(os.environ.get("MGI_GITLAB_HTTP_RETRIES", "3"))
DEFAULT_GITLAB_HTTP_RETRY_DELAY = float(os.environ.get("MGI_GITLAB_HTTP_RETRY_DELAY", "5"))


def _output_path(output_file: str | None = None) -> Path:
    if output_file:
        return Path(output_file)
    if config:
        return config.ISSUES_JSON
    return Path(__file__).parent / "gitlab_issues_raw.json"


def _sync_state_path(issues_path: Path) -> Path:
    return issues_path.parent / SYNC_STATE_FILENAME


def _gitlab_projects() -> list[tuple[str, str]]:
    if config and getattr(config, "GITLAB_PROJECTS", None):
        return list(config.GITLAB_PROJECTS)
    return [
        ("comprasnet%2Fcontratos_v2", "contratos_v2"),
        ("comprasnet%2Fcontratos", "contratos"),
    ]


def _mapear_issue_api(issue: dict, gitlab_repo: str) -> dict:
    """Mapeia resposta da API GitLab para o formato do pipeline."""
    author = issue.get("author") or {}
    assignees = issue.get("assignees") or []
    milestone = issue.get("milestone") or {}
    epic = mapear_epic_api(issue.get("epic"), issue.get("epic_iid"))
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
        "epic": epic,
        "labels": issue.get("labels", []) or [],
        "merge_requests_count": issue.get("merge_requests_count", 0) or 0,
    }


def json_parece_sintetico(issues: list[dict]) -> bool:
    """Detecta se o JSON parece dados de teste, nao exportacao real do GitLab."""
    if not issues:
        return False
    titulos = " ".join(i.get("title", "") for i in issues[:50])
    return any(m in titulos for m in MARCADORES_JSON_SINTETICO)


def _gitlab_token_for_repo(gitlab_repo: str) -> str:
    if config and hasattr(config, "gitlab_token_for_repo"):
        return config.gitlab_token_for_repo(gitlab_repo)
    global_token = os.environ.get("GITLAB_TOKEN", "").strip()
    if global_token:
        return global_token
    by_repo = {
        "contratos_v2": os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", ""),
        "contratos": os.environ.get("GITLAB_TOKEN_CONTRATOS", ""),
    }
    return by_repo.get(gitlab_repo, "").strip()


def _tokens_configurados() -> list[str]:
    if config and hasattr(config, "gitlab_tokens_configurados"):
        return config.gitlab_tokens_configurados()
    repos = [repo for _, repo in _gitlab_projects()]
    return [repo for repo in repos if _gitlab_token_for_repo(repo)]


def format_gitlab_datetime(value: datetime) -> str:
    """Formata datetime para o parametro updated_after da API GitLab (UTC)."""
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_issues_list(path: Path) -> list[dict]:
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


def index_issues_by_key(issues: list[dict]) -> dict[str, dict]:
    """Indexa issues pela chave composta repositorio:iid."""
    indexed: dict[str, dict] = {}
    for issue in issues:
        key = make_issue_key(issue)
        if key:
            indexed[key] = issue
    return indexed


def compute_sync_watermark(
    indexed: dict[str, dict],
    state_path: Path,
    *,
    since_override: str | None = None,
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

    max_dt: datetime | None = None
    for issue in indexed.values():
        for field in ("updatedDate", "createdDate"):
            parsed = parse_issue_datetime(issue.get(field, ""))
            if parsed is not None and (max_dt is None or parsed > max_dt):
                max_dt = parsed

    if max_dt is not None:
        return max_dt - timedelta(seconds=overlap_seconds)

    return datetime.now(UTC).replace(tzinfo=None) - timedelta(days=DEFAULT_BOOTSTRAP_DAYS)


def merge_issues_into_index(
    indexed: dict[str, dict],
    fetched: list[dict],
) -> tuple[int, int]:
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


def _issues_para_enriquecer_merge(
    merged: list[dict],
    *,
    changed_issues: list[dict],
) -> list[dict]:
    """Subset que precisa consultar mergeado_em: alteradas ou ainda sem data."""
    changed_keys = {make_issue_key(issue) for issue in changed_issues if make_issue_key(issue)}
    selected: list[dict] = []
    for issue in merged:
        key = make_issue_key(issue)
        if not key:
            continue
        if key in changed_keys or not (issue.get("mergeado_em") or "").strip():
            selected.append(issue)
    return selected


def replace_repo_issues_in_index(
    indexed: dict[str, dict],
    fetched: list[dict],
    gitlab_repo: str,
) -> int:
    """Substitui todas as issues de um repo no indice. Retorna quantas foram removidas."""
    removed = 0
    for key in list(indexed):
        if indexed[key].get("gitlab_repo") == gitlab_repo:
            del indexed[key]
            removed += 1
    merge_issues_into_index(indexed, fetched)
    return removed


def _gitlab_http_timeout() -> int:
    return DEFAULT_GITLAB_HTTP_TIMEOUT


def _gitlab_http_retries() -> int:
    return max(1, DEFAULT_GITLAB_HTTP_RETRIES)


def _gitlab_http_retry_delay() -> float:
    return max(0.0, DEFAULT_GITLAB_HTTP_RETRY_DELAY)


def _get_gitlab_response(url: str, *, headers: dict[str, str], params: dict[str, object]):
    """GET na API GitLab com retry em timeout/conexao."""
    import time

    import requests

    timeout = _gitlab_http_timeout()
    retries = _gitlab_http_retries()
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt >= retries:
                break
            wait = _gitlab_http_retry_delay() * attempt
            log.warning(
                f"AVISO - GitLab timeout/conexao (tentativa {attempt}/{retries}); "
                f"retry em {wait:.0f}s..."
            )
            time.sleep(wait)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Falha ao consultar GitLab sem excecao capturada")


def _buscar_issues_projeto(
    project_id: str,
    gitlab_repo: str,
    gitlab_token: str,
    *,
    updated_after: datetime | None = None,
) -> list[dict]:
    """Busca issues de um projeto via API REST do GitLab."""
    gitlab_url = config.GITLAB_URL if config else os.environ.get("GITLAB_URL", "https://gitlab.com")

    headers = {"PRIVATE-TOKEN": gitlab_token}
    url = f"{gitlab_url}/api/v4/projects/{project_id}/issues"
    params: dict[str, object] = {"scope": "all", "state": "all", "per_page": 100, "page": 1}
    if updated_after is not None:
        params["updated_after"] = format_gitlab_datetime(updated_after)

    issues: list[dict] = []
    while True:
        page = int(params["page"])
        if page == 1 or page % 10 == 0:
            log.info(f"      pagina {page} ({len(issues)} issues ate agora)...")
        response = _get_gitlab_response(url, headers=headers, params=params)
        data = response.json()
        if not data:
            break
        for issue in data:
            issues.append(_mapear_issue_api(issue, gitlab_repo))
        params["page"] = page + 1

    return issues


def buscar_issues_gitlab(
    *,
    updated_after: datetime | None = None,
    repos: list[str] | None = None,
) -> list[dict]:
    """Busca issues de todos os projetos configurados (contratos_v2 + contratos)."""
    configured = _tokens_configurados()
    if not configured:
        raise RuntimeError(
            "Nenhum token GitLab definido. Use GITLAB_TOKEN (global) ou, por repositorio:\n"
            "  GITLAB_TOKEN_CONTRATOS_V2\n"
            "  GITLAB_TOKEN_CONTRATOS\n"
            "Gere tokens em https://gitlab.com/-/user_settings/personal_access_tokens"
        )

    repo_filter = {repo.strip() for repo in (repos or []) if repo and repo.strip()}
    if repo_filter:
        unknown = sorted(repo_filter - {repo for _, repo in _gitlab_projects()})
        if unknown:
            raise ValueError(f"Repositorio(s) desconhecido(s): {', '.join(unknown)}")

    all_issues: list[dict] = []
    for project_id, repo_name in _gitlab_projects():
        if repo_filter and repo_name not in repo_filter:
            continue
        gitlab_token = _gitlab_token_for_repo(repo_name)
        if not gitlab_token:
            log.info(
                f"   -> Pulando {repo_name}: sem token "
                f"(defina GITLAB_TOKEN_{repo_name.upper()} ou GITLAB_TOKEN)"
            )
            continue
        if updated_after is None:
            log.info(f"   -> Buscando {repo_name} ({project_id}) [completo]...")
        else:
            log.info(
                f"   -> Buscando {repo_name} ({project_id}) "
                f"[desde {format_gitlab_datetime(updated_after)}]..."
            )
        project_issues = _buscar_issues_projeto(
            project_id,
            repo_name,
            gitlab_token,
            updated_after=updated_after,
        )
        log.info(f"      {len(project_issues)} issues")
        all_issues.extend(project_issues)

    if not all_issues and updated_after is None:
        raise RuntimeError(
            "Nenhuma issue obtida. Verifique tokens e permissoes de leitura nos projetos."
        )

    return all_issues


def _aplicar_filtro_fechadas(issues: list[dict]) -> tuple[list[dict], int]:
    exclude_days = config.closed_exclude_days() if config else 60
    if config and config.INITIAL_LOAD:
        log.info("OK - Carga inicial: filtro de issues fechadas DESATIVADO (todas incluidas)")
    filtered, excluidas = filtrar_issues_fechadas_antigas(issues, days=exclude_days)
    if excluidas:
        log.info(
            f"OK - {excluidas} issues fechadas ha mais de {exclude_days} dias "
            f"excluidas do JSON ({len(filtered)} restantes)"
        )
    elif exclude_days <= 0:
        log.info(f"OK - JSON com todas as {len(filtered)} issues (sem filtro de fechadas)")
    return filtered, excluidas


def _salvar_issues(
    destino: Path,
    issues: list[dict],
    *,
    mode: str,
    stats: dict[str, int] | None = None,
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
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

    log.info(f"OK - Arquivo salvo: {destino}")
    log.info(f"OK - Estado de sync: {state_path}")
    log.info(f"OK - Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")


def _ensure_tokens(destino: Path) -> bool:
    configured = _tokens_configurados()
    if configured:
        log.info(f"OK - Tokens configurados para: {', '.join(configured)}")
        return True

    log.warning("AVISO: Nenhum token GitLab definido.")
    log.warning('        Global:  setx GITLAB_TOKEN "<token>"')
    log.warning('        Por repo: setx GITLAB_TOKEN_CONTRATOS_V2 "<token>"')
    log.warning('                  setx GITLAB_TOKEN_CONTRATOS "<token>"')
    log.warning("        Continuando com gitlab_issues_raw.json existente.")
    validar_json_local(destino)
    return False


def atualizar_issues(
    output_file: str | None = None,
    *,
    dry_run: bool = False,
    repos: list[str] | None = None,
    skip_merge_dates: bool = False,
    skip_epicos: bool = False,
) -> bool:
    """Carga completa: substitui gitlab_issues_raw.json a partir da API GitLab."""
    destino = _output_path(output_file)
    repo_filter = [repo.strip() for repo in (repos or []) if repo and repo.strip()]

    log.info("\n" + "=" * 70)
    log.info("ATUALIZADOR DE ISSUES - GitLab [MODO COMPLETO]")
    log.info("=" * 70)

    if not _ensure_tokens(destino):
        return False

    try:
        fetched = buscar_issues_gitlab(repos=repo_filter or None)
    except ImportError:
        log.error("Erro: requests nao instalado. Execute: pip install requests")
        validar_json_local(destino)
        return False
    except Exception as exc:
        log.error(f"Erro ao conectar ao GitLab: {exc}")
        validar_json_local(destino)
        return False

    if repo_filter and destino.exists():
        indexed = index_issues_by_key(load_issues_list(destino))
        for repo_name in repo_filter:
            repo_issues = [issue for issue in fetched if issue.get("gitlab_repo") == repo_name]
            removed = replace_repo_issues_in_index(indexed, repo_issues, repo_name)
            log.info(
                f"OK - Merge parcial: {repo_name} substituiu {removed} issues antigas "
                f"por {len(repo_issues)} novas"
            )
        issues = list(indexed.values())
    else:
        issues = fetched

    by_repo: dict[str, int] = {}
    for issue in issues:
        repo = issue.get("gitlab_repo", "?")
        by_repo[repo] = by_repo.get(repo, 0) + 1

    log.info(f"OK - {len(issues)} issues extraidas do GitLab (usando IID + repositorio)")
    for repo, count in sorted(by_repo.items()):
        log.info(f"     • {repo}: {count}")

    issues, excluidas = _aplicar_filtro_fechadas(issues)
    if excluidas:
        log.warning(
            f"AVISO - {excluidas} issues fechadas excluidas do JSON "
            f"(MGI_CLOSED_EXCLUDE_DAYS={os.environ.get('MGI_CLOSED_EXCLUDE_DAYS', '?')})"
        )
    else:
        log.info(
            f"OK - Filtro fechadas: nenhuma excluida "
            f"(MGI_CLOSED_EXCLUDE_DAYS={os.environ.get('MGI_CLOSED_EXCLUDE_DAYS', '?')})"
        )

    if skip_epicos:
        log.info("OK - Catalogo de epicos ignorado (--sem-epicos); use backfill apos sync")
    else:
        try:
            coletar_e_salvar_epicos(issues=issues, dry_run=dry_run)
        except Exception as exc:
            log.warning(f"AVISO - falha ao coletar epicos do grupo: {exc}")

    try:
        if skip_merge_dates:
            log.info("OK - Datas de merge ignoradas (--sem-merge-dates)")
        else:
            enriquecer_issues_com_merge_dates(issues, repos=repo_filter or None)
    except Exception as exc:
        log.warning(f"AVISO - falha ao coletar datas de merge: {exc}")

    if dry_run:
        log.info(f"OK - Dry-run: {len(issues)} issues seriam gravadas (modo completo)")
        return True

    _salvar_issues(destino, issues, mode="full", stats={"fetched": len(issues)})
    return True


def atualizar_issues_incremental(
    output_file: str | None = None,
    *,
    since: str | None = None,
    dry_run: bool = False,
    skip_merge_dates: bool = False,
    skip_epicos: bool = False,
) -> bool:
    """Sync incremental: novas issues + alteracoes desde a ultima sync (merge local)."""
    destino = _output_path(output_file)
    state_path = _sync_state_path(destino)

    log.info("\n" + "=" * 70)
    log.info("ATUALIZADOR DE ISSUES - GitLab [MODO INCREMENTAL]")
    log.info("=" * 70)

    if not destino.exists():
        log.error(f"ERRO: JSON local nao encontrado: {destino}")
        log.info("       Rode primeiro: python atualizar_gitlab_issues.py --full")
        return False

    if not _ensure_tokens(destino):
        return False

    local_issues = load_issues_list(destino)
    indexed = index_issues_by_key(local_issues)
    log.info(f"OK - Issues locais carregadas: {len(indexed)}")

    try:
        watermark = compute_sync_watermark(indexed, state_path, since_override=since)
    except ValueError as exc:
        log.error(f"ERRO: {exc}")
        return False

    log.info(f"OK - Buscando alteracoes desde: {format_gitlab_datetime(watermark)}")

    try:
        fetched = buscar_issues_gitlab(updated_after=watermark)
    except ImportError:
        log.error("Erro: requests nao instalado. Execute: pip install requests")
        return False
    except Exception as exc:
        log.error(f"Erro ao conectar ao GitLab: {exc}")
        return False

    added, updated = merge_issues_into_index(indexed, fetched)
    unchanged = len(indexed) - added - updated
    merged = list(indexed.values())

    log.info(f"OK - API retornou {len(fetched)} issues")
    log.info(f"OK - Novas: {added} | Atualizadas: {updated} | Sem alteracao: {unchanged}")

    merged, removed_old_closed = _aplicar_filtro_fechadas(merged)
    if removed_old_closed:
        log.info(f"OK - {removed_old_closed} issues removidas do JSON por filtro de fechadas")

    try:
        if skip_epicos:
            log.info("OK - Epicos ignorados (--sem-epicos)")
        else:
            coletar_e_salvar_epicos(
                issues=merged,
                dry_run=dry_run,
                api_scope=fetched,
            )
    except Exception as exc:
        log.warning(f"AVISO - falha ao coletar epicos do grupo: {exc}")

    try:
        if skip_merge_dates:
            log.info("OK - Datas de merge ignoradas (--sem-merge-dates)")
        else:
            merge_scope = _issues_para_enriquecer_merge(merged, changed_issues=fetched)
            log.info(
                "OK - Enriquecimento mergeado_em: %d issues candidatas "
                "(alteradas ou sem data, de %d no JSON)",
                len(merge_scope),
                len(merged),
            )
            enriquecer_issues_com_merge_dates(merged, only_issues=merge_scope)
    except Exception as exc:
        log.warning(f"AVISO - falha ao coletar datas de merge: {exc}")

    if dry_run:
        log.info(
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
    )
    return True


def enriquecer_merge_dates_local(
    output_file: str | None = None,
    *,
    dry_run: bool = False,
) -> bool:
    """Preenche mergeado_em no JSON local para todas as issues com MR (todos os repos)."""
    destino = _output_path(output_file)

    log.info("\n" + "=" * 70)
    log.info("ENRIQUECIMENTO - mergeado_em no JSON local")
    log.info("=" * 70)

    if not destino.exists():
        log.error(f"ERRO: JSON local nao encontrado: {destino}")
        return False

    issues = load_issues_list(destino)
    if not issues:
        log.error("ERRO: JSON sem issues")
        return False

    log.info(
        f"OK - {len(issues)} issues no JSON "
        f"(MGI_CLOSED_EXCLUDE_DAYS={os.environ.get('MGI_CLOSED_EXCLUDE_DAYS', '?')})"
    )
    try:
        filled = enriquecer_issues_com_merge_dates(issues, repos=None)
    except Exception as exc:
        log.error(f"Erro ao enriquecer mergeado_em: {exc}")
        return False

    if dry_run:
        log.info(f"OK - Dry-run: {filled} issues teriam mergeado_em preenchido")
        return True

    _salvar_issues(destino, issues, mode="merge_dates", stats={"merge_dates_filled": filled})
    return True


def validar_json_local(json_path: Path | None = None) -> None:
    """Emite aviso se o JSON local parecer dados de teste."""
    path = json_path or _output_path()
    if not path.exists():
        return
    issues = load_issues_list(path)
    if json_parece_sintetico(issues):
        log.info("\n" + "!" * 70)
        log.warning("AVISO: gitlab_issues_raw.json parece conter DADOS DE TESTE,")
        log.info("       nao issues reais do GitLab!")
        log.info("       Defina GITLAB_TOKEN (ou tokens por repo) e rode:")
        log.info("       python atualizar_gitlab_issues.py --full")
        log.warning("!" * 70 + "\n")
        amostra = next((i for i in issues if i.get("id") == "1289"), None)
        if amostra:
            log.info(f"   Exemplo #1289 no JSON local: {amostra.get('title', '')[:80]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sincroniza issues GitLab -> gitlab_issues_raw.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python atualizar_gitlab_issues.py              # incremental (se JSON existir)\n"
            "  python atualizar_gitlab_issues.py -i           # incremental explicito\n"
            "  python atualizar_gitlab_issues.py --full       # carga completa\n"
            "  python atualizar_gitlab_issues.py --full --repo contratos_v2\n"
            "  python atualizar_gitlab_issues.py --full --repo contratos  # merge no JSON existente\n"
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
        "--repo",
        action="append",
        metavar="SLUG",
        choices=["contratos_v2", "contratos"],
        help="limita a sync a um repositorio (pode repetir). Com --full, faz merge no JSON existente",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="simula a sync sem gravar arquivos",
    )
    parser.add_argument(
        "--sem-merge-dates",
        action="store_true",
        help="nao busca mergeado_em via API de MRs (evita timeouts em carga parcial)",
    )
    parser.add_argument(
        "--enriquecer-merge-dates",
        action="store_true",
        help="apenas preenche mergeado_em no JSON local (todas as issues com MR)",
    )
    parser.add_argument(
        "--sem-epicos",
        action="store_true",
        help="nao coleta epicos ao atualizar JSON (use backfill apos sync)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    destino = _output_path(args.output)

    if args.enriquecer_merge_dates:
        success = enriquecer_merge_dates_local(args.output, dry_run=args.dry_run)
    elif args.full:
        success = atualizar_issues(
            args.output,
            dry_run=args.dry_run,
            repos=args.repo,
            skip_merge_dates=args.sem_merge_dates,
            skip_epicos=args.sem_epicos,
        )
    elif args.incremental or destino.exists():
        if args.since and not args.incremental and not destino.exists():
            parser.error("--since requer sync incremental e JSON local existente")
        if args.repo:
            parser.error("--repo so e suportado com --full no momento")
        success = atualizar_issues_incremental(
            args.output,
            since=args.since,
            dry_run=args.dry_run,
            skip_merge_dates=args.sem_merge_dates,
            skip_epicos=args.sem_epicos,
        )
    else:
        log.info("JSON local ausente — iniciando carga completa (--full)...")
        success = atualizar_issues(
            args.output,
            dry_run=args.dry_run,
            repos=args.repo,
            skip_merge_dates=args.sem_merge_dates,
            skip_epicos=args.sem_epicos,
        )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
