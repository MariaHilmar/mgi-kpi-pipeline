"""Coleta e mapeamento de epicos GitLab (grupo + vinculo em issues).

Fontes: Parent (work item hierarchy), label, REST `issue.epic`,
`GET /groups/:id/epics`. Ver docs/06-epicos-gitlab.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from logging_utils import get_logger

log = get_logger(__name__)

try:
    import config
except ImportError:
    config = None

EPICS_JSON_FILENAME = "gitlab_epics_raw.json"
DEFAULT_GROUP_PATH = "comprasnet"
PARENT_GRAPHQL_BATCH_SIZE = int(os.environ.get("MGI_PARENT_GRAPHQL_BATCH_SIZE", "15"))
_graphql_schema_warned = False


class GraphQLComplexityError(Exception):
    """Query GraphQL excedeu o limite de complexidade do GitLab."""


def _namespace_full_path_for_repo(repo_slug: str) -> str | None:
    from issue_keys import GITLAB_PROJECT_PATHS, normalize_repo

    return GITLAB_PROJECT_PATHS.get(normalize_repo(repo_slug))


def group_path() -> str:
    if config and getattr(config, "GITLAB_GROUP_PATH", None):
        return str(config.GITLAB_GROUP_PATH)
    return os.environ.get("GITLAB_GROUP_PATH", DEFAULT_GROUP_PATH).strip() or DEFAULT_GROUP_PATH


def epics_json_path(base: Path | None = None) -> Path:
    if base is not None:
        return Path(base)
    if config and getattr(config, "EPICS_JSON", None):
        return Path(config.EPICS_JSON)
    return Path(__file__).resolve().parent / EPICS_JSON_FILENAME


def _gitlab_url() -> str:
    if config and getattr(config, "GITLAB_URL", None):
        return str(config.GITLAB_URL).rstrip("/")
    return os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")


def _any_gitlab_token() -> str:
    env_tokens = [
        os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", ""),
        os.environ.get("GITLAB_TOKEN_CONTRATOS", ""),
        os.environ.get("GITLAB_TOKEN", ""),
    ]
    if config and hasattr(config, "gitlab_token_for_repo"):
        for _, repo in getattr(config, "GITLAB_PROJECTS", []) or []:
            token = config.gitlab_token_for_repo(repo)
            if token:
                return token
    for token in env_tokens:
        if token:
            return token
    return ""


def _gid_to_numeric_id(gid: Any) -> int | None:
    if gid in (None, ""):
        return None
    if isinstance(gid, int):
        return gid
    text = str(gid).strip()
    if text.isdigit():
        return int(text)
    if "/" in text:
        tail = text.rsplit("/", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


def _graphql_post(
    query: str,
    *,
    variables: dict[str, Any] | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    import requests

    auth = token if token is not None else _any_gitlab_token()
    if not auth:
        return None
    headers = {"PRIVATE-TOKEN": auth, "Content-Type": "application/json"}
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        response = requests.post(
            f"{_gitlab_url()}/api/graphql",
            headers=headers,
            json=payload,
            timeout=float(os.environ.get("MGI_GITLAB_GRAPHQL_TIMEOUT", "30")),
        )
        if response.status_code in (401, 403):
            return None
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        log.warning(f"AVISO - falha GraphQL work item parent: {exc}")
        return None
    if body.get("errors"):
        global _graphql_schema_warned
        message = str(body["errors"][0].get("message", body["errors"][0]))
        if "complexity" in message.casefold():
            if not _graphql_schema_warned:
                log.warning(
                    "AVISO - GraphQL excedeu complexidade; reduzindo lote de Parents"
                )
                _graphql_schema_warned = True
            raise GraphQLComplexityError(message)
        if not _graphql_schema_warned:
            log.warning(f"AVISO - GraphQL retornou erros: {body['errors'][:1]}")
            _graphql_schema_warned = True
        return None
    return body.get("data")


def _parse_parent_from_work_item_node(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    for widget in node.get("widgets") or []:
        if not isinstance(widget, dict):
            continue
        parent = widget.get("parent")
        if isinstance(parent, dict):
            title = (parent.get("title") or "").strip()
            if title:
                return parent
    return None


def mapear_parent_work_item(parent: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normaliza o Parent da hierarquia de work items para o formato issue.epic."""
    if not isinstance(parent, dict):
        return None
    title = (parent.get("title") or "").strip()
    if not title:
        return None
    iid = parent.get("iid")
    work_item_type = parent.get("workItemType") or parent.get("work_item_type") or ""
    if isinstance(work_item_type, dict):
        work_item_type = work_item_type.get("name") or work_item_type.get("id") or ""
    return {
        "id": _gid_to_numeric_id(parent.get("id")),
        "iid": int(iid) if str(iid).isdigit() else iid,
        "title": title,
        "url": parent.get("webUrl") or parent.get("web_url") or "",
        "work_item_type": work_item_type,
        "source": "parent",
    }


_PARENT_WIDGET_FIELDS = """
          widgets {
            ... on WorkItemWidgetHierarchy {
              parent {
                id
                iid
                title
                workItemType {
                  name
                }
                webUrl
              }
            }
          }
"""


def buscar_parent_work_item_graphql(
    namespace_full_path: str,
    gitlab_iid: int,
    *,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Consulta Parent via GraphQL (namespace.workItem + WorkItemWidgetHierarchy)."""
    query = (
        """
    query($fullPath: ID!, $iid: String!) {
      namespace(fullPath: $fullPath) {
        workItem(iid: $iid) {
"""
        + _PARENT_WIDGET_FIELDS
        + """
        }
      }
    }
    """
    )
    data = _graphql_post(
        query,
        variables={"fullPath": namespace_full_path, "iid": str(gitlab_iid)},
        token=token,
    )
    if not data:
        return None
    namespace = data.get("namespace") or {}
    work_item = namespace.get("workItem")
    return _parse_parent_from_work_item_node(work_item)


def _fetch_parent_rest_work_item(
    repo_slug: str,
    gitlab_iid: int,
    *,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Fallback REST: GET .../work_items/:iid?features=hierarchy."""
    import requests

    from issue_keys import normalize_repo

    slug = normalize_repo(repo_slug)
    auth = token if token is not None else _any_gitlab_token()
    if not auth:
        return None

    if config and getattr(config, "GITLAB_PROJECTS", None):
        projects = list(config.GITLAB_PROJECTS)
    else:
        projects = [
            ("comprasnet%2Fcontratos_v2", "contratos_v2"),
            ("comprasnet%2Fcontratos", "contratos"),
        ]
    project_by_repo = {normalize_repo(repo): project_id for project_id, repo in projects}
    project_id = project_by_repo.get(slug)
    if not project_id:
        return None

    project_token = _token_for_repo_slug(slug, auth)
    url = (
        f"{_gitlab_url()}/api/v4/projects/{project_id}/work_items/{int(gitlab_iid)}"
        "?features=hierarchy"
    )
    try:
        response = requests.get(url, headers={"PRIVATE-TOKEN": project_token}, timeout=30)
        if response.status_code in (401, 403, 404):
            return None
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    hierarchy = payload.get("hierarchy") if isinstance(payload.get("hierarchy"), dict) else {}
    parent = hierarchy.get("parent")
    if isinstance(parent, dict) and (parent.get("title") or "").strip():
        return parent

    widgets = payload.get("widgets")
    if isinstance(widgets, list):
        for widget in widgets:
            if isinstance(widget, dict) and isinstance(widget.get("parent"), dict):
                parent = widget["parent"]
                if (parent.get("title") or "").strip():
                    return parent
    return None


def _batch_parent_graphql_once(
    namespace_full_path: str,
    gitlab_iids: list[int],
    *,
    token: str | None = None,
) -> dict[int, dict[str, Any]]:
    alias_fields: list[str] = []
    for iid in gitlab_iids:
        alias_fields.append(
            f'wi{iid}: workItem(iid: "{iid}") {{\n'
            + _PARENT_WIDGET_FIELDS
            + "\n}"
        )
    query = (
        "query($fullPath: ID!) {\n"
        "  namespace(fullPath: $fullPath) {\n"
        + "\n".join(alias_fields)
        + "\n  }\n}"
    )
    data = _graphql_post(query, variables={"fullPath": namespace_full_path}, token=token)
    if not data:
        return {}

    namespace = data.get("namespace") or {}
    found: dict[int, dict[str, Any]] = {}
    for iid in gitlab_iids:
        node = namespace.get(f"wi{iid}")
        parent = _parse_parent_from_work_item_node(node)
        if parent:
            found[iid] = parent
    return found


def _batch_parent_graphql(
    namespace_full_path: str,
    gitlab_iids: list[int],
    *,
    token: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Busca Parents em lote (aliases GraphQL). Retorna mapa iid -> parent raw."""
    if not gitlab_iids:
        return {}

    if len(gitlab_iids) > PARENT_GRAPHQL_BATCH_SIZE:
        found: dict[int, dict[str, Any]] = {}
        for offset in range(0, len(gitlab_iids), PARENT_GRAPHQL_BATCH_SIZE):
            chunk = gitlab_iids[offset : offset + PARENT_GRAPHQL_BATCH_SIZE]
            found.update(_batch_parent_graphql(namespace_full_path, chunk, token=token))
        return found

    try:
        return _batch_parent_graphql_once(namespace_full_path, gitlab_iids, token=token)
    except GraphQLComplexityError:
        if len(gitlab_iids) == 1:
            iid = gitlab_iids[0]
            parent = buscar_parent_work_item_graphql(
                namespace_full_path, iid, token=token
            )
            if not parent:
                return {}
            return {iid: parent}
        mid = len(gitlab_iids) // 2
        left = _batch_parent_graphql(namespace_full_path, gitlab_iids[:mid], token=token)
        right = _batch_parent_graphql(namespace_full_path, gitlab_iids[mid:], token=token)
        return {**left, **right}


def _fetch_epic_rest_issue(
    repo_slug: str,
    gitlab_iid: int,
    *,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Fallback REST: objeto issue.epic da API de issues."""
    import requests

    from issue_keys import normalize_repo

    slug = normalize_repo(repo_slug)
    auth = token if token is not None else _any_gitlab_token()
    if not auth:
        return None

    if config and getattr(config, "GITLAB_PROJECTS", None):
        projects = list(config.GITLAB_PROJECTS)
    else:
        projects = [
            ("comprasnet%2Fcontratos_v2", "contratos_v2"),
            ("comprasnet%2Fcontratos", "contratos"),
        ]
    project_by_repo = {normalize_repo(repo): project_id for project_id, repo in projects}
    project_id = project_by_repo.get(slug)
    if not project_id:
        return None

    project_token = _token_for_repo_slug(slug, auth)
    url = f"{_gitlab_url()}/api/v4/projects/{project_id}/issues/{int(gitlab_iid)}"
    try:
        response = requests.get(
            url, headers={"PRIVATE-TOKEN": project_token}, timeout=30
        )
        if response.status_code in (401, 403, 404):
            return None
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    epic = mapear_epic_api(payload.get("epic"), payload.get("epic_iid"))
    if isinstance(epic, dict) and (epic.get("title") or "").strip():
        epic["source"] = "rest_epic"
        return epic
    return None


def resolver_epico_issue_api(
    repo_slug: str,
    gitlab_iid: int,
    *,
    token: str | None = None,
    use_graphql: bool = True,
) -> dict[str, Any] | None:
    """Resolve epico: Parent (GraphQL/REST) e depois REST issue.epic."""
    slug = _namespace_full_path_for_repo(repo_slug)
    auth = token if token is not None else _any_gitlab_token()
    if not auth:
        return None

    parent: dict[str, Any] | None = None
    if use_graphql and slug:
        parent = buscar_parent_work_item_graphql(slug, int(gitlab_iid), token=auth)
    if not parent:
        parent = _fetch_parent_rest_work_item(repo_slug, int(gitlab_iid), token=auth)
    epic = mapear_parent_work_item(parent)
    if epic:
        return epic

    from issue_keys import normalize_repo

    return _fetch_epic_rest_issue(normalize_repo(repo_slug), int(gitlab_iid), token=auth)


def enriquecer_epicos_via_rest_fallback(
    issues: list[dict[str, Any]],
    *,
    token: str | None = None,
    max_workers: int = 8,
) -> int:
    """Fallback REST paralelo: work_items/hierarchy e depois issue.epic."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from issue_fields import extract_epico
    from issue_keys import get_gitlab_repo, normalize_repo

    pending = [issue for issue in issues if not extract_epico(issue)]
    if not pending:
        return 0

    fallback_token = token or _any_gitlab_token()
    if not fallback_token:
        log.warning("AVISO - sem token GitLab para REST fallback de epicos")
        return 0

    workers = max(1, min(max_workers, 20))
    total = len(pending)
    filled = 0
    done = 0
    log.info(f"OK - REST paralelo ({workers} workers) para {total} issues...")

    def resolve_one(issue: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        repo_slug = normalize_repo(get_gitlab_repo(issue))
        auth = _token_for_repo_slug(repo_slug, fallback_token)
        epic = resolver_epico_issue_api(
            repo_slug,
            int(issue["id"]),
            token=auth,
            use_graphql=False,
        )
        return issue, epic

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(resolve_one, issue) for issue in pending]
        for future in as_completed(futures):
            done += 1
            try:
                issue, epic = future.result()
            except Exception as exc:
                if done == 1:
                    log.warning(f"AVISO - falha REST fallback: {exc}")
                continue
            if epic:
                issue["epic"] = epic
                filled += 1
            if done % 100 == 0 or done == total:
                log.info(f"OK - REST fallback: {done}/{total}, {filled} com epico")

    return filled


def enriquecer_epicos_via_parent_hierarchy(
    issues: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Preenche issue.epic a partir do Parent (hierarquia work items)."""
    from issue_fields import extract_epico
    from issue_keys import GITLAB_PROJECT_PATHS, get_gitlab_repo, normalize_repo, repo_display_name

    auth = token if token is not None else _any_gitlab_token()
    if not auth:
        return 0, []

    pending_by_repo: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        if extract_epico(issue):
            continue
        raw_iid = issue.get("id")
        if raw_iid in (None, ""):
            continue
        repo_slug = normalize_repo(get_gitlab_repo(issue))
        if repo_slug not in GITLAB_PROJECT_PATHS:
            continue
        pending_by_repo.setdefault(repo_slug, []).append(issue)

    if not pending_by_repo:
        return 0, []

    total_pending = sum(len(items) for items in pending_by_repo.values())
    log.info(
        f"OK - Buscando Parents (work items) para {total_pending} issues via GraphQL..."
    )

    filled = 0
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    processed = 0

    for repo_slug, repo_issues in pending_by_repo.items():
        namespace_path = GITLAB_PROJECT_PATHS[repo_slug]
        iids = [int(issue["id"]) for issue in repo_issues]

        for offset in range(0, len(iids), PARENT_GRAPHQL_BATCH_SIZE):
            batch_iids = iids[offset : offset + PARENT_GRAPHQL_BATCH_SIZE]
            parents = _batch_parent_graphql(namespace_path, batch_iids, token=auth)
            issue_by_iid = {int(issue["id"]): issue for issue in repo_issues}

            for iid, parent_raw in parents.items():
                epic = mapear_parent_work_item(parent_raw)
                if not epic:
                    continue
                issue = issue_by_iid.get(iid)
                if not issue:
                    continue
                issue["work_item_parent"] = parent_raw
                issue["epic"] = epic
                filled += 1
                repo_label = repo_display_name(repo_slug)
                key = (repo_label, iid)
                if key not in seen:
                    seen.add(key)
                    links.append(
                        {
                            "gitlab_group_path": group_path(),
                            "gitlab_repo": repo_label,
                            "gitlab_iid": iid,
                            "gitlab_epic_id": epic.get("id"),
                            "epic_title": epic["title"],
                        }
                    )

            processed += len(batch_iids)
            if processed % 100 == 0 or processed == total_pending:
                log.info(
                    f"OK - Parents GraphQL: {processed}/{total_pending} consultadas, "
                    f"{filled} com epico"
                )

    return filled, links


def mapear_epic_api(epic_obj: dict | None, epic_iid_fallback: Any = None) -> dict[str, Any] | None:
    """Normaliza o objeto `epic` da API de issues para o JSON do pipeline."""
    if not isinstance(epic_obj, dict):
        if epic_iid_fallback in (None, ""):
            return None
        return {
            "id": None,
            "iid": int(epic_iid_fallback)
            if str(epic_iid_fallback).isdigit()
            else epic_iid_fallback,
            "title": "",
            "url": "",
        }
    title = (epic_obj.get("title") or "").strip()
    iid = epic_obj.get("iid") if epic_obj.get("iid") is not None else epic_iid_fallback
    if not title and iid in (None, ""):
        return None
    return {
        "id": epic_obj.get("id"),
        "iid": iid,
        "title": title,
        "url": epic_obj.get("url") or epic_obj.get("web_url") or "",
    }


def mapear_epico_grupo(epic: dict) -> dict[str, Any]:
    """Mapeia um epico de GET /groups/:id/epics para o catalogo local/Supabase."""
    return {
        "gitlab_group_path": group_path(),
        "gitlab_epic_id": int(epic["id"]),
        "gitlab_epic_iid": int(epic["iid"]),
        "title": (epic.get("title") or "").strip(),
        "state": epic.get("state") or "",
        "web_url": epic.get("web_url") or "",
        "parent_iid": epic.get("parent_iid"),
        "work_item_id": epic.get("work_item_id"),
    }


def buscar_epicos_grupo(
    *,
    group: str | None = None,
    token: str | None = None,
    state: str = "all",
) -> list[dict[str, Any]]:
    """Lista epicos do grupo via REST. Grupo publico funciona sem token."""
    import requests

    group_id = group or group_path()
    headers = {}
    auth = token if token is not None else _any_gitlab_token()
    if auth:
        headers["PRIVATE-TOKEN"] = auth

    url = f"{_gitlab_url()}/api/v4/groups/{group_id}/epics"
    params: dict[str, object] = {"per_page": 100, "page": 1, "state": state}
    epics: list[dict[str, Any]] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 401 and headers:
            # Token invalido: tenta novamente como publico.
            log.warning("AVISO - token GitLab rejeitado em /epics; tentando acesso publico")
            headers = {}
            response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        for epic in data:
            mapped = mapear_epico_grupo(epic)
            if mapped["title"]:
                epics.append(mapped)
        params["page"] = int(params["page"]) + 1
    return epics


def _buscar_issues_do_epico(
    epic_iid: int,
    *,
    group: str | None = None,
    token: str | None = None,
) -> list[dict]:
    import requests

    group_id = group or group_path()
    headers = {}
    auth = token if token is not None else _any_gitlab_token()
    if auth:
        headers["PRIVATE-TOKEN"] = auth

    url = f"{_gitlab_url()}/api/v4/groups/{group_id}/epics/{epic_iid}/issues"
    params: dict[str, object] = {"per_page": 100, "page": 1}
    issues: list[dict] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 401:
            if auth:
                raise requests.HTTPError(
                    "401 Unauthorized: GITLAB_TOKEN invalido ou sem permissao para epicos do grupo",
                    response=response,
                )
            raise requests.HTTPError(
                "401 Unauthorized: defina GITLAB_TOKEN no .env com escopo read_api",
                response=response,
            )
        if response.status_code == 404:
            return issues
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        issues.extend(data)
        params["page"] = int(params["page"]) + 1
    return issues


def _repo_label_from_api_issue(child: dict) -> str:
    from issue_keys import DEFAULT_GITLAB_REPO, normalize_repo, repo_display_name

    refs = child.get("references") or {}
    full = str(refs.get("full") or "")
    if "/" in full:
        segment = full.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        if segment:
            return repo_display_name(normalize_repo(segment))

    web = child.get("web_url") or ""
    for slug in ("contratos_v2", "contratos"):
        if f"/{slug}/" in web:
            return repo_display_name(slug)
    return repo_display_name(DEFAULT_GITLAB_REPO)


def _build_epic_link_row(epic: dict, child: dict) -> dict[str, Any] | None:
    iid = child.get("iid")
    if iid is None:
        return None
    title = (epic.get("title") or "").strip()
    if not title:
        return None
    return {
        "gitlab_group_path": epic.get("gitlab_group_path") or group_path(),
        "gitlab_repo": _repo_label_from_api_issue(child),
        "gitlab_iid": int(iid),
        "gitlab_epic_id": epic.get("gitlab_epic_id"),
        "epic_title": title,
    }


def vinculos_epico_de_issues_json(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Monta vinculos issue-epico a partir do JSON local (issue.epic / labels)."""
    from issue_fields import extract_epico
    from issue_keys import get_gitlab_repo, repo_display_name

    links: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for issue in issues:
        title = extract_epico(issue)
        if not title:
            continue
        raw_iid = issue.get("id")
        if raw_iid in (None, ""):
            continue
        repo = repo_display_name(get_gitlab_repo(issue))
        gitlab_iid = int(raw_iid)
        key = (repo, gitlab_iid)
        if key in seen:
            continue
        seen.add(key)
        epic_obj = issue.get("epic") if isinstance(issue.get("epic"), dict) else {}
        links.append(
            {
                "gitlab_group_path": group_path(),
                "gitlab_repo": repo,
                "gitlab_iid": gitlab_iid,
                "gitlab_epic_id": epic_obj.get("id"),
                "epic_title": title,
            }
        )
    return links


def _index_issues_por_repo_iid(
    issues: list[dict[str, Any]],
) -> dict[tuple[str, int], dict[str, Any]]:
    from issue_keys import get_gitlab_repo, repo_display_name

    index: dict[tuple[str, int], dict[str, Any]] = {}
    for issue in issues:
        raw_iid = issue.get("id")
        if raw_iid in (None, ""):
            continue
        repo = repo_display_name(get_gitlab_repo(issue))
        index[(repo, int(raw_iid))] = issue
    return index


def _localizar_issue_filha(
    child: dict[str, Any],
    epic: dict[str, Any],
    by_repo_iid: dict[tuple[str, int], dict[str, Any]],
    by_global: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    link_row = _build_epic_link_row(epic, child)
    if link_row:
        target = by_repo_iid.get((link_row["gitlab_repo"], link_row["gitlab_iid"]))
        if target:
            return target
    global_id = child.get("id")
    if global_id not in (None, ""):
        return by_global.get(str(global_id))
    return None


def enriquecer_epicos_via_filhas_grupo(
    issues: list[dict[str, Any]],
    epics: list[dict[str, Any]],
    *,
    token: str | None = None,
    links: list[dict[str, Any]] | None = None,
    seen_links: set[tuple[str, int]] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Preenche issue.epic a partir das filhas de cada epico do grupo (REST).

    Usa GET /groups/:path/-/epics/:iid/issues - ex.: epico work item #30
    retorna as 29 issues filhas de uma vez.
    """
    from issue_fields import extract_epico

    if not epics:
        return 0, links or []

    by_repo_iid = _index_issues_por_repo_iid(issues)
    by_global = {
        str(issue.get("gitlab_id")): issue
        for issue in issues
        if issue.get("gitlab_id") not in (None, "")
    }
    out_links = links if links is not None else []
    seen = seen_links if seen_links is not None else set()
    auth = token if token is not None else _any_gitlab_token()
    filled = 0

    if not auth:
        return 0, out_links

    log.info(f"OK - Buscando filhas de {len(epics)} epicos do grupo (REST)...")
    for epic in epics:
        epic_iid = epic.get("gitlab_epic_iid")
        title = (epic.get("title") or "").strip()
        if not epic_iid or not title:
            continue
        try:
            children = _buscar_issues_do_epico(int(epic_iid), token=auth)
        except Exception as exc:
            message = str(exc)
            if "401" in message:
                log.warning(
                    "AVISO - GITLAB_TOKEN sem permissao para listar issues dos epicos (401). "
                    "Use um PAT com escopo read_api e acesso ao grupo comprasnet."
                )
                break
            log.warning(f"AVISO - falha ao listar issues do epico #{epic_iid}: {exc}")
            continue

        epic_filled = 0
        for child in children:
            link_row = _build_epic_link_row(epic, child)
            if link_row:
                key = (link_row["gitlab_repo"], link_row["gitlab_iid"])
                if key not in seen:
                    seen.add(key)
                    out_links.append(link_row)

            target = _localizar_issue_filha(child, epic, by_repo_iid, by_global)
            if not target or extract_epico(target):
                continue
            target["epic"] = {
                "id": epic.get("gitlab_epic_id"),
                "iid": epic_iid,
                "title": title,
                "url": epic.get("web_url") or "",
                "source": "epic_children",
            }
            filled += 1
            epic_filled += 1

        if children:
            log.info(
                f"OK - epico #{epic_iid}: {epic_filled}/{len(children)} filhas "
                f"enriquecidas no lote"
            )

    return filled, out_links


def preencher_epicos_filhas_no_supabase(
    *,
    supabase_url: str,
    service_key: str,
    dry_run: bool = False,
    token: str | None = None,
) -> dict[str, Any]:
    """Grava epico em TODAS as filhas de epicos do grupo que existem no Supabase.

    Nao filtra por mergeadas: corrige casos como epico #45 (#2405 fechada sem epico)
    e reporta filhas ausentes do banco (ex.: contratos_v2#1079 do epico #17).
    """
    import requests

    from sync_supabase import SupabaseSync

    epics = buscar_epicos_grupo(token=token)
    auth = token if token is not None else _any_gitlab_token()
    if not auth:
        raise RuntimeError("GITLAB_TOKEN ausente")

    base = supabase_url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    client = SupabaseSync(supabase_url, service_key)

    stats: dict[str, Any] = {
        "preenchidos": 0,
        "ja_ok": 0,
        "fora_sb": 0,
        "por_epico": [],
        "fora_sb_list": [],
        "links": [],
    }
    seen_links: set[tuple[str, int]] = set()

    log.info(f"OK - Sincronizando filhas de {len(epics)} epicos do grupo no Supabase...")
    for epic in epics:
        epic_iid = int(epic["gitlab_epic_iid"])
        title = (epic.get("title") or "").strip()
        if not title:
            continue
        try:
            children = _buscar_issues_do_epico(epic_iid, token=auth)
        except Exception as exc:
            log.warning(f"AVISO - falha ao listar filhas do epico #{epic_iid}: {exc}")
            continue
        if not children:
            continue

        epic_stats = {"epic_iid": epic_iid, "filhas": len(children), "preenchidos": 0, "ja_ok": 0, "fora_sb": 0}

        for child in children:
            link_row = _build_epic_link_row(epic, child)
            if not link_row:
                continue
            repo = link_row["gitlab_repo"]
            iid = link_row["gitlab_iid"]
            key = (repo, iid)
            if key not in seen_links:
                seen_links.add(key)
                stats["links"].append(link_row)

            rows = requests.get(
                f"{base}/issues",
                headers=headers,
                params={
                    "select": "issue_key,epico",
                    "gitlab_repo": f"eq.{repo}",
                    "gitlab_iid": f"eq.{iid}",
                    "limit": 1,
                },
                timeout=60,
            ).json()
            if not rows:
                epic_stats["fora_sb"] += 1
                stats["fora_sb"] += 1
                stats["fora_sb_list"].append(
                    {"epic_iid": epic_iid, "gitlab_repo": repo, "gitlab_iid": iid, "title": title}
                )
                continue

            row = rows[0]
            atual = (row.get("epico") or "").strip()
            if atual == title:
                epic_stats["ja_ok"] += 1
                stats["ja_ok"] += 1
                continue

            epic_stats["preenchidos"] += 1
            stats["preenchidos"] += 1
            if dry_run:
                log.info(f"DRY - {repo}#{iid} -> {title[:60]}")
                continue

            patch = requests.patch(
                f"{base}/issues",
                headers=headers,
                params={"issue_key": f"eq.{row['issue_key']}"},
                json={"epico": title},
                timeout=60,
            )
            if not patch.ok:
                log.warning(
                    f"AVISO - falha ao atualizar {row.get('issue_key')}: {patch.text[:160]}"
                )
                epic_stats["preenchidos"] -= 1
                stats["preenchidos"] -= 1

        stats["por_epico"].append({**epic_stats, "title": title[:55]})
        log.info(
            f"OK - epico #{epic_iid}: {epic_stats['preenchidos']} preenchidas, "
            f"{epic_stats['ja_ok']}/{epic_stats['filhas']} ja ok, "
            f"{epic_stats['fora_sb']} fora do Supabase"
        )

    if not dry_run and stats["links"]:
        try:
            count = client.upsert_gitlab_epic_issue_links(stats["links"])
            log.info(f"OK - {count} vinculos issue-epico sincronizados")
        except Exception as exc:
            log.warning(f"AVISO - vinculos nao gravados ({exc})")

    return stats


def aplicar_epicos_em_issues(
    issues: list[dict[str, Any]],
    epics: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Preenche issue.epic e devolve linhas para gitlab_epic_issue_links."""
    filled = 0
    links: list[dict[str, Any]] = []
    seen_links: set[tuple[str, int]] = set()

    for link_row in vinculos_epico_de_issues_json(issues):
        key = (link_row["gitlab_repo"], link_row["gitlab_iid"])
        if key in seen_links:
            continue
        seen_links.add(key)
        links.append(link_row)

    if links:
        log.info(f"OK - {len(links)} vinculos issue-epico do JSON local")

    auth = token if token is not None else _any_gitlab_token()

    children_filled, links = enriquecer_epicos_via_filhas_grupo(
        issues,
        epics,
        token=auth or None,
        links=links,
        seen_links=seen_links,
    )
    filled += children_filled

    parent_filled, parent_links = enriquecer_epicos_via_parent_hierarchy(
        issues, token=auth or None
    )
    filled += parent_filled
    for link_row in parent_links:
        key = (link_row["gitlab_repo"], link_row["gitlab_iid"])
        if key in seen_links:
            continue
        seen_links.add(key)
        links.append(link_row)

    extra_filled, extra_links = enriquecer_epicos_via_projetos(issues, token=auth or None)
    filled += extra_filled
    for link_row in extra_links:
        key = (link_row["gitlab_repo"], link_row["gitlab_iid"])
        if key in seen_links:
            continue
        seen_links.add(key)
        links.append(link_row)

    return filled, links


def _token_for_repo_slug(repo_slug: str, fallback: str) -> str:
    if config and hasattr(config, "gitlab_token_for_repo"):
        token = config.gitlab_token_for_repo(repo_slug)
        if token:
            return token
    return fallback


def enriquecer_epicos_via_projetos(
    issues: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Busca epic issue a issue via REST (fallback apos Parent em lote)."""
    from issue_fields import extract_epico
    from issue_keys import get_gitlab_repo, normalize_repo, repo_display_name

    if config and getattr(config, "GITLAB_PROJECTS", None):
        projects = list(config.GITLAB_PROJECTS)
    else:
        projects = [
            ("comprasnet%2Fcontratos_v2", "contratos_v2"),
            ("comprasnet%2Fcontratos", "contratos"),
        ]

    project_by_repo = {normalize_repo(repo): project_id for project_id, repo in projects}
    fallback = token or _any_gitlab_token()
    pending = [issue for issue in issues if not extract_epico(issue)]
    if not pending:
        return 0, []

    if not fallback and not any(
        _token_for_repo_slug(normalize_repo(repo), "") for _, repo in projects
    ):
        log.warning("AVISO - sem token GitLab para enriquecer epicos via projetos")
        return 0, []

    workers = max(1, min(int(os.environ.get("MGI_GITLAB_EPIC_WORKERS", "12")), 30))
    log.info(
        f"OK - Buscando epicos via API de projetos para {len(pending)} issues "
        f"({workers} workers)..."
    )
    filled = 0
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _resolve(issue: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        repo_slug = normalize_repo(get_gitlab_repo(issue))
        project_id = project_by_repo.get(repo_slug)
        raw_iid = issue.get("id")
        if not project_id or raw_iid in (None, ""):
            return issue, None
        auth = _token_for_repo_slug(repo_slug, fallback)
        if not auth:
            return issue, None
        return issue, _fetch_epic_rest_issue(repo_slug, int(raw_iid), token=auth)

    done = 0
    total = len(pending)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_resolve, issue) for issue in pending]
        for future in as_completed(futures):
            done += 1
            try:
                issue, epic = future.result()
            except Exception:  # noqa: BLE001
                epic = None
                issue = None
            if isinstance(epic, dict) and (epic.get("title") or "").strip():
                title = epic["title"].strip()
                issue["epic"] = epic
                filled += 1
                repo_slug = normalize_repo(get_gitlab_repo(issue))
                repo_label = repo_display_name(repo_slug)
                gitlab_iid = int(issue["id"])
                key = (repo_label, gitlab_iid)
                if key not in seen:
                    seen.add(key)
                    links.append(
                        {
                            "gitlab_group_path": group_path(),
                            "gitlab_repo": repo_label,
                            "gitlab_iid": gitlab_iid,
                            "gitlab_epic_id": epic.get("id"),
                            "epic_title": title,
                        }
                    )
            if done % 200 == 0 or done == total:
                log.info(
                    f"OK - epicos via projeto: {done}/{total} consultadas, {filled} preenchidas"
                )

    return filled, links


def enriquecer_issues_com_epicos(
    issues: list[dict[str, Any]],
    epics: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> int:
    """Preenche `issue.epic` a partir das issues filhas de cada epico do grupo.

    Util quando o list/get de issues nao traz `epic`, mas o vinculo existe no
    endpoint de epicos. Retorna quantas issues receberam epico.
    """
    filled, _links = aplicar_epicos_em_issues(issues, epics, token=token)
    return filled


def salvar_epicos(epics: list[dict[str, Any]], path: Path | None = None) -> Path:
    destino = epics_json_path(path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as handle:
        json.dump(epics, handle, indent=2, ensure_ascii=False)
    return destino


def carregar_epicos(path: Path | None = None) -> list[dict[str, Any]]:
    destino = epics_json_path(path)
    if not destino.exists():
        return []
    with open(destino, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("epics"), list):
        return data["epics"]
    return []


def coletar_e_salvar_epicos(
    *,
    issues: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Busca epicos do grupo, opcionalmente enriquece issues e grava JSON."""
    log.info(f"OK - Buscando epicos do grupo {group_path()}...")
    epics = buscar_epicos_grupo()
    log.info(f"OK - {len(epics)} epicos obtidos")
    if issues is not None:
        filled = enriquecer_issues_com_epicos(issues, epics)
        if filled:
            log.info(f"OK - {filled} issues enriquecidas com epico via catalogo do grupo")
        else:
            log.info("OK - Nenhuma issue filha vinculada aos epicos do grupo (catalogo apenas)")
    if not dry_run:
        destino = salvar_epicos(epics)
        log.info(f"OK - Catalogo de epicos salvo: {destino}")
    return epics
