"""Testes do pull condicional (WSL)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pull_repos_main as prm


def _coleta_mock(run_git_side_effect):
    coleta = MagicMock()
    coleta.wsl_repo_path = "/root/MGI/contratos_v2"
    coleta.validar_repo.return_value = True
    coleta.run_git.side_effect = run_git_side_effect
    return coleta


def test_resolve_pull_branch_origin_head():
    coleta = MagicMock()
    coleta.run_git.return_value = "origin/master"
    assert prm.resolve_pull_branch(coleta) == "master"


def test_resolve_pull_branch_override():
    coleta = MagicMock()
    assert prm.resolve_pull_branch(coleta, "develop") == "develop"


def test_pull_up_to_date():
    coleta = _coleta_mock(
        lambda cmd, timeout=30: {
            "symbolic-ref --short refs/remotes/origin/HEAD": "origin/master",
            "fetch origin master": "",
            "rev-parse HEAD": "aaa",
            "rev-parse origin/master": "aaa",
        }.get(cmd, "")
    )

    with patch.object(prm, "GitColeta", return_value=coleta):
        result = prm.pull_repo_main("contratos_v2")

    assert result.status == "up_to_date"
    assert result.branch == "master"
    coleta.run_git.assert_any_call("fetch origin master", timeout=prm.FETCH_TIMEOUT)
    assert not any("pull" in str(c) for c in coleta.run_git.call_args_list)


def test_pull_updates_when_behind():
    head_reads = iter(["aaa", "bbb"])

    def side_effect(cmd, timeout=30):
        if cmd == "rev-parse HEAD":
            return next(head_reads)
        return {
            "symbolic-ref --short refs/remotes/origin/HEAD": "origin/master",
            "fetch origin master": "",
            "rev-parse origin/master": "bbb",
            "merge-base HEAD origin/master": "aaa",
            "pull --ff-only origin master": "Updating aaa..bbb\nFast-forward",
        }.get(cmd, "")

    coleta = _coleta_mock(side_effect)

    with patch.object(prm, "GitColeta", return_value=coleta):
        result = prm.pull_repo_main("contratos_v2")

    assert result.status == "updated"
    assert result.branch == "master"
    coleta.run_git.assert_any_call("pull --ff-only origin master", timeout=prm.PULL_TIMEOUT)


def test_pull_skips_when_diverged():
    coleta = _coleta_mock(
        lambda cmd, timeout=30: {
            "symbolic-ref --short refs/remotes/origin/HEAD": "origin/master",
            "fetch origin master": "",
            "rev-parse HEAD": "aaa",
            "rev-parse origin/master": "bbb",
            "merge-base HEAD origin/master": "ccc",
        }.get(cmd, "")
    )

    with patch.object(prm, "GitColeta", return_value=coleta):
        result = prm.pull_repo_main("contratos_v2")

    assert result.status == "diverged"
    assert not any("pull" in str(c) for c in coleta.run_git.call_args_list)


def test_pull_repo_inacessivel():
    coleta = MagicMock()
    coleta.wsl_repo_path = "/root/MGI/contratos"
    coleta.validar_repo.return_value = False

    with patch.object(prm, "GitColeta", return_value=coleta):
        result = prm.pull_repo_main("contratos")

    assert result.status == "error"
