#!/usr/bin/env python3
"""
Configuracao centralizada do pipeline MGI (mgi-workspace/mgi-kpi-pipeline).

Valores podem ser sobrescritos por variaveis de ambiente, evitando
caminhos e credenciais espalhados/hardcoded pelo codigo.
"""

import os
from datetime import datetime
from pathlib import Path
from typing import List, Set, Tuple

# ---------------------------------------------------------------------------
# Caminhos base
# ---------------------------------------------------------------------------
_WORKSPACE_DIR = Path(__file__).resolve().parent.parent
BASE_DIR: Path = Path(os.environ.get("MGI_BASE_DIR", str(_WORKSPACE_DIR)))
MGI_DIR: Path = Path(os.environ.get("MGI_PIPELINE_DIR", str(Path(__file__).resolve().parent)))
LOGS_DIR: Path = BASE_DIR / "logs"

EXCEL_OUTPUT: Path = Path(
    os.environ.get("MGI_EXCEL_OUTPUT", str(BASE_DIR / "MGI_Dashboard.xlsx"))
)
ISSUES_JSON: Path = Path(
    os.environ.get("MGI_ISSUES_JSON", str(MGI_DIR / "gitlab_issues_raw.json"))
)
GIT_DATA_JSON: Path = Path(
    os.environ.get("MGI_GIT_DATA_JSON", str(BASE_DIR / "gitlab_git_data.json"))
)

# ---------------------------------------------------------------------------
# Coleta Git
# ---------------------------------------------------------------------------
REPOS: List[Tuple[str, str]] = [
    ("<path-contratos_v2>", "contratos_v2"),
    ("<path-contratos>", "contratos"),
]
SINCE_DAYS: int = int(os.environ.get("MGI_SINCE_DAYS", "30"))

# ---------------------------------------------------------------------------
# Processamento de issues
# ---------------------------------------------------------------------------
DEFAULT_CUTOFF_DATE: datetime = datetime(2024, 1, 1)
ALLOWED_MODULES: Set[str] = {"Fiscalização", "Fornecedor"}
# True = inclui todas as issues (qualquer modulo no titulo); False = so ALLOWED_MODULES
ALL_MODULES: bool = os.environ.get("MGI_ALL_MODULES", "1").lower() not in (
    "0", "false", "no",
)
# False = apenas atualiza issues ja na planilha, nao insere novas
ALLOW_NEW_ISSUES: bool = os.environ.get("MGI_ALLOW_NEW_ISSUES", "1").lower() not in (
    "0", "false", "no",
)
# True = nao sobrescreve Módulo / Área Funcional em linhas ja presentes no Excel
PRESERVE_EXISTING_TAXONOMY: bool = os.environ.get("MGI_PRESERVE_TAXONOMY", "1").lower() not in (
    "0", "false", "no",
)
# Issues fechadas ha mais de N dias sao excluidas do JSON e do processamento
CLOSED_EXCLUDE_DAYS: int = int(os.environ.get("MGI_CLOSED_EXCLUDE_DAYS", "60"))
# Carga inicial: inclui todas as issues do JSON, exceto fechadas antigas (60 dias)
# A data de corte (ex.: 01/01/2024) continua valendo na carga inicial.
INITIAL_LOAD: bool = os.environ.get("MGI_INITIAL_LOAD", "0").lower() not in (
    "0", "false", "no",
)
# Logs e relatorios JSON mais antigos que N dias sao excluidos automaticamente
LOG_RETENTION_DAYS: int = int(os.environ.get("MGI_LOG_RETENTION_DAYS", "5"))

# Modo de atualizacao: normal (incremental) | full (reprocessa metadados/enriquecimentos)
REFRESH_MODE: str = os.environ.get("MGI_REFRESH_MODE", "normal").strip().lower()


def is_full_refresh() -> bool:
    """True quando a execucao deve reprocessar todos os metadados calculados."""
    return REFRESH_MODE in ("full", "completo", "complete")


def descricao_refresh_mode() -> str:
    if is_full_refresh():
        return "EXECUCAO COMPLETA (reprocessa metadados, labels, tipo e Dev/Git)"
    return "incremental (metadados GitLab so quando vazios)"

# ---------------------------------------------------------------------------
# Integracao GitLab (opcional) - NUNCA hardcodar token aqui
# ---------------------------------------------------------------------------
GITLAB_URL: str = os.environ.get("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN: str = os.environ.get("GITLAB_TOKEN", "")
# Tokens por repositorio (opcional). Se vazio, usa GITLAB_TOKEN global.
GITLAB_TOKEN_CONTRATOS_V2: str = os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", "")
GITLAB_TOKEN_CONTRATOS: str = os.environ.get("GITLAB_TOKEN_CONTRATOS", "")
GITLAB_PROJECT_ID: str = os.environ.get("GITLAB_PROJECT_ID", "comprasnet%2Fcontratos_v2")
# (project_id URL-encoded, nome curto do repo)
GITLAB_PROJECTS: List[Tuple[str, str]] = [
    ("comprasnet%2Fcontratos_v2", "contratos_v2"),
    ("comprasnet%2Fcontratos", "contratos"),
]

_GITLAB_TOKEN_BY_REPO = {
    "contratos_v2": GITLAB_TOKEN_CONTRATOS_V2,
    "contratos": GITLAB_TOKEN_CONTRATOS,
}


def gitlab_token_for_repo(repo_name: str) -> str:
    """Token do GitLab para um repositorio, com fallback para GITLAB_TOKEN."""
    specific = _GITLAB_TOKEN_BY_REPO.get(repo_name, "")
    if specific:
        return specific
    return GITLAB_TOKEN


def gitlab_tokens_configurados() -> List[str]:
    """Nomes dos repositorios com token disponivel (especifico ou global)."""
    configured: List[str] = []
    for _, repo_name in GITLAB_PROJECTS:
        if gitlab_token_for_repo(repo_name):
            configured.append(repo_name)
    return configured


def modulo_permitido(module: str) -> bool:
    """Retorna True se a issue pode ser inserida com base no filtro de modulo."""
    if ALL_MODULES:
        return True
    if not module:
        return False
    return module in ALLOWED_MODULES


def descricao_filtro_modulos() -> str:
    if ALL_MODULES:
        return "TODOS os modulos (MGI_ALL_MODULES=1)"
    return ", ".join(sorted(ALLOWED_MODULES))


def closed_exclude_days() -> int:
    """Dias para excluir issues fechadas; 0 = incluir todas (carga inicial)."""
    if INITIAL_LOAD:
        return 0
    return CLOSED_EXCLUDE_DAYS


def descricao_filtro_fechadas() -> str:
    if INITIAL_LOAD:
        return "DESATIVADO na carga inicial (JSON com todas as issues abertas/recentes)"
    days = CLOSED_EXCLUDE_DAYS
    return f"issues fechadas ha mais de {days} dias excluidas"
