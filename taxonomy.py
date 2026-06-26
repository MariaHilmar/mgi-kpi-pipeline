#!/usr/bin/env python3
"""
Taxonomia oficial de modulos, categorias e areas funcionais (diagnostico repo Git).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# Modulos canonicos (12 ativos + fallback implicito via mapa)
CANONICAL_MODULES: Tuple[str, ...] = (
    "Gestão de Atas",
    "Gestão Contratual",
    "Administração",
    "Fornecedor",
    "Fiscalização",
    "PNCP",
    "Transparência",
    "Gestão Financeira",
    "Instrumento de Cobrança",
    "Minuta de Empenho",
    "API v2",
    "Jobs",
)

# Área padrão por módulo canônico — usada como fallback de alta confiança
# quando nenhuma área está explícita no título nem inferível via Git.
CANONICAL_MODULE_TO_DEFAULT_AREA: Dict[str, str] = {
    "Gestão de Atas": "Gestão de Atas",
    "Gestão Contratual": "Gestão Contratual",
    "Administração": "Administração",
    "Fornecedor": "Portal Fornecedor",
    "Fiscalização": "Plano de Fiscalização",
    "PNCP": "PNCP",
    "Transparência": "Transparência",
    "Gestão Financeira": "Gestão Financeira",
    "Instrumento de Cobrança": "Instrumento de Cobrança",
    "Minuta de Empenho": "Minuta de Empenho",
    "API v2": "API / Integrações",
    "Jobs": "Infraestrutura",
}

MODULE_CATEGORIES: Dict[str, str] = {
    "Gestão de Atas": "Core Business",
    "Gestão Contratual": "Core Business",
    "Administração": "Core Business",
    "Fornecedor": "Core Business",
    "Fiscalização": "Compliance",
    "PNCP": "Compliance",
    "Transparência": "Compliance",
    "Gestão Financeira": "Finance",
    "Instrumento de Cobrança": "Finance",
    "Minuta de Empenho": "Finance",
    "API v2": "Platform",
    "Jobs": "Platform",
}

# Tags [Modulo] recorrentes no repo — aceitas em "Módulo OK?" com categoria propria
MODULE_TAG_CATEGORIES: Dict[str, str] = {
    "Infraestrutura": "Platform",
    "Empenho": "Finance",
    "empenho": "Finance",
    "Instrumento Inicial": "Core Business",
    "Gestão Orçamentária": "Finance",
    "Gestão orçamentária": "Finance",
    "OS/F": "Core Business",
    "OSF": "Core Business",
    "Compras": "Core Business",
    "IC": "Finance",
    "SEI": "Platform",
    "siafi": "Finance",
    "AntecipaGov": "Finance",
    "Parâmetros": "Operations",
    "Parâmetro": "Operations",
    "Integração CPF": "Platform",
    "Termo Aditivo": "Core Business",
    "DOU": "Compliance",
    "NONCE": "Platform",
    "erro": "Não mapeado",
    "Contratos": "Core Business",
    "Contrato": "Core Business",
    "CONTRATOS": "Core Business",
    "Ambiente": "Platform",
    "Pipeline": "Platform",
    "Redis": "Platform",
    "Login": "Operations",
    "Acesso": "Operations",
    "BD": "Operations",
    "admin": "Operations",
    "JOB": "Platform",
    "CI/CD": "Platform",
    "Entregas": "Core Business",
    "Ordem de Serviço": "Core Business",
    "Assinatura Gov.br": "Operations",
    "Notificações": "Operations",
    "Órgãos": "Operations",
    "Instrumento Incial": "Core Business",
    "Permissões": "Operations",
    "Siads": "Platform",
    "API Siads": "Platform",
    "NDC": "Operations",
    "Levantamento de informações": "Operations",
}

# Tags que nao sao modulos funcionais — meta/tecnicas/typos graves.
# Vao para CUSTOM_BUCKET em vez de tentar mapear para um canonico.
NON_MODULE_TAGS: FrozenSet[str] = frozenset({
    "bug", "erro log",
    "Test", "test", "teste",
    "Dashboard", "dashboard",
    "RSS", "rss",
    "telegram", "Telegram",
    "sirius", "Julius", "Comunica", "comunica",
    "CI", "ci",
    "V2", "v2", "Tabela V1",
    "Discussão", "discussao",
    "Página Inicial", "pagina inicial",
    "Usabilidade", "usabilidade",
    "devops", "DevOps",
    "Rancher", "rancher",
    "Performance", "Perfomance",  # typo de Performance
    "Sistema",
    "Base",
    "livre", "Livre", "LIVRE",
    "Otimização",
    "Filtros",
    "Relatório", "Relatórios", "Relatorio",
    "Documentos",
    "Arquivos",
    "Publicação", "Publicações",
    "E-mail", "email",
    "Dependentes",
    "Responsáveis",
    "Reajuste",
    "Termos",
    "Termo",
})

# Variacoes de titulo -> modulo canonico (12 canonicos fixos)
MODULE_ALIASES: Dict[str, str] = {
    # --- Gestão de Atas ---
    "Gestão de Ata": "Gestão de Atas",
    "GESTÃO DE ATAS": "Gestão de Atas",
    "Gestao de Atas": "Gestão de Atas",
    "Criar ata": "Gestão de Atas",
    "Alteração de ata": "Gestão de Atas",
    "ARP": "Gestão de Atas",
    "ADESÃO": "Gestão de Atas",
    "Adesão": "Gestão de Atas",
    "adesao": "Gestão de Atas",
    "Publicações": "Gestão de Atas",
    "Minuta de alteração": "Gestão de Atas",
    "STA": "Gestão de Atas",
    "Termo de contrato": "Gestão Contratual",
    # --- Gestão Contratual ---
    "Contratos": "Gestão Contratual",
    "Contrato": "Gestão Contratual",
    "CONTRATOS": "Gestão Contratual",
    "Instrumento Inicial": "Gestão Contratual",
    "Instrumento inicial": "Gestão Contratual",
    "Instrumento Incial": "Gestão Contratual",   # typo recorrente
    "OS/F": "Gestão Contratual",
    "OSF": "Gestão Contratual",
    "Ordem de Serviço": "Gestão Contratual",
    "Ordem de Serviço/Fornecimento": "Gestão Contratual",
    "Entregas": "Gestão Contratual",
    "Aditivo": "Gestão Contratual",
    "Apostilamento": "Gestão Contratual",
    "Termo Aditivo": "Gestão Contratual",
    "Termo aditivo": "Gestão Contratual",
    "Termo de Apostilamento": "Gestão Contratual",
    "Cronograma": "Gestão Contratual",
    "Termo de rescisão": "Gestão Contratual",
    "Termo encerramento": "Gestão Contratual",
    "Termo de encerramento": "Gestão Contratual",
    "Termo Encerramento": "Gestão Contratual",
    "Itens do Contrato": "Gestão Contratual",
    "Meus Contratos": "Gestão Contratual",
    "Vigência/Saldo": "Gestão Contratual",
    "Contrato em elaboração": "Gestão Contratual",
    "Contrato e Instrumento Inicial": "Gestão Contratual",
    "Fiscalização e Gestão": "Gestão Contratual",
    "Fiscalização e Gestão de Contratos": "Gestão Contratual",
    "Fornecedor": "Fornecedor",             # sem alias, mas garantir sem colapso
    # --- Administração ---
    "Compras": "Administração",
    "Compra": "Administração",
    "CompraService": "Administração",
    "Compr": "Administração",              # typo de Compra
    "admin": "Administração",
    "administração": "Administração",
    "Admnistração": "Administração",       # typo recorrente
    "Acesso": "Administração",
    "Login": "Administração",
    "BD": "Jobs",                           # Banco de Dados → infraestrutura
    "Banco de Dados": "Jobs",
    "Unidades": "Administração",
    "Unidades Descentralizadas": "Administração",
    "Unidades descentralizadas": "Administração",
    "Amparo legal": "Administração",
    "amparo legal": "Administração",
    "Tela início": "Administração",
    "Alterar Senha": "Administração",
    "Permissões": "Administração",
    "Notificações": "Administração",
    "Assinatura Gov.br": "Administração",
    "Órgãos": "Administração",
    "NDC": "Administração",
    "Parâmetros": "Administração",
    "Parâmetro": "Administração",
    "Grupo de Administração": "Administração",
    "Modalidade Licitação": "Administração",
    "Local de entrega": "Administração",
    "Local de execução": "Administração",
    "Solicitação de Adesão": "Administração",
    "Usuários": "Administração",
    "Usuário": "Administração",
    "Administação": "Administração",
    "Aministração": "Administração",
    # --- Fiscalização ---
    "Plano de Fiscalização": "Fiscalização",
    "Fiscalizacao": "Fiscalização",
    "Designação de Gestor e Fiscais": "Fiscalização",
    "Autorização de Execução": "Fiscalização",
    "Autorização de execução": "Fiscalização",
    # --- PNCP ---
    "pncp": "PNCP",
    "PNPC": "PNCP",                        # typo recorrente
    # --- Transparência ---
    "Transparencia": "Transparência",
    "transparência": "Transparência",
    "TRANSPARÊNCIA": "Transparência",
    # --- Instrumento de Cobrança ---
    "Instrumento de cobrança": "Instrumento de Cobrança",
    "Instrumento de Cobrança": "Instrumento de Cobrança",
    "Instrumentos de cobrança": "Instrumento de Cobrança",
    "Instrumentos de Cobrança": "Instrumento de Cobrança",
    "IC": "Instrumento de Cobrança",
    "Gestão Orçamentária": "Instrumento de Cobrança",
    "Gestão orçamentária": "Instrumento de Cobrança",
    "Gestão financeira": "Gestão Financeira",
    "Gestao Financeira": "Gestão Financeira",
    "Gestão Financeira": "Gestão Financeira",
    "Gestão Financeiro": "Gestão Financeira",
    "Apropriação": "Instrumento de Cobrança",
    "Apropriacão": "Instrumento de Cobrança",
    "Conta vinculada": "Gestão Financeira",
    "Conta Vinculada": "Gestão Financeira",
    "Conta depósito vinculada": "Gestão Financeira",
    "Conta-Depósito vinculada": "Instrumento de Cobrança",
    "siafi": "Instrumento de Cobrança",
    "Siafi": "Instrumento de Cobrança",
    "SIAFI": "Instrumento de Cobrança",
    "AntecipaGov": "Gestão Financeira",
    # --- Minuta de Empenho ---
    "Minuta de empenho": "Minuta de Empenho",
    "Empenho": "Minuta de Empenho",
    "empenho": "Minuta de Empenho",
    "Empenhos": "Minuta de Empenho",
    "Minutas de empenho": "Minuta de Empenho",
    "Minutas de Empenho": "Minuta de Empenho",
    "Minuta empenho": "Minuta de Empenho",
    "minuta empenho": "Minuta de Empenho",
    "Minuta Empenho": "Minuta de Empenho",
    "Minuta de documento": "Minuta de Empenho",
    "Minuta de Documento": "Minuta de Empenho",
    "Minutas de documento": "Minuta de Empenho",
    "Minutas de Documento": "Minuta de Empenho",
    "Minutas de Documentos": "Minuta de Empenho",
    "Contrato Fatura Empenhos": "Minuta de Empenho",
    "Alteração de Empenho": "Minuta de Empenho",
    "Contrato do tipo empenho": "Minuta de Empenho",
    "Contrato do Tipo Empenho": "Minuta de Empenho",
    "Contrato Tipo Empenho": "Minuta de Empenho",
    "contrato tipo empenho": "Minuta de Empenho",
    "Minuta de empenho e Contratos": "Minuta de Empenho",
    "minutas": "Minuta de Empenho",
    "Minutas e Contratos": "Minuta de Empenho",
    "Empenho e Instrumento de Cobrança": "Minuta de Empenho",
    # --- API v2 ---
    "API": "API v2",
    "api": "API v2",
    "SEI": "API v2",
    "sei": "API v2",
    "Siads": "API v2",
    "API Siads": "API v2",
    "API SIADS": "API v2",
    "Integração CPF": "API v2",
    "NONCE": "API v2",
    "DOU": "Transparência",
    "Publicação DOU": "Transparência",
    "Análise de adesão": "Instrumento de Cobrança",
    "CompraTrait": "Administração",
    "Instrumento Cobrança": "Instrumento de Cobrança",
    "Fornecedores": "Fornecedor",
    "auditoria": "Administração",
    "API v1": "Gestão de Atas",
    "Gestão de atas v1": "Gestão de Atas",
    "Apropriação de Instrumento de Cobrança": "Instrumento de Cobrança",
    "Teste Unitário": "Jobs",
    "TRD": "Fiscalização",
    # --- Jobs (Infraestrutura) ---
    "Infraestrutura": "Jobs",
    "Ambiente": "Jobs",
    "Pipeline": "Jobs",
    "JOB": "Jobs",
    "CI/CD": "Jobs",
    "Redis": "Jobs",
    "Termo de Infraestrutura": "Jobs",
    "Terceirizados": "Jobs",
    "Terceirizado": "Jobs",
    "Remanejamento": "Jobs",
    "Rescisão": "Jobs",
    "Log": "Jobs",
    "log": "Jobs",
    "LOG": "Jobs",
    "Desenvolvedor": "Jobs",
    "desenvolvedor": "Jobs",
    "SAST/DAST": "Jobs",
}

STANDARD_AREAS_BY_MODULE: Dict[str, Tuple[str, ...]] = {
    "Gestão de Atas": (
        "Gestão de Atas",
        "Sincronização",
        "ARP",
        "Adesão",
        "Análise de adesão",
    ),
    "Gestão Contratual": (
        "Gestão Contratual",
        "Apostilamento",
        "Termo Apostilamento",
        "Entregas",
        "Meus Contratos",
        "Instrumento Inicial",
        "OS/F",
        "Terceirizados",
        "Rescisão",
        "Cronograma",
        "Vigência/Saldo",
        "Remanejamento",
    ),
    "Administração": (
        "Administração",
        "Acesso",
        "Compras",
        "Banco de Dados",
        "Notificações",
        "Permissões",
        "Parâmetros",
    ),
    "Fornecedor": ("Portal Fornecedor", "Cadastro"),
    "Fiscalização": (
        "Plano de Fiscalização",
        "Verificações PF",
        "Relatórios",
        "Declaração Decreto 11.430",
        "Relatório Reembolso Creche",
        "OS/F",
    ),
    "PNCP": ("PNCP",),
    "Transparência": (
        "Transparência",
        "Portal da Transparência",
        "DOU",
    ),
    "Gestão Financeira": (
        "Gestão Financeira",
        "AntecipaGov",
        "Conta-Depósito vinculada",
    ),
    "Instrumento de Cobrança": (
        "Instrumento de Cobrança",
        "Integração IC > TRD",
        "TRP",
        "TRD",
        "Conta-Depósito vinculada",
        "Apropriação",
        "AntecipaGov",
    ),
    "Minuta de Empenho": ("Minuta de Empenho",),
    "API v2": ("API / Integrações", "Integração SEI"),
    "Jobs": ("Infraestrutura", "Banco de Dados"),
}

# Areas validas em qualquer modulo (detectadas via Git / titulo)
GLOBAL_STANDARD_AREAS: Tuple[str, ...] = (
    "Administração",
    "API / Integrações",
    "Acesso",
    "Compras",
    "Declaração Decreto 11.430",
    "Entregas",
    "Gestão Contratual",
    "Gestão de Atas",
    "Infraestrutura",
    "Instrumento de Cobrança",
    "Integração IC > TRD",
    "Integração SEI",
    "Minuta de Empenho",
    "OS/F",
    "Plano de Fiscalização",
    "PNCP",
    "Portal Fornecedor",
    "Relatório Reembolso Creche",
    "Transparência",
    "TRD",
    "TRP",
    "Verificações PF",
    "Banco de Dados",
    "Conta-Depósito vinculada",
    "Conta-Deposito vinculada",
    "AntecipaGov",
    "Termo Apostilamento",
    "Portal da Transparência",
    "Análise de adesão",
    "Auditoria",
    "ARP",
    "Adesão",
    "Fiscalização",
    "Meus Contratos",
    "Cadastro",
    "Sincronização",
    "Relatórios",
)

AREA_ALIASES: Dict[str, str] = {
    "portal fornecedor": "Portal Fornecedor",
    "api / integracoes": "API / Integrações",
    "api v2": "API / Integrações",
    "instrumento de cobranca": "Instrumento de Cobrança",
    "minuta de empenho": "Minuta de Empenho",
    "gestao contratual": "Gestão Contratual",
    "gestao de atas": "Gestão de Atas",
    "plano de fiscalizacao": "Plano de Fiscalização",
    "verificacoes pf": "Verificações PF",
    "os/f": "OS/F",
    "trp": "TRP",
    "trd": "TRD",
    "pncp": "PNCP",
    "transparencia": "Transparência",
    "infraestrutura": "Infraestrutura",
    "administracao": "Administração",
    "banco de dados": "Banco de Dados",
    "conta-deposito vinculada": "Conta-Depósito vinculada",
    "conta deposito vinculada": "Conta-Depósito vinculada",
    "antecipagov": "AntecipaGov",
    "termo apostilamento": "Termo Apostilamento",
    "portal da transparencia": "Portal da Transparência",
    "analise de adesao": "Análise de adesão",
    "auditoria": "Auditoria",
    "arp": "ARP",
    "adesao": "Adesão",
    "fiscalizacao": "Fiscalização",
    "meus contratos": "Meus Contratos",
    "cadastro": "Cadastro",
    "sincronizacao": "Sincronização",
    "relatorios": "Relatórios",
    "compra": "Compras",
    "banco": "Banco de Dados",
    "auditória": "Auditoria",
    "view arp": "ARP",
    "sei": "Integração SEI",
    "tcu": "Análise de adesão",
}

TITLE_PATTERN_WITH_AREA = re.compile(
    r"^\[[^\]]+\]\s*\([^)]+\)",
    re.UNICODE,
)
MODULE_TAG_PATTERN = re.compile(r"^\[([^\]]+)\]")
TITLE_PATTERN_FULL = re.compile(
    r"^\[[^\]]+\]\s*\([^)]+\)\s*-\s*.+",
    re.UNICODE,
)
TITLE_PATTERN_BASIC = re.compile(
    r"^\[[^\]]+\]\s*.+",
    re.UNICODE,
)

_ALL_STANDARD_AREAS: FrozenSet[str] = frozenset(
    list(GLOBAL_STANDARD_AREAS)
    + [a for areas in STANDARD_AREAS_BY_MODULE.values() for a in areas]
)


def _fold(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text.strip())
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents).casefold()


def normalize_module(raw: str) -> str:
    """Normaliza variacao para modulo canonico quando possivel."""
    canon = normalize_module_to_canonical(raw)
    if canon:
        return canon
    text = (raw or "").strip()
    if not text:
        return ""
    return text


def normalize_module_to_canonical(raw: str) -> str:
    """Retorna um dos 12 modulos canonicos ou string vazia se nao mapeavel."""
    text = (raw or "").strip()
    if not text:
        return ""
    if text in CANONICAL_MODULES:
        return text
    if text in MODULE_ALIASES:
        candidate = MODULE_ALIASES[text]
        if candidate in CANONICAL_MODULES:
            return candidate
    folded = _fold(text)
    for alias, canonical in MODULE_ALIASES.items():
        if _fold(alias) == folded and canonical in CANONICAL_MODULES:
            return canonical
    for module in CANONICAL_MODULES:
        if _fold(module) == folded:
            return module
    return ""


def module_category(module: str) -> str:
    text = (module or "").strip()
    if not text:
        return ""
    canon = normalize_module_to_canonical(text)
    if canon in MODULE_CATEGORIES:
        return MODULE_CATEGORIES[canon]
    return "Não mapeado"


def is_canonical_module(module: str) -> bool:
    if not module:
        return False
    return normalize_module_to_canonical(module) in CANONICAL_MODULES


def normalize_area(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text in _ALL_STANDARD_AREAS:
        return text
    key = _fold(text)
    if key in AREA_ALIASES:
        return AREA_ALIASES[key]
    for area in _ALL_STANDARD_AREAS:
        if _fold(area) == key:
            return area
    return text


def is_standard_area(area: str, module: str = "") -> bool:
    if not area:
        return False
    canonical_area = normalize_area(area)
    if canonical_area in _ALL_STANDARD_AREAS:
        return True
    canonical_module = normalize_module(module)
    if not canonical_module:
        return False
    module_areas = STANDARD_AREAS_BY_MODULE.get(canonical_module, ())
    return canonical_area in module_areas or _fold(canonical_area) in {
        _fold(a) for a in module_areas
    }


def extract_module_tag(title: str) -> str:
    match = MODULE_TAG_PATTERN.match((title or "").strip())
    if not match:
        return ""
    return match.group(1).strip()


CUSTOM_BUCKET = "Custom/Não mapeado"
NON_MODULE_BUCKET = "Meta/Não funcional"


def _compound_module_candidates(tag: str) -> List[str]:
    """Gera candidatos para tags compostas com ' - ' (ex.: Gestão de atas - PNCP)."""
    text = (tag or "").strip()
    if not text:
        return []
    return [text]


def _resolve_compound_dash_tag(text: str) -> Optional[str]:
    """Resolve tags com ' - ' priorizando contexto manual validado."""
    if " - " not in text:
        return None
    parts = [part.strip() for part in text.split(" - ") if part.strip()]
    if len(parts) < 2:
        return None
    left, right = parts[0], parts[-1]
    left_canon = normalize_module_to_canonical(left)
    right_canon = normalize_module_to_canonical(right)
    right_fold = _fold(right)

    if right_canon == "PNCP" and left_canon:
        return right_canon
    if right_fold in {_fold("bug"), _fold("bugs"), _fold("test"), _fold("teste")}:
        return left_canon or NON_MODULE_BUCKET
    if left_canon:
        return left_canon
    return right_canon


def _split_compound_tag(tag: str) -> str:
    """Compat: retorna o primeiro candidato de tag composta."""
    resolved = _resolve_compound_dash_tag(tag)
    if resolved:
        return resolved
    return (tag or "").strip()


def canonical_or_bucket(raw: str) -> str:
    """Um dos 12 canonicos, bucket meta/custom, ou vazio."""
    text = (raw or "").strip()
    if not text:
        return ""
    compound = _resolve_compound_dash_tag(text)
    if compound:
        if compound == NON_MODULE_BUCKET:
            return NON_MODULE_BUCKET
        if compound in CANONICAL_MODULES:
            return compound
    if text in NON_MODULE_TAGS or _fold(text) in {_fold(t) for t in NON_MODULE_TAGS}:
        return NON_MODULE_BUCKET
    canon = normalize_module_to_canonical(text)
    if canon:
        return canon
    return CUSTOM_BUCKET


def suggest_title_module_fix(title: str) -> Optional[str]:
    text = (title or "").strip()
    match = MODULE_TAG_PATTERN.match(text)
    if not match:
        return None
    tag = match.group(1).strip()
    canon = normalize_module_to_canonical(tag)
    if not canon or _fold(tag) == _fold(canon):
        return None
    return MODULE_TAG_PATTERN.sub(f"[{canon}]", text, count=1)


def validate_title_pattern(title: str, *, strict: bool = False) -> bool:
    text = (title or "").strip()
    if strict == "full":
        return bool(TITLE_PATTERN_FULL.match(text))
    if strict:
        return bool(TITLE_PATTERN_WITH_AREA.search(text))
    return bool(TITLE_PATTERN_BASIC.match(text))


def confidence_area_label(title: str, area: str, *, git_confidence: float = 0.0) -> str:
    if git_confidence > 0:
        return f"{int(round(git_confidence * 100))}%"
    if not area:
        return ""
    if TITLE_PATTERN_WITH_AREA.search((title or "").strip()):
        return "100%"
    return "75%"


def all_module_de_para_rows() -> List[Tuple[str, str]]:
    rows: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    def add(source: str, target: str) -> None:
        if not source or not target or target not in CANONICAL_MODULES:
            return
        key = _fold(source)
        if key in seen:
            return
        rows.append((source, target))
        seen.add(key)

    for module in CANONICAL_MODULES:
        add(module, module)
    for alias, canonical in MODULE_ALIASES.items():
        add(alias, canonical)
    for tag in MODULE_TAG_CATEGORIES:
        canon = normalize_module_to_canonical(tag)
        if canon:
            add(tag, canon)
    return rows


def all_accepted_modules_sorted() -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for module in CANONICAL_MODULES:
        if module not in seen:
            ordered.append(module)
            seen.add(module)
    for tag in sorted(MODULE_TAG_CATEGORIES, key=_fold):
        if tag not in seen:
            ordered.append(tag)
            seen.add(tag)
    return ordered


def all_module_category_rows() -> List[Tuple[str, str]]:
    return [(module, MODULE_CATEGORIES[module]) for module in CANONICAL_MODULES]


def all_standard_areas_sorted() -> List[str]:
    return sorted(_ALL_STANDARD_AREAS, key=lambda x: _fold(x))


def assess_row_quality(
    title: str,
    module: str,
    area: str,
    area_confidence: float = 0.0,
) -> Dict[str, str]:
    canon = normalize_module_to_canonical(module)
    if not canon and title:
        canon = normalize_module_to_canonical(extract_module_tag(title))
    mod_ok = "Sim" if canon in CANONICAL_MODULES else "Não"
    padrao = "Sim" if validate_title_pattern(title) else "Não"
    padrao_completo = "Sim" if validate_title_pattern(title, strict=True) else "Não"
    mod_ref = canon or module
    if not mod_ref:
        area_ok = "N/A"
    elif not area:
        area_ok = "Não"
    elif is_standard_area(area, mod_ref):
        area_ok = "Sim"
    else:
        area_ok = "Não"
    conf_text = confidence_area_label(title, area, git_confidence=area_confidence)
    return {
        "categoria": module_category(canon or module) if (canon or module) else "",
        "modulo_ok": mod_ok,
        "area_ok": area_ok,
        "padrao_titulo": padrao,
        "padrao_completo": padrao_completo,
        "confianca_area": conf_text,
    }
