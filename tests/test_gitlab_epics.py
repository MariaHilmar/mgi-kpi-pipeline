"""Testes do mapeamento/coleta de epicos GitLab."""

from __future__ import annotations

from gitlab_epics import (
    enriquecer_issues_com_epicos,
    mapear_epic_api,
    mapear_epico_grupo,
)


def test_mapear_epic_api_com_titulo():
    epic = mapear_epic_api(
        {"id": 10, "iid": 5, "title": "Meu Epico", "url": "/groups/x/-/epics/5"},
        epic_iid_fallback=None,
    )
    assert epic == {
        "id": 10,
        "iid": 5,
        "title": "Meu Epico",
        "url": "/groups/x/-/epics/5",
    }


def test_mapear_epic_api_nulo():
    assert mapear_epic_api(None) is None
    assert mapear_epic_api({}) is None


def test_mapear_epico_grupo():
    row = mapear_epico_grupo(
        {
            "id": 5115080,
            "iid": 59,
            "title": "[Gestão] Algo",
            "state": "opened",
            "web_url": "https://gitlab.com/groups/comprasnet/-/epics/59",
            "parent_iid": None,
            "work_item_id": 123,
        }
    )
    assert row["gitlab_epic_id"] == 5115080
    assert row["gitlab_epic_iid"] == 59
    assert row["title"] == "[Gestão] Algo"
    assert row["state"] == "opened"


def test_enriquecer_issues_com_epicos(monkeypatch):
    issues = [
        {"id": "10", "gitlab_id": "100", "gitlab_repo": "contratos_v2", "epic": None},
        {
            "id": "11",
            "gitlab_id": "101",
            "gitlab_repo": "contratos_v2",
            "epic": {"title": "Ja tem"},
        },
    ]
    epics = [
        {
            "gitlab_epic_id": 1,
            "gitlab_epic_iid": 59,
            "title": "Epico Novo",
            "web_url": "https://example/epics/59",
        }
    ]

    def fake_children(epic_iid, **_kwargs):
        assert epic_iid == 59
        return [{"id": 100, "iid": 10}, {"id": 999, "iid": 99}]

    monkeypatch.setattr("gitlab_epics._buscar_issues_do_epico", fake_children)
    filled = enriquecer_issues_com_epicos(issues, epics)
    assert filled == 1
    assert issues[0]["epic"]["title"] == "Epico Novo"
    assert issues[1]["epic"]["title"] == "Ja tem"
