"""Testes do logging central (logging_utils)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

import logging_utils


@pytest.fixture(autouse=True)
def _reset_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isola o logging: força reconfiguração e direciona o arquivo para tmp."""
    monkeypatch.setattr(logging_utils, "_logs_dir", lambda: tmp_path)
    logging_utils._CONFIGURED = False
    yield
    # Limpa handlers para não vazar entre testes
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    logging_utils._CONFIGURED = False


def test_get_logger_retorna_logger_nomeado() -> None:
    log = logging_utils.get_logger("meu.modulo")
    assert isinstance(log, logging.Logger)
    assert log.name == "meu.modulo"


def test_configure_idempotente_nao_duplica_handlers() -> None:
    logging_utils.configure_logging()
    qtd = len(logging.getLogger().handlers)
    logging_utils.configure_logging()
    assert len(logging.getLogger().handlers) == qtd


def test_escreve_no_arquivo_de_log(tmp_path: Path) -> None:
    log = logging_utils.get_logger("teste.arquivo")
    log.info("linha de teste")
    for handler in logging.getLogger().handlers:
        handler.flush()
    log_file = tmp_path / "pipeline.log"
    assert log_file.exists()
    assert "linha de teste" in log_file.read_text(encoding="utf-8")


def test_nivel_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MGI_LOG_LEVEL", "WARNING")
    logging_utils._CONFIGURED = False
    logging_utils.configure_logging(force=True)
    assert logging.getLogger().level == logging.WARNING
