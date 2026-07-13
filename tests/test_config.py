"""Testes para config.py (parsers de env vars)."""

from __future__ import annotations

import config


class TestParsePathRepoPairs:
    def test_um_par(self) -> None:
        raw = r"\\wsl.localhost\Ubuntu\root\MGI\contratos_v2=contratos_v2"
        assert config._parse_path_repo_pairs(raw) == [
            ("<path-contratos_v2>", "contratos_v2"),
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
