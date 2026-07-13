#!/usr/bin/env python3
"""Filtros de issues para o pipeline MGI."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

try:
    import config
except ImportError:
    config = None


def parse_issue_datetime(date_str: str | None) -> datetime | None:
    """Parse datas GitLab (ISO 8601 ou formato humanizado)."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00").split("+")[0].strip())
    except (ValueError, AttributeError):
        pass
    try:
        clean = re.sub(
            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*",
            "",
            date_str,
        )
        clean = re.sub(r"\s+GMT[+-]\d+", "", clean)
        return datetime.strptime(clean, "%B %d, %Y at %I:%M:%S %p")
    except (ValueError, TypeError):
        return None


def _closed_exclude_days() -> int:
    if config is not None and hasattr(config, "closed_exclude_days"):
        return config.closed_exclude_days()
    if config is not None:
        return int(getattr(config, "CLOSED_EXCLUDE_DAYS", 60))
    return 60


def filtrar_issues_fechadas_antigas(
    issues: list[dict],
    days: int | None = None,
) -> tuple[list[dict], int]:
    """Exclui issues fechadas ha mais de N dias. Mantem abertas e fechadas recentes."""
    exclude_days = _closed_exclude_days() if days is None else days
    if exclude_days <= 0:
        return issues, 0

    cutoff = datetime.now() - timedelta(days=exclude_days)
    kept: list[dict] = []
    excluded = 0

    for issue in issues:
        if issue.get("state") != "closed":
            kept.append(issue)
            continue

        closed = parse_issue_datetime(issue.get("closedDate", ""))
        if closed is None or closed >= cutoff:
            kept.append(issue)
        else:
            excluded += 1

    return kept, excluded
