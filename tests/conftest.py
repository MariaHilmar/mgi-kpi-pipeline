"""Fixtures compartilhadas para testes do pipeline MGI."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest


# Baseline "como em CI" (sem .env local). Tests que precisem de outro valor
# devem setá-lo explicitamente (monkeypatch/apply_pipeline_runtime_flags).
_RUNTIME_ENV_VARS = (
    "MGI_CLOSED_EXCLUDE_DAYS",
    "MGI_INITIAL_LOAD",
    "MGI_ALL_MODULES",
    "MGI_REFRESH_MODE",
)
_CONFIG_DEFAULTS = {
    "INITIAL_LOAD": False,
    "ALL_MODULES": False,
    "REFRESH_MODE": "normal",
    "CLOSED_EXCLUDE_DAYS": 60,
}


@pytest.fixture(autouse=True)
def _isolate_runtime_state():
    """Isola o estado global por teste (os.environ + flags do módulo config).

    A coleta importa módulos que acabam carregando o .env local do desenvolvedor
    (ex.: MGI_CLOSED_EXCLUDE_DAYS=0) no os.environ global — e config.closed_exclude_days()
    lê o env em runtime. Sem isolamento, isso muda o comportamento conforme a
    ordem de execução. Aqui forçamos o baseline padrão (como em CI, sem .env) no
    início de cada teste e restauramos o estado original ao final.
    """
    saved_env = dict(os.environ)
    try:
        import config as cfg
    except ImportError:
        cfg = None
    saved_cfg = {a: getattr(cfg, a) for a in _CONFIG_DEFAULTS if cfg and hasattr(cfg, a)}

    for var in _RUNTIME_ENV_VARS:
        os.environ.pop(var, None)
    if cfg is not None:
        for attr, value in _CONFIG_DEFAULTS.items():
            if hasattr(cfg, attr):
                setattr(cfg, attr, value)

    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        if cfg is not None:
            for attr, value in saved_cfg.items():
                setattr(cfg, attr, value)


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
