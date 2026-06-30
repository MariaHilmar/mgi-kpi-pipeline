from gitlab_identities import (
    build_participant_rows,
    collect_gitlab_users_from_records,
    enrich_records_with_developer_ids,
    prepare_issue_rows_for_upsert,
    resolve_developer_gitlab_id,
)


def test_collect_gitlab_users_from_records():
    records = [
        {
            "issue_key": "Contratos v2:1",
            "synced_at": "2026-01-01T00:00:00Z",
            "_gitlab_user_meta": [
                {"id": 10, "username": "ana", "name": "Ana", "email": "ana@example.com"},
            ],
        }
    ]
    users = collect_gitlab_users_from_records(records, "2026-01-01T00:00:00Z")
    assert len(users) == 1
    assert users[0]["id"] == 10
    assert users[0]["username"] == "ana"
    assert users[0]["email"] == "ana@example.com"


def test_build_participant_rows():
    records = [
        {
            "issue_key": "Contratos v2:1",
            "_participants": [
                {
                    "role": "author",
                    "gitlab_user_id": 10,
                    "is_primary": True,
                    "source": "gitlab_api",
                    "display_name": "Ana",
                }
            ],
        }
    ]
    rows = build_participant_rows(records)
    assert rows == [
        {
            "issue_key": "Contratos v2:1",
            "role": "author",
            "gitlab_user_id": 10,
            "is_primary": True,
            "source": "gitlab_api",
            "display_name": "Ana",
        }
    ]


def test_prepare_issue_rows_strips_internal_fields():
    rows = prepare_issue_rows_for_upsert(
        [{"issue_key": "x", "autor": "Ana", "_participants": [], "gitlab_author_id": 1}]
    )
    assert rows == [{"issue_key": "x", "autor": "Ana", "gitlab_author_id": 1}]


def test_resolve_developer_by_email():
    dev_id, source = resolve_developer_gitlab_id(
        dev_author_email="dev@example.com",
        dev_author_name="Dev",
        assignee_ids=[99],
        users_by_id={5: {"email": "dev@example.com"}},
        users_by_email={"dev@example.com": 5},
        users_by_name={},
    )
    assert dev_id == 5
    assert source == "git_commits"


def test_enrich_records_with_developer_ids():
    records = [
        {
            "issue_key": "Contratos v2:1",
            "gitlab_assignee_ids": [202],
            "desenvolvedor": "Bob",
            "dev_autor_dev": "Bob",
            "_dev_author_email": "bob@example.com",
            "_gitlab_user_meta": [
                {"id": 202, "username": "bob", "name": "Bob", "email": "bob@example.com"}
            ],
            "_participants": [],
        }
    ]
    enrich_records_with_developer_ids(records)
    assert records[0]["gitlab_developer_id"] == 202
    assert any(p["role"] == "developer" for p in records[0]["_participants"])
