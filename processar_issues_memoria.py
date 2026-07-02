#!/usr/bin/env python3
"""Processa issues GitLab em memoria e gera registros prontos para o Supabase.

Substitui o caminho legado via Excel (process_gitlab_issues_v2 + sync a partir do
.xlsx). Reaproveita os mesmos detectores (area funcional, tipo, dev/git) e a
taxonomia, mas opera sobre dicts e devolve uma lista de registros com as colunas
exatas da tabela public.issues.

Campos manuais (situacao_analise, desenvolvedor_futuro, observacao_geral,
chamado, priorizar, epico) sao deliberadamente omitidos para que o upsert
preserve valores existentes no Supabase.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any, Dict, List, Optional

from gitlab_identities import enrich_records_with_developer_ids
import issue_fields
from issue_keys import get_gitlab_repo, repo_display_name

try:
    import config as _config
except ImportError:
    _config = None

_WSL_GIT_AVAILABLE: Optional[bool] = None
_LOCAL_GIT_AVAILABLE: Optional[bool] = None


def probe_local_git_repos() -> bool:
    """True se pelo menos um repo Git local (config.REPOS) esta acessivel."""
    global _LOCAL_GIT_AVAILABLE
    if _LOCAL_GIT_AVAILABLE is not None:
        return _LOCAL_GIT_AVAILABLE

    try:
        from coleta_git_contratos import GitColeta

        if _config is None or not getattr(_config, "REPOS", None):
            _LOCAL_GIT_AVAILABLE = False
            return False

        for repo_path, repo_name in _config.REPOS:
            if GitColeta(repo_path, repo_name).validar_repo():
                _LOCAL_GIT_AVAILABLE = True
                return True
        _LOCAL_GIT_AVAILABLE = False
    except Exception:
        _LOCAL_GIT_AVAILABLE = False
    return _LOCAL_GIT_AVAILABLE


def probe_wsl_git_available(timeout_seconds: int = 8) -> bool:
    """Verifica se WSL Ubuntu + repo Git respondem (cache em memoria)."""
    del timeout_seconds  # GitColeta valida via WSL com timeout proprio
    global _WSL_GIT_AVAILABLE
    if _WSL_GIT_AVAILABLE is not None:
        return _WSL_GIT_AVAILABLE

    _WSL_GIT_AVAILABLE = probe_local_git_repos()
    return _WSL_GIT_AVAILABLE


def resolve_enable_git(requested: bool = True) -> bool:
    """True se detectores Git devem rodar (respeita MGI_FAST_REPO_SYNC + repos locais)."""
    if not requested:
        return False
    if os.environ.get("MGI_FAST_REPO_SYNC", "0").lower() not in ("0", "false", "no"):
        return False
    if not probe_local_git_repos():
        return False
    return probe_wsl_git_available()


def reset_git_availability_cache() -> None:
    """Limpa cache de disponibilidade (util em testes)."""
    global _WSL_GIT_AVAILABLE, _LOCAL_GIT_AVAILABLE
    _WSL_GIT_AVAILABLE = None
    _LOCAL_GIT_AVAILABLE = None

try:
    from detectar_area_funcional import AreaDetection, build_detector
except ImportError:  # pragma: no cover - import defensivo
    AreaDetection = None  # type: ignore
    build_detector = None  # type: ignore

try:
    from inferir_tipo_issue import build_tipo_detector
except ImportError:  # pragma: no cover
    build_tipo_detector = None  # type: ignore

try:
    from enriquecer_dev_git import build_dev_enricher, resolve_desenvolvedor
except ImportError:  # pragma: no cover
    build_dev_enricher = None  # type: ignore
    resolve_desenvolvedor = None  # type: ignore


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_detectors(enable_git: bool = True):
    """Constroi os detectores Git. Com enable_git=False, usa apenas titulo/labels."""
    if not enable_git:
        return None, None, None
    area = build_detector() if build_detector else None
    tipo = build_tipo_detector() if build_tipo_detector else None
    dev = build_dev_enricher() if build_dev_enricher else None
    return area, tipo, dev


def _resolve_area(issue: Dict, title: str, area_detector) -> "AreaDetection":
    title_area = issue_fields.extract_functional_area(title)
    if area_detector is not None:
        return area_detector.detect(issue, title_area=title_area)

    # Modo rapido (sem Git): ainda infere area por titulo/modulo canonico.
    if build_detector is not None:
        from detectar_area_funcional import MultiRepoAreaDetector

        return MultiRepoAreaDetector(enabled=False).detect(issue, title_area=title_area)

    if AreaDetection is not None:
        method = "titulo_explicito" if title_area else "none"
        return AreaDetection(title_area, method, 1.0 if title_area else 0.0)

    class _Simple:
        def __init__(self, area: str, confidence: float) -> None:
            self.area = area
            self.method = "titulo_explicito" if area else "none"
            self.confidence = confidence

    return _Simple(title_area, 1.0 if title_area else 0.0)


def _resolve_tipo(issue: Dict, label_tipo: str, tipo_detector) -> str:
    if label_tipo:
        return label_tipo
    if tipo_detector is not None:
        return tipo_detector.detect(issue).tipo
    return ""


def _parse_gitlab_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _person_meta(person: Dict) -> Optional[Dict[str, Any]]:
    user_id = _parse_gitlab_int(person.get("id"))
    if not user_id:
        return None
    return {
        "id": user_id,
        "username": (person.get("username") or "").strip() or None,
        "name": (person.get("name") or "").strip() or None,
        "email": None,
    }


def _build_gitlab_identity_fields(issue: Dict) -> Dict[str, Any]:
    author = issue.get("author") if isinstance(issue.get("author"), dict) else {}
    participants: List[Dict[str, Any]] = []
    user_meta: List[Dict[str, Any]] = []
    assignee_ids: List[int] = []

    author_meta = _person_meta(author)
    author_id = author_meta["id"] if author_meta else None
    if author_meta:
        user_meta.append(author_meta)
        participants.append(
            {
                "role": "author",
                "gitlab_user_id": author_meta["id"],
                "is_primary": True,
                "source": "gitlab_api",
                "display_name": author_meta.get("name") or "",
            }
        )

    for index, person in enumerate(issue.get("assignees") or []):
        if not isinstance(person, dict):
            continue
        assignee_meta = _person_meta(person)
        if not assignee_meta:
            continue
        user_meta.append(assignee_meta)
        assignee_ids.append(assignee_meta["id"])
        participants.append(
            {
                "role": "assignee",
                "gitlab_user_id": assignee_meta["id"],
                "is_primary": index == 0,
                "source": "gitlab_api",
                "display_name": assignee_meta.get("name") or "",
            }
        )

    return {
        "gitlab_author_id": author_id,
        "gitlab_developer_id": None,
        "gitlab_assignee_ids": assignee_ids,
        "_participants": participants,
        "_gitlab_user_meta": user_meta,
    }


def _resolve_dev(issue: Dict, dev_enricher) -> Dict[str, Any]:
    mr_count = issue.get("merge_requests_count") or 0
    try:
        mr_count = int(mr_count)
    except (TypeError, ValueError):
        mr_count = 0

    if dev_enricher is not None:
        info = dev_enricher.enrich(issue)
        desenvolvedor = (
            resolve_desenvolvedor(issue, info) if resolve_desenvolvedor else info.autor_dev
        )
        return {
            "dev_tem_branch": info.tem_branch,
            "dev_branch": info.branch,
            "dev_commits": info.commits,
            "dev_ultimo_commit": info.ultimo_commit.isoformat()
            if info.ultimo_commit
            else None,
            "dev_autor_dev": info.autor_dev,
            "gitlab_mrs": info.mr_gitlab,
            "dev_mergeado": info.mergeado,
            "desenvolvedor": desenvolvedor,
            "_dev_author_email": info.autor_email or None,
        }

    desenvolvedor = ""
    assignee_id = None
    for person in issue.get("assignees") or []:
        name = person.get("name") if isinstance(person, dict) else str(person)
        name = (name or "").strip()
        if name and not desenvolvedor:
            desenvolvedor = name
        if isinstance(person, dict) and assignee_id is None:
            assignee_id = _parse_gitlab_int(person.get("id"))
    return {
        "dev_tem_branch": "Não",
        "dev_branch": "",
        "dev_commits": 0,
        "dev_ultimo_commit": None,
        "dev_autor_dev": "",
        "gitlab_mrs": mr_count,
        "dev_mergeado": "Não",
        "desenvolvedor": desenvolvedor,
        "_dev_author_email": None,
        "_fallback_developer_id": assignee_id,
    }


def build_issue_record(
    issue: Dict,
    *,
    area_detector=None,
    tipo_detector=None,
    dev_enricher=None,
    synced_at: Optional[str] = None,
    today: Optional[date] = None,
) -> Optional[Dict[str, Any]]:
    """Constroi um registro Supabase a partir de uma issue crua. None se sem IID."""
    iid_raw = str(issue.get("id", "")).strip()
    if not iid_raw:
        return None
    try:
        gitlab_iid = int(iid_raw)
    except ValueError:
        return None

    synced_at = synced_at or _utc_now_iso()
    title = issue.get("title", "") or ""

    repo_slug = get_gitlab_repo(issue)
    repo_label = repo_display_name(repo_slug)
    issue_key = f"{repo_label}:{gitlab_iid}"

    labels = issue_fields.parse_labels(issue.get("labels") or [])
    estado = issue_fields.map_estado(issue.get("state", ""))
    created_date = issue_fields.parse_date(issue.get("createdDate", ""))
    closed_date = issue_fields.parse_date(issue.get("closedDate", ""))

    modulo = issue_fields.extract_module(title)
    modulo_norm = issue_fields.normalized_module(title, modulo)

    detection = _resolve_area(issue, title, area_detector)
    area = detection.area
    area_conf = float(getattr(detection, "confidence", 0.0) or 0.0)

    tipo = _resolve_tipo(issue, labels["tipo"], tipo_detector)

    record: Dict[str, Any] = {
        "issue_key": issue_key,
        "gitlab_repo": repo_label,
        "gitlab_iid": gitlab_iid,
        "repositorio": repo_label,
        "titulo": title,
        "modulo": modulo,
        "modulo_normalizado": modulo_norm,
        "area_funcional": area,
        "tipo": tipo,
        "estado": estado,
        "status": labels["status"],
        "prioridade": labels["prioridade"],
        "equipe": labels["equipe"],
        "parceria": labels["parceria"],
        "sprint": (issue.get("milestone") or {}).get("title", "") or "",
        "assignee": issue_fields.format_assignees(issue),
        "autor": (issue.get("author") or {}).get("name", "") or "",
        "solicitante": labels["solicitante"],
        "alteracao_escopo": labels["alteracao_escopo"],
        "synced_at": synced_at,
        "updated_at": synced_at,
    }

    record.update(
        issue_fields.derive_date_fields(created_date, closed_date, estado, today=today)
    )
    record["entrega_prevista"] = issue_fields.parse_due_date(
        issue.get("dueDate") or issue.get("due_date")
    )
    record.update(_resolve_dev(issue, dev_enricher))
    record.update(issue_fields.quality_fields(title, modulo, area, area_conf))
    record["faixa_idade"] = issue_fields.faixa_idade(
        record.get("idade_dias"), record.get("aberto", False)
    )
    record.update(_build_gitlab_identity_fields(issue))

    fallback_dev_id = record.pop("_fallback_developer_id", None)
    if fallback_dev_id and not record.get("gitlab_developer_id"):
        record["gitlab_developer_id"] = fallback_dev_id
        participants = list(record.get("_participants") or [])
        if not any(
            p.get("role") == "developer" and p.get("gitlab_user_id") == fallback_dev_id
            for p in participants
        ):
            participants.append(
                {
                    "role": "developer",
                    "gitlab_user_id": fallback_dev_id,
                    "is_primary": True,
                    "source": "assignee_fallback",
                    "display_name": record.get("desenvolvedor") or "",
                }
            )
        record["_participants"] = participants

    return record


def build_issue_records(
    issues: List[Dict],
    *,
    enable_git: bool = True,
    area_detector=None,
    tipo_detector=None,
    dev_enricher=None,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Processa a lista de issues e devolve registros unicos (por issue_key).

    Se nenhum detector for passado explicitamente, eles sao construidos conforme
    enable_git. A ultima ocorrencia de cada issue_key prevalece (paridade com o
    dedupe do sync legado)."""
    total = len(issues)
    git_on = resolve_enable_git(enable_git)

    if area_detector is None and tipo_detector is None and dev_enricher is None:
        mode = "Git + titulo/labels" if git_on else "rapido - titulo/labels"
        print(f"OK - Modo: {mode}", flush=True)
        area_detector, tipo_detector, dev_enricher = build_detectors(git_on)

    print(f"OK - Iniciando processamento de {total} issues...", flush=True)

    synced_at = _utc_now_iso()
    seen: Dict[str, Dict[str, Any]] = {}
    progress_step = max(25, total // 20) if total else 1

    for index, issue in enumerate(issues, start=1):
        record = build_issue_record(
            issue,
            area_detector=area_detector,
            tipo_detector=tipo_detector,
            dev_enricher=dev_enricher,
            synced_at=synced_at,
            today=today,
        )
        if record:
            seen[record["issue_key"]] = record
        if index == 1 or index == total or index % progress_step == 0:
            print(f"OK - Processadas {index}/{total} issues...", flush=True)

    records = list(seen.values())
    enrich_records_with_developer_ids(records)
    return records
