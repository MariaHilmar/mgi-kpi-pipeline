"""Coleta e mapeamento de epicos GitLab (grupo + vinculo em issues).

Fonte primaria: REST Premium/Ultimate (`issue.epic` / `GET /groups/:id/epics`).
O catalogo de epicos do grupo alimenta o filtro do dashboard mesmo quando
ainda nao ha issues filhas vinculadas.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from logging_utils import get_logger

log = get_logger(__name__)

try:
    import config
except ImportError:
    config = None

EPICS_JSON_FILENAME = "gitlab_epics_raw.json"
DEFAULT_GROUP_PATH = "comprasnet"


def group_path() -> str:
    if config and getattr(config, "GITLAB_GROUP_PATH", None):
        return str(config.GITLAB_GROUP_PATH)
    return os.environ.get("GITLAB_GROUP_PATH", DEFAULT_GROUP_PATH).strip() or DEFAULT_GROUP_PATH


def epics_json_path(base: Path | None = None) -> Path:
    if base is not None:
        return Path(base)
    if config and getattr(config, "EPICS_JSON", None):
        return Path(config.EPICS_JSON)
    return Path(__file__).resolve().parent / EPICS_JSON_FILENAME


def _gitlab_url() -> str:
    if config and getattr(config, "GITLAB_URL", None):
        return str(config.GITLAB_URL).rstrip("/")
    return os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")


def _any_gitlab_token() -> str:
    if config and hasattr(config, "gitlab_token_for_repo"):
        for _, repo in getattr(config, "GITLAB_PROJECTS", []) or []:
            token = config.gitlab_token_for_repo(repo)
            if token:
                return token
        return getattr(config, "GITLAB_TOKEN", "") or ""
    return (
        os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", "")
        or os.environ.get("GITLAB_TOKEN_CONTRATOS", "")
        or os.environ.get("GITLAB_TOKEN", "")
    )


def mapear_epic_api(epic_obj: dict | None, epic_iid_fallback: Any = None) -> dict[str, Any] | None:
    """Normaliza o objeto `epic` da API de issues para o JSON do pipeline."""
    if not isinstance(epic_obj, dict):
        if epic_iid_fallback in (None, ""):
            return None
        return {
            "id": None,
            "iid": int(epic_iid_fallback) if str(epic_iid_fallback).isdigit() else epic_iid_fallback,
            "title": "",
            "url": "",
        }
    title = (epic_obj.get("title") or "").strip()
    iid = epic_obj.get("iid") if epic_obj.get("iid") is not None else epic_iid_fallback
    if not title and iid in (None, ""):
        return None
    return {
        "id": epic_obj.get("id"),
        "iid": iid,
        "title": title,
        "url": epic_obj.get("url") or epic_obj.get("web_url") or "",
    }


def mapear_epico_grupo(epic: dict) -> dict[str, Any]:
    """Mapeia um epico de GET /groups/:id/epics para o catalogo local/Supabase."""
    return {
        "gitlab_group_path": group_path(),
        "gitlab_epic_id": int(epic["id"]),
        "gitlab_epic_iid": int(epic["iid"]),
        "title": (epic.get("title") or "").strip(),
        "state": epic.get("state") or "",
        "web_url": epic.get("web_url") or "",
        "parent_iid": epic.get("parent_iid"),
        "work_item_id": epic.get("work_item_id"),
    }


def buscar_epicos_grupo(
    *,
    group: str | None = None,
    token: str | None = None,
    state: str = "all",
) -> list[dict[str, Any]]:
    """Lista epicos do grupo via REST. Grupo publico funciona sem token."""
    import requests

    group_id = group or group_path()
    headers = {}
    auth = token if token is not None else _any_gitlab_token()
    if auth:
        headers["PRIVATE-TOKEN"] = auth

    url = f"{_gitlab_url()}/api/v4/groups/{group_id}/epics"
    params: dict[str, object] = {"per_page": 100, "page": 1, "state": state}
    epics: list[dict[str, Any]] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 401 and headers:
            # Token invalido: tenta novamente como publico.
            log.warning("AVISO - token GitLab rejeitado em /epics; tentando acesso publico")
            headers = {}
            response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        for epic in data:
            mapped = mapear_epico_grupo(epic)
            if mapped["title"]:
                epics.append(mapped)
        params["page"] = int(params["page"]) + 1
    return epics


def _buscar_issues_do_epico(
    epic_iid: int,
    *,
    group: str | None = None,
    token: str | None = None,
) -> list[dict]:
    import requests

    group_id = group or group_path()
    headers = {}
    auth = token if token is not None else _any_gitlab_token()
    if auth:
        headers["PRIVATE-TOKEN"] = auth

    url = f"{_gitlab_url()}/api/v4/groups/{group_id}/epics/{epic_iid}/issues"
    params: dict[str, object] = {"per_page": 100, "page": 1}
    issues: list[dict] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 401 and headers:
            headers = {}
            response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 404:
            return issues
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        issues.extend(data)
        params["page"] = int(params["page"]) + 1
    return issues


def enriquecer_issues_com_epicos(
    issues: list[dict[str, Any]],
    epics: list[dict[str, Any]],
    *,
    token: str | None = None,
) -> int:
    """Preenche `issue.epic` a partir das issues filhas de cada epico do grupo.

    Util quando o list/get de issues nao traz `epic`, mas o vinculo existe no
    endpoint de epicos. Retorna quantas issues receberam epico.
    """
    by_global = {
        str(issue.get("gitlab_id")): issue
        for issue in issues
        if issue.get("gitlab_id") not in (None, "")
    }
    filled = 0
    for epic in epics:
        iid = epic.get("gitlab_epic_iid")
        title = (epic.get("title") or "").strip()
        if not iid or not title:
            continue
        try:
            children = _buscar_issues_do_epico(int(iid), token=token)
        except Exception as exc:
            log.warning(f"AVISO - falha ao listar issues do epico #{iid}: {exc}")
            continue
        for child in children:
            target = by_global.get(str(child.get("id")))
            if not target:
                continue
            current = target.get("epic") if isinstance(target.get("epic"), dict) else None
            if current and (current.get("title") or "").strip():
                continue
            target["epic"] = {
                "id": epic.get("gitlab_epic_id"),
                "iid": iid,
                "title": title,
                "url": epic.get("web_url") or "",
            }
            filled += 1
    return filled


def salvar_epicos(epics: list[dict[str, Any]], path: Path | None = None) -> Path:
    destino = epics_json_path(path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as handle:
        json.dump(epics, handle, indent=2, ensure_ascii=False)
    return destino


def carregar_epicos(path: Path | None = None) -> list[dict[str, Any]]:
    destino = epics_json_path(path)
    if not destino.exists():
        return []
    with open(destino, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("epics"), list):
        return data["epics"]
    return []


def coletar_e_salvar_epicos(
    *,
    issues: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Busca epicos do grupo, opcionalmente enriquece issues e grava JSON."""
    log.info(f"OK - Buscando epicos do grupo {group_path()}...")
    epics = buscar_epicos_grupo()
    log.info(f"OK - {len(epics)} epicos obtidos")
    if issues is not None:
        filled = enriquecer_issues_com_epicos(issues, epics)
        if filled:
            log.info(f"OK - {filled} issues enriquecidas com epico via catalogo do grupo")
        else:
            log.info("OK - Nenhuma issue filha vinculada aos epicos do grupo (catalogo apenas)")
    if not dry_run:
        destino = salvar_epicos(epics)
        log.info(f"OK - Catalogo de epicos salvo: {destino}")
    return epics
