#!/usr/bin/env python3
"""
Pull condicional da branch padrao nos repos contratos* via WSL.

Para cada repositorio configurado:
  1. resolve branch (origin/HEAD, env ou master)
  2. git fetch origin <branch>
  3. compara HEAD local com origin/<branch>
  4. pull --ff-only somente se o remoto estiver a frente (fast-forward)
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import config as mgi_config
    from coleta_git_contratos import GitColeta
except ImportError as exc:
    print(f"ERRO importando modulos: {exc}")
    sys.exit(1)

DEFAULT_BRANCH = "master"
FETCH_TIMEOUT = int(os.environ.get("MGI_GIT_PULL_FETCH_TIMEOUT", "120"))
PULL_TIMEOUT = int(os.environ.get("MGI_GIT_PULL_TIMEOUT", "180"))


@dataclass
class PullResult:
    repo_name: str
    status: str  # up_to_date | updated | diverged | error | skipped
    branch: str
    local_before: str = ""
    remote: str = ""
    local_after: str = ""
    message: str = ""


def _rev_parse(coleta: GitColeta, ref: str, *, timeout: int = 30) -> str:
    return (coleta.run_git(f"rev-parse {ref}", timeout=timeout) or "").strip()


def resolve_pull_branch(coleta: GitColeta, override: str | None = None) -> str:
    """Branch para pull: override CLI/env, senao origin/HEAD, branch atual ou master."""
    if override and override.strip().lower() != "auto":
        return override.strip()

    env_branch = os.environ.get("MGI_GIT_PULL_BRANCH", "").strip()
    if env_branch and env_branch.lower() != "auto":
        return env_branch

    sym = (
        coleta.run_git("symbolic-ref --short refs/remotes/origin/HEAD", timeout=10) or ""
    ).strip()
    if sym.startswith("origin/"):
        return sym[len("origin/") :]
    if sym:
        return sym

    current = (coleta.run_git("branch --show-current", timeout=10) or "").strip()
    if current:
        return current

    return DEFAULT_BRANCH


def _default_repos() -> list[tuple[str, str]]:
    repos = list(mgi_config.REPOS)
    if repos:
        return repos
    return [(path, name) for name, path in mgi_config.WSL_REPO_PATHS.items()]


def pull_repo_main(
    repo_name: str,
    *,
    branch: str | None = None,
    dry_run: bool = False,
) -> PullResult:
    """Fetch + pull --ff-only se origin/<branch> estiver a frente de HEAD."""
    coleta = GitColeta("", repo_name)

    if not coleta.validar_repo():
        return PullResult(
            repo_name=repo_name,
            status="error",
            branch=branch or DEFAULT_BRANCH,
            message=f"repositorio inacessivel ({coleta.wsl_repo_path})",
        )

    branch_name = resolve_pull_branch(coleta, branch)
    print(f"\n--- {repo_name} ({coleta.wsl_repo_path}) ---")
    print(f"Branch:    {branch_name}")

    coleta.run_git(f"fetch origin {branch_name}", timeout=FETCH_TIMEOUT)

    local = _rev_parse(coleta, "HEAD")
    remote = _rev_parse(coleta, f"origin/{branch_name}")

    if not local:
        return PullResult(
            repo_name=repo_name,
            status="error",
            branch=branch_name,
            message="nao foi possivel ler HEAD local",
        )
    if not remote:
        return PullResult(
            repo_name=repo_name,
            status="error",
            branch=branch_name,
            message=f"nao foi possivel ler origin/{branch_name}",
        )

    if local == remote:
        print(f"OK - Ja atualizado ({local[:12]}...)")
        return PullResult(
            repo_name=repo_name,
            status="up_to_date",
            branch=branch_name,
            local_before=local,
            remote=remote,
            local_after=local,
            message="sem alteracoes no remoto",
        )

    merge_base = (coleta.run_git(f"merge-base HEAD origin/{branch_name}", timeout=30) or "").strip()
    if merge_base != local:
        print(f"AVISO - Historico divergente (local={local[:12]}..., remoto={remote[:12]}...)")
        print("        Pull ignorado - resolva manualmente no WSL.")
        return PullResult(
            repo_name=repo_name,
            status="diverged",
            branch=branch_name,
            local_before=local,
            remote=remote,
            message=f"HEAD local nao e ancestral de origin/{branch_name}",
        )

    if dry_run:
        print(f"OK - Dry-run: pull --ff-only origin {branch_name} ({local[:12]} -> {remote[:12]})")
        return PullResult(
            repo_name=repo_name,
            status="updated",
            branch=branch_name,
            local_before=local,
            remote=remote,
            local_after=remote,
            message="dry-run",
        )

    coleta.run_git(f"pull --ff-only origin {branch_name}", timeout=PULL_TIMEOUT)
    after = _rev_parse(coleta, "HEAD")

    if after != remote:
        return PullResult(
            repo_name=repo_name,
            status="error",
            branch=branch_name,
            local_before=local,
            remote=remote,
            local_after=after,
            message=f"pull concluido mas HEAD difere de origin/{branch_name}",
        )

    print(f"OK - Atualizado {local[:12]} -> {after[:12]}")
    return PullResult(
        repo_name=repo_name,
        status="updated",
        branch=branch_name,
        local_before=local,
        remote=remote,
        local_after=after,
        message="pull --ff-only concluido",
    )


def _branch_override(branch: str | None) -> str | None:
    if branch and branch.strip().lower() != "auto":
        return branch.strip()
    env_branch = os.environ.get("MGI_GIT_PULL_BRANCH", "").strip()
    if env_branch and env_branch.lower() != "auto":
        return env_branch
    return None


def pull_all_repos(
    repos: list[tuple[str, str]] | None = None,
    *,
    branch: str | None = None,
    dry_run: bool = False,
) -> tuple[list[PullResult], int]:
    """Executa pull condicional em todos os repos configurados."""
    repo_list = repos if repos is not None else _default_repos()
    branch_override = _branch_override(branch)
    branch_label = branch_override or "auto (origin/HEAD por repo, fallback master)"

    print("=" * 70)
    print("PULL CONDICIONAL - repos contratos* (WSL)")
    print("=" * 70)
    print(f"Data/Hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"Branch:    {branch_label}")
    print(f"Repos:     {', '.join(name for _, name in repo_list)}")
    if dry_run:
        print("Modo:      dry-run (sem pull)")

    results: list[PullResult] = []
    for _, repo_name in repo_list:
        results.append(pull_repo_main(repo_name, branch=branch_override, dry_run=dry_run))

    updated = sum(1 for r in results if r.status == "updated")
    up_to_date = sum(1 for r in results if r.status == "up_to_date")
    errors = sum(1 for r in results if r.status == "error")
    diverged = sum(1 for r in results if r.status == "diverged")

    print("\n" + "=" * 70)
    print("RESUMO")
    print("=" * 70)
    print(f"  Atualizados:     {updated}")
    print(f"  Ja em dia:       {up_to_date}")
    print(f"  Divergentes:     {diverged}")
    print(f"  Erros:           {errors}")

    exit_code = 1 if errors else 0
    return results, exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull condicional nos repos contratos* (WSL Ubuntu)",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="branch remota fixa (padrao: detecta origin/HEAD; fallback master)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="simula fetch/comparacao sem executar pull",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _, exit_code = pull_all_repos(branch=args.branch, dry_run=args.dry_run)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
