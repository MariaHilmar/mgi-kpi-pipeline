#!/usr/bin/env python3
"""
Sincroniza issues (GitLab -> JSON -> Supabase) sem passar por Excel.

As issues sao processadas em memoria por processar_issues_memoria.build_issue_records
(mesmos detectores e taxonomia do pipeline) e enviadas direto para a tabela
public.issues via PostgREST. Releases vem de gitlab_git_data.json.

Uso:
  python sync_supabase.py
  python sync_supabase.py --json D:\\caminho\\gitlab_issues_raw.json
  python sync_supabase.py --sem-releases
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from gitlab_identities import (
    build_participant_rows,
    collect_gitlab_users_from_records,
    issue_keys_from_records,
    prepare_issue_rows_for_upsert,
)
from issue_filters import filtrar_issues_fechadas_antigas, parse_issue_datetime
from logging_utils import get_logger
from processar_issues_memoria import build_issue_records, resolve_enable_git

try:
    import config as _config
except ImportError:
    _config = None

log = get_logger(__name__)

def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _issues_json_path(explicit: Path | None) -> Path:
    if explicit:
        return explicit
    if _config and hasattr(_config, "ISSUES_JSON"):
        return Path(_config.ISSUES_JSON)
    return Path(__file__).resolve().parent / "gitlab_issues_raw.json"


def _git_data_path() -> Path:
    if _config:
        return Path(_config.GIT_DATA_JSON)
    return Path(__file__).resolve().parent.parent / "gitlab_git_data.json"


def _load_issues_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"JSON de issues nao encontrado: {path}")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("issues"), list):
        return data["issues"]
    return []


def _cutoff_date() -> datetime | None:
    if _config and hasattr(_config, "DEFAULT_CUTOFF_DATE"):
        return _config.DEFAULT_CUTOFF_DATE
    return datetime(2024, 1, 1)


def _filter_issues_for_sync(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aplica os mesmos filtros do pipeline: fechadas antigas + data de corte."""
    filtered, excluded = filtrar_issues_fechadas_antigas(issues)
    if excluded:
        log.info(f"OK - {excluded} issues fechadas antigas ignoradas")

    cutoff = _cutoff_date()
    if cutoff is None:
        return filtered

    kept: list[dict[str, Any]] = []
    before = 0
    for issue in filtered:
        created = parse_issue_datetime(issue.get("createdDate", ""))
        if created is not None and created < cutoff:
            before += 1
            continue
        kept.append(issue)
    if before:
        log.info(f"OK - {before} issues criadas antes de {cutoff:%d/%m/%Y} ignoradas")
    return kept


class SupabaseSync:
    def __init__(self, url: str, service_key: str) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }

    def upsert_gitlab_users(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        response = requests.post(
            f"{self.base}/gitlab_users?on_conflict=id",
            headers=self.headers,
            json=rows,
            timeout=120,
        )
        if not response.ok:
            detail = response.text[:500]
            raise RuntimeError(
                f"Erro Supabase gitlab_users ({response.status_code}): {detail}"
            )
        return len(rows)

    def replace_issue_participants(self, issue_keys: list[str], rows: list[dict[str, Any]]) -> int:
        if issue_keys:
            keys_filter = f"in.({','.join(json.dumps(key) for key in issue_keys)})"
            delete_response = requests.delete(
                f"{self.base}/issue_participants?issue_key={keys_filter}",
                headers=self.headers,
                timeout=120,
            )
            if not delete_response.ok:
                detail = delete_response.text[:500]
                raise RuntimeError(
                    f"Erro ao limpar issue_participants ({delete_response.status_code}): {detail}"
                )
        if not rows:
            return 0
        total = 0
        chunk_size = 500
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            response = requests.post(
                f"{self.base}/issue_participants?on_conflict=issue_key,role,gitlab_user_id",
                headers=self.headers,
                json=chunk,
                timeout=120,
            )
            if not response.ok:
                detail = response.text[:500]
                raise RuntimeError(
                    f"Erro Supabase issue_participants ({response.status_code}): {detail}"
                )
            total += len(chunk)
        return total

    def upsert_issues(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        total = 0
        chunk_size = 200
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            response = requests.post(
                f"{self.base}/issues?on_conflict=issue_key",
                headers=self.headers,
                json=chunk,
                timeout=120,
            )
            if not response.ok:
                detail = response.text[:500]
                raise RuntimeError(
                    f"Erro Supabase issues ({response.status_code}): {detail}"
                )
            total += len(chunk)
            log.info(f"OK - Enviadas {total}/{len(rows)} issues")
        return total

    def upsert_releases(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        response = requests.post(
            f"{self.base}/releases?on_conflict=repositorio,versao",
            headers=self.headers,
            json=rows,
            timeout=60,
        )
        if not response.ok:
            detail = response.text[:500]
            raise RuntimeError(
                f"Erro Supabase releases ({response.status_code}): {detail}"
            )
        return len(rows)

    def start_sync_run(self) -> str:
        response = requests.post(
            f"{self.base}/sync_runs",
            headers={**self.headers, "Prefer": "return=representation"},
            json={"source": "gitlab", "status": "running"},
            timeout=30,
        )
        if not response.ok:
            detail = response.text[:500]
            raise RuntimeError(
                f"Erro Supabase sync_runs ({response.status_code}): {detail}"
            )
        return response.json()[0]["id"]

    def finish_sync_run(
        self,
        run_id: str,
        *,
        status: str,
        rows: int,
        releases: int,
        message: str = "",
    ) -> None:
        payload = {
            "status": status,
            "rows_upserted": rows,
            "releases_upserted": releases,
            "finished_at": _utc_now(),
            "message": message[:500],
        }
        response = requests.patch(
            f"{self.base}/sync_runs?id=eq.{run_id}",
            headers=self.headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()


def _notify_dashboard(url: str, secret: str) -> None:
    """Invalida o cache de KPIs do dashboard após sync bem-sucedido."""
    endpoint = url.rstrip("/") + "/api/revalidate"
    try:
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            timeout=15,
        )
        if response.ok:
            log.info(f"OK - Cache do dashboard invalidado ({endpoint})")
        else:
            log.warning(f"AVISO - Falha ao invalidar cache ({response.status_code}): {response.text[:200]}")
    except Exception as exc:
        log.warning(f"AVISO - Nao foi possivel notificar o dashboard: {exc}")


def _dedupe_releases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for record in rows:
        key = (str(record["repositorio"]), str(record["versao"]))
        seen[key] = record
    return list(seen.values())


def _load_releases(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    rows: list[dict[str, Any]] = []
    synced_at = _utc_now()

    def append(repo_name: str, rel: dict[str, Any]) -> None:
        versao = str(rel.get("versao", "")).strip()
        if not versao:
            return
        rows.append(
            {
                "repositorio": repo_name,
                "versao": versao,
                "data_release": rel.get("data") or None,
                "rotulo": f"{repo_name}: {versao}",
                "synced_at": synced_at,
            }
        )

    if isinstance(data.get("repositorios"), list):
        for repo_block in data["repositorios"]:
            repo_name = repo_block.get("repositorio", "contratos_v2")
            for rel in repo_block.get("releases") or []:
                append(repo_name, rel)
        return rows

    repo_name = data.get("repositorio", "contratos_v2")
    for rel in data.get("releases") or []:
        append(repo_name, rel)
    return rows


def _load_dotenv() -> None:
    """Carrega variaveis de .env na raiz do projeto (se existir)."""
    candidates = [
        Path(__file__).resolve().parent.parent / ".env",
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
    ]
    for path in candidates:
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
        log.info(f"OK - Variaveis carregadas de {path}")
        return


def sync_issues_to_supabase(
    issues: list[dict[str, Any]] | None = None,
    *,
    json_path: Path | None = None,
    include_releases: bool = True,
    enable_git: bool = True,
) -> int:
    """Processa issues em memoria e sincroniza com o Supabase (sem Excel).

    Se ``issues`` for None, carrega de ``json_path`` (ou config.ISSUES_JSON)."""
    _load_dotenv()
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit(
            "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY em .env na raiz do workspace (mgi-workspace/.env)"
        )

    if issues is None:
        path = _issues_json_path(json_path)
        log.info(f"OK - Carregando issues de {path}")
        issues = _load_issues_json(path)

    issues = _filter_issues_for_sync(issues)
    git_enabled = resolve_enable_git(enable_git)
    if enable_git and not git_enabled:
        log.warning(
            "AVISO - WSL/Git indisponivel ou MGI_FAST_REPO_SYNC=1. "
            "Usando titulo/labels (sem detectores Git).",
        )
    log.info(f"OK - Processando {len(issues)} issues em memoria")
    raw_records = build_issue_records(issues, enable_git=git_enabled)
    synced_at = raw_records[0]["synced_at"] if raw_records else _utc_now()
    gitlab_users = collect_gitlab_users_from_records(raw_records, synced_at)
    participant_rows = build_participant_rows(raw_records)
    rows = prepare_issue_rows_for_upsert(raw_records)
    issue_keys = issue_keys_from_records(raw_records)
    log.info(f"OK - {len(rows)} issues unicas preparadas")

    client = SupabaseSync(url, key)
    run_id: str | None = None
    try:
        run_id = client.start_sync_run()
    except Exception as exc:
        log.warning(f"AVISO - sync_runs indisponivel ({exc}). Continuando upsert...")

    try:
        if gitlab_users:
            client.upsert_gitlab_users(gitlab_users)
            log.info(f"OK - {len(gitlab_users)} identidades GitLab sincronizadas")
        upserted = client.upsert_issues(rows)
        participant_count = client.replace_issue_participants(issue_keys, participant_rows)
        log.info(f"OK - {participant_count} participantes de issues sincronizados")
        release_count = 0
        if include_releases:
            release_rows = _dedupe_releases(_load_releases(_git_data_path()))
            release_count = client.upsert_releases(release_rows)
            log.info(f"OK - {release_count} releases sincronizadas")

        if run_id:
            client.finish_sync_run(
                run_id,
                status="success",
                rows=upserted,
                releases=release_count,
                message="sync from gitlab_issues_raw.json",
            )
        log.info(f"OK - Sync concluido: {upserted} issues")

        dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
        revalidate_secret = os.environ.get("REVALIDATE_SECRET", "").strip()
        if dashboard_url and revalidate_secret:
            _notify_dashboard(dashboard_url, revalidate_secret)
        else:
            log.warning("AVISO - DASHBOARD_URL ou REVALIDATE_SECRET nao configurados; cache nao invalidado.")

        return upserted
    except Exception as exc:
        if run_id:
            client.finish_sync_run(
                run_id,
                status="error",
                rows=0,
                releases=0,
                message=str(exc),
            )
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync issues GitLab/JSON -> Supabase")
    parser.add_argument("--json", type=Path, default=None, help="Caminho do gitlab_issues_raw.json")
    parser.add_argument("--sem-releases", action="store_true")
    parser.add_argument(
        "--sem-git",
        action="store_true",
        help="Desativa detectores Git (area/tipo/dev) — usa apenas titulo/labels",
    )
    args = parser.parse_args()

    sync_issues_to_supabase(
        json_path=args.json,
        include_releases=not args.sem_releases,
        enable_git=not args.sem_git,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
