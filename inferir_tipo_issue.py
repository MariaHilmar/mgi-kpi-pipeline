#!/usr/bin/env python3
"""
Infere o Tipo da issue (Bug, Melhoria, Performance) quando nao ha label tipo::.

Prioridade:
1. Label tipo:: no GitLab (nao inferido aqui)
2. Mensagens de commit em branches/MRs vinculadas a issue ({iid}-*)
3. Nome da branch vinculada
4. Palavras-chave no titulo da issue
"""

from __future__ import annotations

import re
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

VALID_TIPOS = frozenset({"Bug", "Melhoria", "Performance"})

COMMIT_TIPO_RULES: Sequence[Tuple[str, str]] = (
    (r"^\s*fix\b", "Bug"),
    (r"^\s*bugfix\b", "Bug"),
    (r"^\s*hotfix\b", "Bug"),
    (r"^\s*perf\b", "Performance"),
    (r"^\s*feat\b", "Melhoria"),
    (r"^\s*feature\b", "Melhoria"),
)

BRANCH_TIPO_RULES: Sequence[Tuple[str, str]] = (
    (r"bug|fix|hotfix|correc", "Bug"),
    (r"feat|feature|melhoria", "Melhoria"),
    (r"perf|performance", "Performance"),
)

TITLE_TIPO_RULES: Sequence[Tuple[str, str]] = (
    (r"\bincidente\b|\bbug\b|\bcorr(?:e|i)(?:ç|c)?(?:ã|a)o\b|\berro\b|\bfalha\b", "Bug"),
    (r"\bperformance\b|\botimiz", "Performance"),
    (r"\bmelhoria\b|\bpermitir\b|\bincluir\b|\bimplement", "Melhoria"),
)


@dataclass
class TipoDetection:
    tipo: str
    method: str
    confidence: float


class TipoIssueDetector:
    """Infere tipo cruzando issue com branches e commits do Git."""

    def __init__(
        self,
        wsl_repo_path: str = DEFAULT_WSL_REPO,
        enabled: bool = True,
    ):
        self.wsl_repo_path = wsl_repo_path
        self.enabled = enabled
        self._branch_index: Optional[Dict[str, List[str]]] = None
        self._commits_cache: Dict[str, List[str]] = {}

    def detect(self, issue: Dict) -> TipoDetection:
        issue_id = str(issue.get("id", "")).strip()
        if not issue_id:
            return TipoDetection("", "none", 0.0)

        branches: List[str] = []
        if self.enabled:
            branches = self._branches_for_issue(issue_id)
            if branches:
                commits = self._commits_for_issue(issue_id, branches)
                tipo = _infer_tipo_from_commits(commits)
                if tipo:
                    return TipoDetection(tipo, "git_commits", 0.9)

                branch_text = " ".join(branches)
                tipo = _infer_tipo_from_text(branch_text, BRANCH_TIPO_RULES)
                if tipo:
                    return TipoDetection(tipo, "git_branch", 0.85)

        title = issue.get("title", "") or ""
        tipo = _infer_tipo_from_text(title, TITLE_TIPO_RULES)
        if tipo:
            return TipoDetection(tipo, "palavras_chave_titulo", 0.65)

        return TipoDetection("", "none", 0.0)

    def _run_git(self, git_args: str, timeout: int = 45) -> str:
        cmd = [
            "wsl",
            "-d",
            "Ubuntu",
            "bash",
            "-lc",
            f"cd {self.wsl_repo_path} && git {git_args}",
        ]
        try:
            import subprocess

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                return ""
            return result.stdout
        except (ImportError, OSError, subprocess.TimeoutExpired):
            return ""

    def _ensure_branch_index(self) -> None:
        if self._branch_index is not None:
            return

        output = self._run_git("branch -a --format='%(refname:short)'")
        index: Dict[str, List[str]] = {}
        for line in output.splitlines():
            branch = line.strip().lstrip("origin/").lstrip("remotes/")
            short = branch.split("/")[-1]
            match = re.match(r"^(\d{3,5})-", short)
            if match:
                index.setdefault(match.group(1), []).append(branch)
        self._branch_index = index

    def _branches_for_issue(self, issue_id: str) -> List[str]:
        self._ensure_branch_index()
        return self._branch_index.get(issue_id, []) if self._branch_index else []

    def _commits_for_issue(self, issue_id: str, branches: List[str]) -> List[str]:
        if issue_id in self._commits_cache:
            return self._commits_cache[issue_id]

        messages: List[str] = []

        for branch in branches:
            branch_ref = branch if branch.startswith("origin/") else f"origin/{branch}"
            output = self._run_git(
                f"log {branch_ref} --format=%s -n 80 2>/dev/null"
            )
            messages.extend(line.strip() for line in output.splitlines() if line.strip())

            merge_output = self._run_git(
                f"log --all --grep='Merge branch .{issue_id}-' -n 5 --format=%s 2>/dev/null"
            )
            messages.extend(
                line.strip() for line in merge_output.splitlines() if line.strip()
            )

        unique = list(dict.fromkeys(messages))
        self._commits_cache[issue_id] = unique
        return unique


def _infer_tipo_from_commits(messages: Sequence[str]) -> Optional[str]:
    if not messages:
        return None
    scores: Counter = Counter()
    for message in messages:
        normalized = message.strip().lower()
        for pattern, tipo in COMMIT_TIPO_RULES:
            if re.search(pattern, normalized, re.IGNORECASE):
                scores[tipo] += 1
                break
    if not scores:
        return None
    tipo, _ = scores.most_common(1)[0]
    return tipo if tipo in VALID_TIPOS else None


def _infer_tipo_from_text(text: str, rules: Sequence[Tuple[str, str]]) -> Optional[str]:
    if not text:
        return None
    normalized = text.lower()
    normalized = re.sub(r"[\-_/]+", " ", normalized)
    for pattern, tipo in rules:
        if re.search(pattern, normalized, re.IGNORECASE):
            return tipo
    return None


def build_tipo_detector() -> TipoIssueDetector:
    return MultiRepoTipoDetector(enabled=True)


class MultiRepoTipoDetector:
    """Seleciona detector de tipo conforme gitlab_repo da issue."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._detectors: Dict[str, TipoIssueDetector] = {}

    def _get_detector(self, repo: str) -> TipoIssueDetector:
        if repo not in self._detectors:
            self._detectors[repo] = TipoIssueDetector(
                wsl_repo_path=wsl_path_for_repo(repo),
                enabled=self.enabled,
            )
        return self._detectors[repo]

    def detect(self, issue: Dict) -> TipoDetection:
        repo = get_gitlab_repo(issue)
        return self._get_detector(repo).detect(issue)
