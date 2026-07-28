"""Testes para config.py (parsers de env vars)."""

from __future__ import annotations

import os

import pytest

import config


class TestParsePathRepoPairs:
    def test_um_par(self) -> None:
        raw = r"/data/contratos_v2=contratos_v2"
        assert config._parse_path_repo_pairs(raw) == [
            ("/data/contratos_v2", "contratos_v2"),
        ]

    def test_multiplos_pares(self) -> None:
        raw = (
            r"/data/contratos_v2=contratos_v2;"
            r"/data/contratos=contratos"
        )
        assert config._parse_path_repo_pairs(raw) == [
            ("/data/contratos_v2", "contratos_v2"),
            ("/data/contratos", "contratos"),
        ]

    def test_vazio(self) -> None:
        assert config._parse_path_repo_pairs("") == []


class TestParseRepoPathMap:
    def test_mapa_wsl(self) -> None:
        raw = "contratos_v2=/root/MGI/contratos_v2;contratos=/root/MGI/contratos"
        assert config._parse_repo_path_map(raw) == {
            "contratos_v2": "/root/MGI/contratos_v2",
            "contratos": "/root/MGI/contratos",
        }

    def test_vazio(self) -> None:
        assert config._parse_repo_path_map("") == {}


class TestGitlabTokenForRepo:
    def test_global_token_vale_para_ambos_repos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITLAB_TOKEN", "global-token")
        monkeypatch.setenv("GITLAB_TOKEN_CONTRATOS_V2", "v2-only")
        monkeypatch.setenv("GITLAB_TOKEN_CONTRATOS", "v1-only")
        assert config.gitlab_token_for_repo("contratos_v2") == "global-token"
        assert config.gitlab_token_for_repo("contratos") == "global-token"

    def test_token_por_repo_sem_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setenv("GITLAB_TOKEN_CONTRATOS_V2", "v2-only")
        monkeypatch.setenv("GITLAB_TOKEN_CONTRATOS", "v1-only")
        assert config.gitlab_token_for_repo("contratos_v2") == "v2-only"
        assert config.gitlab_token_for_repo("contratos") == "v1-only"


class TestApplyPipelineRuntimeFlags:
    def test_flags_ativam_env_e_modulo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import config as cfg

        old_initial = cfg.INITIAL_LOAD
        old_all = cfg.ALL_MODULES
        old_refresh = cfg.REFRESH_MODE
        try:
            monkeypatch.delenv("MGI_INITIAL_LOAD", raising=False)
            monkeypatch.delenv("MGI_ALL_MODULES", raising=False)
            monkeypatch.delenv("MGI_REFRESH_MODE", raising=False)
            cfg.INITIAL_LOAD = False
            cfg.ALL_MODULES = False
            cfg.REFRESH_MODE = ""

            cfg.apply_pipeline_runtime_flags(
                all_modules=True,
                initial_load=True,
                full_refresh=True,
            )

            assert os.environ["MGI_INITIAL_LOAD"] == "1"
            assert os.environ["MGI_ALL_MODULES"] == "1"
            assert os.environ["MGI_REFRESH_MODE"] == "full"
            assert cfg.INITIAL_LOAD is True
            assert cfg.ALL_MODULES is True
            assert cfg.REFRESH_MODE == "full"
        finally:
            cfg.INITIAL_LOAD = old_initial
            cfg.ALL_MODULES = old_all
            cfg.REFRESH_MODE = old_refresh
            monkeypatch.delenv("MGI_INITIAL_LOAD", raising=False)
            monkeypatch.delenv("MGI_ALL_MODULES", raising=False)
            monkeypatch.delenv("MGI_REFRESH_MODE", raising=False)
