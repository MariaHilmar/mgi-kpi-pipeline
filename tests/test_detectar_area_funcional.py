"""Testes para detectar_area_funcional.py (funcoes puras)."""

from __future__ import annotations

import os

import pytest

from detectar_area_funcional import (
    MultiRepoAreaDetector,
    _infer_area_from_files,
    _infer_area_from_text,
    _infer_default_area_from_canonical_module,
    _normalize_branch_name,
    _normalize_title_area,
)


class TestNormalizeBranchName:
    def test_remove_prefixos(self) -> None:
        assert _normalize_branch_name("* remotes/origin/1234-feat-x") == "origin/1234-feat-x"

    def test_branch_simples(self) -> None:
        assert _normalize_branch_name("  master  ") == "master"


class TestNormalizeTitleArea:
    def test_area_valida(self) -> None:
        assert _normalize_title_area("PNCP") == "PNCP"

    def test_area_vazia(self) -> None:
        assert _normalize_title_area("") == ""

    def test_area_negada(self) -> None:
        assert _normalize_title_area("fornecedor") == ""


class TestInferAreaFromFiles:
    def test_instrumento_cobranca(self) -> None:
        files = ["src/main/java/br/gov/InstrumentoCobrancaService.java"]
        assert _infer_area_from_files(files) == "Instrumento de Cobrança"

    def test_pncp(self) -> None:
        files = ["app/controllers/pncp/envio_controller.rb"]
        assert _infer_area_from_files(files) == "PNCP"

    def test_lista_vazia(self) -> None:
        assert _infer_area_from_files([]) is None


class TestInferAreaFromText:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1234-trp-visualizar", "TRP"),
            ("integracao ic > trd", "Integração IC > TRD"),
            ("plano de fiscalizacao", "Plano de Fiscalização"),
            ("minuta de empenho", "Minuta de Empenho"),
        ],
    )
    def test_palavras_chave(self, text: str, expected: str) -> None:
        assert _infer_area_from_text(text) == expected

    def test_texto_vazio(self) -> None:
        assert _infer_area_from_text("") is None


class TestInferDefaultAreaFromCanonicalModule:
    def test_modulo_canonico_no_titulo(self) -> None:
        title = "[PNCP] Enviar dados ao portal"
        assert _infer_default_area_from_canonical_module(title) == "PNCP"

    def test_fornecedor_mapeia_portal(self) -> None:
        title = "[Fornecedor] Ajuste cadastro"
        assert _infer_default_area_from_canonical_module(title) == "Portal Fornecedor"

    def test_sem_modulo(self) -> None:
        assert _infer_default_area_from_canonical_module("Titulo solto") is None


class TestMultiRepoAreaDetector:
    def test_area_explicita_no_titulo(self) -> None:
        detector = MultiRepoAreaDetector(enabled=False)
        issue = {"id": "100", "title": "[PNCP] (PNCP) - Teste"}
        result = detector.detect(issue, title_area="PNCP")
        assert result.area == "PNCP"
        assert result.method == "titulo_explicito"
        assert result.confidence == 1.0

    def test_inferencia_por_titulo_sem_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MGI_AREA_TITULO_ONLY", "1")
        detector = MultiRepoAreaDetector(enabled=True)
        issue = {
            "id": "200",
            "title": "[Empenho] Consultar minuta de empenho",
        }
        result = detector.detect(issue)
        assert result.area == "Minuta de Empenho"
        assert result.method in ("palavras_chave_titulo", "modulo_canonico_default")

    def test_modulo_canonico_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MGI_AREA_TITULO_ONLY", "1")
        detector = MultiRepoAreaDetector(enabled=False)
        issue = {"id": "300", "title": "[Jobs] Atualizar pipeline CI"}
        result = detector.detect(issue)
        assert result.area == "Infraestrutura"
        assert result.method == "modulo_canonico_default"
