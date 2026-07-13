"""Testes para inferir_tipo_issue.py."""

from __future__ import annotations

import pytest

from inferir_tipo_issue import (
    BRANCH_TIPO_RULES,
    TITLE_TIPO_RULES,
    TipoIssueDetector,
    _infer_tipo_from_commits,
    _infer_tipo_from_text,
)


class TestInferTipoFromCommits:
    def test_fix_e_bugfix(self) -> None:
        messages = ["fix: corrige validacao", "feat: nova tela", "bugfix: null pointer"]
        assert _infer_tipo_from_commits(messages) == "Bug"

    def test_feat_prioridade_sobre_fix_unico(self) -> None:
        messages = ["feat: adiciona filtro", "fix: typo"]
        assert _infer_tipo_from_commits(messages) == "Melhoria"

    def test_perf(self) -> None:
        messages = ["perf: reduz queries"]
        assert _infer_tipo_from_commits(messages) == "Performance"

    def test_vazio(self) -> None:
        assert _infer_tipo_from_commits([]) is None


class TestInferTipoFromText:
    @pytest.mark.parametrize(
        ("text", "rules", "expected"),
        [
            ("1234-bug-correcao-login", BRANCH_TIPO_RULES, "Bug"),
            ("4567-feat-nova-funcionalidade", BRANCH_TIPO_RULES, "Melhoria"),
            ("7890-perf-cache", BRANCH_TIPO_RULES, "Performance"),
            ("Corrigir erro no empenho", TITLE_TIPO_RULES, "Bug"),
            ("Melhoria na usabilidade", TITLE_TIPO_RULES, "Melhoria"),
            ("Otimizar performance da listagem", TITLE_TIPO_RULES, "Performance"),
        ],
    )
    def test_regras(self, text: str, rules, expected: str) -> None:
        assert _infer_tipo_from_text(text, rules) == expected

    def test_texto_vazio(self) -> None:
        assert _infer_tipo_from_text("", TITLE_TIPO_RULES) is None


class TestTipoIssueDetector:
    def test_detect_por_titulo_sem_git(self) -> None:
        detector = TipoIssueDetector(enabled=False)
        issue = {"id": "100", "title": "Corrigir bug no cadastro"}
        result = detector.detect(issue)
        assert result.tipo == "Bug"
        assert result.method == "palavras_chave_titulo"
        assert result.confidence == 0.65

    def test_detect_sem_sinais(self) -> None:
        detector = TipoIssueDetector(enabled=False)
        issue = {"id": "100", "title": "[PNCP] Atualizar documentação"}
        result = detector.detect(issue)
        assert result.tipo == ""
        assert result.method == "none"

    def test_detect_sem_id(self) -> None:
        detector = TipoIssueDetector(enabled=False)
        result = detector.detect({})
        assert result.tipo == ""
        assert result.confidence == 0.0
