from status_events import (
    dedupe_event_rows,
    event_rows_from_gitlab_events,
    issue_key_from_raw_issue,
)


def test_issue_key_from_raw_issue():
    key = issue_key_from_raw_issue(
        {"id": "2706", "gitlab_repo": "contratos_v2", "title": "Teste"},
    )
    assert key == "Contratos v2:2706"


def test_event_rows_from_gitlab_events():
    events = [
        {
            "id": 101,
            "created_at": "2026-01-10T12:00:00.000Z",
            "action": "add",
            "label": {"name": "status::Backlog"},
        },
        {
            "id": 102,
            "created_at": "2026-02-15T09:30:00.000Z",
            "action": "remove",
            "label": {"name": "status::Backlog"},
        },
        {
            "id": 103,
            "created_at": "2026-02-15T09:31:00.000Z",
            "action": "add",
            "label": {"name": "status::Doing"},
        },
        {
            "id": 999,
            "created_at": "2026-02-16T10:00:00.000Z",
            "action": "add",
            "label": {"name": "tipo::Bug"},
        },
    ]

    rows = event_rows_from_gitlab_events("Contratos v2:2706", events, estado="Aberto")

    assert len(rows) == 3
    assert rows[0]["event_type"] == "status_add"
    assert rows[0]["status_novo"] == "Backlog"
    assert rows[0]["etapa_nova"] == "Backlog"
    assert rows[2]["status_novo"] == "Doing"
    assert rows[2]["etapa_nova"] == "Em Desenvolvimento"
    assert rows[2]["gitlab_event_id"] == 103


def test_dedupe_event_rows():
    rows = dedupe_event_rows(
        [
            {"gitlab_event_id": 1, "issue_key": "a:1"},
            {"gitlab_event_id": 1, "issue_key": "a:1", "status_novo": "X"},
        ]
    )
    assert len(rows) == 1
