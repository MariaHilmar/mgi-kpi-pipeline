"""Testes do sync incremental de issues GitLab."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from atualizar_gitlab_issues import (
    _get_gitlab_response,
    _issues_para_enriquecer_merge,
    _mapear_issue_api,
    compute_sync_watermark,
    format_gitlab_datetime,
    index_issues_by_key,
    load_issues_list,
    merge_issues_into_index,
    replace_repo_issues_in_index,
)


def test_format_gitlab_datetime_naive_utc():
    dt = datetime(2026, 6, 26, 14, 30, 0)
    assert format_gitlab_datetime(dt) == "2026-06-26T14:30:00Z"


def test_mapear_issue_api_inclui_epic():
    raw = {
        "id": 193599560,
        "iid": 1350,
        "title": "[PNCP] teste",
        "description": "",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "closed_at": None,
        "state": "opened",
        "author": {"id": 1, "username": "a", "name": "Ana"},
        "assignees": [],
        "milestone": None,
        "labels": [],
        "merge_requests_count": 0,
        "epic_iid": 59,
        "epic": {"id": 10, "iid": 59, "title": "Meu Epico", "url": "/epics/59"},
    }
    mapped = _mapear_issue_api(raw, "contratos_v2")
    assert mapped["epic"]["iid"] == 59
    assert mapped["epic"]["title"] == "Meu Epico"


def test_mapear_issue_api_sem_epic():
    raw = {
        "id": 1,
        "iid": 2,
        "title": "x",
        "description": "",
        "created_at": "",
        "updated_at": "",
        "closed_at": None,
        "state": "opened",
        "author": {},
        "assignees": [],
        "milestone": None,
        "labels": [],
        "merge_requests_count": 0,
        "epic": None,
        "epic_iid": None,
    }
    assert _mapear_issue_api(raw, "contratos_v2")["epic"] is None


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


def test_replace_repo_issues_in_index():
    indexed = index_issues_by_key(
        [
            {"id": "10", "gitlab_repo": "contratos_v2", "title": "v2"},
            {"id": "20", "gitlab_repo": "contratos", "title": "v1 antiga"},
        ]
    )
    fetched = [{"id": "21", "gitlab_repo": "contratos", "title": "v1 nova"}]
    removed = replace_repo_issues_in_index(indexed, fetched, "contratos")
    assert removed == 1
    assert "contratos_v2:10" in indexed
    assert "contratos:20" not in indexed
    assert indexed["contratos:21"]["title"] == "v1 nova"


def test_get_gitlab_response_retries_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    import atualizar_gitlab_issues as agi

    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.Timeout("timed out")
        response = type("Resp", (), {})()
        response.raise_for_status = lambda: None
        response.json = lambda: []
        return response

    monkeypatch.setattr(agi, "DEFAULT_GITLAB_HTTP_RETRIES", 2)
    monkeypatch.setattr(agi, "DEFAULT_GITLAB_HTTP_RETRY_DELAY", 0)
    monkeypatch.setattr(requests, "get", fake_get)

    response = _get_gitlab_response("https://gitlab.com/api/v4/test", headers={}, params={})
    assert response is not None
    assert calls["count"] == 2


def test_issues_para_enriquecer_merge_somente_alteradas_ou_sem_data():
    merged = [
        {"id": "1", "gitlab_repo": "contratos_v2", "mergeado_em": "2026-01-01T00:00:00Z"},
        {"id": "2", "gitlab_repo": "contratos_v2"},
        {"id": "3", "gitlab_repo": "contratos_v2", "mergeado_em": "2026-02-01T00:00:00Z"},
    ]
    changed = [{"id": "3", "gitlab_repo": "contratos_v2"}]
    scope = _issues_para_enriquecer_merge(merged, changed_issues=changed)
    ids = {issue["id"] for issue in scope}
    assert ids == {"2", "3"}
