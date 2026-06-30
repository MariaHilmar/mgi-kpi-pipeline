#!/usr/bin/env python3
"""
Lista membros ativos dos projetos GitLab comprasnet/contratos_v2 e comprasnet/contratos
e cria contas correspondentes no Supabase Auth (dashboard MGI).

Uso:
  python provision_gitlab_users.py
  python provision_gitlab_users.py --dry-run
  python provision_gitlab_users.py --password "<senha-inicial>"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

sys.path.insert(0, str(Path(__file__).parent))
from sync_supabase import _load_dotenv

try:
    import config
except ImportError:
    config = None

# use --password ou MGI_PROVISION_PASSWORD
GITLAB_GROUP = "comprasnet"
BOT_USERNAME_MARKERS = ("_bot", "bot_")
BOT_NAME_MARKERS = ("_TOKEN", "API_TOKEN", "Security Policy Bot", "Duo Developer")
GITLAB_PROJECTS: List[Tuple[str, str]] = (
    list(config.GITLAB_PROJECTS)
    if config and getattr(config, "GITLAB_PROJECTS", None)
    else [
        ("comprasnet%2Fcontratos_v2", "contratos_v2"),
        ("comprasnet%2Fcontratos", "contratos"),
    ]
)


def _gitlab_token_for_repo(gitlab_repo: str) -> str:
    if config and hasattr(config, "gitlab_token_for_repo"):
        return config.gitlab_token_for_repo(gitlab_repo)
    by_repo = {
        "contratos_v2": os.environ.get("GITLAB_TOKEN_CONTRATOS_V2", ""),
        "contratos": os.environ.get("GITLAB_TOKEN_CONTRATOS", ""),
    }
    return by_repo.get(gitlab_repo, "") or os.environ.get("GITLAB_TOKEN", "")


def _gitlab_base_url() -> str:
    return (config.GITLAB_URL if config else os.environ.get("GITLAB_URL", "https://gitlab.com")).rstrip("/")


def _fetch_paginated(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> List[Dict]:
    items: List[Dict] = []
    page = 1
    while True:
        query = {"per_page": 100, "page": page}
        if params:
            query.update(params)
        response = requests.get(url, headers=headers, params=query, timeout=60)
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list):
            raise RuntimeError(f"Resposta inesperada de {url}: {batch!r}")
        items.extend(batch)
        next_page = response.headers.get("X-Next-Page")
        if not next_page:
            break
        page = int(next_page)
    return items


def _is_bot(member: Dict[str, Any]) -> bool:
    username = (member.get("username") or "").lower()
    name = member.get("name") or ""
    if any(marker in username for marker in BOT_USERNAME_MARKERS):
        return True
    if any(marker in name for marker in BOT_NAME_MARKERS):
        return True
    if username in {"gbdevhub", "duo-developer"}:
        return True
    return False


def _fetch_group_members(group_id: str, token: str) -> List[Dict[str, Any]]:
    base = _gitlab_base_url()
    headers = {"PRIVATE-TOKEN": token}
    url = f"{base}/api/v4/groups/{group_id}/members/all"
    try:
        return _fetch_paginated(url, headers)
    except requests.HTTPError as exc:
        print(f"AVISO - membros do grupo {group_id}: {exc}")
        return []


def _collect_commit_emails(project_id: str, token: str, max_pages: int = 5) -> Dict[str, str]:
    """Mapeia author_name -> author_email a partir de commits recentes."""
    base = _gitlab_base_url()
    headers = {"PRIVATE-TOKEN": token}
    mapping: Dict[str, str] = {}
    page = 1
    while page <= max_pages:
        response = requests.get(
            f"{base}/api/v4/projects/{project_id}/repository/commits",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=60,
        )
        if response.status_code >= 400:
            break
        commits = response.json()
        if not commits:
            break
        for commit in commits:
            name = (commit.get("author_name") or "").strip()
            email = (commit.get("author_email") or "").strip().lower()
            if name and email and "@" in email and not email.endswith("@users.noreply.gitlab.com"):
                mapping.setdefault(name, email)
        next_page = response.headers.get("X-Next-Page")
        if not next_page:
            break
        page = int(next_page)
    return mapping


def _collect_author_commit_emails(
    project_id: str,
    token: str,
    usernames: List[str],
) -> Dict[str, str]:
    """Busca e-mail de commits filtrados por autor (username GitLab)."""
    base = _gitlab_base_url()
    headers = {"PRIVATE-TOKEN": token}
    mapping: Dict[str, str] = {}
    for username in usernames:
        if not username:
            continue
        response = requests.get(
            f"{base}/api/v4/projects/{project_id}/repository/commits",
            headers=headers,
            params={"author": username, "per_page": 20},
            timeout=60,
        )
        if response.status_code >= 400:
            continue
        for commit in response.json():
            email = (commit.get("author_email") or "").strip().lower()
            if email and "@" in email and not email.endswith("@users.noreply.gitlab.com"):
                mapping[username] = email
                break
    return mapping


def _merge_email(
    user: Dict[str, Any],
    commit_emails: Dict[str, str],
) -> str:
    if user.get("email"):
        return user["email"]
    name = (user.get("name") or "").strip()
    if name and name in commit_emails:
        return commit_emails[name]
    username = (user.get("username") or "").strip()
    for commit_name, email in commit_emails.items():
        if commit_name.casefold() == name.casefold():
            return email
        if username and username.casefold() in email.casefold():
            return email
    return ""


def _member_is_active(member: Dict[str, Any]) -> bool:
    if member.get("state") != "active":
        return False
    expires_at = member.get("expires_at")
    if expires_at:
        return False
    return True


def _fetch_project_members(project_id: str, token: str) -> List[Dict[str, Any]]:
    base = _gitlab_base_url()
    headers = {"PRIVATE-TOKEN": token}
    url = f"{base}/api/v4/projects/{project_id}/members/all"
    return _fetch_paginated(url, headers)


def _fetch_user_details(
    user_id: int,
    token: str,
    fallback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base = _gitlab_base_url()
    headers = {"PRIVATE-TOKEN": token}
    last_error: Optional[Exception] = None

    for attempt in range(3):
        try:
            response = requests.get(
                f"{base}/api/v4/users/{user_id}",
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Resposta inesperada para user {user_id}")
            return data
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else 0
            if attempt < 2 and status >= 500:
                time.sleep(2**attempt)
                continue
            break
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            break

    if fallback:
        return fallback
    if last_error:
        raise last_error
    raise RuntimeError(f"Nao foi possivel obter detalhes do user {user_id}")


def collect_active_gitlab_users() -> Tuple[List[Dict[str, Any]], List[str]]:
    """Retorna usuarios unicos (por id) e avisos."""
    warnings: List[str] = []
    by_id: Dict[int, Dict[str, Any]] = {}
    commit_emails: Dict[str, str] = {}
    token_for_group = os.environ.get("GITLAB_TOKEN", "")
    if not token_for_group:
        for repo_name in ("contratos_v2", "contratos"):
            token_for_group = token_for_group or _gitlab_token_for_repo(repo_name)

    if token_for_group:
        group_members = _fetch_group_members(GITLAB_GROUP, token_for_group)
        print(f"OK - grupo {GITLAB_GROUP}: {len(group_members)} membros (referencia)")

    for project_id, repo_name in GITLAB_PROJECTS:
        token = _gitlab_token_for_repo(repo_name)
        if not token:
            warnings.append(f"Sem token para {repo_name}; projeto ignorado.")
            continue

        commit_emails.update(_collect_commit_emails(project_id, token, max_pages=30))
        members = _fetch_project_members(project_id, token)
        active_members = [m for m in members if _member_is_active(m) and not _is_bot(m)]
        print(f"OK - {repo_name}: {len(active_members)} membros ativos humanos (de {len(members)} total)")

        for member in active_members:
            uid = int(member["id"])
            if uid in by_id:
                by_id[uid]["repos"].add(repo_name)
                continue
            details = _fetch_user_details(uid, token, fallback=member)
            email = (details.get("email") or details.get("public_email") or "").strip().lower()
            by_id[uid] = {
                "gitlab_id": uid,
                "username": details.get("username") or member.get("username"),
                "name": details.get("name") or member.get("name"),
                "email": email,
                "state": details.get("state") or member.get("state"),
                "repos": {repo_name},
            }

    for user in by_id.values():
        user["email"] = _merge_email(user, commit_emails)

    missing_usernames = [u["username"] for u in by_id.values() if not u.get("email") and u.get("username")]
    if missing_usernames:
        for project_id, repo_name in GITLAB_PROJECTS:
            token = _gitlab_token_for_repo(repo_name)
            if not token:
                continue
            by_username = _collect_author_commit_emails(project_id, token, missing_usernames)
            for user in by_id.values():
                if user.get("email"):
                    continue
                username = user.get("username") or ""
                if username in by_username:
                    user["email"] = by_username[username]

    users = sorted(by_id.values(), key=lambda u: (u.get("name") or u.get("username") or "").lower())
    if commit_emails:
        print(f"OK - {len(commit_emails)} e-mail(s) inferido(s) de commits Git")
    return users, warnings


def _supabase_config() -> Tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise SystemExit(
            "Defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY em .env na raiz do workspace."
        )
    return url, key


def _list_existing_emails(supabase_url: str, service_key: str) -> Set[str]:
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
    }
    emails: Set[str] = set()
    page = 1
    per_page = 200
    while True:
        response = requests.get(
            f"{supabase_url}/auth/v1/admin/users",
            headers=headers,
            params={"page": page, "per_page": per_page},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        users = payload.get("users") if isinstance(payload, dict) else payload
        if not users:
            break
        for user in users:
            email = (user.get("email") or "").strip().lower()
            if email:
                emails.add(email)
        if len(users) < per_page:
            break
        page += 1
    return emails


def _upsert_gitlab_user(
    supabase_url: str,
    service_key: str,
    *,
    gitlab_id: int,
    username: Optional[str],
    name: Optional[str],
    email: Optional[str],
) -> None:
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    body = {
        "id": gitlab_id,
        "username": (username or f"user-{gitlab_id}").strip(),
        "name": (name or "").strip() or None,
        "email": (email or "").strip().lower() or None,
    }
    response = requests.post(
        f"{supabase_url}/rest/v1/gitlab_users?on_conflict=id",
        headers=headers,
        json=body,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")


def _create_supabase_user(
    supabase_url: str,
    service_key: str,
    *,
    email: str,
    password: str,
    full_name: Optional[str],
    autor_issues: Optional[str],
    gitlab_user_id: Optional[int],
) -> None:
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {
        "email": email,
        "password": password,
        "email_confirm": True,
    }
    if full_name:
        body["user_metadata"] = {"full_name": full_name}

    response = requests.post(
        f"{supabase_url}/auth/v1/admin/users",
        headers=headers,
        json=body,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")

    created = response.json()
    user_id = created.get("id")
    if not user_id:
        raise RuntimeError(f"Usuario criado sem id: {created!r}")

    profile_headers = {
        **headers,
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    profile_body = {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "gitlab_user_id": gitlab_user_id,
        "autor_issues": autor_issues,
        "role": "user",
        "active": True,
    }
    profile_response = requests.post(
        f"{supabase_url}/rest/v1/profiles",
        headers=profile_headers,
        params={"on_conflict": "id"},
        json=profile_body,
        timeout=60,
    )
    if profile_response.status_code >= 400:
        raise RuntimeError(profile_response.text or f"HTTP {profile_response.status_code}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Provisiona usuarios GitLab no Supabase.")
    parser.add_argument("--dry-run", action="store_true", help="Apenas lista, nao cria contas.")
    parser.add_argument("--password", default=None, help="Senha inicial dos novos usuarios.")
    args = parser.parse_args()

    _load_dotenv()

    users, warnings = collect_active_gitlab_users()
    for warning in warnings:
        print(f"AVISO - {warning}")

    if not users:
        print("Nenhum membro ativo encontrado (ou tokens ausentes).")
        return 1

    print("\nUsuarios ativos nos projetos GitLab:\n")
    print(f"{'Nome':<35} {'E-mail':<40} {'Repos'}")
    print("-" * 90)
    for user in users:
        repos = ", ".join(sorted(user["repos"]))
        email = user["email"] or "(sem e-mail)"
        name = (user["name"] or user["username"] or "?")[:34]
        print(f"{name:<35} {email:<40} {repos}")

    without_email = [u for u in users if not u["email"]]
    if without_email:
        print(f"\nAVISO - {len(without_email)} usuario(s) sem e-mail visivel na API GitLab:")
        for user in without_email:
            print(f"  - {user['name']} (@{user['username']}, id={user['gitlab_id']})")

    provisionable = [u for u in users if u["email"]]
    if args.dry_run:
        print(f"\nDRY-RUN: {len(provisionable)} usuario(s) seriam provisionados.")
        return 0

    supabase_url, service_key = _supabase_config()
    existing = _list_existing_emails(supabase_url, service_key)

    created = 0
    skipped = 0
    failed = 0

    for user in provisionable:
        email = user["email"]
        if email in existing:
            print(f"PULADO - ja existe: {email}")
            skipped += 1
            continue
        try:
            gitlab_id = int(user["gitlab_id"])
            _upsert_gitlab_user(
                supabase_url,
                service_key,
                gitlab_id=gitlab_id,
                username=user.get("username"),
                name=user.get("name"),
                email=email,
            )
            _create_supabase_user(
                supabase_url,
                service_key,
                email=email,
                password=args.password,
                full_name=user.get("name"),
                autor_issues=user.get("name"),
                gitlab_user_id=gitlab_id,
            )
            print(f"CRIADO - {email} ({user.get('name')})")
            existing.add(email)
            created += 1
        except Exception as exc:
            print(f"ERRO - {email}: {exc}")
            failed += 1

    print(f"\nResumo: {created} criado(s), {skipped} ja existente(s), {failed} erro(s).")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
