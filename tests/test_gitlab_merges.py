"""Testes da coleta de datas de merge via API GitLab."""

from __future__ import annotations

import gitlab_merges
from gitlab_merges import enriquecer_issues_com_merge_dates, merged_at_for_issue


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, headers=None, timeout=None):
        for iid, payload in self.mapping.items():
            if f"/issues/{iid}/" in url:
                return _FakeResp(payload)
        return _FakeResp([], status=404)


def test_merged_at_pega_maior_entre_mergeados():
    session = _FakeSession(
        {
            1410: [
                {"state": "merged", "merged_at": "2026-07-01T10:00:00.000Z"},
                {"state": "merged", "merged_at": "2026-07-05T12:00:00.000Z"},
                {"state": "opened", "merged_at": None},
            ]
        }
    )
    assert (
        merged_at_for_issue(1410, "contratos_v2", token="t", session=session)
        == "2026-07-05T12:00:00.000Z"
    )


def test_merged_at_sem_merge_retorna_none():
    session = _FakeSession({1409: [{"state": "opened", "merged_at": None}]})
    assert merged_at_for_issue(1409, "contratos_v2", token="t", session=session) is None


def test_enriquecer_issues_preenche_mergeado_em(monkeypatch):
    issues = [
        {"id": "1410", "gitlab_repo": "contratos_v2", "merge_requests_count": 1},
        {"id": "1409", "gitlab_repo": "contratos_v2", "merge_requests_count": 0},  # ignorada
        {"id": "1408", "gitlab_repo": "contratos_v2", "merge_requests_count": 2},
    ]

    def fake_merged_at(iid, repo, **_kwargs):
        return "2026-07-05T12:00:00.000Z" if iid == 1410 else None

    monkeypatch.setattr(gitlab_merges, "merged_at_for_issue", fake_merged_at)
    filled = enriquecer_issues_com_merge_dates(issues)

    assert filled == 1
    assert issues[0]["mergeado_em"] == "2026-07-05T12:00:00.000Z"
    assert "mergeado_em" not in issues[1]
    assert "mergeado_em" not in issues[2]
