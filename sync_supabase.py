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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from gitlab_identities import (
    build_participant_rows,
    collect_gitlab_users_from_records,
    issue_keys_from_records,
    prepare_issue_rows_for_upsert,
)
from issue_filters import filtrar_issues_fechadas_antigas, parse_issue_datetime
from issue_keys import normalize_repo
from processar_issues_memoria import build_issue_records, resolve_enable_git
from status_events import (
    collect_and_upsert_status_events,
    is_status_events_sync_enabled,
    log_stage,
    status_events_issue_limit,
)

try:
    import config as _config
except ImportError:
    _config = None

SYNC_STATE_FILENAME = "gitlab_issues_sync_state.json"


@dataclass(frozen=True)
class SyncResult:
    issues_upserted: int
    status_events_upserted: int = 0
    status_issues_targeted: int = 0


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _issues_json_path(explicit: Optional[Path]) -> Path:
    if explicit:
        return explicit
    if _config and hasattr(_config, "ISSUES_JSON"):
        return Path(_config.ISSUES_JSON)
    return Path(__file__).resolve().parent / "gitlab_issues_raw.json"


def _git_data_path() -> Path:
    if _config:
        return Path(_config.GIT_DATA_JSON)
    return Path(__file__).resolve().parent.parent / "gitlab_git_data.json"


def _load_issues_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"JSON de issues nao encontrado: {path}")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("issues"), list):
        return data["issues"]
    return []


def _cutoff_date() -> Optional[datetime]:
    if _config and hasattr(_config, "DEFAULT_CUTOFF_DATE"):
        return _config.DEFAULT_CUTOFF_DATE
    return datetime(2024, 1, 1)


def _filter_issues_for_sync(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aplica os mesmos filtros do pipeline: fechadas antigas + data de corte."""
    filtered, excluded = filtrar_issues_fechadas_antigas(issues)
    if excluded:
        print(f"OK - {excluded} issues fechadas antigas ignoradas")

    cutoff = _cutoff_date()
    if cutoff is None:
        return filtered

    kept: List[Dict[str, Any]] = []
    before = 0
    for issue in filtered:
        created = parse_issue_datetime(issue.get("createdDate", ""))
        if created is not None and created < cutoff:
            before += 1
            continue
        kept.append(issue)
    if before:
        print(f"OK - {before} issues criadas antes de {cutoff:%d/%m/%Y} ignoradas")
    return kept


def _sync_state_path(json_path: Optional[Path] = None) -> Path:
    return _issues_json_path(json_path).parent / SYNC_STATE_FILENAME


def _load_status_event_issue_keys(json_path: Optional[Path] = None) -> Optional[List[str]]:
    """Chaves gravadas pelo sync incremental GitLab (etapa 0 do pipeline diario)."""
    state_path = _sync_state_path(json_path)
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    keys = data.get("status_event_issue_keys")
    if keys is None:
        return None
    if not isinstance(keys, list):
        return None
    return [str(key) for key in keys if key]


def issues_for_status_events_from_sync(
    rows: List[Dict[str, Any]],
    *,
    json_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Monta fila de status_events a partir das issues upsertadas neste sync."""
    targeted = rows
    use_incremental = os.environ.get("MGI_STATUS_EVENTS_INCREMENTAL", "0").lower() not in (
        "0",
        "false",
        "no",
    )
    if use_incremental:
        incremental_keys = _load_status_event_issue_keys(json_path)
        if incremental_keys is not None:
            if not incremental_keys:
                return []
            key_set = set(incremental_keys)
            targeted = [row for row in rows if row.get("issue_key") in key_set]
            print(
                f"OK - status_events incremental: {len(targeted)} issues "
                f"(de {len(incremental_keys)} alteradas no GitLab)",
                flush=True,
            )
    return [supabase_row_to_raw_issue(row) for row in targeted]


SUPABASE_ISSUES_SELECT = (
    "issue_key,gitlab_iid,gitlab_repo,estado,criado_em,fechado_em"
)


def _estado_to_gitlab_state(estado: Optional[str]) -> str:
    if estado == "Aberto":
        return "opened"
    if estado == "Fechado":
        return "closed"
    return ""


def supabase_row_to_raw_issue(row: Dict[str, Any]) -> Dict[str, Any]:
    """Converte linha de public.issues para o formato esperado por status_events."""
    criado = str(row.get("criado_em") or "").strip()
    fechado = str(row.get("fechado_em") or "").strip()
    iid = row.get("gitlab_iid")
    repo_label = str(row.get("gitlab_repo") or "").strip()
    return {
        "id": str(iid).strip() if iid is not None else "",
        "gitlab_repo": normalize_repo(repo_label) if repo_label else "",
        "state": _estado_to_gitlab_state(str(row.get("estado") or "").strip()),
        "createdDate": criado,
        "closedDate": fechado,
        "issue_key": str(row.get("issue_key") or "").strip(),
    }


def load_issues_for_status_events(
    *,
    source: str,
    json_path: Optional[Path] = None,
    client: Optional["SupabaseSync"] = None,
    apply_sync_filters: bool = False,
) -> List[Dict[str, Any]]:
    """Carrega issues para coleta de status_events (Supabase ou JSON local)."""
    normalized = (source or "supabase").strip().lower()
    if normalized == "json":
        path = _issues_json_path(json_path)
        print(f"OK - Carregando issues de {path}")
        issues = _load_issues_json(path)
    elif normalized == "supabase":
        if client is None:
            raise ValueError("client Supabase obrigatorio quando source=supabase")
        print("OK - Carregando issues de public.issues (Supabase)")
        issues = client.fetch_all_issues_for_status_events()
    else:
        raise ValueError(f"source invalido: {source!r} (use supabase ou json)")

    if apply_sync_filters:
        issues = _filter_issues_for_sync(issues)
    return issues


class SupabaseSync:
    def __init__(self, url: str, service_key: str) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }

    def fetch_all_issues_for_status_events(
        self,
        *,
        page_size: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Lista todas as issues de public.issues paginadas via PostgREST."""
        rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            response = requests.get(
                f"{self.base}/issues",
                headers=self.headers,
                params={
                    "select": SUPABASE_ISSUES_SELECT,
                    "order": "issue_key",
                    "limit": str(page_size),
                    "offset": str(offset),
                },
                timeout=120,
            )
            if not response.ok:
                detail = response.text[:500]
                raise RuntimeError(
                    f"Erro ao listar issues Supabase ({response.status_code}): {detail}"
                )
            batch = response.json()
            if not batch:
                break
            rows.extend(supabase_row_to_raw_issue(row) for row in batch)
            if len(batch) < page_size:
                break
            offset += page_size
        print(f"OK - {len(rows)} issues carregadas do Supabase")
        return rows

    def upsert_gitlab_users(self, rows: List[Dict[str, Any]]) -> int:
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

    def replace_issue_participants(self, issue_keys: List[str], rows: List[Dict[str, Any]]) -> int:
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

    def upsert_issues(self, rows: List[Dict[str, Any]]) -> int:
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
            print(f"OK - Enviadas {total}/{len(rows)} issues")
        return total

    def upsert_releases(self, rows: List[Dict[str, Any]]) -> int:
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

    def upsert_status_events(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        total = 0
        chunk_size = 500
        headers = {
            **self.headers,
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start : start + chunk_size]
            response = requests.post(
                f"{self.base}/issue_status_events?on_conflict=gitlab_event_id",
                headers=headers,
                json=chunk,
                timeout=120,
            )
            if not response.ok:
                detail = response.text[:500]
                hint = ""
                if response.status_code == 400 and "42P10" in detail:
                    hint = (
                        " Aplique a migration 028_issue_status_events_upsert_constraint.sql "
                        "(UNIQUE em gitlab_event_id para PostgREST on_conflict)."
                    )
                raise RuntimeError(
                    f"Erro Supabase issue_status_events ({response.status_code}): {detail}{hint}"
                )
            total += len(chunk)
        return total

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
            print(f"OK - Cache do dashboard invalidado ({endpoint})")
        else:
            print(f"AVISO - Falha ao invalidar cache ({response.status_code}): {response.text[:200]}")
    except Exception as exc:
        print(f"AVISO - Nao foi possivel notificar o dashboard: {exc}")


def _dedupe_releases(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[tuple[str, str], Dict[str, Any]] = {}
    for record in rows:
        key = (str(record["repositorio"]), str(record["versao"]))
        seen[key] = record
    return list(seen.values())


def _load_releases(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    rows: List[Dict[str, Any]] = []
    synced_at = _utc_now()

    def append(repo_name: str, rel: Dict[str, Any]) -> None:
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
        print(f"OK - Variaveis carregadas de {path}")
        return


def sync_issues_to_supabase(
    issues: Optional[List[Dict[str, Any]]] = None,
    *,
    json_path: Optional[Path] = None,
    include_releases: bool = True,
    enable_git: bool = True,
    sync_status_events: Optional[bool] = None,
) -> SyncResult:
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
        print(f"OK - Carregando issues de {path}")
        issues = _load_issues_json(path)

    issues = _filter_issues_for_sync(issues)
    git_enabled = resolve_enable_git(enable_git)
    if enable_git and not git_enabled:
        print(
            "AVISO - WSL/Git indisponivel ou MGI_FAST_REPO_SYNC=1. "
            "Usando titulo/labels (sem detectores Git).",
            flush=True,
        )
    print(f"OK - Processando {len(issues)} issues em memoria", flush=True)
    raw_records = build_issue_records(issues, enable_git=git_enabled)
    synced_at = raw_records[0]["synced_at"] if raw_records else _utc_now()
    gitlab_users = collect_gitlab_users_from_records(raw_records, synced_at)
    participant_rows = build_participant_rows(raw_records)
    rows = prepare_issue_rows_for_upsert(raw_records)
    issue_keys = issue_keys_from_records(raw_records)
    print(f"OK - {len(rows)} issues unicas preparadas")

    client = SupabaseSync(url, key)
    run_id: Optional[str] = None
    try:
        run_id = client.start_sync_run()
    except Exception as exc:
        print(f"AVISO - sync_runs indisponivel ({exc}). Continuando upsert...")

    try:
        if gitlab_users:
            client.upsert_gitlab_users(gitlab_users)
            print(f"OK - {len(gitlab_users)} identidades GitLab sincronizadas")
        upserted = client.upsert_issues(rows)
        participant_count = client.replace_issue_participants(issue_keys, participant_rows)
        print(f"OK - {participant_count} participantes de issues sincronizados")

        events_upserted = 0
        status_issues_targeted = 0
        should_sync_events = (
            is_status_events_sync_enabled()
            if sync_status_events is None
            else sync_status_events
        )
        if should_sync_events:
            issues_for_events = issues_for_status_events_from_sync(
                rows,
                json_path=json_path,
            )
            status_issues_targeted = len(issues_for_events)
            if not issues_for_events:
                log_stage(
                    "status_events omitido — nenhuma issue alvo "
                    "(incremental sem alteracoes no GitLab)"
                )
            else:
                limit = status_events_issue_limit()
                log_stage(
                    f"Inicio etapa status_events — {status_issues_targeted} issues alvo"
                )
                _, events_upserted = collect_and_upsert_status_events(
                    issues_for_events,
                    client.upsert_status_events,
                    issue_limit=limit if limit > 0 else len(issues_for_events),
                )
                log_stage(f"Fim etapa status_events — {events_upserted} eventos gravados")
        else:
            print("AVISO - Coleta issue_status_events desabilitada (MGI_SYNC_STATUS_EVENTS=0)")

        release_count = 0
        if include_releases:
            release_rows = _dedupe_releases(_load_releases(_git_data_path()))
            release_count = client.upsert_releases(release_rows)
            print(f"OK - {release_count} releases sincronizadas")

        if run_id:
            client.finish_sync_run(
                run_id,
                status="success",
                rows=upserted,
                releases=release_count,
                message="sync from gitlab_issues_raw.json",
            )
        print(
            f"OK - Sync concluido: {upserted} issues, "
            f"{events_upserted} eventos de status"
        )

        dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
        revalidate_secret = os.environ.get("REVALIDATE_SECRET", "").strip()
        if dashboard_url and revalidate_secret:
            _notify_dashboard(dashboard_url, revalidate_secret)
        else:
            print("AVISO - DASHBOARD_URL ou REVALIDATE_SECRET nao configurados; cache nao invalidado.")

        return SyncResult(
            issues_upserted=upserted,
            status_events_upserted=events_upserted,
            status_issues_targeted=status_issues_targeted,
        )
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
    parser.add_argument(
        "--sem-status-events",
        action="store_true",
        help="Nao coleta resource_label_events (issue_status_events)",
    )
    args = parser.parse_args()

    sync_issues_to_supabase(
        json_path=args.json,
        include_releases=not args.sem_releases,
        enable_git=not args.sem_git,
        sync_status_events=not args.sem_status_events,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
