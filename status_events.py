#!/usr/bin/env python3
"""Coleta eventos de label `status::` do GitLab (resource_label_events) → Supabase."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import requests

from flow_stages import flow_map_etapa, parse_status_label
from issue_fields import map_estado
from issue_keys import get_gitlab_repo, normalize_repo, repo_display_name

try:
    import config as _config
except ImportError:
    _config = None

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_UPSERT_EVERY_ISSUES = 50
DEFAULT_PROGRESS_EVERY = 50
_thread_local = threading.local()


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log_stage(message: str) -> None:
    """Log com horario local (HH:MM:SS)."""
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {secs}s"


def _gitlab_url() -> str:
    if _config and getattr(_config, "GITLAB_URL", None):
        return _config.GITLAB_URL.rstrip("/")
    return os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")


def _gitlab_projects() -> List[Tuple[str, str]]:
    if _config and getattr(_config, "GITLAB_PROJECTS", None):
        return list(_config.GITLAB_PROJECTS)
    return [
        ("comprasnet%2Fcontratos_v2", "contratos_v2"),
        ("comprasnet%2Fcontratos", "contratos"),
    ]


def _project_id_for_repo(repo_slug: str) -> Optional[str]:
    slug = normalize_repo(repo_slug)
    for project_id, repo_name in _gitlab_projects():
        if repo_name == slug:
            return project_id
    return None


def _gitlab_token_for_repo(repo_slug: str) -> str:
    slug = normalize_repo(repo_slug)
    if _config and hasattr(_config, "gitlab_token_for_repo"):
        return _config.gitlab_token_for_repo(slug)
    by_repo = {
        "contratos_v2": os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", ""),
        "contratos": os.environ.get("GITLAB_TOKEN_CONTRATOS", ""),
    }
    return by_repo.get(slug) or os.environ.get("GITLAB_TOKEN", "")


def issue_key_from_raw_issue(issue: Dict[str, Any]) -> Optional[str]:
    iid = str(issue.get("id", "")).strip()
    if not iid:
        return None
    repo_slug = get_gitlab_repo(issue)
    return f"{repo_display_name(repo_slug)}:{iid}"


def is_status_events_sync_enabled() -> bool:
    return os.environ.get("MGI_SYNC_STATUS_EVENTS", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def status_events_issue_limit() -> int:
    raw = os.environ.get("MGI_STATUS_EVENTS_ISSUE_LIMIT", "0").strip()
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


def status_events_workers() -> int:
    raw = os.environ.get("MGI_STATUS_EVENTS_WORKERS", "8").strip()
    try:
        return max(int(raw), 1)
    except ValueError:
        return 8


def _get_http_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def fetch_resource_label_events(
    project_id: str,
    issue_iid: int,
    token: str,
    *,
    gitlab_url: Optional[str] = None,
    timeout: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """Lista resource_label_events de uma issue (paginado)."""
    http = session or _get_http_session()
    base = (gitlab_url or _gitlab_url()).rstrip("/")
    url = f"{base}/api/v4/projects/{project_id}/issues/{issue_iid}/resource_label_events"
    headers = {"PRIVATE-TOKEN": token}
    params: Dict[str, Any] = {"per_page": 100, "page": 1}
    events: List[Dict[str, Any]] = []
    max_retries = 3

    while True:
        for attempt in range(max_retries):
            response = http.get(url, headers=headers, params=params, timeout=timeout)
            if response.status_code == 404:
                return []
            if response.status_code == 429:
                wait = min(2 ** attempt, 30)
                time.sleep(wait)
                continue
            response.raise_for_status()
            break
        else:
            response.raise_for_status()

        batch = response.json()
        if not batch:
            break
        events.extend(batch)
        next_page = response.headers.get("X-Next-Page")
        if not next_page:
            break
        params["page"] = int(next_page)

    return events


def event_rows_from_gitlab_events(
    issue_key: str,
    events: Iterable[Dict[str, Any]],
    *,
    estado: str = "Aberto",
    synced_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Converte eventos GitLab filtrados em linhas para issue_status_events."""
    synced_at = synced_at or _utc_now_iso()
    rows: List[Dict[str, Any]] = []

    for event in events:
        label = event.get("label") or {}
        label_name = str(label.get("name") or "")
        status_value = parse_status_label(label_name)
        if status_value is None:
            continue

        action = str(event.get("action") or "").lower()
        if action not in {"add", "remove"}:
            continue

        event_at = str(event.get("created_at") or "").strip()
        if not event_at:
            continue

        gitlab_event_id = event.get("id")
        etapa = flow_map_etapa(status_value, estado)

        if action == "add":
            row = {
                "issue_key": issue_key,
                "event_at": event_at,
                "event_type": "status_add",
                "status_anterior": None,
                "status_novo": status_value,
                "etapa_anterior": None,
                "etapa_nova": etapa,
                "source": "gitlab_api",
                "gitlab_event_id": gitlab_event_id,
                "synced_at": synced_at,
            }
        else:
            row = {
                "issue_key": issue_key,
                "event_at": event_at,
                "event_type": "status_remove",
                "status_anterior": status_value,
                "status_novo": None,
                "etapa_anterior": etapa,
                "etapa_nova": None,
                "source": "gitlab_api",
                "gitlab_event_id": gitlab_event_id,
                "synced_at": synced_at,
            }
        rows.append(row)

    return rows


@dataclass(frozen=True)
class _IssueFetchJob:
    issue_key: str
    project_id: str
    token: str
    iid: int
    estado: str


def _build_fetch_jobs(issues: List[Dict[str, Any]], limit: int) -> Tuple[List[_IssueFetchJob], Dict[str, int]]:
    stats = {
        "issues_skipped_no_token": 0,
        "issues_skipped_no_project": 0,
        "issues_skipped_invalid": 0,
    }
    jobs: List[_IssueFetchJob] = []
    slice_issues = issues[:limit] if limit > 0 else issues

    for issue in slice_issues:
        issue_key = issue_key_from_raw_issue(issue)
        if not issue_key:
            stats["issues_skipped_invalid"] += 1
            continue

        repo_slug = get_gitlab_repo(issue)
        token = _gitlab_token_for_repo(repo_slug)
        if not token:
            stats["issues_skipped_no_token"] += 1
            continue

        project_id = _project_id_for_repo(repo_slug)
        if not project_id:
            stats["issues_skipped_no_project"] += 1
            continue

        try:
            iid = int(str(issue.get("id", "")).strip())
        except ValueError:
            stats["issues_skipped_invalid"] += 1
            continue

        jobs.append(
            _IssueFetchJob(
                issue_key=issue_key,
                project_id=project_id,
                token=token,
                iid=iid,
                estado=map_estado(issue.get("state", "")),
            )
        )

    return jobs, stats


def _fetch_job_rows(job: _IssueFetchJob, synced_at: str) -> Tuple[List[Dict[str, Any]], bool]:
    """Retorna (linhas, teve_erro_api)."""
    try:
        raw_events = fetch_resource_label_events(job.project_id, job.iid, job.token)
    except requests.RequestException:
        return [], True
    rows = event_rows_from_gitlab_events(
        job.issue_key,
        raw_events,
        estado=job.estado,
        synced_at=synced_at,
    )
    return rows, False


def _collect_rows_parallel(
    jobs: List[_IssueFetchJob],
    *,
    workers: int,
    synced_at: str,
    progress_every: int,
    on_rows_batch: Optional[Callable[[List[Dict[str, Any]], int, int], None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Coleta paralela com callback opcional por lote concluido."""
    stats = {
        "issues_requested": len(jobs),
        "issues_fetched": 0,
        "events_collected": 0,
        "api_errors": 0,
    }
    all_rows: List[Dict[str, Any]] = []
    total = len(jobs)
    completed = 0
    started = time.monotonic()

    log_stage(f"Inicio coleta GitLab — {total} issues, {workers} workers paralelos")

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_fetch_job_rows, job, synced_at): job for job in jobs
        }
        for future in as_completed(future_map):
            completed += 1
            rows, had_error = future.result()
            if had_error:
                stats["api_errors"] += 1
            else:
                stats["issues_fetched"] += 1
                stats["events_collected"] += len(rows)
                all_rows.extend(rows)
                if on_rows_batch and rows:
                    on_rows_batch(rows, completed, total)

            if progress_every and completed % progress_every == 0:
                log_stage(
                    f"Coleta GitLab: {completed}/{total} issues — "
                    f"{stats['events_collected']} eventos, "
                    f"{stats['api_errors']} erros API "
                    f"(elapsed {format_elapsed(time.monotonic() - started)})"
                )

    log_stage(
        f"Fim coleta GitLab — {stats['issues_fetched']} ok, "
        f"{stats['events_collected']} eventos em {format_elapsed(time.monotonic() - started)}"
    )
    return all_rows, stats


def collect_status_event_rows(
    issues: List[Dict[str, Any]],
    *,
    issue_limit: int = 0,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    workers: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Busca resource_label_events no GitLab (paralelo)."""
    limit = issue_limit if issue_limit > 0 else len(issues)
    log_stage(f"Preparacao — ate {limit} issues")
    jobs, prep_stats = _build_fetch_jobs(issues, limit)
    worker_count = workers or status_events_workers()

    rows, stats = _collect_rows_parallel(
        jobs,
        workers=worker_count,
        synced_at=_utc_now_iso(),
        progress_every=progress_every,
    )
    stats.update(prep_stats)
    return dedupe_event_rows(rows), stats


def collect_and_upsert_status_events(
    issues: List[Dict[str, Any]],
    upsert_fn,
    *,
    issue_limit: int = 0,
    progress_every: int = DEFAULT_PROGRESS_EVERY,
    upsert_every_issues: int = DEFAULT_UPSERT_EVERY_ISSUES,
    workers: Optional[int] = None,
) -> Tuple[Dict[str, int], int]:
    """Coleta paralela no GitLab e grava no Supabase incrementalmente."""
    run_started = time.monotonic()
    limit = issue_limit if issue_limit > 0 else len(issues)
    worker_count = workers or status_events_workers()
    synced_at = _utc_now_iso()

    log_stage(
        f"Inicio status_events — ate {limit} issues, "
        f"{worker_count} workers, flush Supabase a cada {upsert_every_issues} issues"
    )
    log_stage("Preparacao da fila de issues")
    jobs, prep_stats = _build_fetch_jobs(issues, limit)
    log_stage(f"Fila pronta — {len(jobs)} issues elegiveis para coleta")
    if not jobs and limit > 0:
        log_stage(
            "AVISO: fila vazia — nenhuma issue sera consultada no GitLab. "
            f"Puladas: sem token={prep_stats['issues_skipped_no_token']}, "
            f"sem project_id={prep_stats['issues_skipped_no_project']}, "
            f"invalidas={prep_stats['issues_skipped_invalid']}"
        )

    stats: Dict[str, int] = {
        "issues_requested": len(jobs),
        "issues_skipped_no_token": prep_stats["issues_skipped_no_token"],
        "issues_skipped_no_project": prep_stats["issues_skipped_no_project"],
        "issues_skipped_invalid": prep_stats["issues_skipped_invalid"],
        "issues_fetched": 0,
        "events_collected": 0,
        "events_upserted": 0,
        "api_errors": 0,
        "upsert_errors": 0,
    }

    pending: List[Dict[str, Any]] = []
    total_upserted = 0
    issues_since_flush = 0
    collect_started = time.monotonic()

    def flush_pending(force_log: bool = False) -> None:
        nonlocal total_upserted, pending, issues_since_flush
        if not pending:
            return
        batch = dedupe_event_rows(pending)
        pending = []
        issues_since_flush = 0
        upsert_started = time.monotonic()
        log_stage(f"Inicio gravacao Supabase — lote com {len(batch)} eventos")
        try:
            written = upsert_fn(batch)
            total_upserted += written
            stats["events_upserted"] = total_upserted
            log_stage(
                f"Fim gravacao Supabase — {written} eventos em "
                f"{format_elapsed(time.monotonic() - upsert_started)} "
                f"(total gravado: {total_upserted})"
            )
        except Exception as exc:
            stats["upsert_errors"] += 1
            raise RuntimeError(
                f"Falha ao gravar issue_status_events ({exc}). "
                "Verifique migrations 026+027 e se as issues ja existem em public.issues."
            ) from exc
        if force_log and not batch:
            return

    log_stage(f"Inicio coleta GitLab — {len(jobs)} issues, {worker_count} workers")

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(_fetch_job_rows, job, synced_at): job for job in jobs
        }
        completed = 0
        for future in as_completed(future_map):
            completed += 1
            rows, had_error = future.result()
            if had_error:
                stats["api_errors"] += 1
            else:
                stats["issues_fetched"] += 1
                stats["events_collected"] += len(rows)
                pending.extend(rows)
                issues_since_flush += 1

            if upsert_every_issues and issues_since_flush >= upsert_every_issues:
                flush_pending()

            if progress_every and completed % progress_every == 0:
                log_stage(
                    f"Coleta GitLab: {completed}/{len(jobs)} — "
                    f"{stats['events_collected']} coletados, {total_upserted} gravados, "
                    f"{stats['api_errors']} erros "
                    f"(elapsed {format_elapsed(time.monotonic() - collect_started)})"
                )

    log_stage(
        f"Fim coleta GitLab em {format_elapsed(time.monotonic() - collect_started)} — "
        f"flush final pendente: {len(pending)} eventos"
    )
    flush_pending()

    log_stage(
        f"Concluido status_events em {format_elapsed(time.monotonic() - run_started)} — "
        f"{stats['issues_fetched']} issues, {stats['events_collected']} coletados, "
        f"{total_upserted} gravados, {stats['api_errors']} erros API"
    )
    return stats, total_upserted


def dedupe_event_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicatas locais por gitlab_event_id."""
    seen: Dict[int, Dict[str, Any]] = {}
    without_id: List[Dict[str, Any]] = []
    for row in rows:
        event_id = row.get("gitlab_event_id")
        if event_id is None:
            without_id.append(row)
            continue
        seen[int(event_id)] = row
    return list(seen.values()) + without_id
