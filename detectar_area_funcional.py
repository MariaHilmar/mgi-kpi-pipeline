#!/usr/bin/env python3
"""
Infere a Area Funcional de uma issue a partir do codigo no Git.

Prioridade:
1. Area explicita no titulo: [Modulo] (Area) - ...
2. Arquivos alterados em branches/commits vinculados a issue ({iid}-*, #iid, etc.)
3. Palavras-chave no nome da branch
4. Palavras-chave apenas no titulo da issue (nao usa descricao — evita falso positivo)
5. Modulo [X] mapeado somente quando X corresponde a area conhecida
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import config as _config
except ImportError:
    _config = None

try:
    from issue_keys import get_gitlab_repo, wsl_path_for_repo
except ImportError:
    def get_gitlab_repo(issue):
        return issue.get("gitlab_repo") or "contratos_v2"

    def wsl_path_for_repo(repo):
        return "/root/MGI/contratos_v2" if repo == "contratos_v2" else "/root/MGI/contratos"

DEFAULT_WSL_REPO = "/root/MGI/contratos_v2"
DEFAULT_BASE_BRANCH = "master"

FILE_AREA_RULES: Sequence[Tuple[str, str]] = (
    (r"InstrumentoCobranca|instrumento.?cobranca|InstrumentoCobrancaService|/ic[/\"']", "Instrumento de Cobrança"),
    (r"TermoRecebimentoDefinitivo|/trd[/\"']|TRDCrud", "TRD"),
    (r"TermoRecebimentoProvisorio|/trp[/\"']|TRPCrud", "TRP"),
    (r"PlanoFiscalizacaoVerificacao|verificacao.*plano|plf_item", "Verificações PF"),
    (r"PlanoFiscalizacao|planofiscalizacao", "Plano de Fiscalização"),
    (r"ReembolsoCreche", "Relatório Reembolso Creche"),
    (r"DeclaracaoOpm|DeclaracaoDecreto|decreto.?11.?430", "Declaração Decreto 11.430"),
    (r"AutorizacaoExecucao|OrdemServico|/osf[/\"']", "OS/F"),
    (r"(?:^|/)(?:FornecedorCompras|UsuarioFornecedor)/|portal.?fornecedor", "Portal Fornecedor"),
    (r"EntregaCrud|AutorizacaoExecucaoEntrega|/entrega[/\"']", "Entregas"),
    (r"MeusContratos", "Meus Contratos"),
    (r"pncp|/pncp[/\"']", "PNCP"),
    (r"Apostilamento|apostilamento", "Gestão Contratual"),
    (r"MinutaEmpenho|minuta.?empenho|/empenho[/\"']", "Minuta de Empenho"),
)

TEXT_AREA_RULES: Sequence[Tuple[str, str]] = (
    (r"integra(?:ç|c)?(?:ã|a)o\s+ic\s*>\s*trd|integracao\s+ic.*trd", "Integração IC > TRD"),
    (r"termo\s+recebimento\s+provis|\btrp\b|visualizar\s+trp|consultar\s+trp", "TRP"),
    (r"termo\s+recebimento\s+definitivo|\btrd\b|visualizar\s+trd|consultar\s+trd", "TRD"),
    (r"declara(?:ç|c)?(?:ã|a)o|decreto\s*11\.430", "Declaração Decreto 11.430"),
    (r"plano\s+de\s+fiscal|\bplf\b|verifica(?:ç|c)?(?:õ|o)es\s+pf", "Plano de Fiscalização"),
    (r"\bos/f\b|ordem\s+de\s+servi", "OS/F"),
    (r"instrumento\s+de\s+cobran|\bapropria", "Instrumento de Cobrança"),
    (r"reembolso\s+creche", "Relatório Reembolso Creche"),
    (r"\bentregas?\b", "Entregas"),
    (r"\bpncp\b", "PNCP"),
    (r"portal\s+fornecedor|modulo\s+fornecedor|\[fornecedor\]", "Portal Fornecedor"),
    (r"apostilamento", "Gestão Contratual"),
    (r"minuta\s+de\s+empenho|\bempenhos?\b", "Minuta de Empenho"),
    (r"gest[aã]o\s+contratual", "Gestão Contratual"),
    (r"gest[aã]o\s+de\s+atas", "Gestão de Atas"),
    (r"instrumento\s+inicial", "Gestão Contratual"),
)

# Mapeamento canônico: módulo canônico → área padrão.
# Usado como fallback quando nenhuma outra fonte de área está disponível.
# Prioridade elevada: se o módulo está claro, a área padrão é aplicada diretamente.
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

# Mapeamento estendido: tags/aliases → área (para inferência via título e módulo raw)
MODULE_TO_AREA: Dict[str, str] = {
    # Canônicos diretos
    "PNCP": "PNCP",
    "Fornecedor": "Portal Fornecedor",
    "Fiscalização": "Plano de Fiscalização",
    "Gestão Financeira": "Gestão Financeira",
    "Instrumento de Cobrança": "Instrumento de Cobrança",
    "Minuta de Empenho": "Minuta de Empenho",
    "Gestão Contratual": "Gestão Contratual",
    "Gestão de Atas": "Gestão de Atas",
    "Transparência": "Transparência",
    "Administração": "Administração",
    "API v2": "API / Integrações",
    "Jobs": "Infraestrutura",
    # Aliases → área
    "Fiscalizacao": "Plano de Fiscalização",
    "Gestão financeira": "Gestão Financeira",
    "Gestao Financeira": "Gestão Financeira",
    "Instrumento de cobrança": "Instrumento de Cobrança",
    "Instrumentos de cobrança": "Instrumento de Cobrança",
    "Instrumentos de Cobrança": "Instrumento de Cobrança",
    "OS/F": "OS/F",
    "OSF": "OS/F",
    "Autorização de Execução": "Plano de Fiscalização",
    "Autorização de execução": "Plano de Fiscalização",
    "Minuta empenho": "Minuta de Empenho",
    "minuta empenho": "Minuta de Empenho",
    "Minuta Empenho": "Minuta de Empenho",
    "Contrato Fatura Empenhos": "Minuta de Empenho",
    "Gestão Financeiro": "Gestão Financeira",
    "Conta vinculada": "Gestão Financeira",
    "Conta Vinculada": "Gestão Financeira",
    "Conta depósito vinculada": "Gestão Financeira",
    "STA": "Gestão de Atas",
    "Terceirizados": "Infraestrutura",
    "Terceirizado": "Infraestrutura",
    "Remanejamento": "Infraestrutura",
    "Rescisão": "Infraestrutura",
    "Log": "Infraestrutura",
    "log": "Infraestrutura",
    "LOG": "Infraestrutura",
    "Desenvolvedor": "Infraestrutura",
    "desenvolvedor": "Infraestrutura",
    "SAST/DAST": "Infraestrutura",
    "Usuários": "Administração",
    "Usuário": "Administração",
    "Minuta de empenho": "Minuta de Empenho",
    "Minutas de empenho": "Minuta de Empenho",
    "Empenho": "Minuta de Empenho",
    "Empenhos": "Minuta de Empenho",
    "Contrato do tipo empenho": "Minuta de Empenho",
    "Contrato do Tipo Empenho": "Minuta de Empenho",
    "Gestão contratual": "Gestão Contratual",
    "Contratos": "Gestão Contratual",
    "Contrato": "Gestão Contratual",
    "CONTRATOS": "Gestão Contratual",
    "Instrumento Inicial": "Gestão Contratual",
    "Instrumento inicial": "Gestão Contratual",
    "Instrumento Incial": "Gestão Contratual",
    "Entregas": "Entregas",
    "Meus Contratos": "Gestão Contratual",
    "Cronograma": "Gestão Contratual",
    "Apostilamento": "Apostilamento",
    "Termo Aditivo": "Apostilamento",
    "Gestão de atas": "Gestão de Atas",
    "Gestão Orçamentária": "Instrumento de Cobrança",
    "Gestão orçamentária": "Instrumento de Cobrança",
    "Apropriação": "Instrumento de Cobrança",
    "Apropriacão": "Instrumento de Cobrança",
    "Conta-Depósito vinculada": "Conta-Depósito vinculada",
    "AntecipaGov": "AntecipaGov",
    "siafi": "Instrumento de Cobrança",
    "Siafi": "Instrumento de Cobrança",
    "IC": "Instrumento de Cobrança",
    "API": "API / Integrações",
    "SEI": "Integração SEI",
    "sei": "Integração SEI",
    "Siads": "API / Integrações",
    "API Siads": "API / Integrações",
    "admin": "Administração",
    "BD": "Infraestrutura",
    "Banco de Dados": "Banco de Dados",
    "Ambiente": "Infraestrutura",
    "Login": "Acesso",
    "Acesso": "Acesso",
    "acesso": "Acesso",
    "Jobs": "Infraestrutura",
    "JOB": "Infraestrutura",
    "Pipeline": "Infraestrutura",
    "CI/CD": "Infraestrutura",
    "Redis": "Infraestrutura",
    "Compra": "Compras",
    "Compras": "Compras",
    "CompraTrait": "Compras",
    "Notificações": "Notificações",
    "Permissões": "Permissões",
    "Parâmetros": "Parâmetros",
}

_MODULE_ALIASES: Dict[str, str] = {
    re.sub(r"\s+", " ", k.strip().casefold()): v for k, v in MODULE_TO_AREA.items()
}

# Parenteses no titulo que indicam fluxo/persona, nao area funcional.
_TITLE_AREA_DENYLIST = frozenset(
    {
        "fornecedor",
        "gestor",
        "fiscal",
        "admin",
        "usuario",
        "usuário",
    }
)

_FILE_RULE_WEIGHTS: Dict[str, int] = {
    "Portal Fornecedor": 1,
}


@dataclass
class AreaDetection:
    area: str
    method: str
    confidence: float


class AreaFuncionalDetector:
    """Detecta area funcional cruzando issue com branches/arquivos/commits do Git."""

    def __init__(
        self,
        wsl_repo_path: str = DEFAULT_WSL_REPO,
        base_branch: str = DEFAULT_BASE_BRANCH,
        enabled: bool = True,
    ):
        self.wsl_repo_path = wsl_repo_path
        self.base_branch = base_branch
        self.enabled = enabled
        self._branch_index: Optional[Dict[str, List[str]]] = None
        self._files_cache: Dict[str, List[str]] = {}

    def detect(self, issue: Dict, title_area: str = "") -> AreaDetection:
        title_area = _normalize_title_area(title_area)
        if title_area:
            return AreaDetection(title_area, "titulo_explicito", 1.0)

        issue_id = str(issue.get("id", "")).strip()
        if not issue_id:
            return AreaDetection("", "none", 0.0)

        skip_git = os.environ.get("MGI_AREA_TITULO_ONLY", "0").lower() in ("1", "true", "yes")
        if self.enabled and not skip_git:
            files = self._files_for_issue(issue_id)
            area = _infer_area_from_files(files)
            if area:
                return AreaDetection(area, "git_arquivos", 0.95)

            branch_text = " ".join(self._branches_for_issue(issue_id))
            area = _infer_area_from_text(branch_text)
            if area:
                return AreaDetection(area, "git_branch", 0.85)

        title = issue.get("title", "") or ""

        module_area = _infer_default_area_from_canonical_module(title)
        if module_area:
            return AreaDetection(module_area, "modulo_canonico_default", 0.80)

        area = _infer_area_from_text(title)
        if area:
            return AreaDetection(area, "palavras_chave_titulo", 0.75)

        module_area = _infer_area_from_module(title)
        if module_area:
            return AreaDetection(module_area, "modulo", 0.60)

        return AreaDetection("", "none", 0.0)

    def _run_git(self, git_args: str, timeout: int = 60) -> str:
        cmd = [
            "wsl",
            "-d",
            "Ubuntu",
            "bash",
            "-lc",
            f"cd {self.wsl_repo_path} && git {git_args}",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                return ""
            return result.stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def _ensure_branch_index(self) -> None:
        if self._branch_index is not None:
            return

        output = self._run_git("branch -a --format='%(refname:short)'")
        index: Dict[str, List[str]] = {}
        for line in output.splitlines():
            branch = _normalize_branch_name(line.strip())
            if not branch:
                continue
            short = branch.split("/")[-1]
            match = re.match(r"^(\d{3,5})-", short)
            if match:
                index.setdefault(match.group(1), []).append(branch)
        self._branch_index = index

    def _branches_for_issue(self, issue_id: str) -> List[str]:
        self._ensure_branch_index()
        if not self._branch_index:
            return []
        return self._branch_index.get(issue_id, [])

    def _branch_refs(self, branch: str) -> List[str]:
        short = branch.split("/")[-1]
        refs = []
        if branch.startswith("origin/"):
            refs.append(branch)
        refs.extend([f"origin/{short}", short])
        return list(dict.fromkeys(refs))

    def _collect_paths_from_git_output(self, output: str) -> List[str]:
        paths: List[str] = []
        for line in output.splitlines():
            path = line.strip()
            if not path or path.startswith("."):
                continue
            if "/" in path or path.endswith((".php", ".js", ".vue", ".ts", ".tsx", ".java")):
                paths.append(path)
        return paths

    def _files_from_branches(self, issue_id: str, branches: List[str]) -> List[str]:
        files: List[str] = []
        max_branches = int(os.environ.get("MGI_AREA_MAX_BRANCHES", "2"))
        for branch in branches[:max_branches]:
            for ref in self._branch_refs(branch)[:1]:
                diff_files = self._run_git(
                    f"log {self.base_branch}..{ref} --name-only --pretty=format: -n 80 2>/dev/null"
                )
                files.extend(self._collect_paths_from_git_output(diff_files))
        return files

    def _files_from_commit_grep(self, issue_id: str, limited: bool = False) -> List[str]:
        files: List[str] = []
        patterns = [
            f"#{issue_id}",
            f"{issue_id}-",
            f"issue {issue_id}",
            f"issues/{issue_id}",
            f"Closes #{issue_id}",
            f"Resolve #{issue_id}",
        ]
        if limited:
            patterns = patterns[:2]
        for pattern in patterns:
            quoted = shlex.quote(pattern)
            output = self._run_git(
                f"log --all -i --grep={quoted} --name-only --pretty=format: -n 80 2>/dev/null"
            )
            files.extend(self._collect_paths_from_git_output(output))
        return files

    def _files_for_issue(self, issue_id: str) -> List[str]:
        if issue_id in self._files_cache:
            return self._files_cache[issue_id]

        branches = self._branches_for_issue(issue_id)
        files: List[str] = []
        if branches:
            files.extend(self._files_from_branches(issue_id, branches))
            files.extend(self._files_from_commit_grep(issue_id))
        elif os.environ.get("MGI_AREA_SKIP_GIT_GREP", "1").lower() not in ("0", "false", "no"):
            pass
        else:
            files.extend(self._files_from_commit_grep(issue_id, limited=True))

        unique = sorted(set(files))
        self._files_cache[issue_id] = unique
        return unique


def _normalize_branch_name(raw: str) -> str:
    branch = raw.strip().lstrip("* ")
    branch = branch.replace("remotes/origin/", "origin/")
    if branch.startswith("origin/origin/"):
        branch = branch.replace("origin/origin/", "origin/", 1)
    return branch


def _normalize_title_area(area: str) -> str:
    cleaned = (area or "").strip()
    if not cleaned:
        return ""
    if cleaned.casefold() in _TITLE_AREA_DENYLIST:
        return ""
    return cleaned


def _infer_area_from_files(files: Sequence[str]) -> Optional[str]:
    if not files:
        return None
    scores: Counter = Counter()
    for path in files:
        for pattern, area in FILE_AREA_RULES:
            if re.search(pattern, path, re.IGNORECASE):
                scores[area] += _FILE_RULE_WEIGHTS.get(area, 2)
    if not scores:
        return None
    return scores.most_common(1)[0][0]


def _infer_area_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    normalized = text.lower()
    normalized = re.sub(r"[\-_/]+", " ", normalized)
    for pattern, area in TEXT_AREA_RULES:
        if re.search(pattern, normalized, re.IGNORECASE):
            return area
    return None


def _infer_area_from_module(title: str) -> Optional[str]:
    match = re.match(r"^\[([^\]\}]+)", title or "")
    if not match:
        return None
    module = match.group(1).strip()
    if module in MODULE_TO_AREA:
        return MODULE_TO_AREA[module]
    normalized = re.sub(r"\s+", " ", module.casefold())
    return _MODULE_ALIASES.get(normalized)

def _infer_default_area_from_canonical_module(title: str) -> Optional[str]:
    """Retorna área padrão quando o módulo canônico está claro no título.

    Usa apenas os 12 canônicos + mapeamento direto módulo→área.
    Alta confiança (0.80) — cobre a maioria das issues sem área explícita.
    """
    from taxonomy import (  # noqa: PLC0415
        CANONICAL_MODULE_TO_DEFAULT_AREA,
        NON_MODULE_BUCKET,
        _resolve_compound_dash_tag,
        normalize_module_to_canonical,
    )

    match = re.match(r"^\[([^\]]+)\]", title or "")
    if not match:
        return None
    tag = match.group(1).strip()
    compound = _resolve_compound_dash_tag(tag)
    if compound and compound != NON_MODULE_BUCKET and compound in CANONICAL_MODULE_TO_DEFAULT_AREA:
        return CANONICAL_MODULE_TO_DEFAULT_AREA.get(compound)
    for candidate in (tag,):
        canon = normalize_module_to_canonical(candidate)
        if canon:
            return CANONICAL_MODULE_TO_DEFAULT_AREA.get(canon)
    return None


class MultiRepoAreaDetector:
    """Seleciona detector de area funcional conforme gitlab_repo da issue."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._detectors: Dict[str, AreaFuncionalDetector] = {}

    def _get_detector(self, repo: str) -> AreaFuncionalDetector:
        if repo not in self._detectors:
            self._detectors[repo] = AreaFuncionalDetector(
                wsl_repo_path=wsl_path_for_repo(repo),
                enabled=self.enabled,
            )
        return self._detectors[repo]

    def detect(self, issue: Dict, title_area: str = "") -> AreaDetection:
        title_area = _normalize_title_area(title_area)
        if title_area:
            return AreaDetection(title_area, "titulo_explicito", 1.0)

        issue_id = str(issue.get("id", "")).strip()
        if not issue_id:
            return AreaDetection("", "none", 0.0)

        skip_git = os.environ.get("MGI_AREA_TITULO_ONLY", "0").lower() in ("1", "true", "yes")
        if self.enabled and not skip_git:
            repo = get_gitlab_repo(issue)
            alt_repo = "contratos" if repo == "contratos_v2" else "contratos_v2"
            for try_repo in (repo, alt_repo):
                detector = self._get_detector(try_repo)
                files = detector._files_for_issue(issue_id)
                area = _infer_area_from_files(files)
                if area:
                    return AreaDetection(area, "git_arquivos", 0.95)

                branch_text = " ".join(detector._branches_for_issue(issue_id))
                area = _infer_area_from_text(branch_text)
                if area:
                    return AreaDetection(area, "git_branch", 0.85)

        title = issue.get("title", "") or ""

        module_area = _infer_default_area_from_canonical_module(title)
        if module_area:
            return AreaDetection(module_area, "modulo_canonico_default", 0.80)

        area = _infer_area_from_text(title)
        if area:
            return AreaDetection(area, "palavras_chave_titulo", 0.75)

        module_area = _infer_area_from_module(title)
        if module_area:
            return AreaDetection(module_area, "modulo", 0.60)

        return AreaDetection("", "none", 0.0)


def build_detector() -> MultiRepoAreaDetector:
    return MultiRepoAreaDetector(enabled=True)


def detect_functional_area(issue: dict, title_area: str = "") -> str:
    detector = build_detector()
    return detector.detect(issue, title_area=title_area).area
