#!/usr/bin/env python3
"""
Pipeline Maestro - Orquestra coleta de dados GitLab e sincronizacao com o Supabase
Integra: coleta_git_contratos.py (MULTIPLOS REPOS) + JSON issues + sync_supabase.py

Fluxo:
1. Coleta dados Git de contratos_v2 E contratos (consolidado)
2. Carrega issues do JSON (gitlab_issues_raw.json)
3. Processa issues em memoria (taxonomia + detectores Git)
4. Sincroniza issues e releases direto no Supabase (sem Excel)
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Importa os modulos locais
sys.path.insert(0, str(Path(__file__).parent))

try:
    import config as mgi_config
    from coleta_git_contratos import GitColeta
    from sync_supabase import sync_issues_to_supabase
    from atualizar_gitlab_issues import validar_json_local
    from log_maintenance import limpar_logs_antigos
    from logging_utils import configure_logging, get_logger
except ImportError as e:
    print(f"ERRO importando modulos: {e}")
    sys.exit(1)


class PipelineMaestro:
    def __init__(self, config, data_input=None, all_modules: bool = False, initial_load: bool = False, full_refresh: bool = False):
        self.config = config
        self.repo_path = Path(config['repo_path'])
        self.output_dir = Path(config['output_dir'])
        self.issues_json = Path(config['issues_json_path'])
        self.data_input = data_input  # Data do batch script
        self.all_modules = all_modules
        self.initial_load = initial_load
        self.full_refresh = full_refresh
        if initial_load:
            os.environ["MGI_INITIAL_LOAD"] = "1"
            mgi_config.INITIAL_LOAD = True
        if all_modules:
            os.environ["MGI_ALL_MODULES"] = "1"
            mgi_config.ALL_MODULES = True
        if full_refresh:
            os.environ["MGI_REFRESH_MODE"] = "full"
            mgi_config.REFRESH_MODE = "full"

        # Logging central (console em stdout + arquivo rotacionado)
        configure_logging()
        self.logger = get_logger(__name__)

    def validar_ambiente(self) -> bool:
        """Valida existencia de arquivos e diretorios necessarios"""
        self.logger.info("\n[VALIDACAO] Validando ambiente...")
        self.logger.info(f"   [INFO] Repositorio: {self.repo_path}")

        # Validar JSON de issues
        if not self.issues_json.exists():
            self.logger.error(f"ERRO: JSON de issues nao encontrado: {self.issues_json}")
            return False

        # Criar diretorio de saida se necessario
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("OK - Ambiente validado com sucesso")
        return True

    def executar_coleta_git(self):
        """Executa coleta de dados Git (ambos repositorios)"""
        self.logger.info("\n[COLETA GIT] ETAPA 1: Coleta Git - Multiplos Repositorios")
        self.logger.info("=" * 70)
        try:
            git_output = self.output_dir / "gitlab_git_data.json"

            # Coleta de multiplos repositorios (configuravel em config.py)
            repos = mgi_config.REPOS

            dados_consolidados = {
                'timestamp': datetime.now().isoformat(),
                'repositorios': [],
                'total_commits': 0,
                'total_branches': 0,
                'total_releases': 0,
            }

            for repo_path, repo_name in repos:
                self.logger.info(f"   [INFO] {repo_name}...")
                try:
                    coleta = GitColeta(repo_path, repo_name)
                    if not coleta.validar_repo():
                        self.logger.warning(f"      AVISO: repositorio inacessivel ({repo_name}) - {repo_path}")
                        dados_consolidados['repositorios'].append(coleta.data)
                        continue
                    coleta.processar_completo(None, since_days=mgi_config.SINCE_DAYS)  # None = nao exporta individual
                    dados_consolidados['repositorios'].append(coleta.data)
                    dados_consolidados['total_commits'] += len(coleta.data['commits'])
                    dados_consolidados['total_branches'] += len(coleta.data['branches'])
                    dados_consolidados['total_releases'] += len(coleta.data['releases'])
                    self.logger.info(f"      OK - {repo_name} concluido")
                except Exception as e:
                    self.logger.error(f"      ERRO ao coletar {repo_name}: {e}")

            # Exportar consolidado
            with open(str(git_output), 'w', encoding='utf-8') as f:
                json.dump(dados_consolidados, f, indent=2, ensure_ascii=False)

            self.logger.info(f"OK - Coleta Git consolidada: {git_output}")
            self.logger.info(
                f"\n   [RESUMO] {len(dados_consolidados['repositorios'])} repos, "
                f"{dados_consolidados['total_commits']} commits"
            )
            return git_output
        except Exception as e:
            self.logger.error(f"ERRO na coleta Git: {e}")
            return None

    def carregar_issues_json(self) -> List[Dict]:
        """Carrega issues do JSON exportado"""
        self.logger.info("\n[ISSUES] ETAPA 2: Carregamento de Issues")
        self.logger.info("=" * 70)
        try:
            with open(self.issues_json, 'r', encoding='utf-8') as f:
                issues_data = json.load(f)

            if isinstance(issues_data, list):
                issues = issues_data
            elif isinstance(issues_data, dict) and 'issues' in issues_data:
                issues = issues_data['issues']
            else:
                issues = []

            # Filtros (fechadas antigas e data de corte) sao aplicados no sync.
            self.logger.info(f"OK - Issues carregadas: {len(issues)}")
            return issues
        except Exception as e:
            self.logger.error(f"ERRO carregando issues: {e}")
            return []

    def sincronizar_supabase(self, issues: List[Dict]) -> bool:
        """Processa issues em memoria e sincroniza direto no Supabase (sem Excel)."""
        self.logger.info("\n[SUPABASE] ETAPA 3: Processamento e sync de Issues")
        self.logger.info("=" * 70)
        try:
            fast = os.environ.get("MGI_FAST_REPO_SYNC", "0").lower() not in ("0", "false", "no")
            upserted = sync_issues_to_supabase(
                issues=issues,
                include_releases=True,
                enable_git=not fast,  # detectores Git ativos por padrao
            )
            self.issues_sincronizadas = upserted
            self.logger.info(f"OK - {upserted} issues sincronizadas no Supabase")
            self.logger.info("OK - Processamento concluido")
            return True
        except SystemExit as e:
            self.logger.error(f"ERRO de configuracao no sync: {e}")
            return False
        except Exception as e:
            self.logger.error(f"ERRO sincronizando issues: {e}", exc_info=True)
            return False

    def gerar_relatorio_final(self, git_stats, issues_count):
        """Gera relatorio final de execucao"""
        relatorio = {
            'timestamp': datetime.now().isoformat(),
            'data_entrada': self.data_input,
            'status': 'sucesso',
            'etapas': {
                'coleta_git': {
                    'commits': git_stats.get('commits_total', 0),
                    'branches': git_stats.get('branches_total', 0),
                    'releases': git_stats.get('releases_total', 0),
                },
                'processamento_issues': {
                    'total': issues_count
                },
                'supabase': {
                    'issues_sincronizadas': getattr(self, 'issues_sincronizadas', 0),
                    'atualizado': datetime.now().isoformat()
                }
            }
        }

        logs_dir = self.output_dir / "Logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        relatorio_file = logs_dir / f"relatorio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(relatorio_file, 'w', encoding='utf-8') as f:
            json.dump(relatorio, f, indent=2, ensure_ascii=False)

        return relatorio

    def executar_pipeline(self) -> bool:
        """Executa pipeline completo"""
        self.logger.info("\n" + "=" * 70)
        self.logger.info("PIPELINE MAESTRO - CONTRATOS v2")
        self.logger.info("=" * 70)
        self.logger.info(f"Data/Hora Inicio: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        if self.data_input:
            self.logger.info(f"Data Entrada: {self.data_input}")
        if self.all_modules:
            self.logger.info("Modo modulos: TODOS (MGI_ALL_MODULES=1)")
        if self.initial_load:
            self.logger.info("Modo carga: INICIAL (sem filtro de issues fechadas > 60 dias)")
        if self.full_refresh:
            self.logger.info("Modo atualizacao: EXECUCAO COMPLETA (reprocessa metadados e enriquecimentos)")

        removed_logs = limpar_logs_antigos(Path(self.output_dir))
        if removed_logs:
            self.logger.info(f"OK - {removed_logs} arquivo(s) de log com mais de {mgi_config.LOG_RETENTION_DAYS} dias removidos")

        # Validacao
        if not self.validar_ambiente():
            self.logger.error("\nERRO: Validacao falhou. Abortando.")
            return False

        # Coleta Git (OPCIONAL)
        git_data_file = None
        git_stats = {}

        # Tentar coletar dados Git (pode falhar gracefully se repo nao existir)
        git_data_file = self.executar_coleta_git()
        if git_data_file:
            # Carregar dados Git para estatisticas (totais consolidados na raiz)
            try:
                with open(git_data_file, 'r', encoding='utf-8') as f:
                    git_data = json.load(f)
                git_stats = {
                    'commits_total': git_data.get('total_commits', 0),
                    'branches_total': git_data.get('total_branches', 0),
                    'releases_total': git_data.get('total_releases', 0),
                }
            except Exception as e:
                self.logger.warning(f"Aviso ao carregar stats Git: {e}")
                git_stats = {}

        # GitLab: atualizado pelo executar_pipeline.bat (etapa 0).
        # Se pipeline rodar direto, apenas valida JSON local.
        validar_json_local(self.issues_json)

        # Carregar issues
        issues = self.carregar_issues_json()
        if not issues:
            self.logger.error("\nERRO: Nenhuma issue carregada. Abortando.")
            return False

        # Processar issues e sincronizar no Supabase
        if not self.sincronizar_supabase(issues):
            self.logger.error("\nERRO: Sincronizacao de issues falhou. Abortando.")
            return False

        # Gerar relatorio final
        self.gerar_relatorio_final(git_stats, len(issues))

        self.logger.info("\n" + "=" * 70)
        self.logger.info("OK - PIPELINE CONCLUIDO COM SUCESSO")
        self.logger.info("=" * 70)
        self.logger.info("\nResumo Final:")
        self.logger.info(f"   Commits: {git_stats.get('commits_total', 0)}")
        self.logger.info(f"   Branches: {git_stats.get('branches_total', 0)}")
        self.logger.info(f"   Releases: {git_stats.get('releases_total', 0)}")
        self.logger.info(f"   Issues: {len(issues)}")
        self.logger.info(f"   Sincronizadas no Supabase: {getattr(self, 'issues_sincronizadas', 0)}")
        self.logger.info(f"\nData/Hora Fim: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        return True


def main():
    """Funcao principal"""
    configure_logging()
    logger = get_logger(__name__)

    all_modules = os.environ.get("MGI_ALL_MODULES", "1").lower() not in ("0", "false", "no")
    initial_load = os.environ.get("MGI_INITIAL_LOAD", "0").lower() not in ("0", "false", "no")
    full_refresh = mgi_config.is_full_refresh()
    argv = [arg for arg in sys.argv[1:] if arg not in ("--all-modules", "--initial-load", "--full")]
    if "--all-modules" in sys.argv[1:]:
        all_modules = True
    if "--initial-load" in sys.argv[1:]:
        initial_load = True
        os.environ["MGI_INITIAL_LOAD"] = "1"
    if "--full" in sys.argv[1:]:
        full_refresh = True
        os.environ["MGI_REFRESH_MODE"] = "full"
        mgi_config.REFRESH_MODE = "full"

    # LER DATA DO STDIN (enviado pelo batch script)
    data_input = None
    try:
        # Tenta ler do stdin
        input_data = sys.stdin.readline().strip()
        if input_data:
            data_input = input_data
            logger.info(f"[INFO] Data recebida do batch: {data_input}")
    except (EOFError, OSError, ValueError):
        pass

    # Configuracao padrao (centralizada em config.py / variaveis de ambiente)
    pipeline_config = {
        'repo_path': mgi_config.REPOS[0][0],
        'output_dir': str(mgi_config.BASE_DIR),
        'issues_json_path': str(mgi_config.ISSUES_JSON),
    }

    # Permitir override via argumentos
    if len(argv) > 0:
        pipeline_config['repo_path'] = argv[0]
    if len(argv) > 1:
        pipeline_config['output_dir'] = argv[1]
    if len(argv) > 2:
        pipeline_config['issues_json_path'] = argv[2]

    # Executar pipeline
    maestro = PipelineMaestro(
        pipeline_config,
        data_input,
        all_modules=all_modules,
        initial_load=initial_load,
        full_refresh=full_refresh,
    )
    success = maestro.executar_pipeline()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
