"""Testes da coleta do catalogo de labels de tipo (`tipo::*`)."""

from __future__ import annotations

import gitlab_labels
from gitlab_labels import buscar_tipo_labels, tipo_de_label


def test_tipo_de_label_extrai_valor():
    assert tipo_de_label("tipo::Bug") == "Bug"
    assert tipo_de_label("tipo::Documentação") == "Documentação"
    assert tipo_de_label("  tipo::Melhoria  ") == "Melhoria"


def test_tipo_de_label_case_insensitive_no_prefixo():
    assert tipo_de_label("Tipo::Performance") == "Performance"


def test_tipo_de_label_ignora_nao_tipo():
    assert tipo_de_label("status::Doing") is None
    assert tipo_de_label("Equipe::MGI") is None
    assert tipo_de_label("") is None
    assert tipo_de_label("tipo::") is None


def test_buscar_tipo_labels_dedup_e_ordenacao(monkeypatch):
    projeto = [
        {"name": "tipo::Bug", "color": "#111", "description": "b"},
        {"name": "tipo::Melhoria", "color": "#222", "description": ""},
        {"name": "status::Doing", "color": "#333", "description": ""},
    ]
    grupo = [
        {"name": "tipo::Bug", "color": "#999", "description": "dup"},  # duplicado
        {"name": "tipo::Ambiente", "color": "#444", "description": ""},
    ]

    calls = {"n": 0}

    def fake_fetch(url, token):
        calls["n"] += 1
        return grupo if "/groups/" in url else projeto

    monkeypatch.setattr(gitlab_labels, "_buscar_labels", fake_fetch)
    monkeypatch.setattr(gitlab_labels, "_projects", lambda: [("pid", "contratos_v2")])

    labels = buscar_tipo_labels()
    tipos = [item["tipo"] for item in labels]

    assert tipos == ["Ambiente", "Bug", "Melhoria"]  # ordenado, sem duplicata
    bug = next(item for item in labels if item["tipo"] == "Bug")
    assert bug["label"] == "tipo::Bug"
    assert bug["color"] == "#111"  # primeira ocorrencia (projeto) vence
