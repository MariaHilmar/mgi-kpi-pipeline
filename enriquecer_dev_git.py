#!/usr/bin/env python3
"""
Enriquece issues com metadados de desenvolvimento a partir do Git local (WSL).

Coleta por issue (padrao de branch {iid}-*):
- Tem branch vinculada
- Nome da branch principal
- Quantidade de commits ahead of master
- Data do ultimo commit
- Autor principal (mais commits na branch)
- Indicio de merge em master
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import config as _config
except ImportError:
    _config = None

try:
    from issue_keys import DEFAULT_GITLAB_REPO, get_gitlab_repo, wsl_path_for_repo
except ImportError:
    DEFAULT_GITLAB_REPO = "contratos_v2"

    def get_gitlab_repo(issue):
        return issue.get("gitlab_repo") or DEFAULT_GITLAB_REPO

    def wsl_path_for_repo(repo):
        return "/root/MGI/contratos_v2" if repo == "contratos_v2" else "/root/MGI/contratos"

DEFAULT_WSL_REPO = "/root/MGI/contratos_v2"
DEFAULT_BASE_BRANCH = "master"


@dataclass
class DevGitInfo:
    tem_branch: str
    branch: str
    commits: int
    ultimo_commit: Optional[datetime]
    autor_dev: str
    mr_gitlab: int
    mergeado: str


class GitDevEnricher:
    """Coleta sinais de desenvolvimento Git vinculados a issues."""

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
        self._branch_stats_cache: Dict[str, Tuple[int, Optional[datetime], str]] = {}
        self._merged_cache: Dict[str, bool] = {}

    def enrich(self, issue: Dict) -> DevGitInfo:
        issue_id = str(issue.get("id", "")).strip()
        mr_count = _parse_int(issue.get("merge_requests_count"))

        if not issue_id or not self.enabled:
            return DevGitInfo("Não", "", 0, None, "", mr_count, "Não")

        branches = self._branches_for_issue(issue_id)

        if not branches:
            merged = False
            if mr_count > 0:
                merged = self._is_merged_to_master(issue_id, branches)
            author = self._author_from_commit_grep(issue_id)
            return DevGitInfo(
                "Não",
                "",
                0,
                None,
                author,
                mr_count,
                "Sim" if merged else "Não",
            )

        merged = self._is_merged_to_master(issue_id, branches)

        primary = _pick_primary_branch(branches)
        commits, last_date, author = self._branch_stats(primary)

        return DevGitInfo(
            tem_branch="Sim",
            branch=primary,
            commits=commits,
            ultimo_commit=last_date,
            autor_dev=author,
            mr_gitlab=mr_count,
            mergeado="Sim" if merged else "Não",
        )

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

    def _branch_stats(self, branch: str) -> Tuple[int, Optional[datetime], str]:
        if branch in self._branch_stats_cache:
            return self._branch_stats_cache[branch]

        refs = _branch_refs(branch)
        commit_count = 0
        for ref in refs:
            output = self._run_git(
                f"rev-list --count {self.base_branch}..{ref} 2>/dev/null"
            )
            if output.strip().isdigit():
                commit_count = max(commit_count, int(output.strip()))
                break

        last_date: Optional[datetime] = None
        author = ""
        authors: Counter = Counter()

        for ref in refs:
            log_output = self._run_git(
                f"log {ref} -n 80 --format='%aI|%an' 2>/dev/null"
            )
            if not log_output.strip():
                continue
            for line in log_output.splitlines():
                parts = line.split("|", 1)
                if len(parts) != 2:
                    continue
                date_raw, author_name = parts[0].strip(), parts[1].strip()
                authors[author_name] += 1
                parsed = _parse_git_date(date_raw)
                if parsed and (last_date is None or parsed > last_date):
                    last_date = parsed
            if authors:
                author = authors.most_common(1)[0][0]
            if commit_count or last_date:
                break

        stats = (commit_count, last_date, author)
        self._branch_stats_cache[branch] = stats
        return stats

    def _is_merged_to_master(self, issue_id: str, branches: List[str]) -> bool:
        cache_key = f"{issue_id}:{'|'.join(sorted(branches))}"
        if cache_key in self._merged_cache:
            return self._merged_cache[cache_key]

        merged = False

        for branch in branches:
            short = branch.split("/")[-1]
            listed = self._run_git(
                f"branch -a --merged {self.base_branch} --list '*{short}*' 2>/dev/null"
            )
            if listed.strip():
                merged = True
                break

        if not merged:
            merge_log = self._run_git(
                f"log {self.base_branch} --merges --grep='{issue_id}-' -1 --format=%H 2>/dev/null"
            )
            if merge_log.strip():
                merged = True

        if not merged:
            merge_log = self._run_git(
                f"log {self.base_branch} --grep=\"Merge branch '{issue_id}-\" -1 --format=%H 2>/dev/null"
            )
            merged = bool(merge_log.strip())

        self._merged_cache[cache_key] = merged
        return merged

    def _author_from_commit_grep(self, issue_id: str) -> str:
        if os.environ.get("MGI_DEV_SKIP_GIT_GREP", "1").lower() not in ("0", "false", "no"):
            return ""

        authors: Counter = Counter()
        patterns = [f"#{issue_id}", f"{issue_id}-", f"Closes #{issue_id}"]
        for pattern in patterns[:2]:
            quoted = shlex.quote(pattern)
            output = self._run_git(
                f"log --all -i --grep={quoted} -n 50 --format='%an' 2>/dev/null"
            )
            for line in output.splitlines():
                name = line.strip()
                if name:
                    authors[name] += 1
        if not authors:
            return ""
        return authors.most_common(1)[0][0]


def _normalize_branch_name(raw: str) -> str:
    branch = raw.strip()
    branch = branch.replace("remotes/origin/", "origin/")
    if branch.startswith("origin/origin/"):
        branch = branch.replace("origin/origin/", "origin/", 1)
    return branch.lstrip("* ").strip()


def _branch_refs(branch: str) -> List[str]:
    short = branch.split("/")[-1]
    refs = []
    if branch.startswith("origin/"):
        refs.append(branch)
    else:
        refs.extend([f"origin/{short}", short])
    return refs


def _pick_primary_branch(branches: List[str]) -> str:
    normalized = [_normalize_branch_name(b) for b in branches]
    normalized.sort(key=lambda name: (len(name), name))
    for name in normalized:
        if not name.startswith("origin/HEAD"):
            return name.split("/")[-1] if "/" in name else name
    return normalized[0].split("/")[-1]


def _parse_git_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").strip())
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError):
        return None


def _parse_int(value) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_dev_enricher() -> GitDevEnricher:
    return MultiRepoDevEnricher(enabled=True)


class MultiRepoDevEnricher:
    """Seleciona o enricher Git conforme gitlab_repo da issue."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._enrichers: Dict[str, GitDevEnricher] = {}

    def _get_enricher(self, repo: str) -> GitDevEnricher:
        if repo not in self._enrichers:
            self._enrichers[repo] = GitDevEnricher(
                wsl_repo_path=wsl_path_for_repo(repo),
                enabled=self.enabled,
            )
        return self._enrichers[repo]

    def enrich(self, issue: Dict) -> DevGitInfo:
        repo = get_gitlab_repo(issue)
        alt_repo = "contratos" if repo == "contratos_v2" else "contratos_v2"
        best: Optional[DevGitInfo] = None
        for try_repo in (repo, alt_repo):
            info = self._get_enricher(try_repo).enrich(issue)
            if _dev_info_score(info) > _dev_info_score(best):
                best = info
        return best or DevGitInfo("Não", "", 0, None, "", 0, "Não")


def _dev_info_score(info: Optional[DevGitInfo]) -> int:
    if not info:
        return -1
    score = 0
    if info.tem_branch == "Sim":
        score += 100
    if info.autor_dev:
        score += 50
    score += min(info.commits, 20)
    if info.mergeado == "Sim":
        score += 5
    return score


def resolve_desenvolvedor(issue: Dict, info: Optional[DevGitInfo] = None) -> str:
    """Desenvolvedor principal: Git (mais commits) > assignee GitLab."""
    if info is None:
        info = build_dev_enricher().enrich(issue)
    if info.autor_dev:
        return info.autor_dev.strip()
    assignees = issue.get("assignees") or []
    for person in assignees:
        name = (person.get("name") if isinstance(person, dict) else str(person)).strip()
        if name:
            return name
    return ""
