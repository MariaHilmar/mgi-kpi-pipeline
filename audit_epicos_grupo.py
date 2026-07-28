#!/usr/bin/env python3
"""Auditoria: filhas de epicos GitLab vs Supabase (todos os epicos do grupo).

Uso:
  python audit_epicos_grupo.py
"""

from __future__ import annotations

import os
import sys

import requests

from gitlab_epics import _buscar_issues_do_epico, buscar_epicos_grupo
from issue_keys import normalize_repo, repo_display_name
from logging_utils import get_logger
from sync_supabase import _load_dotenv

log = get_logger(__name__)


def _repo_from_child(child: dict) -> str:
    refs = child.get("references") or {}
    full = str(refs.get("full") or "")
    if "/" in full:
        slug = full.split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
        return repo_display_name(normalize_repo(slug))
    web = child.get("web_url") or ""
    for slug in ("contratos_v2", "contratos"):
        if f"/{slug}/" in web:
            return repo_display_name(slug)
    return "Contratos v2"


def main() -> int:
    _load_dotenv()
    token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_TOKEN_CONTRATOS_V2")
    if not token:
        raise SystemExit("Defina GITLAB_TOKEN no .env")

    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    sh = {"apikey": key, "Authorization": f"Bearer {key}"}

    epics = buscar_epicos_grupo(token=token)
    print(f"Epicos no catalogo: {len(epics)}\n")

    totais = {"filhas": 0, "no_sb": 0, "epico_ok": 0, "epico_vazio": 0, "fora_sb": 0}
    problemas = 0

    for epic in sorted(epics, key=lambda e: int(e["gitlab_epic_iid"])):
        epic_iid = int(epic["gitlab_epic_iid"])
        title = epic["title"]
        try:
            children = _buscar_issues_do_epico(epic_iid, token=token)
        except Exception as exc:
            print(f"ERRO epico #{epic_iid}: {exc}")
            continue
        if not children:
            continue

        no_sb = []
        sem_epico = []
        ok = 0
        for child in children:
            repo = _repo_from_child(child)
            iid = int(child["iid"])
            totais["filhas"] += 1
            rows = requests.get(
                f"{url}/issues",
                headers=sh,
                params={
                    "select": "epico",
                    "gitlab_repo": f"eq.{repo}",
                    "gitlab_iid": f"eq.{iid}",
                    "limit": 1,
                },
                timeout=60,
            ).json()
            if not rows:
                no_sb.append((iid, repo, child.get("title", "")[:50]))
                totais["fora_sb"] += 1
                continue
            totais["no_sb"] += 1
            ep = (rows[0].get("epico") or "").strip()
            if ep == title:
                ok += 1
                totais["epico_ok"] += 1
            elif not ep:
                sem_epico.append((iid, repo))
                totais["epico_vazio"] += 1
            else:
                sem_epico.append((iid, repo))
                totais["epico_vazio"] += 1

        if no_sb or sem_epico or ok < len(children):
            problemas += 1
            print(f"Epico #{epic_iid}: {title[:55]}")
            print(f"  GitLab filhas: {len(children)} | SB ok: {ok} | sem epico: {len(sem_epico)} | fora SB: {len(no_sb)}")
            for iid, repo, t in no_sb:
                print(f"    FORA SB  #{iid} {repo} {t}")
            for iid, repo in sem_epico:
                print(f"    SEM EPICO #{iid} {repo}")
            print()

    print("=" * 60)
    print(f"Filhas GitLab (total):     {totais['filhas']}")
    print(f"No Supabase com epico ok:  {totais['epico_ok']}")
    print(f"No Supabase sem epico:     {totais['epico_vazio']}")
    print(f"Fora do Supabase:          {totais['fora_sb']}")
    print(f"Epicos com gap:            {problemas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
