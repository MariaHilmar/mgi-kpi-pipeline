"""Testes para process_gitlab_issues_v2.py (funcoes puras)."""

from __future__ import annotations

from datetime import datetime

import pytest

from process_gitlab_issues_v2 import (
    _format_assignees,
    _map_estado,
    _modulo_permitido,
    _parse_labels,
    extract_functional_area,
    extract_module,
    parse_date,
)


class TestParseDate:
    def test_iso8601(self) -> None:
        assert parse_date("2026-06-02T09:23:58Z") == datetime(2026, 6, 2, 9, 23, 58)

    def test_formato_humanizado(self) -> None:
        raw = "Tuesday, June 2, 2026 at 9:23:58 AM GMT-3"
        assert parse_date(raw) == datetime(2026, 6, 2, 9, 23, 58)

    def test_invalido(self) -> None:
        assert parse_date("nao-e-data") is None
        assert parse_date("") is None


class TestExtractModule:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("[PNCP] (PNCP) - Enviar", "PNCP"),
            ("[Empenho] (Minuta de Empenho) - Ajuste", "Minuta de Empenho"),
            ("[Contratos] (Gestão Contratual) - CRUD", "Gestão Contratual"),
            ("Titulo sem tag", ""),
        ],
    )
    def test_extracao(self, title: str, expected: str) -> None:
        assert extract_module(title) == expected


class TestExtractFunctionalArea:
    def test_area_explicita(self) -> None:
        title = "[PNCP] (PNCP) - Integrar envio"
        assert extract_functional_area(title) == "PNCP"

    def test_area_com_prefixo_hifen(self) -> None:
        title = "[IC] (- Instrumento de Cobrança) - Ajuste"
        assert extract_functional_area(title) == "Instrumento de Cobrança"

    def test_sem_area(self) -> None:
        assert extract_functional_area("[PNCP] Enviar dados") == ""


class TestMapEstado:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("opened", "Aberto"),
            ("closed", "Fechado"),
            ("unknown", "unknown"),
            (None, ""),
        ],
    )
    def test_mapeamento(self, state: str | None, expected: str) -> None:
        assert _map_estado(state) == expected


class TestParseLabels:
    def test_labels_completas(self) -> None:
        labels = [
            "tipo::Bug",
            "status::Em andamento",
            "Equipe::Alpha",
            "Parceria::Beta",
            "priority::high",
            "Solicitante::Maria",
            "Alteração Escopo",
        ]
        parsed = _parse_labels(labels)
        assert parsed["tipo"] == "Bug"
        assert parsed["status"] == "Em andamento"
        assert parsed["equipe"] == "Alpha"
        assert parsed["parceria"] == "Beta"
        assert parsed["prioridade"] == "high"
        assert parsed["solicitante"] == "Maria"
        assert parsed["alteracao_escopo"] == "Sim"

    def test_labels_vazias(self) -> None:
        parsed = _parse_labels([])
        assert parsed["tipo"] == ""
        assert parsed["alteracao_escopo"] == "Não"


class TestFormatAssignees:
    def test_lista_de_nomes(self) -> None:
        issue = {
            "assignees": [
                {"name": "Alice"},
                {"name": "Bob"},
                {"email": "x@y.com"},
            ]
        }
        assert _format_assignees(issue) == "Alice, Bob"

    def test_vazio(self) -> None:
        assert _format_assignees({}) == ""


class TestModuloPermitido:
    @pytest.fixture(autouse=True)
    def _filtro_restrito(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import config

        monkeypatch.setattr(config, "ALL_MODULES", False)
        monkeypatch.setattr(
            config, "ALLOWED_MODULES", {"Fiscalização", "Fornecedor", "PNCP"}
        )

    def test_modulo_permitido(self) -> None:
        assert _modulo_permitido("PNCP") is True

    def test_modulo_nao_permitido(self) -> None:
        assert _modulo_permitido("ModuloInventado") is False

    def test_all_modules_flag(self) -> None:
        assert _modulo_permitido("ModuloInventado", all_modules=True) is True

    def test_vazio(self) -> None:
        assert _modulo_permitido("") is False


class TestExcecoesWiring:
    """Regressao: o bloco de excecoes chamava coletar_excecoes_wb sem importar."""

    def test_simbolo_chamado_esta_importado(self) -> None:
        import process_gitlab_issues_v2 as pgi

        assert hasattr(pgi, "coletar_excecoes_wb")

    def test_referencia_a_funcao_real(self) -> None:
        import process_gitlab_issues_v2 as pgi
        import relatorio_excecoes

        assert pgi.coletar_excecoes_wb is relatorio_excecoes.coletar_excecoes_wb


class TestOptionalFeaturesVisibility:
    """Recursos opcionais que falham ao importar devem ser observaveis, nao silenciosos."""

    def test_recurso_none_e_listado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import process_gitlab_issues_v2 as pgi

        monkeypatch.setattr(pgi, "build_detector", None)
        indisponiveis = pgi._unavailable_optional_features()
        assert any("build_detector" in item for item in indisponiveis)

    def test_recurso_carregado_nao_e_listado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import process_gitlab_issues_v2 as pgi

        sentinel = object()
        monkeypatch.setattr(pgi, "coletar_excecoes_wb", sentinel)
        indisponiveis = pgi._unavailable_optional_features()
        assert not any("coletar_excecoes_wb" in item for item in indisponiveis)
