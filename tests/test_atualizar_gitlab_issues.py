"""Testes do sync incremental de issues GitLab."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from atualizar_gitlab_issues import (
    compute_sync_watermark,
    format_gitlab_datetime,
    index_issues_by_key,
    load_issues_list,
    merge_issues_into_index,
)


def test_format_gitlab_datetime_naive_utc():
    dt = datetime(2026, 6, 26, 14, 30, 0)
    assert format_gitlab_datetime(dt) == "2026-06-26T14:30:00Z"


def test_load_issues_list_from_array(tmp_path: Path):
    path = tmp_path / "issues.json"
    path.write_text(json.dumps([{"id": "1", "gitlab_repo": "contratos_v2"}]), encoding="utf-8")
    assert len(load_issues_list(path)) == 1


def test_load_issues_list_from_object(tmp_path: Path):
    path = tmp_path / "issues.json"
    path.write_text(json.dumps({"issues": [{"id": "2"}]}), encoding="utf-8")
    assert load_issues_list(path)[0]["id"] == "2"


def test_index_and_merge_issues():
    local = [
        {"id": "10", "gitlab_repo": "contratos_v2", "title": "Antiga", "state": "opened"},
        {"id": "20", "gitlab_repo": "contratos", "title": "Outra", "state": "opened"},
    ]
    indexed = index_issues_by_key(local)
    fetched = [
        {"id": "10", "gitlab_repo": "contratos_v2", "title": "Atualizada", "state": "opened"},
        {"id": "30", "gitlab_repo": "contratos_v2", "title": "Nova", "state": "opened"},
    ]
    added, updated = merge_issues_into_index(indexed, fetched)
    assert added == 1
    assert updated == 1
    assert indexed["contratos_v2:10"]["title"] == "Atualizada"
    assert "contratos_v2:30" in indexed
    assert indexed["contratos:20"]["title"] == "Outra"


def test_compute_sync_watermark_from_state(tmp_path: Path):
    state = tmp_path / "gitlab_issues_sync_state.json"
    state.write_text(
        json.dumps({"last_sync_at": "2026-06-20T10:00:00Z"}),
        encoding="utf-8",
    )
    watermark = compute_sync_watermark({}, state, overlap_seconds=120)
    assert watermark == datetime(2026, 6, 20, 9, 58, 0)


def test_compute_sync_watermark_from_local_updated_date(tmp_path: Path):
    issues = {
        "contratos_v2:1": {
            "id": "1",
            "gitlab_repo": "contratos_v2",
            "updatedDate": "2026-06-15T08:00:00Z",
        }
    }
    watermark = compute_sync_watermark(issues, tmp_path / "missing.json", overlap_seconds=60)
    assert watermark == datetime(2026, 6, 15, 7, 59, 0)


def test_compute_sync_watermark_since_override():
    watermark = compute_sync_watermark(
        {},
        Path("/nonexistent"),
        since_override="2026-06-01T12:00:00Z",
        overlap_seconds=0,
    )
    assert watermark == datetime(2026, 6, 1, 12, 0, 0)


def test_compute_sync_watermark_invalid_since():
    with pytest.raises(ValueError, match="Data invalida"):
        compute_sync_watermark({}, Path("/nonexistent"), since_override="invalid")


def test_merge_empty_fetch_keeps_local():
    indexed = index_issues_by_key([{"id": "1", "gitlab_repo": "contratos_v2"}])
    added, updated = merge_issues_into_index(indexed, [])
    assert added == 0
    assert updated == 0
    assert len(indexed) == 1
