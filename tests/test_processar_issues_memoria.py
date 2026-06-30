"""Testes do processador de issues em memoria (sem Excel, sem Git)."""

from __future__ import annotations

from datetime import date

import processar_issues_memoria as p
from issue_fields import MANUAL_FIELDS


def _issue(**kwargs):
    base = {
        "id": 1338,
        "gitlab_repo": "contratos_v2",
        "title": "[PNCP] (Envio) Corrigir bug",
        "state": "opened",
        "createdDate": "2025-01-10T09:00:00",
        "closedDate": "",
        "labels": ["tipo::Bug", "priority::Alta", "Parceria::SERPRO"],
        "author": {"id": 101, "username": "ana", "name": "Ana"},
        "assignees": [{"id": 202, "username": "bob", "name": "Bob"}],
        "milestone": {"title": "Sprint 5"},
        "merge_requests_count": 2,
    }
    base.update(kwargs)
    return base


def test_record_basico_sem_git():
    rec = p.build_issue_record(_issue(), today=date(2025, 3, 1))
    assert rec["gitlab_iid"] == 1338
    assert rec["issue_key"] == "Contratos v2:1338"
    assert rec["gitlab_repo"] == "Contratos v2"
    assert rec["repositorio"] == "Contratos v2"
    assert rec["modulo"] == "PNCP"
    assert rec["area_funcional"] == "Envio"
    assert rec["tipo"] == "Bug"  # label tem prioridade
    assert rec["estado"] == "Aberto"
    assert rec["prioridade"] == "Alta"
    assert rec["parceria"] == "SERPRO"
    assert rec["sprint"] == "Sprint 5"
    assert rec["assignee"] == "Bob"
    assert rec["autor"] == "Ana"
    assert rec["gitlab_author_id"] == 101
    assert rec["gitlab_assignee_ids"] == [202]
    assert rec["aberto"] is True
    assert rec["gitlab_mrs"] == 2


def test_issue_key_usa_nome_de_exibicao_contratos_v1():
    rec = p.build_issue_record(_issue(gitlab_repo="contratos", id=42), today=date(2025, 3, 1))
    assert rec["issue_key"] == "Contratos v1:42"
    assert rec["repositorio"] == "Contratos v1"


def test_repo_default_quando_ausente():
    issue = _issue()
    del issue["gitlab_repo"]
    rec = p.build_issue_record(issue, today=date(2025, 3, 1))
    assert rec["issue_key"] == "Contratos v2:1338"


def test_campos_manuais_omitidos():
    rec = p.build_issue_record(_issue(), today=date(2025, 3, 1))
    for campo in MANUAL_FIELDS:
        assert campo not in rec


def test_record_sem_id_retorna_none():
    issue = _issue()
    issue["id"] = ""
    assert p.build_issue_record(issue) is None


def test_tipo_inferido_quando_sem_label():
    issue = _issue(labels=[], title="[PNCP] (Envio) Corrigir bug urgente")

    class _FakeTipo:
        def detect(self, _issue):
            class D:
                tipo = "Bug"

            return D()

    rec = p.build_issue_record(issue, tipo_detector=_FakeTipo(), today=date(2025, 3, 1))
    assert rec["tipo"] == "Bug"


def test_desenvolvedor_usa_assignee_sem_git():
    rec = p.build_issue_record(_issue(), today=date(2025, 3, 1))
    assert rec["desenvolvedor"] == "Bob"
    assert rec["gitlab_developer_id"] == 202
    assert rec["dev_tem_branch"] == "Não"


def test_build_records_dedupe_por_issue_key():
    issues = [
        _issue(id=1, title="[PNCP] (Envio) Primeira"),
        _issue(id=1, title="[PNCP] (Envio) Segunda"),  # mesma key, ultima vence
        _issue(id=2, title="[Jobs] (Jobs) Outra"),
    ]
    records = p.build_issue_records(issues, enable_git=False, today=date(2025, 3, 1))
    assert len(records) == 2
    by_key = {r["issue_key"]: r for r in records}
    assert by_key["Contratos v2:1"]["titulo"] == "[PNCP] (Envio) Segunda"


def test_build_records_chaves_consistentes():
    """Todos os registros precisam do mesmo conjunto de chaves (upsert em lote)."""
    issues = [
        _issue(id=1, state="opened", closedDate=""),
        _issue(id=2, state="closed", closedDate="2025-02-01T10:00:00"),
    ]
    records = p.build_issue_records(issues, enable_git=False, today=date(2025, 3, 1))
    assert {tuple(sorted(r)) for r in records} == {tuple(sorted(records[0]))}
