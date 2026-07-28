"""Testes do mapeamento/coleta de epicos GitLab."""

from __future__ import annotations

from gitlab_epics import (
    GraphQLComplexityError,
    _batch_parent_graphql,
    aplicar_epicos_em_issues,
    enriquecer_epicos_via_filhas_grupo,
    enriquecer_epicos_via_parent_hierarchy,
    enriquecer_epicos_via_projetos,
    enriquecer_issues_com_epicos,
    mapear_epic_api,
    mapear_epico_grupo,
    mapear_parent_work_item,
    vinculos_epico_de_issues_json,
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


def test_enriquecer_epicos_via_filhas_grupo_por_repo_iid(monkeypatch):
  issues = [{"id": "1053", "gitlab_repo": "contratos_v2", "epic": None}]
  epics = [
      {
          "gitlab_epic_id": 3928721,
          "gitlab_epic_iid": 30,
          "title": "[Fiscalizacao] Checklist",
          "web_url": "https://gitlab.com/groups/comprasnet/-/epics/30",
      }
  ]

  def fake_children(epic_iid, **_kwargs):
      assert epic_iid == 30
      return [
          {
              "id": 192599460,
              "iid": 1053,
              "web_url": "https://gitlab.com/comprasnet/contratos_v2/-/work_items/1053",
          }
      ]

  monkeypatch.setattr("gitlab_epics._buscar_issues_do_epico", fake_children)
  filled, links = enriquecer_epicos_via_filhas_grupo(issues, epics, token="tok")
  assert filled == 1
  assert issues[0]["epic"]["title"] == "[Fiscalizacao] Checklist"
  assert links[0]["gitlab_iid"] == 1053


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


def test_aplicar_epicos_em_issues_retorna_vinculos(monkeypatch):
    issues = [
        {"id": "10", "gitlab_id": "100", "gitlab_repo": "contratos_v2", "epic": None},
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
        return [
            {
                "id": 100,
                "iid": 10,
                "web_url": "https://gitlab.com/comprasnet/contratos_v2/-/work_items/10",
            }
        ]

    monkeypatch.setattr("gitlab_epics._buscar_issues_do_epico", fake_children)
    filled, links = aplicar_epicos_em_issues(issues, epics)
    assert filled == 1
    assert len(links) == 1
    assert links[0]["gitlab_repo"] == "Contratos v2"
    assert links[0]["gitlab_iid"] == 10
    assert links[0]["epic_title"] == "Epico Novo"


def test_vinculos_epico_de_issues_json():
    issues = [
        {
            "id": "42",
            "gitlab_repo": "contratos_v2",
            "epic": {"id": 1, "title": "[Modulo] Meu epico"},
        }
    ]
    links = vinculos_epico_de_issues_json(issues)
    assert len(links) == 1
    assert links[0]["gitlab_repo"] == "Contratos v2"
    assert links[0]["gitlab_iid"] == 42
    assert links[0]["epic_title"] == "[Modulo] Meu epico"


def test_mapear_parent_work_item():
    epic = mapear_parent_work_item(
        {
            "id": "gid://gitlab/WorkItem/99",
            "iid": "12",
            "title": "[Fiscalização] Checklist",
            "workItemType": "EPIC",
            "webUrl": "https://gitlab.com/groups/comprasnet/-/work_items/12",
        }
    )
    assert epic is not None
    assert epic["title"] == "[Fiscalização] Checklist"
    assert epic["iid"] == 12
    assert epic["id"] == 99
    assert epic["source"] == "parent"


def test_mapear_parent_work_item_tipo_objeto():
    epic = mapear_parent_work_item(
        {
            "id": "gid://gitlab/WorkItem/99",
            "iid": "12",
            "title": "[Fiscalização] Checklist",
            "workItemType": {"name": "Epic"},
            "webUrl": "https://gitlab.com/groups/comprasnet/-/work_items/12",
        }
    )
    assert epic is not None
    assert epic["work_item_type"] == "Epic"


def test_batch_parent_graphql_divide_em_complexidade(monkeypatch):
    calls: list[int] = []

    def fake_once(namespace_full_path, gitlab_iids, *, token=None):
        calls.append(len(gitlab_iids))
        if len(gitlab_iids) > 10:
            raise GraphQLComplexityError("complexity")
        return {iid: {"title": f"Epic {iid}"} for iid in gitlab_iids}

    monkeypatch.setattr("gitlab_epics._batch_parent_graphql_once", fake_once)
    monkeypatch.setattr("gitlab_epics.PARENT_GRAPHQL_BATCH_SIZE", 20)
    found = _batch_parent_graphql("comprasnet/contratos_v2", list(range(1, 16)))
    assert len(found) == 15
    assert 15 in calls
    assert len(calls) >= 2


def test_enriquecer_epicos_via_parent_hierarchy(monkeypatch):
    issues = [
        {"id": "1053", "gitlab_repo": "contratos_v2", "epic": None},
        {"id": "10", "gitlab_repo": "contratos_v2", "epic": {"title": "Ja tem"}},
    ]

    def fake_batch(namespace_full_path, gitlab_iids, *, token=None):
        assert namespace_full_path == "comprasnet/contratos_v2"
        return {
            1053: {
                "title": "[Fiscalização] Checklist de fiscalização",
                "iid": "59",
                "id": "gid://gitlab/WorkItem/59",
                "webUrl": "https://example/epic/59",
            }
        }

    monkeypatch.setattr("gitlab_epics._batch_parent_graphql", fake_batch)
    filled, links = enriquecer_epicos_via_parent_hierarchy(issues, token="tok")
    assert filled == 1
    assert issues[0]["epic"]["title"] == "[Fiscalização] Checklist de fiscalização"
    assert issues[1]["epic"]["title"] == "Ja tem"
    assert len(links) == 1
    assert links[0]["gitlab_iid"] == 1053


def test_enriquecer_epicos_via_projetos(monkeypatch):
    issues = [{"id": "10", "gitlab_repo": "contratos_v2", "epic": None}]

    def fake_rest(repo_slug, gitlab_iid, *, token=None):
        assert repo_slug == "contratos_v2"
        assert gitlab_iid == 10
        return {
            "id": 1,
            "iid": 5,
            "title": "Epico projeto",
            "url": "/epics/5",
            "source": "rest_epic",
        }

    monkeypatch.setattr("gitlab_epics._fetch_epic_rest_issue", fake_rest)
    filled, links = enriquecer_epicos_via_projetos(issues, token="token-teste")
    assert filled == 1
    assert issues[0]["epic"]["title"] == "Epico projeto"
    assert links[0]["epic_title"] == "Epico projeto"
