#!/usr/bin/env python3
"""Backfill de issue_status_events a partir do GitLab (resource_label_events).

Por padrao le a lista de issues em public.issues (Supabase), nao no JSON local.
Grava no Supabase incrementalmente (a cada lote). Coleta paralela via
MGI_STATUS_EVENTS_WORKERS (default 8).

Uso:
  python backfill_status_events.py
  python backfill_status_events.py --workers 12
  python backfill_status_events.py --source json --json gitlab_issues_raw.json
  python backfill_status_events.py --filtrar
  python backfill_status_events.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from status_events import (
    collect_and_upsert_status_events,
    collect_status_event_rows,
    is_status_events_sync_enabled,
    format_elapsed,
    log_stage,
    status_events_issue_limit,
    status_events_workers,
)
from sync_supabase import SupabaseSync, _load_dotenv, load_issues_for_status_events


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill issue_status_events via GitLab resource_label_events",
    )
    parser.add_argument(
        "--source",
        choices=("supabase", "json"),
        default="supabase",
        help="Origem da lista de issues (default: supabase / public.issues)",
    )
    parser.add_argument("--json", type=Path, default=None, help="gitlab_issues_raw.json (source=json)")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximo de issues a processar (0 = todas da origem)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Threads paralelas GitLab (0 = env MGI_STATUS_EVENTS_WORKERS ou 8)",
    )
    parser.add_argument(
        "--filtrar",
        action="store_true",
        help="Aplica filtros do sync (corte 2024 + fechadas antigas)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas busca eventos no GitLab, sem gravar no Supabase",
    )
    args = parser.parse_args()

    if not is_status_events_sync_enabled():
        print("MGI_SYNC_STATUS_EVENTS=0 — coleta desabilitada.")
        return 0

    _load_dotenv()
    import os

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    needs_supabase = args.source == "supabase" or not args.dry_run
    if needs_supabase and (not url or not key):
        print("Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.", file=sys.stderr)
        return 1

    run_started = time.monotonic()
    log_stage("Inicio backfill_status_events")

    apply_filters = args.filtrar or args.source == "json"
    client = SupabaseSync(url, key) if needs_supabase else None
    log_stage(f"Origem: {args.source}" + (" (com filtros do sync)" if apply_filters else ""))
    issues = load_issues_for_status_events(
        source=args.source,
        json_path=args.json,
        client=client,
        apply_sync_filters=apply_filters,
    )
    limit = args.limit or status_events_issue_limit() or len(issues)
    workers = args.workers or status_events_workers()

    log_stage(f"Issues elegiveis: {limit} de {len(issues)} (workers={workers})")

    if args.dry_run:
        rows, stats = collect_status_event_rows(
            issues,
            issue_limit=limit,
            workers=workers,
        )
        log_stage(
            f"Dry-run concluido em {format_elapsed(time.monotonic() - run_started)} — "
            f"{stats['issues_fetched']} issues, {len(rows)} eventos, "
            f"{stats['api_errors']} erros API (nada gravado)"
        )
        return 0

    log_stage("Conectando Supabase")
    stats, upserted = collect_and_upsert_status_events(
        issues,
        client.upsert_status_events,
        issue_limit=limit,
        workers=workers,
    )

    log_stage(
        f"Backfill finalizado em {format_elapsed(time.monotonic() - run_started)} — "
        f"{stats['issues_fetched']} issues, {upserted} eventos gravados"
    )
    log_stage(
        "Confira: select count(distinct issue_key), count(*) from issue_status_events;"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
