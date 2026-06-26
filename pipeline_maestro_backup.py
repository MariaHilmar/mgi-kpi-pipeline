#!/usr/bin/env python3
"""
Pipeline Maestro - Orquestra coleta de dados GitLab e consolidação em Excel
Integra: coleta_git_contratos.py (MÚLTIPLOS REPOS) + JSON issues + process_gitlab_issues_v2.py

Fluxo:
1. Coleta dados Git de contratos_v2 E contratos (consolidado)
2. Carrega issues do JSON (gitlab_issues_raw.json)
3. Processa issues com openpyxl (protegendo colunas)
4. Consolida tudo em MGI_Dashboard.xlsx
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import logging

# Importa os módulos locais
sys.path.insert(0, str(Path(__file__).parent))

try:
    from coleta_git_contratos import GitColeta
    from process_gitlab_issues_v2 import process_issues
except ImportError as e:
    print(f"❌ Erro importando módulos: {e}")
    sys.exit(1)


class PipelineMaestro:
    def __init__(self, config):
        self.config = config
        self.repo_path = Path(config['repo_path'])
        self.output_dir = Path(config['output_dir'])
        self.issues_json = Path(config['issues_json_path'])
        self.excel_output = Path(config['excel_output_path'])

        # Logging
        self.setup_logging()
        self.logger = logging.getLogger(__name__)

    def setup_logging(self):
        """Configura logging para arquivo e console"""
        logs_dir = self.output_dir / "Logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

    def validar_ambiente(self):
        """Valida existência de arquivos e diretórios necessários"""
        print("\n🔍 Validando ambiente...")

        # Validar repositório
        if not self.repo_path.exists():
            self.logger.error(f"❌ Repositório não encontrado: {self.repo_path}")
            return False

        # Validar JSON de issues
        if not self.issues_json.exists():
            self.logger.error(f"❌ JSON de issues não encontrado: {self.issues_json}")
            return False

        # Criar diretório de saída se necessário
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info("✅ Ambiente validado com sucesso")
        return True

    def executar_coleta_git(self):
        """Executa coleta de dados Git (ambos repositórios)"""
        print("\n📥 ETAPA 1: Coleta Git - Múltiplos Repositórios")
        print("="*70)

        try:
            git_output = self.output_dir / "gitlab_git_data.json"

            # Coleta de múltiplos repositórios (contratos_v2 e contratos)
            repos = [
                ("<path-contratos_v2>", "contratos_v2"),
                ("<path-contratos>", "contratos"),
            ]

            dados_consolidados = {
                'timestamp': datetime.now().isoformat(),
                'repositorios': [],
                'total_commits': 0,
                'total_branches': 0,
                'total_releases': 0,
            }

            for repo_path, repo_name in repos:
                print(f"\n   📂 {repo_name}...")
                try:
                    coleta = GitColeta(repo_path, repo_name)
                    coleta.processar_completo(None, since_days=30)  # None = não exporta individual

                    dados_consolidados['repositorios'].append(coleta.data)
                    dados_consolidados['total_commits'] += len(coleta.data['commits'])
                    dados_consolidados['total_branches'] += len(coleta.data['branches'])
                    dados_consolidados['total_releases'] += len(coleta.data['releases'])

                    print(f"      ✅ {repo_name} concluído")
                except Exception as e:
                    self.logger.error(f"Erro ao coletar {repo_name}: {e}")
                    print(f"      ❌ Erro: {e}")

            # Exportar consolidado
            with open(str(git_output), 'w', encoding='utf-8') as f:
                json.dump(dados_consolidados, f, indent=2, ensure_ascii=False)

            self.logger.info(f"✅ Coleta Git consolidada: {git_output}")
            print(f"\n   📊 Resumo: {len(dados_consolidados['repositorios'])} repos, "
                  f"{dados_consolidados['total_commits']} commits")
            return git_output

        except Exception as e:
            self.logger.error(f"❌ Erro na coleta Git: {e}")
            return None

    def carregar_issues_json(self):
        """Carrega issues do JSON exportado"""
        print("\n📥 ETAPA 2: Carregamento de Issues")
        print("="*70)

        try:
            with open(self.issues_json, 'r', encoding='utf-8') as f:
                issues_data = json.load(f)

            if isinstance(issues_data, list):
                issues = issues_data
            elif isinstance(issues_data, dict) and 'issues' in issues_data:
                issues = issues_data['issues']
            else:
                issues = []

            # Filtrar por data mínima
            cutoff_date = '2024-01-01'
            issues_filtradas = [
                issue for issue in issues
                if issue.get('createdDate', '')[:10] >= cutoff_date
            ]

            self.logger.info(f"✅ Issues carregadas: {len(issues_filtradas)}/{len(issues)}")
            print(f"✅ Issues carregadas: {len(issues_filtradas)} (desde {cutoff_date})")

            return issues_filtradas

        except Exception as e:
            self.logger.error(f"❌ Erro carregando issues: {e}")
            return []

    def processar_issues_excel(self, issues):
        """Processa issues e exporta para Excel"""
        print("\n📊 ETAPA 3: Processamento de Issues")
        print("="*70)

        try:
            # Garantir que o Excel existe (criar se necessário)
            excel_file = str(self.excel_output)
            self.logger.info(f"Excel de destino: {excel_file}")

            # Converter issues para formato esperado
            issues_processadas = self._converter_issues(issues)

            # Usar o processor existente
            result = process_issues(
                excel_file=excel_file,
                issues=issues_processadas
            )

            self.logger.info(f"✅ Issues processadas: {result}")
            print(f"✅ Processamento concluído")

            return True

        except Exception as e:
            self.logger.error(f"❌ Erro processando issues: {e}")
            return False

    @staticmethod
    def _converter_issues(issues):
        """Converte issues para formato esperado por process_gitlab_issues_v2"""
        convertidas = []

        for issue in issues:
            convertida = {
                'id': issue.get('id'),
                'title': issue.get('title', ''),
                'description': issue.get('description', ''),
                'createdDate': issue.get('createdDate', ''),
                'updatedDate': issue.get('updatedDate', ''),
                'author': issue.get('author', {}),
                'milestone': issue.get('milestone', {}),
                'labels': issue.get('labels', []),
            }
            convertidas.append(convertida)

        return convertidas

    def gerar_relatorio_final(self, git_stats, issues_count):
        """Gera relatório final de execução"""
        relatorio = {
            'timestamp': datetime.now().isoformat(),
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
                'excel': {
                    'arquivo': str(self.excel_output),
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

    def executar_pipeline(self):
        """Executa pipeline completo"""
        print("\n" + "="*70)
        print("🚀 PIPELINE MAESTRO - CONTRATOS v2")
        print("="*70)
        print(f"📅 Início: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

        # Validação
        if not self.validar_ambiente():
            print("\n❌ Validação falhou. Abortando.")
            return False

        # Coleta Git
        git_data_file = self.executar_coleta_git()
        if not git_data_file:
            print("\n❌ Coleta Git falhou. Abortando.")
            return False

        # Carregar dados Git para estatísticas
        try:
            with open(git_data_file, 'r', encoding='utf-8') as f:
                git_data = json.load(f)
            git_stats = git_data.get('stats', {})
        except:
            git_stats = {}

        # Carregar issues
        issues = self.carregar_issues_json()
        if not issues:
            print("\n❌ Nenhuma issue carregada. Abortando.")
            return False

        # Processar issues
        if not self.processar_issues_excel(issues):
            print("\n❌ Processamento de issues falhou. Abortando.")
            return False

        # Gerar relatório final
        self.gerar_relatorio_final(git_stats, len(issues))

        print("\n" + "="*70)
        print("✅ PIPELINE CONCLUÍDO COM SUCESSO")
        print("="*70)
        print(f"\n📊 Resumo:")
        print(f"   📈 Commits: {git_stats.get('commits_total', 0)}")
        print(f"   🌿 Branches: {git_stats.get('branches_total', 0)}")
        print(f"   📅 Releases: {git_stats.get('releases_total', 0)}")
        print(f"   📋 Issues: {len(issues)}")
        print(f"   📁 Excel: {self.excel_output}")
        print(f"\n🕒 Fim: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

        return True


def main():
    """Função principal"""

    # Configuração padrão
    config = {
        'repo_path': r'\\wsl.localhost\Ubuntu\root\MGI\contratos_v2',
        'output_dir': r'D:\MGI-Relatórios',
        'issues_json_path': r'D:\MGI-Relatórios\gitlab_issues_raw.json',
        'excel_output_path': r'D:\MGI-Relatórios\MGI_Dashboard.xlsx',
    }

    # Permitir override via argumentos
    if len(sys.argv) > 1:
        config['repo_path'] = sys.argv[1]
    if len(sys.argv) > 2:
        config['output_dir'] = sys.argv[2]
    if len(sys.argv) > 3:
        config['issues_json_path'] = sys.argv[3]
    if len(sys.argv) > 4:
        config['excel_output_path'] = sys.argv[4]

    # Executar pipeline
    maestro = PipelineMaestro(config)
    success = maestro.executar_pipeline()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
