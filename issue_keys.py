#!/usr/bin/env python3
"""Chaves compostas para issues de multiplos projetos GitLab."""

from __future__ import annotations

from typing import Dict, Tuple

DEFAULT_GITLAB_REPO = "contratos_v2"

GITLAB_BASE_URL = "https://gitlab.com"

GITLAB_PROJECT_PATHS: Dict[str, str] = {
    "contratos_v2": "comprasnet/contratos_v2",
    "contratos": "comprasnet/contratos",
}

REPO_DISPLAY_NAMES: Dict[str, str] = {
    "contratos_v2": "Contratos v2",
    "contratos": "Contratos v1",
}

# Aliases gravados na planilha -> slug canonico
REPO_ALIASES: Dict[str, str] = {
    "contratos v2": "contratos_v2",
    "contratos v1": "contratos",
    "contrato v1": "contratos",
    "contratos_v2": "contratos_v2",
    "contratos": "contratos",
}


def normalize_repo(raw: str) -> str:
    """Normaliza rotulo da coluna Repositório para slug GitLab."""
    text = (raw or "").strip()
    if not text:
        return DEFAULT_GITLAB_REPO
    key = text.casefold()
    if key in REPO_ALIASES:
        return REPO_ALIASES[key]
    if text in GITLAB_PROJECT_PATHS:
        return text
    return text


def repo_display_name(repo: str) -> str:
    slug = normalize_repo(repo)
    return REPO_DISPLAY_NAMES.get(slug, slug)


def gitlab_work_item_url(repo: str, iid: str) -> str:
    """URL do work item no GitLab conforme o projeto."""
    slug = normalize_repo(repo)
    project = GITLAB_PROJECT_PATHS.get(slug, GITLAB_PROJECT_PATHS[DEFAULT_GITLAB_REPO])
    iid = str(iid).strip()
    return f"{GITLAB_BASE_URL}/{project}/-/work_items/{iid}"

WSL_REPO_PATHS: Dict[str, str] = {
    "contratos_v2": "/root/MGI/contratos_v2",
    "contratos": "/root/MGI/contratos",
}


def get_gitlab_repo(issue: Dict) -> str:
    repo = (issue.get("gitlab_repo") or issue.get("repositorio") or "").strip()
    return repo or DEFAULT_GITLAB_REPO


def make_issue_key(issue: Dict) -> str:
    iid = str(issue.get("id", "")).strip()
    return f"{get_gitlab_repo(issue)}:{iid}"


def make_key_from_parts(repo: str, iid: str) -> str:
    repo = (repo or DEFAULT_GITLAB_REPO).strip()
    return f"{repo}:{iid}"


def parse_issue_key(key: str) -> Tuple[str, str]:
    if ":" in key:
        repo, iid = key.split(":", 1)
        return repo.strip() or DEFAULT_GITLAB_REPO, iid.strip()
    return DEFAULT_GITLAB_REPO, key.strip()


def lookup_issue(issues_by_id: Dict[str, Dict], issue_key: str) -> Dict | None:
    """Busca issue pela chave composta; tenta o outro repo se o IID so existir la."""
    issue = issues_by_id.get(issue_key)
    if issue:
        return issue
    repo, iid = parse_issue_key(issue_key)
    if not iid:
        return None
    alt_repo = "contratos" if repo == "contratos_v2" else "contratos_v2"
    return issues_by_id.get(make_key_from_parts(alt_repo, iid))


def wsl_path_for_repo(repo: str) -> str:
    return WSL_REPO_PATHS.get(repo, WSL_REPO_PATHS[DEFAULT_GITLAB_REPO])


def summarize_issues_by_repo(issues) -> Tuple[Dict[str, int], int]:
    """Conta issues por gitlab_repo e quantas nao tem o campo."""
    from collections import Counter

    counts: Counter = Counter()
    missing = 0
    for issue in issues:
        raw = (issue.get("gitlab_repo") or issue.get("repositorio") or "").strip()
        if not raw:
            missing += 1
        counts[get_gitlab_repo(issue)] += 1
    return dict(counts), missing
