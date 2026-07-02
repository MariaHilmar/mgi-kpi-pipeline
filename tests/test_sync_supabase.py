"""Testes do sync_supabase (filtros + cliente HTTP com requests mockado)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

import sync_supabase as s


def test_filter_remove_fechadas_antigas_e_antes_do_corte():
    antiga_fechada = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%dT10:00:00")
    issues = [
        {"id": 1, "state": "opened", "createdDate": "2025-01-01T10:00:00"},
        {"id": 2, "state": "closed", "createdDate": "2025-01-01T10:00:00", "closedDate": antiga_fechada},
        {"id": 3, "state": "opened", "createdDate": "2020-01-01T10:00:00"},  # antes do corte
    ]
    kept = s._filter_issues_for_sync(issues)
    ids = {i["id"] for i in kept}
    assert ids == {1}


def test_filter_mantem_sem_data_criacao():
    issues = [{"id": 9, "state": "opened", "createdDate": ""}]
    kept = s._filter_issues_for_sync(issues)
    assert len(kept) == 1


class _FakeResponse:
    def __init__(self, ok=True, status_code=201, text="", json_data=None):
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text) if self.text else []

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.text)


def test_upsert_issues_chunking(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(len(json))
        return _FakeResponse(ok=True)

    monkeypatch.setattr(s.requests, "post", fake_post)
    client = s.SupabaseSync("https://x.supabase.co", "key")
    rows = [{"issue_key": f"k:{i}"} for i in range(450)]
    total = client.upsert_issues(rows)
    assert total == 450
    assert calls == [200, 200, 50]


def test_upsert_issues_erro_lança(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(ok=False, status_code=400, text="erro")

    monkeypatch.setattr(s.requests, "post", fake_post)
    client = s.SupabaseSync("https://x.supabase.co", "key")
    with pytest.raises(RuntimeError):
        client.upsert_issues([{"issue_key": "k:1"}])


def test_upsert_issues_vazio_retorna_zero(monkeypatch):
    client = s.SupabaseSync("https://x.supabase.co", "key")
    assert client.upsert_issues([]) == 0


def test_cutoff_date_default():
    assert s._cutoff_date() == datetime(2024, 1, 1)


def test_supabase_row_to_raw_issue():
    raw = s.supabase_row_to_raw_issue(
        {
            "issue_key": "Contratos v2:2706",
            "gitlab_iid": 2706,
            "gitlab_repo": "Contratos v2",
            "estado": "Aberto",
            "criado_em": "2026-02-15T09:30:00+00:00",
            "fechado_em": None,
        }
    )
    assert raw["id"] == "2706"
    assert raw["gitlab_repo"] == "contratos_v2"
    assert raw["state"] == "opened"
    assert raw["createdDate"].startswith("2026-02-15")


def test_build_fetch_jobs_aceita_repo_display_name():
    from status_events import _build_fetch_jobs

    issues = [
        {
            "id": "2706",
            "gitlab_repo": "Contratos v2",
            "state": "opened",
        },
        {
            "id": "100",
            "gitlab_repo": "Contratos v1",
            "state": "closed",
        },
    ]
    jobs, stats = _build_fetch_jobs(issues, len(issues))
    assert stats["issues_skipped_no_project"] == 0
    assert len(jobs) == 2
    assert jobs[0].issue_key == "Contratos v2:2706"
    assert jobs[1].issue_key == "Contratos v1:100"


def test_issues_for_status_events_from_sync_incremental(monkeypatch, tmp_path):
    rows = [
        {"issue_key": "Contratos v2:1", "gitlab_iid": 1, "gitlab_repo": "Contratos v2", "estado": "Aberto"},
        {"issue_key": "Contratos v2:2", "gitlab_iid": 2, "gitlab_repo": "Contratos v2", "estado": "Aberto"},
    ]
    state_path = tmp_path / "gitlab_issues_sync_state.json"
    state_path.write_text(
        json.dumps({"status_event_issue_keys": ["Contratos v2:2"]}),
        encoding="utf-8",
    )
    issues_json = tmp_path / "gitlab_issues_raw.json"
    issues_json.write_text("[]", encoding="utf-8")

    monkeypatch.setenv("MGI_STATUS_EVENTS_INCREMENTAL", "1")
    monkeypatch.setattr(s, "_issues_json_path", lambda explicit=None: issues_json)
    monkeypatch.setattr(s, "_sync_state_path", lambda json_path=None: state_path)

    targeted = s.issues_for_status_events_from_sync(rows)
    assert len(targeted) == 1
    assert targeted[0]["id"] == "2"
    assert targeted[0]["gitlab_repo"] == "contratos_v2"


def test_issues_for_status_events_from_sync_sem_incremental(monkeypatch):
    rows = [
        {"issue_key": "Contratos v1:9", "gitlab_iid": 9, "gitlab_repo": "Contratos v1", "estado": "Fechado"},
    ]
    monkeypatch.delenv("MGI_STATUS_EVENTS_INCREMENTAL", raising=False)
    targeted = s.issues_for_status_events_from_sync(rows)
    assert len(targeted) == 1
    assert targeted[0]["gitlab_repo"] == "contratos"


def test_fetch_all_issues_for_status_events_pagina(monkeypatch):
    pages = [
        [
            {
                "issue_key": "Contratos v2:1",
                "gitlab_iid": 1,
                "gitlab_repo": "Contratos v2",
                "estado": "Fechado",
                "criado_em": "2025-01-01T00:00:00+00:00",
                "fechado_em": "2025-02-01T00:00:00+00:00",
            }
        ],
        [],
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        offset = int(params.get("offset", 0))
        batch = pages[0] if offset == 0 else pages[1]
        return _FakeResponse(ok=True, json_data=batch)

    monkeypatch.setattr(s.requests, "get", fake_get)
    client = s.SupabaseSync("https://x.supabase.co", "key")
    rows = client.fetch_all_issues_for_status_events(page_size=1000)
    assert len(rows) == 1
    assert rows[0]["state"] == "closed"
    assert rows[0]["id"] == "1"
