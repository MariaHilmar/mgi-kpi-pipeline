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
    global_token = os.environ.get("GITLAB_TOKEN", "").strip()
    if global_token:
        return global_token
    if slug == "contratos":
        return os.environ.get("GITLAB_TOKEN_CONTRATOS", "").strip()
    return os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", "").strip()


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
    retries: int = 1,
    retry_delay: float = 5.0,
) -> tuple[str | None, int]:
    """Retorna (max_merged_at|None, http_status). status 0 = erro de rede."""
    import time

    import requests

    pid = _repo_project_map().get(slug, DEFAULT_PROJECT_ID)
    auth = token if token is not None else _token_for_repo(slug)
    headers = {"PRIVATE-TOKEN": auth} if auth else {}
    getter = session.get if session is not None else requests.get
    url = f"{_gitlab_url()}/api/v4/projects/{pid}/issues/{iid}/related_merge_requests"
    last_exc: Exception | None = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            response = getter(url, headers=headers, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                log.warning("AVISO - falha ao buscar MRs da issue %s/%s: %s", slug, iid, exc)
                return None, 0
            time.sleep(retry_delay * attempt)
            continue
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
    if last_exc is not None:
        log.warning("AVISO - falha ao buscar MRs da issue %s/%s: %s", slug, iid, last_exc)
    return None, 0


def merged_at_for_issue(
    iid: int,
    repo: str,
    *,
    token: str | None = None,
    session=None,
    timeout: float | None = None,
    retries: int = 1,
    retry_delay: float = 5.0,
) -> str | None:
    """Maior `merged_at` entre os MRs mergeados vinculados a uma issue (ISO) ou None.

    Se o projeto rotulado retornar 404 (issues com gitlab_repo incorreto no banco),
    tenta o outro projeto conhecido (contratos <-> contratos_v2).
    """
    import os

    import requests

    if timeout is None:
        timeout = float(os.environ.get("MGI_GITLAB_HTTP_TIMEOUT", "120"))
    if retries <= 1:
        retries = max(1, int(os.environ.get("MGI_GITLAB_HTTP_RETRIES", "3")))

    if session is None:
        session = requests.Session()

    slug = _normalize_repo(repo)
    data, status = _related_mrs_merged_ats(
        iid,
        slug,
        token=token,
        session=session,
        timeout=timeout,
        retries=retries,
        retry_delay=retry_delay,
    )
    if status != 404:
        return data

    fallback = "contratos" if slug == "contratos_v2" else "contratos_v2"
    data_fb, status_fb = _related_mrs_merged_ats(
        iid,
        fallback,
        token=token,
        session=session,
        timeout=timeout,
        retries=retries,
        retry_delay=retry_delay,
    )
    if status_fb == 200:
        return data_fb
    return None


def _has_mergeado_em(issue: dict) -> bool:
    value = issue.get("mergeado_em")
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def enriquecer_issues_com_merge_dates(
    issues: list[dict[str, Any]],
    *,
    token: str | None = None,
    repos: list[str] | None = None,
    only_issues: list[dict[str, Any]] | None = None,
    skip_if_present: bool = True,
) -> int:
    """Preenche `issue['mergeado_em']` para issues com MR. Retorna quantas foram preenchidas."""
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import requests

    repo_filter = {_normalize_repo(repo) for repo in (repos or []) if repo and repo.strip()}
    timeout = float(os.environ.get("MGI_GITLAB_HTTP_TIMEOUT", "120"))
    retries = max(1, int(os.environ.get("MGI_GITLAB_HTTP_RETRIES", "3")))
    retry_delay = float(os.environ.get("MGI_GITLAB_HTTP_RETRY_DELAY", "5"))
    workers = max(1, min(int(os.environ.get("MGI_GITLAB_MERGE_WORKERS", "10")), 30))

    source = only_issues if only_issues is not None else issues
    candidatas = []
    skipped = 0
    for issue in source:
        if _mr_count(issue) <= 0 or _iid_of(issue) is None:
            continue
        if skip_if_present and _has_mergeado_em(issue):
            skipped += 1
            continue
        repo = _normalize_repo(issue.get("gitlab_repo") or "contratos_v2")
        if repo_filter and repo not in repo_filter:
            continue
        candidatas.append(issue)

    if skipped:
        log.info("OK - %d issues com mergeado_em ja preenchido (puladas)", skipped)

    log.info(
        "OK - Buscando datas de merge de %d issues com MR (%d workers)...",
        len(candidatas),
        workers,
    )

    # Sessao por thread: requests.Session nao e garantidamente thread-safe.
    _local = threading.local()

    def _session() -> requests.Session:
        sess = getattr(_local, "session", None)
        if sess is None:
            sess = requests.Session()
            _local.session = sess
        return sess

    def _resolve(issue: dict[str, Any]) -> str | None:
        iid = _iid_of(issue)
        repo = _normalize_repo(issue.get("gitlab_repo") or "contratos_v2")
        return merged_at_for_issue(
            iid,
            repo,
            token=token,
            session=_session(),
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
        )

    filled = 0
    done = 0
    total = len(candidatas)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_issue = {pool.submit(_resolve, issue): issue for issue in candidatas}
        for future in as_completed(future_to_issue):
            issue = future_to_issue[future]
            try:
                data = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("AVISO - falha ao resolver merge da issue %s: %s", _iid_of(issue), exc)
                data = None
            if data:
                issue["mergeado_em"] = data
                filled += 1
            done += 1
            if done % 50 == 0:
                log.info("OK - %d/%d issues verificadas para merge", done, total)
    log.info("OK - %d issues com data de merge", filled)
    return filled
