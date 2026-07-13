"""Testes do pipeline_maestro (orquestracao com dependencias mockadas)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pipeline_maestro as pm


def _sample_issue() -> dict:
    return {
        "id": "1",
        "gitlab_repo": "contratos_v2",
        "title": "[PNCP] (PNCP) - Issue teste",
        "state": "opened",
        "createdDate": "2025-06-01T10:00:00",
        "labels": [],
        "author": {"name": "Autor"},
        "assignees": [],
        "milestone": {},
    }


@pytest.fixture
def pipeline_config(tmp_path: Path) -> dict:
    issues_json = tmp_path / "gitlab_issues_raw.json"
    issues_json.write_text(json.dumps([_sample_issue()]), encoding="utf-8")
    return {
        "repo_path": "",
        "output_dir": str(tmp_path),
        "issues_json_path": str(issues_json),
    }


def test_executar_pipeline_feliz(pipeline_config: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pm, "limpar_logs_antigos", lambda output_dir: 0)
    monkeypatch.setattr(pm, "validar_json_local", lambda path: None)
    monkeypatch.setattr(pm, "sync_issues_to_supabase", lambda issues, **kwargs: len(issues))

    maestro = pm.PipelineMaestro(pipeline_config)
    monkeypatch.setattr(maestro, "executar_coleta_git", lambda: None)

    assert maestro.executar_pipeline() is True
    assert maestro.issues_sincronizadas == 1


def test_executar_pipeline_falha_sem_issues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    issues_json = tmp_path / "gitlab_issues_raw.json"
    issues_json.write_text("[]", encoding="utf-8")
    config = {
        "repo_path": "",
        "output_dir": str(tmp_path),
        "issues_json_path": str(issues_json),
    }

    monkeypatch.setattr(pm, "limpar_logs_antigos", lambda output_dir: 0)
    monkeypatch.setattr(pm, "validar_json_local", lambda path: None)

    maestro = pm.PipelineMaestro(config)
    monkeypatch.setattr(maestro, "executar_coleta_git", lambda: None)

    assert maestro.executar_pipeline() is False


def test_executar_pipeline_falha_sync(pipeline_config: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pm, "limpar_logs_antigos", lambda output_dir: 0)
    monkeypatch.setattr(pm, "validar_json_local", lambda path: None)

    def _falha_sync(issues, **kwargs):
        raise RuntimeError("sync indisponivel")

    monkeypatch.setattr(pm, "sync_issues_to_supabase", _falha_sync)

    maestro = pm.PipelineMaestro(pipeline_config)
    monkeypatch.setattr(maestro, "executar_coleta_git", lambda: None)

    assert maestro.executar_pipeline() is False
