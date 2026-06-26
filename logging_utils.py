#!/usr/bin/env python3
"""Logging central do pipeline MGI.

Objetivo: um único ponto de configuração para todo o pipeline, no lugar de
`print()` espalhado. Mantém o comportamento atual no console (texto puro em
stdout, sem prefixo) e adiciona um arquivo de log estruturado e rotacionado.

Uso:
    from logging_utils import get_logger
    log = get_logger(__name__)
    log.info("mensagem")

Nível controlado por MGI_LOG_LEVEL (default INFO).
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    import config as _config
except ImportError:  # pragma: no cover - config sempre presente em runtime
    _config = None

_CONFIGURED = False


def _logs_dir() -> Path:
    if _config is not None and hasattr(_config, "LOGS_DIR"):
        return Path(_config.LOGS_DIR)
    return Path(os.environ.get("MGI_LOGS_DIR", "logs"))


def _level() -> int:
    name = os.environ.get("MGI_LOG_LEVEL", "INFO").upper()
    return getattr(logging, name, logging.INFO)


def configure_logging(*, force: bool = False) -> None:
    """Configura o root logger uma única vez (idempotente).

    - Console: texto puro em stdout (preserva a aparência dos prints atuais).
    - Arquivo: `logs/pipeline.log` rotacionado, com timestamp/nível/módulo.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level = _level()
    root = logging.getLogger()
    root.setLevel(level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    try:
        logs_dir = _logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / "pipeline.log",
            maxBytes=2_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root.addHandler(file_handler)
    except OSError:
        # Sem permissão/erro de disco: segue apenas com console.
        pass

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Retorna um logger garantindo que o logging esteja configurado."""
    configure_logging()
    return logging.getLogger(name)
