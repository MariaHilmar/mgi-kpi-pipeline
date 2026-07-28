"""Coleta o catalogo de labels de tipo (`tipo::*`) do GitLab.

O filtro "Tipo" do dashboard deve listar todos os tipos definidos como label
no GitLab, mesmo quando ainda nao ha issues com aquele tipo. Este modulo busca
os labels dos projetos e do grupo, filtra os que comecam com `tipo::` e monta
um catalogo (paridade com gitlab_epics.py).
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

LABELS_JSON_FILENAME = "gitlab_tipo_labels_raw.json"
TIPO_PREFIX = "tipo::"
DEFAULT_GROUP_PATH = "comprasnet"


def group_path() -> str:
    if config and getattr(config, "GITLAB_GROUP_PATH", None):
        return str(config.GITLAB_GROUP_PATH)
    return os.environ.get("GITLAB_GROUP_PATH", DEFAULT_GROUP_PATH).strip() or DEFAULT_GROUP_PATH


def labels_json_path(base: Path | None = None) -> Path:
    if base is not None:
        return Path(base)
    if config and getattr(config, "TIPO_LABELS_JSON", None):
        return Path(config.TIPO_LABELS_JSON)
    return Path(__file__).resolve().parent / LABELS_JSON_FILENAME


def _gitlab_url() -> str:
    if config and getattr(config, "GITLAB_URL", None):
        return str(config.GITLAB_URL).rstrip("/")
    return os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")


def _projects() -> list[tuple[str, str]]:
    """Lista (project_id_encoded, repo_slug) para buscar labels de projeto."""
    if config and getattr(config, "GITLAB_PROJECTS", None):
        return list(config.GITLAB_PROJECTS)
    return [("comprasnet%2Fcontratos_v2", "contratos_v2")]


def _token_for_repo(repo: str) -> str:
    if config and hasattr(config, "gitlab_token_for_repo"):
        return config.gitlab_token_for_repo(repo) or ""
    return (
        os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", "")
        or os.environ.get("GITLAB_TOKEN_CONTRATOS", "")
        or os.environ.get("GITLAB_TOKEN", "")
    )


def _any_token() -> str:
    for _, repo in _projects():
        token = _token_for_repo(repo)
        if token:
            return token
    if config and getattr(config, "GITLAB_TOKEN", None):
        return str(config.GITLAB_TOKEN)
    return os.environ.get("GITLAB_TOKEN", "")


def tipo_de_label(name: str) -> str | None:
    """Extrai o valor do tipo de um nome de label `tipo::<valor>`.

    Match case-insensitive no prefixo (paridade tolerante), preservando o valor.
    Retorna None quando o label nao e de tipo.
    """
    if not name:
        return None
    stripped = name.strip()
    if stripped.lower().startswith(TIPO_PREFIX):
        valor = stripped.split("::", 1)[1].strip()
        return valor or None
    return None


def _buscar_labels(url: str, token: str) -> list[dict[str, Any]]:
    import requests

    headers = {"PRIVATE-TOKEN": token} if token else {}
    params: dict[str, object] = {"per_page": 100, "page": 1}
    labels: list[dict[str, Any]] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code == 401 and headers:
            log.warning("AVISO - token GitLab rejeitado em %s; tentando acesso publico", url)
            headers = {}
            response = requests.get(url, headers=headers, params=params, timeout=60)
        if response.status_code in (403, 404):
            return labels
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        labels.extend(data)
        params["page"] = int(params["page"]) + 1
    return labels


def buscar_tipo_labels() -> list[dict[str, Any]]:
    """Coleta labels `tipo::*` dos projetos e do grupo, deduplicando por tipo."""
    base = _gitlab_url()
    fontes: list[tuple[str, str]] = []
    for pid, repo in _projects():
        fontes.append((f"{base}/api/v4/projects/{pid}/labels", _token_for_repo(repo)))
    fontes.append((f"{base}/api/v4/groups/{group_path()}/labels", _any_token()))

    por_tipo: dict[str, dict[str, Any]] = {}
    for url, token in fontes:
        try:
            raw = _buscar_labels(url, token)
        except Exception as exc:  # noqa: BLE001
            log.warning("AVISO - falha ao listar labels em %s: %s", url, exc)
            continue
        for label in raw:
            nome = (label.get("name") or "").strip()
            tipo = tipo_de_label(nome)
            if not tipo:
                continue
            # Primeira ocorrencia vence; preserva metadados uteis.
            por_tipo.setdefault(
                tipo,
                {
                    "tipo": tipo,
                    "label": nome,
                    "color": label.get("color") or "",
                    "description": label.get("description") or "",
                },
            )
    return sorted(por_tipo.values(), key=lambda item: item["tipo"].lower())


def salvar_tipo_labels(labels: list[dict[str, Any]], path: Path | None = None) -> Path:
    destino = labels_json_path(path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8") as handle:
        json.dump(labels, handle, indent=2, ensure_ascii=False)
    return destino


def carregar_tipo_labels(path: Path | None = None) -> list[dict[str, Any]]:
    destino = labels_json_path(path)
    if not destino.exists():
        return []
    with open(destino, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("labels"), list):
        return data["labels"]
    return []


def coletar_e_salvar_tipo_labels(*, dry_run: bool = False) -> list[dict[str, Any]]:
    """Busca labels de tipo e grava o catalogo JSON."""
    log.info("OK - Buscando labels de tipo (tipo::*) no GitLab...")
    labels = buscar_tipo_labels()
    log.info("OK - %d tipos de label obtidos", len(labels))
    if not dry_run:
        destino = salvar_tipo_labels(labels)
        log.info("OK - Catalogo de tipos salvo: %s", destino)
    return labels


if __name__ == "__main__":
    for item in coletar_e_salvar_tipo_labels():
        print(item["tipo"], "->", item["label"])
