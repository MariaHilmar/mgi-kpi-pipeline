"""Fixtures compartilhadas para testes do pipeline MGI."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest


@pytest.fixture
def sample_issue_open() -> dict:
    return {
        "id": "1234",
        "gitlab_repo": "contratos_v2",
        "title": "[PNCP] (PNCP) - Integrar envio ao portal",
        "state": "opened",
        "closedDate": "",
        "labels": ["tipo::Melhoria", "status::Em andamento"],
        "assignees": [{"name": "Dev Teste"}],
    }


@pytest.fixture
def sample_issue_closed_recent() -> dict:
    recent = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%dT10:00:00")
    return {
        "id": "5678",
        "gitlab_repo": "contratos",
        "title": "[Empenho] (Minuta de Empenho) - Corrigir cálculo",
        "state": "closed",
        "closedDate": recent,
    }


@pytest.fixture
def sample_issue_closed_old() -> dict:
    old = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%dT10:00:00")
    return {
        "id": "9999",
        "state": "closed",
        "closedDate": old,
    }
