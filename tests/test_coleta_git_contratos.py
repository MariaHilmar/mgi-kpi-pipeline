"""Testes da coleta Git via WSL."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import coleta_git_contratos as cgc


def test_validar_repo_usa_wsl():
    coleta = cgc.GitColeta("<path-contratos_v2>", "contratos_v2")
    assert coleta.wsl_repo_path == "/root/MGI/contratos_v2"

    with patch.object(coleta, "_run_git", return_value=".git") as mock_run:
        assert coleta.validar_repo() is True
        mock_run.assert_called_once_with("rev-parse --git-dir", timeout=10)


def test_run_git_remove_prefixo_git():
    coleta = cgc.GitColeta("<path-contratos>", "contratos")

    with patch.object(coleta, "_run_git", return_value="ok") as mock_run:
        assert coleta.run_git('git status -sb') == "ok"
        mock_run.assert_called_once_with("status -sb", timeout=30)


def test_run_git_via_wsl_comando():
    coleta = cgc.GitColeta("<path-contratos_v2>", "contratos_v2")
    mock_result = MagicMock(returncode=0, stdout="main\n", stderr="")

    with patch("coleta_git_contratos.subprocess.run", return_value=mock_result) as mock_sub:
        output = coleta._run_git("branch --show-current")

    assert output == "main"
    mock_sub.assert_called_once()
    cmd = mock_sub.call_args.args[0]
    assert cmd[:5] == ["wsl", "-d", "Ubuntu", "bash", "-lc"]
    assert "cd /root/MGI/contratos_v2 && git branch --show-current" == cmd[5]
