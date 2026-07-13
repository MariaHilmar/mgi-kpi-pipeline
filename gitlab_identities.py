#!/usr/bin/env python3
"""Sincroniza gitlab_users e issue_participants a partir dos registros de issues."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    email = value.strip().lower()
    if "@" not in email or email.endswith("@users.noreply.gitlab.com"):
        return None
    return email


def gitlab_user_row(
    *,
    user_id: int,
    username: str | None = None,
    name: str | None = None,
    email: str | None = None,
    synced_at: str,
) -> dict[str, Any]:
    return {
        "id": user_id,
        "username": (username or f"user-{user_id}").strip(),
        "name": (name or "").strip() or None,
        "email": _normalize_email(email),
        "synced_at": synced_at,
    }


def collect_gitlab_users_from_records(records: Iterable[dict[str, Any]], synced_at: str) -> list[dict[str, Any]]:
    """Agrega usuarios unicos a partir de metadados embutidos nos registros."""
    users: dict[int, dict[str, Any]] = {}

    def merge(user_id: int, **fields: Any) -> None:
        current = users.setdefault(
            user_id,
            gitlab_user_row(user_id=user_id, synced_at=synced_at),
        )
        for key, value in fields.items():
            if not value:
                continue
            if key == "username" and str(current.get("username", "")).startswith("user-"):
                current[key] = value
            elif not current.get(key):
                current[key] = value

    for record in records:
        for meta in record.get("_gitlab_user_meta") or []:
            uid = _parse_int(meta.get("id"))
            if not uid:
                continue
            merge(
                uid,
                username=meta.get("username"),
                name=meta.get("name"),
                email=meta.get("email"),
            )

    return list(users.values())


def build_participant_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        issue_key = record.get("issue_key")
        if not issue_key:
            continue
        for participant in record.get("_participants") or []:
            uid = _parse_int(participant.get("gitlab_user_id"))
            role = participant.get("role")
            if not uid or role not in {"author", "assignee", "developer"}:
                continue
            rows.append(
                {
                    "issue_key": issue_key,
                    "role": role,
                    "gitlab_user_id": uid,
                    "is_primary": bool(participant.get("is_primary")),
                    "source": participant.get("source") or "gitlab_api",
                    "display_name": participant.get("display_name") or None,
                }
            )
    return rows


def strip_internal_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def prepare_issue_rows_for_upsert(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [strip_internal_fields(record) for record in records]


def resolve_developer_gitlab_id(
    *,
    dev_author_email: str | None,
    dev_author_name: str | None,
    assignee_ids: list[int],
    users_by_id: dict[int, dict[str, Any]],
    users_by_email: dict[str, int],
    users_by_name: dict[str, int],
) -> tuple[int | None, str]:
    """Resolve desenvolvedor principal para gitlab_user_id. Retorna (id, source)."""
    email = _normalize_email(dev_author_email)
    if email and email in users_by_email:
        return users_by_email[email], "git_commits"

    name = (dev_author_name or "").strip().lower()
    if name and name in users_by_name:
        return users_by_name[name], "git_commits"

    if assignee_ids:
        first = assignee_ids[0]
        if first in users_by_id:
            return first, "assignee_fallback"

    return None, ""


def enrich_records_with_developer_ids(records: list[dict[str, Any]]) -> None:
    """Preenche gitlab_developer_id e participante developer in-place."""
    users_by_id: dict[int, dict[str, Any]] = {}
    users_by_email: dict[str, int] = {}
    users_by_name: dict[str, int] = {}

    for record in records:
        for meta in record.get("_gitlab_user_meta") or []:
            uid = _parse_int(meta.get("id"))
            if not uid:
                continue
            users_by_id[uid] = meta
            email = _normalize_email(meta.get("email"))
            if email:
                users_by_email.setdefault(email, uid)
            name = (meta.get("name") or "").strip().lower()
            if name:
                users_by_name.setdefault(name, uid)

    for record in records:
        assignee_ids = list(record.get("gitlab_assignee_ids") or [])
        dev_id, source = resolve_developer_gitlab_id(
            dev_author_email=record.get("_dev_author_email"),
            dev_author_name=record.get("dev_autor_dev") or record.get("desenvolvedor"),
            assignee_ids=assignee_ids,
            users_by_id=users_by_id,
            users_by_email=users_by_email,
            users_by_name=users_by_name,
        )
        if not dev_id:
            continue

        record["gitlab_developer_id"] = dev_id
        participants = list(record.get("_participants") or [])
        if not any(p.get("role") == "developer" and p.get("gitlab_user_id") == dev_id for p in participants):
            participants.append(
                {
                    "role": "developer",
                    "gitlab_user_id": dev_id,
                    "is_primary": True,
                    "source": source or "git_commits",
                    "display_name": record.get("desenvolvedor") or record.get("dev_autor_dev") or "",
                }
            )
        record["_participants"] = participants


def issue_keys_from_records(records: Iterable[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for record in records:
        key = record.get("issue_key")
        if key and key not in seen:
            seen.add(key)
            keys.append(str(key))
    return keys
