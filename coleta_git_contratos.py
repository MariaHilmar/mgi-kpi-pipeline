#!/usr/bin/env python3
"""
Coleta dados de múltiplos repositórios Git locais (contratos_v2 e contratos)
Extrai: commits, branches, releases/tags
Exporta como JSON estruturado para pipeline
Consolidação de múltiplos repositórios na mesma saída
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from logging_utils import get_logger

log = get_logger(__name__)

try:
    from issue_keys import wsl_path_for_repo
except ImportError:
    def wsl_path_for_repo(repo: str) -> str:
        paths = {
            "contratos_v2": "/root/MGI/contratos_v2",
            "contratos": "/root/MGI/contratos",
        }
        return paths.get(repo, "/root/MGI/contratos_v2")

WSL_DISTRO = os.environ.get("MGI_WSL_DISTRO", "Ubuntu")


class GitColeta:
    def __init__(self, repo_path: str, repo_name: str | None = None):
        self.repo_path = Path(repo_path)
        self.repo_name = repo_name or Path(repo_path).name
        self.wsl_repo_path = wsl_path_for_repo(self.repo_name)
        self.data: dict = {
            'timestamp': datetime.now().isoformat(),
            'repositorio': self.repo_name,
            'caminho': str(repo_path),
            'wsl_caminho': self.wsl_repo_path,
            'commits': [],
            'branches': [],
            'releases': [],
            'stats': {}
        }

    def _run_git(self, git_args: str, timeout: int = 30) -> str:
        """Executa git dentro do WSL Ubuntu (repos em /root/MGI/...)."""
        cmd = [
            "wsl",
            "-d",
            WSL_DISTRO,
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
                stderr = (result.stderr or "").strip()
                if stderr:
                    log.error(f"ERRO Git ({self.repo_name}): {stderr}")
                return ""
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            log.error(f"ERRO Timeout ({timeout}s) git em {self.repo_name}: {git_args[:80]}")
            return ""
        except Exception as e:
            log.error(f"ERRO executando git em {self.repo_name}: {e}")
            return ""

    def run_git(self, cmd: str, timeout: int = 30) -> str:
        """Executa comando git no repositório (aceita 'git ...' ou args diretos)."""
        git_args = cmd.strip()
        if git_args.startswith("git "):
            git_args = git_args[4:]
        return self._run_git(git_args, timeout=timeout)

    def validar_repo(self) -> bool:
        """Verifica se o repositório WSL é acessível e é um repositório Git válido."""
        return bool(self._run_git("rev-parse --git-dir", timeout=10))

    def coleta_commits(self, since_days: int = 30) -> list[dict[str, str]]:
        """Extrai commits dos últimos N dias"""
        log.info(f"📥 Coletando commits (últimos {since_days} dias)...")

        # Git log format: hash|author|email|date|message
        cmd = f'git log --since="{since_days} days ago" --format="%h|%an|%ae|%aI|%s"'
        output = self.run_git(cmd)

        commits_by_author = {}

        for line in output.split('\n'):
            if not line:
                continue

            try:
                hash_id, author, email, date, message = line.split('|', 4)

                commit = {
                    'id': hash_id,
                    'autor': author,
                    'email': email,
                    'data': date[:10],  # YYYY-MM-DD
                    'mensagem': message[:100]
                }
                self.data['commits'].append(commit)

                # Agregação por autor
                if author not in commits_by_author:
                    commits_by_author[author] = 0
                commits_by_author[author] += 1

            except ValueError:
                continue

        self.data['stats']['commits_total'] = len(self.data['commits'])
        self.data['stats']['commits_por_autor'] = commits_by_author
        log.info(f"✅ {len(self.data['commits'])} commits encontrados")
        return self.data['commits']

    def coleta_branches(self) -> list[dict[str, str]]:
        """Extrai branches ativos"""
        log.info("📥 Coletando branches...")

        # Listar branches locais com último commit
        cmd = 'git branch -v --format="%(refname:short)|%(objectname:short)|%(committerdate:short)"'
        output = self.run_git(cmd)

        for line in output.split('\n'):
            if not line or line.startswith('*'):
                continue

            try:
                parts = line.replace('* ', '').split('|')
                if len(parts) >= 2:
                    branch = {
                        'nome': parts[0].strip(),
                        'commit': parts[1].strip() if len(parts) > 1 else '',
                        'data': parts[2].strip() if len(parts) > 2 else ''
                    }
                    self.data['branches'].append(branch)
            except Exception:
                continue

        log.info(f"✅ {len(self.data['branches'])} branches encontrados")
        return self.data['branches']

    def coleta_releases(self) -> list[dict[str, str]]:
        """Extrai tags (simula releases)"""
        log.info("📥 Coletando releases/tags...")

        # Git tags com data
        cmd = 'git tag -l --format="%(refname:short)|%(creatordate:short)"'
        output = self.run_git(cmd)

        releases = []
        for line in output.split('\n'):
            if not line:
                continue

            try:
                parts = line.split('|')
                release = {
                    'versao': parts[0].strip(),
                    'data': parts[1].strip() if len(parts) > 1 else ''
                }
                releases.append(release)
            except Exception:
                continue

        # Ordenar por versão (semântica)
        self.data['releases'] = sorted(
            releases,
            key=lambda x: self._parse_version(x['versao']),
            reverse=True
        )

        log.info(f"✅ {len(self.data['releases'])} releases encontradas")
        return self.data['releases']

    @staticmethod
    def _parse_version(version_str):
        """Parse versão semântica para ordenação"""
        # Remove prefixos como 'v', 'release-', etc
        clean = re.sub(r'^[a-zA-Z-]+', '', version_str)
        parts = clean.split('.')
        return tuple(int(p) if p.isdigit() else 0 for p in parts[:3])

    def coleta_estatisticas(self):
        """Calcula estatísticas gerais"""
        log.info("📊 Calculando estatísticas...")

        # Commits por mês
        commits_por_mes = {}
        for commit in self.data['commits']:
            mes = commit['data'][:7]  # YYYY-MM
            commits_por_mes[mes] = commits_por_mes.get(mes, 0) + 1

        self.data['stats']['commits_por_mes'] = commits_por_mes
        self.data['stats']['branches_total'] = len(self.data['branches'])
        self.data['stats']['releases_total'] = len(self.data['releases'])

    def exportar_json(self, output_file):
        """Exporta dados como JSON"""
        self.coleta_estatisticas()

        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            log.info(f"✅ Dados exportados: {output_file}")
            return output_file
        else:
            # Apenas calcula estatísticas sem exportar
            return None

    def processar_completo(self, output_file: str | None, since_days: int = 30) -> dict:
        """Pipeline completo de coleta"""
        log.info("\n" + "="*70)
        log.info("🚀 COLETA DE DADOS GIT - CONTRATOS v2")
        log.info("="*70)
        log.info(f"📂 Repositório: {self.repo_path}")
        log.info(f"📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")

        self.coleta_commits(since_days=since_days)
        self.coleta_branches()
        self.coleta_releases()

        self.exportar_json(output_file)

        self._print_resumo()

        return self.data

    def _print_resumo(self):
        """Exibe resumo dos dados coletados"""
        log.info("\n" + "="*70)
        log.info("📊 RESUMO")
        log.info("="*70)
        log.info("\n📈 COMMITS:")
        log.info(f"   Total: {self.data['stats'].get('commits_total', 0)}")
        if self.data['stats'].get('commits_por_autor'):
            log.info("   Top 3 autores:")
            for autor, count in sorted(
                self.data['stats']['commits_por_autor'].items(),
                key=lambda x: -x[1]
            )[:3]:
                log.info(f"     • {autor}: {count}")

        log.info(f"\n🌿 BRANCHES: {self.data['stats'].get('branches_total', 0)}")
        if self.data['branches']:
            for branch in self.data['branches'][:5]:
                log.info(f"   • {branch['nome']} ({branch['data']})")

        log.info(f"\n📅 RELEASES: {self.data['stats'].get('releases_total', 0)}")
        if self.data['releases']:
            for release in self.data['releases'][:5]:
                log.info(f"   • {release['versao']} ({release['data']})")

        log.info("\n" + "="*70)


if __name__ == '__main__':
    import sys

    # Configuração centralizada (config.py) com fallback legado
    try:
        import config as _cfg
        REPOS = list(_cfg.REPOS)
        OUTPUT_FILE = str(_cfg.GIT_DATA_JSON)
        DIAS = _cfg.SINCE_DAYS
    except Exception:
        REPOS = []
        OUTPUT_FILE = r"D:\MGI-Relatórios\gitlab_git_data.json"
        DIAS = 30

    # Se passado via linha de comando
    if len(sys.argv) > 1:
        OUTPUT_FILE = sys.argv[1]
    if len(sys.argv) > 2:
        DIAS = int(sys.argv[2])

    # Consolidar dados de ambos repositórios
    dados_consolidados = {
        'timestamp': datetime.now().isoformat(),
        'repositorios': [],
        'total_commits': 0,
        'total_branches': 0,
        'total_releases': 0,
    }

    log.info("="*70)
    log.info("🔄 COLETA GIT - MÚLTIPLOS REPOSITÓRIOS")
    log.info("="*70)

    for repo_path, repo_name in REPOS:
        log.info(f"\n📂 Processando: {repo_name}")
        log.info(f"   Caminho: {repo_path}")

        try:
            coleta = GitColeta(repo_path, repo_name)
            coleta.processar_completo(None, since_days=DIAS)  # None = não exporta individualmente

            dados_consolidados['repositorios'].append(coleta.data)
            dados_consolidados['total_commits'] += len(coleta.data['commits'])
            dados_consolidados['total_branches'] += len(coleta.data['branches'])
            dados_consolidados['total_releases'] += len(coleta.data['releases'])

            log.info("   ✅ Sucesso")
        except Exception as e:
            log.info(f"   ❌ Erro: {e}")

    # Exportar consolidado
    log.info(f"\n💾 Exportando para: {OUTPUT_FILE}")
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(dados_consolidados, f, indent=2, ensure_ascii=False)
        log.info("✅ Dados consolidados exportados com sucesso!")
        log.info("\n📊 RESUMO:")
        log.info(f"   Repositórios: {len(dados_consolidados['repositorios'])}")
        log.info(f"   Total commits: {dados_consolidados['total_commits']}")
        log.info(f"   Total branches: {dados_consolidados['total_branches']}")
        log.info(f"   Total releases: {dados_consolidados['total_releases']}")
    except Exception as e:
        log.error(f"❌ Erro ao exportar: {e}")
