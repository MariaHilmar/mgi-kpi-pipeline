#!/usr/bin/env python3
"""Derivacao de campos de uma issue GitLab (logica pura, sem Excel/openpyxl).

Este modulo concentra as transformacoes que antes estavam acopladas a escrita
celula-a-celula no Excel (process_gitlab_issues_v2). Cada funcao recebe dados
da issue crua e devolve valores prontos, permitindo gerar registros diretamente
para o Supabase sem depender de planilha.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Dict, List, Optional

import taxonomy

# Mapeamento de tags de modulo nao canonicas -> rotulo final (paridade com o
# pipeline legado em process_gitlab_issues_v2.MODULE_MAP).
MODULE_MAP: Dict[str, str] = {
    "Gestão de Ata": "Gestão de Atas",
    "GESTÃO DE ATAS": "Gestão de Atas",
    "Transparência": "Transparência",
    "Transparencia": "Transparência",
    "API v2": "API v2",
    "API": "API v2",
    "Fiscalização": "Fiscalização",
    "Fornecedor": "Fornecedor",
    "Gestão Contratual": "Gestão Contratual",
    "Gestão Financeira": "Gestão Financeira",
    "Instrumento de Cobrança": "Instrumento de Cobrança",
    "Jobs": "Jobs",
    "Minuta de Empenho": "Minuta de Empenho",
    "PNCP": "PNCP",
    "Administração": "Administração",
}

# Colunas preenchidas manualmente no historico (Excel). NUNCA sao calculadas
# aqui; ficam de fora dos registros para que o upsert no Supabase preserve o
# valor existente em vez de sobrescrever com nulo.
MANUAL_FIELDS = (
    "situacao_analise",
    "desenvolvedor_futuro",
    "observacao_geral",
    "chamado",
    "priorizar",
    "epico",
)


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Converte data do GitLab (ISO 8601 ou formato humanizado) em datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(
            date_str.replace("Z", "+00:00").split("+")[0].strip()
        )
    except (ValueError, AttributeError):
        pass
    try:
        clean = re.sub(
            r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*",
            "",
            date_str,
        )
        clean = re.sub(r"\s+GMT[+-]\d+", "", clean)
        return datetime.strptime(clean, "%B %d, %Y at %I:%M:%S %p")
    except (ValueError, TypeError):
        return None


def extract_module(title: str) -> str:
    """Extrai o modulo da tag [..] do titulo e normaliza para canonico."""
    tag = taxonomy.extract_module_tag(title or "")
    if not tag:
        return ""
    canon = taxonomy.normalize_module_to_canonical(tag)
    if canon:
        return canon
    return MODULE_MAP.get(tag, tag)


def normalized_module(title: str, modulo: str = "") -> str:
    """Modulo normalizado para um dos canonicos ou bucket (paridade dashboard)."""
    tag = taxonomy.extract_module_tag(title or "") or (modulo or "").strip()
    return taxonomy.canonical_or_bucket(tag)


def extract_functional_area(title: str) -> str:
    """Area funcional declarada entre parenteses apos o ] no titulo."""
    match = re.search(r"\]\s*\(([^)]+)\)", title or "")
    if not match:
        return ""
    area = match.group(1).strip()
    if area.startswith("- "):
        area = area[2:]
    return area


def map_estado(state: Optional[str]) -> str:
    if state == "opened":
        return "Aberto"
    if state == "closed":
        return "Fechado"
    return state or ""


def parse_labels(labels: Optional[List[str]]) -> Dict[str, str]:
    """Extrai colunas derivadas das labels GitLab (paridade com o legado)."""
    parsed = {
        "tipo": "",
        "status": "",
        "equipe": "",
        "parceria": "",
        "prioridade": "",
        "solicitante": "",
        "alteracao_escopo": "Não",
    }
    for label in labels or []:
        if label.startswith("tipo::"):
            parsed["tipo"] = label.split("::", 1)[1]
        elif label.startswith("status::"):
            parsed["status"] = label.split("::", 1)[1]
        elif label.startswith("Equipe::"):
            parsed["equipe"] = label.split("::", 1)[1]
        elif label.startswith("Parceria::"):
            parsed["parceria"] = label.split("::", 1)[1]
        elif label.startswith("priority::"):
            parsed["prioridade"] = label.split("::", 1)[1]
        elif label.startswith("Solicitante::"):
            parsed["solicitante"] = label.split("::", 1)[1]
        elif label.strip() == "Alteração Escopo":
            parsed["alteracao_escopo"] = "Sim"
    return parsed


def format_assignees(issue: Dict) -> str:
    assignees = issue.get("assignees") or []
    names = [person.get("name", "") for person in assignees if person.get("name")]
    return ", ".join(names)


def faixa_idade(idade_dias: Optional[int], aberto: bool) -> Optional[str]:
    """Faixa etaria da issue aberta (mesmas faixas do dashboard_faixa_idade)."""
    if not aberto or idade_dias is None:
        return None
    if idade_dias <= 30:
        return "0-30 dias"
    if idade_dias <= 60:
        return "31-60 dias"
    if idade_dias <= 90:
        return "61-90 dias"
    if idade_dias <= 120:
        return "91-120 dias"
    return "Mais de 120 dias"


def derive_date_fields(
    created_date: Optional[datetime],
    closed_date: Optional[datetime],
    estado: str,
    *,
    today: Optional[date] = None,
) -> Dict[str, object]:
    """Campos derivados de datas/estado (datas, lead time, idade, SLA, flags)."""
    today = today or date.today()
    aberto = estado == "Aberto"
    fechado = estado == "Fechado"

    fields: Dict[str, object] = {
        "criado_em": created_date.isoformat() if created_date else None,
        "fechado_em": closed_date.isoformat() if closed_date else None,
        "ano_mes_criacao": None,
        "ano_criacao": None,
        "mes_criacao": None,
        "ano_mes_fechamento": None,
        "mes_fechamento": None,
        "lead_time_dias": None,
        "aberto": aberto,
        "fechado": fechado,
        "idade_dias": None,
        "sla_mais_90_dias": False,
    }

    if created_date:
        fields["ano_mes_criacao"] = f"{created_date.year}/{created_date.month:02d}"
        fields["ano_criacao"] = created_date.year
        fields["mes_criacao"] = date(created_date.year, created_date.month, 1).isoformat()

    if closed_date:
        fields["ano_mes_fechamento"] = f"{closed_date.year}/{closed_date.month:02d}"
        fields["mes_fechamento"] = date(closed_date.year, closed_date.month, 1).isoformat()
        if created_date:
            fields["lead_time_dias"] = max(
                (closed_date.date() - created_date.date()).days, 0
            )

    if aberto and created_date:
        idade = max((today - created_date.date()).days, 0)
        fields["idade_dias"] = idade
        fields["sla_mais_90_dias"] = idade > 90
    elif fechado:
        fields["idade_dias"] = 0
        fields["sla_mais_90_dias"] = False

    return fields


def quality_fields(
    title: str,
    modulo: str,
    area: str,
    area_confidence: float = 0.0,
) -> Dict[str, str]:
    """Campos de qualidade (categoria, modulo_ok, area_ok, padroes, confianca)."""
    return taxonomy.assess_row_quality(title, modulo, area, area_confidence)
