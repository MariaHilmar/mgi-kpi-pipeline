"""Testes do sync_supabase (filtros + cliente HTTP com requests mockado)."""

from __future__ import annotations

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
    def __init__(self, ok=True, status_code=201, text=""):
        self.ok = ok
        self.status_code = status_code
        self.text = text

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
