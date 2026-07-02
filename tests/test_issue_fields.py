"""Testes da logica pura de derivacao de campos (issue_fields)."""

from __future__ import annotations

from datetime import date, datetime

import issue_fields as f


def test_parse_date_iso():
    assert f.parse_date("2025-01-10T09:23:58") == datetime(2025, 1, 10, 9, 23, 58)
    assert f.parse_date("2025-01-10T09:23:58Z") == datetime(2025, 1, 10, 9, 23, 58)


def test_parse_date_humanizado():
    parsed = f.parse_date("Tuesday, June 2, 2026 at 9:23:58 AM GMT-3")
    assert parsed == datetime(2026, 6, 2, 9, 23, 58)


def test_parse_date_vazio():
    assert f.parse_date("") is None
    assert f.parse_date(None) is None
    assert f.parse_date("texto invalido") is None


def test_parse_due_date():
    assert f.parse_due_date("2026-03-15") == "2026-03-15"
    assert f.parse_due_date("") is None
    assert f.parse_due_date(None) is None


def test_extract_module_canonico():
    assert f.extract_module("[PNCP] (Envio) algo") == "PNCP"
    assert f.extract_module("sem tag") == ""


def test_normalized_module_bucket():
    # Modulo nao mapeado cai em bucket, nunca vazio quando ha tag
    assert f.normalized_module("[PNCP] x") == "PNCP"
    assert f.normalized_module("[XYZ-Inexistente] x") != ""


def test_extract_functional_area():
    assert f.extract_functional_area("[PNCP] (Envio ao portal) x") == "Envio ao portal"
    assert f.extract_functional_area("[PNCP] (- Com traco) x") == "Com traco"
    assert f.extract_functional_area("[PNCP] sem parenteses") == ""


def test_map_estado():
    assert f.map_estado("opened") == "Aberto"
    assert f.map_estado("closed") == "Fechado"
    assert f.map_estado("") == ""


def test_parse_labels():
    labels = [
        "tipo::Bug",
        "status::Em andamento",
        "Equipe::Squad A",
        "Parceria::SERPRO",
        "priority::Alta",
        "Solicitante::Joao",
        "Alteração Escopo",
    ]
    parsed = f.parse_labels(labels)
    assert parsed["tipo"] == "Bug"
    assert parsed["status"] == "Em andamento"
    assert parsed["equipe"] == "Squad A"
    assert parsed["parceria"] == "SERPRO"
    assert parsed["prioridade"] == "Alta"
    assert parsed["solicitante"] == "Joao"
    assert parsed["alteracao_escopo"] == "Sim"


def test_parse_labels_default_escopo():
    assert f.parse_labels([])["alteracao_escopo"] == "Não"
    assert f.parse_labels(None)["tipo"] == ""


def test_format_assignees():
    issue = {"assignees": [{"name": "Ana"}, {"name": "Bob"}, {"name": ""}]}
    assert f.format_assignees(issue) == "Ana, Bob"
    assert f.format_assignees({}) == ""


def test_faixa_idade():
    assert f.faixa_idade(10, True) == "0-30 dias"
    assert f.faixa_idade(45, True) == "31-60 dias"
    assert f.faixa_idade(80, True) == "61-90 dias"
    assert f.faixa_idade(100, True) == "91-120 dias"
    assert f.faixa_idade(150, True) == "121-180 dias"
    assert f.faixa_idade(200, True) == "181-360 dias"
    assert f.faixa_idade(400, True) == "Mais de 1 ano"
    assert f.faixa_idade(10, False) is None
    assert f.faixa_idade(None, True) is None


def test_derive_date_fields_aberta():
    created = datetime(2025, 1, 1, 10, 0, 0)
    fields = f.derive_date_fields(created, None, "Aberto", today=date(2025, 3, 1))
    assert fields["aberto"] is True
    assert fields["fechado"] is False
    assert fields["ano_mes_criacao"] == "2025/01"
    assert fields["ano_criacao"] == 2025
    assert fields["mes_criacao"] == "2025-01-01"
    assert fields["idade_dias"] == 59
    assert fields["sla_mais_90_dias"] is False
    assert fields["lead_time_dias"] is None
    assert fields["fechado_em"] is None


def test_derive_date_fields_sla_acima_90():
    created = datetime(2025, 1, 1, 10, 0, 0)
    fields = f.derive_date_fields(created, None, "Aberto", today=date(2025, 6, 1))
    assert fields["idade_dias"] > 90
    assert fields["sla_mais_90_dias"] is True


def test_derive_date_fields_fechada_com_lead_time():
    created = datetime(2025, 1, 1, 10, 0, 0)
    closed = datetime(2025, 1, 11, 10, 0, 0)
    fields = f.derive_date_fields(created, closed, "Fechado", today=date(2025, 3, 1))
    assert fields["fechado"] is True
    assert fields["lead_time_dias"] == 10
    assert fields["idade_dias"] == 0
    assert fields["sla_mais_90_dias"] is False
    assert fields["ano_mes_fechamento"] == "2025/01"
    assert fields["mes_fechamento"] == "2025-01-01"
    assert fields["fechado_em"] == "2025-01-11T10:00:00"


def test_quality_fields():
    q = f.quality_fields("[PNCP] (Envio) x", "PNCP", "Envio", 0.95)
    assert set(q.keys()) == {
        "categoria",
        "modulo_ok",
        "area_ok",
        "padrao_titulo",
        "padrao_completo",
        "confianca_area",
    }
    assert q["modulo_ok"] == "Sim"
    assert q["confianca_area"] == "95%"
