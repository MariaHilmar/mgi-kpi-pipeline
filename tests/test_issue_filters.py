"""Testes para issue_filters.py."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from issue_filters import filtrar_issues_fechadas_antigas, parse_issue_datetime


class TestParseIssueDatetime:
    def test_iso8601(self) -> None:
        result = parse_issue_datetime("2026-06-02T09:23:58Z")
        assert result == datetime(2026, 6, 2, 9, 23, 58)

    def test_iso8601_com_offset(self) -> None:
        result = parse_issue_datetime("2026-06-02T09:23:58+00:00")
        assert result == datetime(2026, 6, 2, 9, 23, 58)

    def test_formato_humanizado(self) -> None:
        raw = "Tuesday, June 2, 2026 at 9:23:58 AM GMT-3"
        result = parse_issue_datetime(raw)
        assert result == datetime(2026, 6, 2, 9, 23, 58)

    def test_vazio_ou_invalido(self) -> None:
        assert parse_issue_datetime("") is None
        assert parse_issue_datetime(None) is None
        assert parse_issue_datetime("data-invalida") is None


class TestFiltrarIssuesFechadasAntigas:
    def test_mantem_abertas(self, sample_issue_open: dict) -> None:
        kept, excluded = filtrar_issues_fechadas_antigas([sample_issue_open], days=60)
        assert kept == [sample_issue_open]
        assert excluded == 0

    def test_exclui_fechadas_antigas(self, sample_issue_closed_old: dict) -> None:
        kept, excluded = filtrar_issues_fechadas_antigas(
            [sample_issue_closed_old], days=60
        )
        assert kept == []
        assert excluded == 1

    def test_mantem_fechadas_recentes(self, sample_issue_closed_recent: dict) -> None:
        kept, excluded = filtrar_issues_fechadas_antigas(
            [sample_issue_closed_recent], days=60
        )
        assert kept == [sample_issue_closed_recent]
        assert excluded == 0

    def test_mantem_fechada_sem_data(self) -> None:
        issue = {"state": "closed", "closedDate": ""}
        kept, excluded = filtrar_issues_fechadas_antigas([issue], days=60)
        assert kept == [issue]
        assert excluded == 0

    def test_days_zero_desativa_filtro(self, sample_issue_closed_old: dict) -> None:
        kept, excluded = filtrar_issues_fechadas_antigas(
            [sample_issue_closed_old], days=0
        )
        assert kept == [sample_issue_closed_old]
        assert excluded == 0

    def test_mistura_de_estados(
        self,
        sample_issue_open: dict,
        sample_issue_closed_recent: dict,
        sample_issue_closed_old: dict,
    ) -> None:
        issues = [sample_issue_open, sample_issue_closed_recent, sample_issue_closed_old]
        kept, excluded = filtrar_issues_fechadas_antigas(issues, days=60)
        assert len(kept) == 2
        assert excluded == 1
