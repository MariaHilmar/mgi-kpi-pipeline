#!/usr/bin/env python3
"""Captura snapshot diário de status/etapa das issues no Supabase.

Executar após o sync GitLab (cron diário). Popula issue_status_snapshots via RPC
flow_capture_daily_snapshots, habilitando CFD histórico a partir da data de coleta.

Uso:
  python snapshot_issue_status.py
  python snapshot_issue_status.py --date 2026-06-30
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from typing import Union

import requests

from sync_supabase import _load_dotenv

DateInput = Union[date, str, None]


def is_daily_snapshot_enabled() -> bool:
    return os.environ.get("MGI_SYNC_DAILY_SNAPSHOT", "1").lower() not in (
        "0",
        "false",
        "no",
    )


def _resolve_snapshot_date(snapshot_date: DateInput) -> date:
    if snapshot_date is None:
        return date.today()
    if isinstance(snapshot_date, date):
        return snapshot_date
    return date.fromisoformat(snapshot_date)


def capture_daily_snapshot(
    snapshot_date: DateInput = None,
    *,
    supabase_url: str | None = None,
    service_role_key: str | None = None,
    timeout: int = 120,
) -> int:
    """Grava snapshot diário via RPC flow_capture_daily_snapshots. Retorna contagem."""
    ref = _resolve_snapshot_date(snapshot_date)
    url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = service_role_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY.")

    endpoint = f"{url}/rest/v1/rpc/flow_capture_daily_snapshots"
    response = requests.post(
        endpoint,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={"p_date": ref.isoformat()},
        timeout=timeout,
    )
    response.raise_for_status()
    count = response.json()
    if not isinstance(count, int):
        raise RuntimeError(f"Resposta inesperada do Supabase: {count!r}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot diário de status das issues")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Data do snapshot (YYYY-MM-DD). Default: hoje.",
    )
    args = parser.parse_args()

    if not is_daily_snapshot_enabled():
        print("MGI_SYNC_DAILY_SNAPSHOT=0 — snapshot omitido.")
        return 0

    _load_dotenv()
    try:
        count = capture_daily_snapshot(args.date)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Snapshot {args.date}: {count} issues registradas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
