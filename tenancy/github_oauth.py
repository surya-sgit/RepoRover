"""GitHub OAuth web-flow helpers for the dashboard (PRD §3.1).

Users authenticate exclusively via GitHub OAuth — no passwords are stored. We
exchange the OAuth code for a user token (stdlib only, no extra deps) and use it
to discover which App installations the user can administer.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import List

from django.conf import settings

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API_BASE = "https://api.github.com"


def authorize_url(state: str, redirect_uri: str) -> str:
    params = {
        "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "read:user",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str, redirect_uri: str) -> str:
    data = urllib.parse.urlencode(
        {
            "client_id": settings.GITHUB_OAUTH_CLIENT_ID,
            "client_secret": settings.GITHUB_OAUTH_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL, data=data, headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"OAuth token exchange failed: {body}")
    return token


def _api_get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_user_login(token: str) -> str:
    return _api_get("/user", token).get("login", "")


def list_user_installations(token: str) -> List[dict]:
    """Installations of this App the authenticated user can access."""
    data = _api_get("/user/installations", token)
    return data.get("installations", [])
