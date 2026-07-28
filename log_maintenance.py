#!/usr/bin/env python3
"""Manutencao de arquivos de log do pipeline MGI."""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

try:
    import config
except ImportError:
    config = None


DEFAULT_LOG_PATTERNS: tuple[str, ...] = (
    "pipeline_*.log",
    "scheduled_*.log",
    "pull_repos_*.log",
    "relatorio_*.json",
)


def _retention_days() -> int:
    if config is not None:
        return int(getattr(config, "LOG_RETENTION_DAYS", 7))
    return int(os.environ.get("MGI_LOG_RETENTION_DAYS", "7"))


def _log_directories(base_dir: Path) -> list[Path]:
    dirs: list[Path] = []
    for name in ("logs", "Logs"):
        path = base_dir / name
        if path.is_dir():
            dirs.append(path)
    return dirs


def limpar_logs_antigos(
    base_dir: Path,
    dias: int | None = None,
    patterns: Iterable[str] = DEFAULT_LOG_PATTERNS,
) -> int:
    """Remove logs e relatorios mais antigos que N dias (mantem os ultimos N dias)."""
    exclude_days = _retention_days() if dias is None else dias
    if exclude_days <= 0:
        return 0

    cutoff = datetime.now() - timedelta(days=exclude_days)
    removed = 0

    for logs_dir in _log_directories(base_dir):
        for pattern in patterns:
            for path in logs_dir.glob(pattern):
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    if mtime < cutoff:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    continue

    return removed


def executar_limpeza_logs(
    base_dir: Path | None = None,
    dias: int | None = None,
) -> int:
    """Limpeza padrao com mensagem para execucao agendada ou manual."""
    if base_dir is None:
        base_dir = Path(getattr(config, "BASE_DIR", Path(__file__).resolve().parent.parent))
    retention = _retention_days() if dias is None else dias
    removed = limpar_logs_antigos(base_dir, dias=retention)
    if removed:
        print(f"OK - {removed} arquivo(s) de log com mais de {retention} dias removidos")
    else:
        print(f"OK - Nenhum log com mais de {retention} dias para remover")
    return removed
