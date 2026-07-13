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


def _sample_issue() -> dict:
    return {
        "id": "42",
        "gitlab_repo": "contratos_v2",
        "title": "[PNCP] (PNCP) - Teste sync",
        "state": "opened",
        "createdDate": "2025-06-01T10:00:00",
        "labels": [],
        "author": {"name": "Autor"},
        "assignees": [],
        "milestone": {},
    }


def _fake_records() -> list[dict]:
    return [
        {
            "issue_key": "Contratos v2:42",
            "synced_at": "2025-06-01T12:00:00Z",
            "_participants": [],
            "_gitlab_user_meta": [],
        }
    ]


class _FakeSyncClient:
    def __init__(self) -> None:
        self.finish: tuple[str, str] | None = None

    def start_sync_run(self) -> str:
        return "run-1"

    def upsert_gitlab_users(self, rows: list) -> int:
        return len(rows)

    def upsert_issues(self, rows: list) -> int:
        return len(rows)

    def replace_issue_participants(self, issue_keys: list, rows: list) -> int:
        return len(rows)

    def upsert_releases(self, rows: list) -> int:
        return len(rows)

    def finish_sync_run(
        self,
        run_id: str,
        *,
        status: str,
        rows: int,
        releases: int,
        message: str = "",
    ) -> None:
        self.finish = (status, message)


def test_sync_issues_to_supabase_feliz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(s, "_load_dotenv", lambda: None)
    monkeypatch.setattr(s, "resolve_enable_git", lambda requested=True: False)
    monkeypatch.setattr(s, "build_issue_records", lambda issues, enable_git=False: _fake_records())

    fake_client = _FakeSyncClient()
    monkeypatch.setattr(s, "SupabaseSync", lambda url, key: fake_client)

    count = s.sync_issues_to_supabase(
        [_sample_issue()],
        enable_git=False,
        include_releases=False,
    )

    assert count == 1
    assert fake_client.finish == ("success", "sync from gitlab_issues_raw.json")


def test_sync_issues_to_supabase_erro_no_upsert(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(s, "_load_dotenv", lambda: None)
    monkeypatch.setattr(s, "resolve_enable_git", lambda requested=True: False)
    monkeypatch.setattr(s, "build_issue_records", lambda issues, enable_git=False: _fake_records())

    class _FailingClient(_FakeSyncClient):
        def upsert_issues(self, rows: list) -> int:
            raise RuntimeError("falha supabase")

    fake_client = _FailingClient()
    monkeypatch.setattr(s, "SupabaseSync", lambda url, key: fake_client)

    with pytest.raises(RuntimeError, match="falha supabase"):
        s.sync_issues_to_supabase(
            [_sample_issue()],
            enable_git=False,
            include_releases=False,
        )

    assert fake_client.finish == ("error", "falha supabase")


def test_sync_issues_to_supabase_sem_credenciais(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(s, "_load_dotenv", lambda: None)

    with pytest.raises(SystemExit):
        s.sync_issues_to_supabase([_sample_issue()], enable_git=False, include_releases=False)
