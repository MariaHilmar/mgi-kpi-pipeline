"""Testes para issue_keys.py."""

from __future__ import annotations

import pytest

from issue_keys import (
    DEFAULT_GITLAB_REPO,
    get_gitlab_repo,
    gitlab_work_item_url,
    lookup_issue,
    make_issue_key,
    make_key_from_parts,
    normalize_repo,
    parse_issue_key,
    repo_display_name,
    summarize_issues_by_repo,
    wsl_path_for_repo,
)


class TestNormalizeRepo:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", DEFAULT_GITLAB_REPO),
            ("Contratos v2", "contratos_v2"),
            ("contratos v1", "contratos"),
            ("contratos_v2", "contratos_v2"),
            ("contratos", "contratos"),
            ("Contrato v1", "contratos"),
            ("outro_repo", "outro_repo"),
        ],
    )
    def test_aliases_e_default(self, raw: str, expected: str) -> None:
        assert normalize_repo(raw) == expected


class TestIssueKey:
    def test_make_issue_key_com_repo(self) -> None:
        issue = {"id": "42", "gitlab_repo": "contratos"}
        assert make_issue_key(issue) == "contratos:42"

    def test_make_issue_key_default_repo(self) -> None:
        issue = {"id": "42"}
        assert make_issue_key(issue) == f"{DEFAULT_GITLAB_REPO}:42"

    def test_make_key_from_parts(self) -> None:
        assert make_key_from_parts("contratos_v2", "100") == "contratos_v2:100"

    def test_parse_issue_key_composta(self) -> None:
        assert parse_issue_key("contratos:123") == ("contratos", "123")

    def test_parse_issue_key_sem_repo(self) -> None:
        assert parse_issue_key("123") == (DEFAULT_GITLAB_REPO, "123")

    def test_get_gitlab_repo_fallback_repositorio(self) -> None:
        issue = {"repositorio": "contratos", "id": "1"}
        assert get_gitlab_repo(issue) == "contratos"


class TestLookupIssue:
    def test_lookup_direto(self) -> None:
        issue = {"id": "10", "title": "Teste"}
        issues = {"contratos_v2:10": issue}
        assert lookup_issue(issues, "contratos_v2:10") is issue

    def test_lookup_repo_alternativo(self) -> None:
        issue = {"id": "10", "title": "Teste"}
        issues = {"contratos:10": issue}
        assert lookup_issue(issues, "contratos_v2:10") is issue

    def test_lookup_inexistente(self) -> None:
        assert lookup_issue({}, "contratos_v2:999") is None


class TestUrlsAndDisplay:
    def test_gitlab_work_item_url(self) -> None:
        url = gitlab_work_item_url("contratos_v2", "123")
        assert url == "https://gitlab.com/comprasnet/contratos_v2/-/work_items/123"

    def test_repo_display_name(self) -> None:
        assert repo_display_name("Contratos v2") == "Contratos v2"

    def test_wsl_path_for_repo(self) -> None:
        assert wsl_path_for_repo("contratos_v2") == "/root/MGI/contratos_v2"


class TestSummarizeIssuesByRepo:
    def test_contagem_por_repo(self) -> None:
        issues = [
            {"gitlab_repo": "contratos_v2", "id": "1"},
            {"gitlab_repo": "contratos_v2", "id": "2"},
            {"repositorio": "contratos", "id": "3"},
            {"id": "4"},
        ]
        counts, missing = summarize_issues_by_repo(issues)
        assert counts["contratos_v2"] == 3  # 2 explicitos + 1 default
        assert counts["contratos"] == 1
        assert missing == 1
        assert sum(counts.values()) == 4
