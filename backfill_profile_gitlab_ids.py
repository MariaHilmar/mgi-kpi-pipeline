#!/usr/bin/env python3
"""
Vincula profiles.gitlab_user_id a contas existentes no dashboard.

Estrategia:
  1. Busca perfis sem gitlab_user_id em public.profiles
  2. Cruza e-mail (case-insensitive) com gitlab_users e, se necessario,
     com membros ativos dos projetos GitLab (API)
  3. Atualiza profiles.gitlab_user_id

Uso:
  python backfill_profile_gitlab_ids.py --dry-run
  python backfill_profile_gitlab_ids.py
  python backfill_profile_gitlab_ids.py --from-gitlab-only
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parent))
from logging_utils import get_logger
from provision_gitlab_users import (
    _supabase_config,
    _upsert_gitlab_user,
    collect_active_gitlab_users,
)
from sync_supabase import _load_dotenv

log = get_logger(__name__)


def _headers(service_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _fetch_profiles_without_gitlab_id(
    supabase_url: str, service_key: str
) -> list[dict[str, Any]]:
    response = requests.get(
        f"{supabase_url}/rest/v1/profiles",
        headers=_headers(service_key),
        params={
            "select": "id,email,full_name,gitlab_user_id",
            "gitlab_user_id": "is.null",
            "order": "email.asc",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _fetch_gitlab_users_table(supabase_url: str, service_key: str) -> list[dict[str, Any]]:
    response = requests.get(
        f"{supabase_url}/rest/v1/gitlab_users",
        headers=_headers(service_key),
        params={"select": "id,username,name,email", "order": "id.asc"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _fetch_profiles_with_gitlab_id(
    supabase_url: str, service_key: str
) -> dict[int, str]:
    response = requests.get(
        f"{supabase_url}/rest/v1/profiles",
        headers=_headers(service_key),
        params={"select": "id,email,gitlab_user_id", "gitlab_user_id": "not.is.null"},
        timeout=60,
    )
    response.raise_for_status()
    mapping: dict[int, str] = {}
    for row in response.json():
        gid = row.get("gitlab_user_id")
        if gid is not None:
            mapping[int(gid)] = row.get("email") or row["id"]
    return mapping


def _build_email_to_gitlab_id(
    gitlab_users_rows: list[dict[str, Any]],
    gitlab_api_users: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    email_map: dict[str, int] = {}

    def register(email: str | None, gitlab_id: int, username: str | None = None) -> None:
        if not email:
            return
        key = email.strip().lower()
        if "@" not in key:
            return
        if key in email_map and email_map[key] != gitlab_id:
            return
        email_map[key] = gitlab_id

    for row in gitlab_users_rows:
        register(row.get("email"), int(row["id"]), row.get("username"))

    if gitlab_api_users:
        for user in gitlab_api_users:
            register(user.get("email"), int(user["gitlab_id"]), user.get("username"))

    return email_map


def _update_profile_gitlab_id(
    supabase_url: str,
    service_key: str,
    *,
    profile_id: str,
    gitlab_user_id: int,
) -> None:
    response = requests.patch(
        f"{supabase_url}/rest/v1/profiles?id=eq.{profile_id}",
        headers=_headers(service_key),
        json={"gitlab_user_id": gitlab_user_id},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")


def run_backfill(*, dry_run: bool, from_gitlab_only: bool) -> int:
    _load_dotenv()
    supabase_url, service_key = _supabase_config()

    profiles = _fetch_profiles_without_gitlab_id(supabase_url, service_key)
    if not profiles:
        log.info("OK - Todos os perfis ja possuem gitlab_user_id.")
        return 0

    gitlab_users_rows: list[dict[str, Any]] = []
    if not from_gitlab_only:
        gitlab_users_rows = _fetch_gitlab_users_table(supabase_url, service_key)
        log.info(f"OK - {len(gitlab_users_rows)} registro(s) em gitlab_users")

    gitlab_api_users: list[dict[str, Any]] = []
    api_warnings: list[str] = []
    for attempt in range(3):
        try:
            gitlab_api_users, api_warnings = collect_active_gitlab_users()
            break
        except requests.RequestException as exc:
            if attempt < 2:
                log.warning(f"AVISO - Falha na API GitLab ({exc}); tentando novamente...")
                time.sleep(3 * (attempt + 1))
                continue
            raise
    log.info(f"OK - {len(gitlab_api_users)} usuario(s) ativos na API GitLab")
    for warning in api_warnings:
        log.warning(f"AVISO - {warning}")

    email_map = _build_email_to_gitlab_id(gitlab_users_rows, gitlab_api_users)
    assigned = _fetch_profiles_with_gitlab_id(supabase_url, service_key)

    linked = 0
    skipped = 0
    unmatched: list[str] = []

    log.info(f"\nPerfis sem gitlab_user_id: {len(profiles)}\n")
    log.info(f"{'E-mail':<42} {'Nome':<28} {'GitLab ID':<10} Acao")
    log.info("-" * 95)

    for profile in profiles:
        email = (profile.get("email") or "").strip().lower()
        name = (profile.get("full_name") or profile.get("email") or "?")[:27]
        gitlab_id = email_map.get(email)

        if not gitlab_id:
            unmatched.append(email or profile["id"])
            log.info(f"{email or '(sem e-mail)':<42} {name:<28} {'—':<10} sem match")
            skipped += 1
            continue

        owner = assigned.get(gitlab_id)
        if owner and owner != email:
            log.info(f"{email:<42} {name:<28} {gitlab_id:<10} PULADO (ID ja usado por {owner})")
            skipped += 1
            continue

        if dry_run:
            log.info(f"{email:<42} {name:<28} {gitlab_id:<10} vincularia")
            linked += 1
            continue

        gitlab_row = next((row for row in gitlab_users_rows if int(row["id"]) == gitlab_id), None)
        api_row = next(
            (row for row in gitlab_api_users if int(row["gitlab_id"]) == gitlab_id),
            None,
        )
        _upsert_gitlab_user(
            supabase_url,
            service_key,
            gitlab_id=gitlab_id,
            username=(gitlab_row or {}).get("username") or (api_row or {}).get("username"),
            name=(gitlab_row or {}).get("name")
            or (api_row or {}).get("name")
            or profile.get("full_name"),
            email=email,
        )
        _update_profile_gitlab_id(
            supabase_url,
            service_key,
            profile_id=profile["id"],
            gitlab_user_id=gitlab_id,
        )
        assigned[gitlab_id] = email
        log.info(f"{email:<42} {name:<28} {gitlab_id:<10} VINCULADO")
        linked += 1

    log.info(
        f"\nResumo: {linked} vinculado(s), {skipped} ignorado(s)/sem match."
    )
    if unmatched:
        log.info("\nSem correspondencia por e-mail (vincule manualmente em Admin > Usuarios > ID GitLab):")
        for email in unmatched:
            log.info(f"  - {email}")

    if dry_run:
        log.info("\nDRY-RUN: nenhuma alteracao foi gravada. Rode sem --dry-run para aplicar.")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Vincula profiles.gitlab_user_id por e-mail (GitLab <-> dashboard)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Apenas mostra o que seria atualizado.",
    )
    parser.add_argument(
        "--from-gitlab-only",
        action="store_true",
        help="Ignora gitlab_users do Supabase e usa somente a API GitLab.",
    )
    args = parser.parse_args()
    return run_backfill(dry_run=args.dry_run, from_gitlab_only=args.from_gitlab_only)


if __name__ == "__main__":
    raise SystemExit(main())
