#!/usr/bin/env python3
"""Mapeamento status GitLab → etapa Kanban (espelha flow_map_etapa no Supabase)."""

from __future__ import annotations

import unicodedata


def _normalize_status_key(status: str | None) -> str:
    text = (status or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def flow_map_etapa(status: str | None, estado: str | None = "Aberto") -> str:
    s = _normalize_status_key(status)

    if (estado or "") == "Fechado" or s in {
        "delivered",
        "done",
        "concluida",
        "fechada",
        "finalizado",
        "finalizada",
    }:
        return "Concluído"

    if s in {"cancelado", "cancelada", "recusado", "recusada", "canceled", "rejected"}:
        return "Cancelado"

    if s in {"backlog", "aberta", ""}:
        return "Backlog"

    if s in {"sprint atual", "a fazer", "todo", "to do", "fazer"}:
        return "A Fazer"

    if s in {"doing", "em andamento", "desenvolvimento", "em desenvolvimento", "dev"}:
        return "Em Desenvolvimento"

    if s in {"em revisao", "teste", "em teste", "qa", "review"}:
        return "Em Teste"

    if s in {"homologacao", "uat", "hml"}:
        return "Homologação"

    return "Backlog"


def parse_status_label(label_name: str | None) -> str | None:
    """Extrai valor de label GitLab `status::Doing` → `Doing`."""
    if not label_name:
        return None
    prefix = "status::"
    if not label_name.startswith(prefix):
        return None
    value = label_name.split("::", 1)[1].strip()
    return value or None
