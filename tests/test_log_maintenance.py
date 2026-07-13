"""Testes para log_maintenance.py."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


from log_maintenance import limpar_logs_antigos


class TestLimparLogsAntigos:
    def test_remove_logs_antigos(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        old_file = logs_dir / "pipeline_20260101.log"
        new_file = logs_dir / "pipeline_20260601.log"
        old_file.write_text("log antigo")
        new_file.write_text("log recente")

        old_ts = (datetime.now() - timedelta(days=30)).timestamp()
        new_ts = datetime.now().timestamp()
        import os

        os.utime(old_file, (old_ts, old_ts))
        os.utime(new_file, (new_ts, new_ts))

        removed = limpar_logs_antigos(tmp_path, dias=7)
        assert removed == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_dias_zero_nao_remove(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "Logs"
        logs_dir.mkdir()
        log_file = logs_dir / "pipeline_old.log"
        log_file.write_text("conteudo")

        removed = limpar_logs_antigos(tmp_path, dias=0)
        assert removed == 0
        assert log_file.exists()

    def test_relatorio_json(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        report = logs_dir / "relatorio_20260101.json"
        report.write_text("{}")

        old_ts = (datetime.now() - timedelta(days=20)).timestamp()
        import os

        os.utime(report, (old_ts, old_ts))

        removed = limpar_logs_antigos(tmp_path, dias=10)
        assert removed == 1
        assert not report.exists()

    def test_sem_diretorio_logs(self, tmp_path: Path) -> None:
        assert limpar_logs_antigos(tmp_path, dias=5) == 0
