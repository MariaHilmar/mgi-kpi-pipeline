"""Testes para calc_formulas.py."""

from __future__ import annotations

from calc_formulas import (
    DATA_START_ROW,
    DADOS_SHEET,
    EMPTY_LABEL,
    YEAR_FILTER,
    count_by_label_formula,
    outros_count_formula,
)


class TestCountByLabelFormula:
    def test_label_informado(self) -> None:
        formula = count_by_label_formula("A3", data_col=5, last_row=100)
        assert formula.startswith("=IF(A3=")
        assert f"{DADOS_SHEET}!$E${DATA_START_ROW}:$E$100" in formula
        assert f'">="&{YEAR_FILTER}' in formula

    def test_label_vazio(self) -> None:
        formula = count_by_label_formula("A3", data_col=5, last_row=50)
        assert EMPTY_LABEL in formula
        assert 'COUNTIFS(' in formula


class TestOutrosCountFormula:
    def test_primeira_linha_retorna_zero(self) -> None:
        assert outros_count_formula("AU", DATA_START_ROW, last_row=200) == "=0"

    def test_linha_subsequente(self) -> None:
        row = DATA_START_ROW + 3
        formula = outros_count_formula("AU", row, last_row=200)
        assert formula.startswith("=MAX(0,COUNTIFS(")
        assert f"$AU${DATA_START_ROW}:$AU{row - 1}" in formula
        assert f'">="&{YEAR_FILTER}' in formula
