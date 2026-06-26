"""Testes para taxonomy.py."""

from __future__ import annotations

import pytest

from taxonomy import (
    CANONICAL_MODULES,
    CUSTOM_BUCKET,
    NON_MODULE_BUCKET,
    assess_row_quality,
    canonical_or_bucket,
    confidence_area_label,
    extract_module_tag,
    is_canonical_module,
    is_standard_area,
    module_category,
    normalize_area,
    normalize_module_to_canonical,
    suggest_title_module_fix,
    validate_title_pattern,
)


class TestExtractModuleTag:
    def test_tag_simples(self) -> None:
        assert extract_module_tag("[PNCP] (PNCP) - Enviar dados") == "PNCP"

    def test_sem_tag(self) -> None:
        assert extract_module_tag("Titulo sem padrao") == ""


class TestNormalizeModuleToCanonical:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("PNCP", "PNCP"),
            ("pncp", "PNCP"),
            ("Empenho", "Minuta de Empenho"),
            ("Contratos", "Gestão Contratual"),
            ("Infraestrutura", "Jobs"),
            ("Modulo Desconhecido XYZ", ""),
        ],
    )
    def test_aliases(self, raw: str, expected: str) -> None:
        assert normalize_module_to_canonical(raw) == expected

    def test_modulo_canonico_direto(self) -> None:
        for module in CANONICAL_MODULES:
            assert normalize_module_to_canonical(module) == module


class TestCanonicalOrBucket:
    def test_modulo_canonico(self) -> None:
        assert canonical_or_bucket("PNCP") == "PNCP"

    def test_tag_nao_funcional(self) -> None:
        assert canonical_or_bucket("bug") == NON_MODULE_BUCKET
        assert canonical_or_bucket("Dashboard") == NON_MODULE_BUCKET

    def test_tag_desconhecida(self) -> None:
        assert canonical_or_bucket("AlgumaCoisaNova") == CUSTOM_BUCKET

    def test_composto_pncp(self) -> None:
        assert canonical_or_bucket("Gestão de atas - PNCP") == "PNCP"

    def test_composto_bug_no_final(self) -> None:
        result = canonical_or_bucket("Gestão Contratual - bug")
        assert result in ("Gestão Contratual", NON_MODULE_BUCKET)

    def test_vazio(self) -> None:
        assert canonical_or_bucket("") == ""


class TestModuleCategory:
    def test_core_business(self) -> None:
        assert module_category("Gestão Contratual") == "Core Business"

    def test_compliance(self) -> None:
        assert module_category("PNCP") == "Compliance"

    def test_nao_mapeado(self) -> None:
        assert module_category("ModuloInexistente") == "Não mapeado"


class TestNormalizeArea:
    def test_area_canonica(self) -> None:
        assert normalize_area("Portal Fornecedor") == "Portal Fornecedor"

    def test_alias_casefold(self) -> None:
        assert normalize_area("portal fornecedor") == "Portal Fornecedor"

    def test_area_desconhecida_preserva(self) -> None:
        assert normalize_area("Area Nova") == "Area Nova"


class TestIsStandardArea:
    def test_area_global(self) -> None:
        assert is_standard_area("PNCP") is True

    def test_area_por_modulo(self) -> None:
        assert is_standard_area("Minuta de Empenho", "Minuta de Empenho") is True

    def test_area_invalida(self) -> None:
        assert is_standard_area("Area Inventada", "PNCP") is False


class TestValidateTitlePattern:
    def test_padrao_basico(self) -> None:
        assert validate_title_pattern("[PNCP] Enviar dados") is True

    def test_padrao_com_area(self) -> None:
        title = "[PNCP] (PNCP) - Enviar dados"
        assert validate_title_pattern(title, strict=True) is True

    def test_padrao_completo(self) -> None:
        title = "[PNCP] (PNCP) - Enviar dados"
        assert validate_title_pattern(title, strict="full") is True

    def test_titulo_invalido(self) -> None:
        assert validate_title_pattern("Sem colchetes") is False


class TestSuggestTitleModuleFix:
    def test_sugere_correcao(self) -> None:
        title = "[Empenho] (Minuta de Empenho) - Ajuste"
        fixed = suggest_title_module_fix(title)
        assert fixed == "[Minuta de Empenho] (Minuta de Empenho) - Ajuste"

    def test_sem_correcao_quando_canonico(self) -> None:
        title = "[PNCP] (PNCP) - Ajuste"
        assert suggest_title_module_fix(title) is None


class TestConfidenceAreaLabel:
    def test_git_confidence(self) -> None:
        assert confidence_area_label("", "PNCP", git_confidence=0.95) == "95%"

    def test_titulo_com_area(self) -> None:
        title = "[PNCP] (PNCP) - Teste"
        assert confidence_area_label(title, "PNCP") == "100%"

    def test_sem_area_explicita(self) -> None:
        assert confidence_area_label("[PNCP] Teste", "PNCP") == "75%"


class TestAssessRowQuality:
    def test_linha_boa(self) -> None:
        title = "[PNCP] (PNCP) - Integrar envio"
        result = assess_row_quality(title, "PNCP", "PNCP", area_confidence=1.0)
        assert result["modulo_ok"] == "Sim"
        assert result["area_ok"] == "Sim"
        assert result["padrao_titulo"] == "Sim"
        assert result["categoria"] == "Compliance"

    def test_modulo_invalido(self) -> None:
        result = assess_row_quality("Titulo solto", "XYZ", "")
        assert result["modulo_ok"] == "Não"
        assert result["area_ok"] == "Não"

    def test_sem_modulo_sem_area(self) -> None:
        result = assess_row_quality("Titulo solto", "", "")
        assert result["modulo_ok"] == "Não"
        assert result["area_ok"] == "N/A"


class TestIsCanonicalModule:
    def test_canonico(self) -> None:
        assert is_canonical_module("Jobs") is True

    def test_nao_canonico(self) -> None:
        assert is_canonical_module("bug") is False
