#!/usr/bin/env python3
"""Backfill de issues.epico e gitlab_epic_issue_links.

Escopos:
  filhas     - TODAS as filhas dos epicos do grupo no Supabase (recomendado)
  mergeadas  - so mergeadas sem epico (legado / pivô mergeadas)
  todas      - qualquer issue no Supabase sem epico

Uso:
  python backfill_epicos_mergeadas.py --escopo filhas --dry-run
  python backfill_epicos_mergeadas.py --escopo filhas
  python audit_epicos_grupo.py
"""

from __future__ import annotations

import argparse
import os
from typing import Any

import requests

from gitlab_epics import (
    _any_gitlab_token,
    buscar_epicos_grupo,
    enriquecer_epicos_via_filhas_grupo,
    enriquecer_epicos_via_parent_hierarchy,
    enriquecer_epicos_via_rest_fallback,
    group_path,
    preencher_epicos_filhas_no_supabase,
)
from issue_fields import extract_epico
from issue_keys import normalize_repo, repo_display_name
from logging_utils import get_logger
from sync_supabase import SupabaseSync, _load_dotenv

log = get_logger(__name__)

ORDER_RECENT = "mergeado_em.desc"
ORDER_IID = "gitlab_iid.asc"


def fetch_issues_sem_epico(
    base: str,
    headers: dict[str, str],
    *,
    mergeadas_only: bool,
    order: str = ORDER_RECENT,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        params: dict[str, Any] = {
            "select": "issue_key,gitlab_repo,gitlab_iid,epico,mergeado_em",
            "or": "(epico.is.null,epico.eq.)",
            "order": order,
            "limit": page_size,
            "offset": offset,
        }
        if mergeadas_only:
            params["mergeado_em"] = "not.is.null"
        response = requests.get(f"{base}/issues", headers=headers, params=params, timeout=120)
        response.raise_for_status()
        chunk = response.json()
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return rows


def _rows_to_issue_dicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in rows:
        gitlab_iid = row.get("gitlab_iid")
        if gitlab_iid in (None, ""):
            continue
        repo_slug = normalize_repo((row.get("gitlab_repo") or "").strip())
        issues.append(
            {
                "id": str(int(gitlab_iid)),
                "gitlab_repo": repo_slug,
                "epic": None,
                "_supabase_row": row,
            }
        )
    return issues


def _backfill_lote_issues(
    issues: list[dict[str, Any]],
    *,
    token: str,
    rest_fallback: bool,
    workers: int,
    base: str,
    headers: dict[str, str],
    dry_run: bool,
    client: SupabaseSync,
) -> int:
    if not issues:
        return 0

    try:
        epics = buscar_epicos_grupo(token=token)
        children_filled, _ = enriquecer_epicos_via_filhas_grupo(issues, epics, token=token)
        log.info(f"OK - {children_filled} issues via filhas dos epicos do grupo")
    except Exception as exc:
        log.warning(f"AVISO - filhas de epicos do grupo ignoradas ({exc})")

    parent_filled, _ = enriquecer_epicos_via_parent_hierarchy(issues, token=token)
    log.info(f"OK - {parent_filled} Parents resolvidos via GraphQL em lote")

    rest_pending = [issue for issue in issues if not extract_epico(issue)]
    if rest_pending and rest_fallback:
        enriquecer_epicos_via_rest_fallback(issues, token=token, max_workers=workers)

    filled = 0
    link_rows: list[dict[str, Any]] = []
    for idx, issue in enumerate(issues, start=1):
        title = extract_epico(issue)
        if not title:
            continue
        row = issue["_supabase_row"]
        repo_slug = issue["gitlab_repo"]
        gitlab_iid = int(issue["id"])
        epic_obj = issue.get("epic") if isinstance(issue.get("epic"), dict) else {}
        filled += 1
        link_rows.append(
            {
                "gitlab_group_path": group_path(),
                "gitlab_repo": repo_display_name(repo_slug),
                "gitlab_iid": gitlab_iid,
                "gitlab_epic_id": epic_obj.get("id"),
                "epic_title": title,
            }
        )
        if dry_run:
            log.info(f"DRY - {row.get('issue_key')} -> {title}")
            continue
        patch = requests.patch(
            f"{base}/issues",
            headers=headers,
            params={"issue_key": f"eq.{row['issue_key']}"},
            json={"epico": title},
            timeout=60,
        )
        if not patch.ok:
            log.warning(f"AVISO - falha ao atualizar {row.get('issue_key')}: {patch.text[:200]}")
            continue
        if idx % 50 == 0 or idx == len(issues):
            log.info(f"OK - gravacao {idx}/{len(issues)}, {filled} com epico")

    if not dry_run and link_rows:
        try:
            count = client.upsert_gitlab_epic_issue_links(link_rows)
            log.info(f"OK - {count} vinculos issue-epico sincronizados")
        except Exception as exc:
            log.warning(f"AVISO - vinculos nao gravados ({exc})")
    return filled


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill epico no Supabase")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--escopo",
        choices=("filhas", "mergeadas", "todas"),
        default="filhas",
        help="filhas=todas filhas de epicos no SB (padrao); mergeadas=so mergeadas sem epico",
    )
    parser.add_argument("--rest-fallback", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--order", choices=("recent", "iid"), default="recent")
    args = parser.parse_args()

    _load_dotenv()
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit("Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no .env")

    token = _any_gitlab_token()
    client = SupabaseSync(url, key)

    if args.escopo == "filhas":
        stats = preencher_epicos_filhas_no_supabase(
            supabase_url=url,
            service_key=key,
            dry_run=args.dry_run,
            token=token,
        )
        log.info(
            f"OK - Concluido (filhas): {stats['preenchidos']} preenchidas, "
            f"{stats['ja_ok']} ja ok, {stats['fora_sb']} fora do Supabase"
        )
        if stats["fora_sb"]:
            log.warning(
                f"AVISO - {stats['fora_sb']} filhas de epico nao estao no Supabase. "
                "Rode: python atualizar_gitlab_issues.py --full && python sync_supabase.py"
            )
        return 0

    base = url.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    order = ORDER_RECENT if args.order == "recent" else ORDER_IID
    mergeadas_only = args.escopo == "mergeadas"
    pending_rows = fetch_issues_sem_epico(
        base, headers, mergeadas_only=mergeadas_only, order=order
    )
    if args.limit > 0:
        pending_rows = pending_rows[: args.limit]
    label = "mergeadas sem epico" if mergeadas_only else "sem epico"
    log.info(f"OK - {len(pending_rows)} issues {label} no Supabase")

    issues = _rows_to_issue_dicts(pending_rows)
    filled = _backfill_lote_issues(
        issues,
        token=token,
        rest_fallback=args.rest_fallback,
        workers=args.workers,
        base=base,
        headers=headers,
        dry_run=args.dry_run,
        client=client,
    )
    log.info(f"OK - Concluido: {filled} com epico no escopo {args.escopo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
