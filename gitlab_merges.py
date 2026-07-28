"""Data de merge das issues via API GitLab (Merge Requests).

Para cada issue com MR relacionado, busca os merge requests vinculados e usa o
maior `merged_at` entre os MRs no estado `merged` como `mergeado_em` da issue.
Fonte: GET /projects/:id/issues/:iid/related_merge_requests.
"""

from __future__ import annotations

import os
from typing import Any

from logging_utils import get_logger

log = get_logger(__name__)

try:
    import config
except ImportError:
    config = None

DEFAULT_PROJECT_ID = "comprasnet%2Fcontratos_v2"


def _gitlab_url() -> str:
    if config and getattr(config, "GITLAB_URL", None):
        return str(config.GITLAB_URL).rstrip("/")
    return os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")


def _normalize_repo(repo: str) -> str:
    """Aceita slug (`contratos_v2`) ou display name (`Contratos v2`)."""
    raw = (repo or "").strip()
    key = raw.lower().replace(" ", "_")
    aliases = {
        "contratos_v2": "contratos_v2",
        "contratos_v1": "contratos",
        "contratos": "contratos",
        "comprasnet/contratos_v2": "contratos_v2",
        "comprasnet/contratos": "contratos",
    }
    return aliases.get(key, raw or "contratos_v2")


def _repo_project_map() -> dict[str, str]:
    """Mapa repo_slug -> project_id (URL-encoded)."""
    if config and getattr(config, "GITLAB_PROJECTS", None):
        return {repo: pid for pid, repo in config.GITLAB_PROJECTS}
    return {"contratos_v2": DEFAULT_PROJECT_ID, "contratos": "comprasnet%2Fcontratos"}


def _token_for_repo(repo: str) -> str:
    slug = _normalize_repo(repo)
    if config and hasattr(config, "gitlab_token_for_repo"):
        return config.gitlab_token_for_repo(slug) or ""
    if slug == "contratos":
        return (
            os.environ.get("GITLAB_TOKEN_CONTRATOS", "")
            or os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", "")
            or os.environ.get("GITLAB_TOKEN", "")
        )
    return (
        os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", "")
        or os.environ.get("GITLAB_TOKEN_CONTRATOS", "")
        or os.environ.get("GITLAB_TOKEN", "")
    )


def _iid_of(issue: dict) -> int | None:
    raw = str(issue.get("id", "")).strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _mr_count(issue: dict) -> int:
    try:
        return int(issue.get("merge_requests_count") or 0)
    except (TypeError, ValueError):
        return 0


def _related_mrs_merged_ats(
    iid: int,
    slug: str,
    *,
    token: str | None,
    session,
    timeout: float,
) -> tuple[str | None, int]:
    """Retorna (max_merged_at|None, http_status). status 0 = erro de rede."""
    import requests

    pid = _repo_project_map().get(slug, DEFAULT_PROJECT_ID)
    auth = token if token is not None else _token_for_repo(slug)
    headers = {"PRIVATE-TOKEN": auth} if auth else {}
    getter = session.get if session is not None else requests.get
    url = f"{_gitlab_url()}/api/v4/projects/{pid}/issues/{iid}/related_merge_requests"
    try:
        response = getter(url, headers=headers, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        log.warning("AVISO - falha ao buscar MRs da issue %s/%s: %s", slug, iid, exc)
        return None, 0
    if response.status_code == 404:
        return None, 404
    if not response.ok:
        log.warning(
            "AVISO - related_merge_requests %s/%s status %s", slug, iid, response.status_code
        )
        return None, response.status_code

    datas = [
        (mr.get("merged_at") or "").strip()
        for mr in response.json()
        if (mr.get("state") == "merged") and (mr.get("merged_at"))
    ]
    return (max(datas) if datas else None), response.status_code


def merged_at_for_issue(
    iid: int,
    repo: str,
    *,
    token: str | None = None,
    session=None,
    timeout: float = 20,
) -> str | None:
    """Maior `merged_at` entre os MRs mergeados vinculados a uma issue (ISO) ou None.

    Se o projeto rotulado retornar 404 (issues com gitlab_repo incorreto no banco),
    tenta o outro projeto conhecido (contratos <-> contratos_v2).
    """
    import requests

    if session is None:
        session = requests.Session()

    slug = _normalize_repo(repo)
    data, status = _related_mrs_merged_ats(iid, slug, token=token, session=session, timeout=timeout)
    if status != 404:
        return data

    fallback = "contratos" if slug == "contratos_v2" else "contratos_v2"
    data_fb, status_fb = _related_mrs_merged_ats(
        iid, fallback, token=token, session=session, timeout=timeout
    )
    if status_fb == 200:
        return data_fb
    return None


def enriquecer_issues_com_merge_dates(
    issues: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> int:
    """Preenche `issue['mergeado_em']` para issues com MR. Retorna quantas foram preenchidas."""
    import requests

    session = requests.Session()
    filled = 0
    candidatas = [i for i in issues if _mr_count(i) > 0 and _iid_of(i) is not None]
    log.info("OK - Buscando datas de merge de %d issues com MR...", len(candidatas))
    for index, issue in enumerate(candidatas, start=1):
        iid = _iid_of(issue)
        repo = _normalize_repo(issue.get("gitlab_repo") or "contratos_v2")
        data = merged_at_for_issue(iid, repo, token=token, session=session)
        if data:
            issue["mergeado_em"] = data
            filled += 1
        if index % 50 == 0:
            log.info("OK - %d/%d issues verificadas para merge", index, len(candidatas))
    log.info("OK - %d issues com data de merge", filled)
    return filled
