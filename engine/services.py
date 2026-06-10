"""Shared orchestration services: tenant resolution, concurrency, connectors.

These helpers sit between the Celery tasks and the data/agent layers. They keep
the tasks readable and concentrate the multi-tenant security rules (config is
read ONLY from the database, never from PR contents — PRD §6.1).
"""
from __future__ import annotations

from typing import Optional, Tuple

from django.conf import settings

from src.github_tools import GitHubConnector
from tenancy.models import OrganizationConfig, RepoSettings, ReviewSession


def resolve_tenant(
    installation_id: int, repo_full_name: str
) -> Tuple[Optional[OrganizationConfig], Optional[RepoSettings]]:
    """Look up the org + repo config from the DB (PRD §6.1 — never from the PR)."""
    try:
        org = OrganizationConfig.objects.get(github_installation_id=installation_id)
    except OrganizationConfig.DoesNotExist:
        return None, None

    repo = (
        RepoSettings.objects.filter(org_config=org, repository_name=repo_full_name)
        .first()
    )
    return org, repo


def active_session_count(repo: RepoSettings) -> int:
    """Count sessions currently occupying a concurrency slot (PRD §5.1)."""
    return ReviewSession.objects.filter(
        repo_settings=repo,
        current_status__in=ReviewSession.ACTIVE_STATUSES,
    ).count()


def at_capacity(repo: RepoSettings) -> bool:
    return active_session_count(repo) >= repo.max_concurrency


def build_connector(org: OrganizationConfig, repo: RepoSettings) -> GitHubConnector:
    """Authenticate to GitHub as the App installation for this tenant (PRD §3.4)."""
    return GitHubConnector.from_installation(
        repo_name=repo.repository_name,
        installation_id=org.github_installation_id,
        app_id=settings.GITHUB_APP_ID,
        private_key=settings.GITHUB_APP_PRIVATE_KEY,
    )


def tenant_runtime_config(org: OrganizationConfig, thread_id: str) -> dict:
    """Build the LangGraph ``configurable`` dict, decrypting BYOK keys in-memory.

    The plaintext keys live only for the duration of the task and are passed
    through ``configurable`` (not persisted state), so they never enter the
    checkpoint store (PRD §3.1, §1).
    """
    return {
        "configurable": {
            "thread_id": thread_id,
            "gemini_api_key": org.get_gemini_key(),
            "e2b_api_key": org.get_e2b_key(),
        }
    }


def select_target_file(pr_data: dict) -> Optional[dict]:
    """Pick the changed Python file to review.

    Phase 1.0 reviews the first non-removed Python file per PR so the
    human-in-the-loop gate maps cleanly to a single PR comment thread.
    Multi-file fan-out with disambiguated slash commands is future work.
    """
    for f in pr_data["files"]:
        if f["filename"].endswith(".py") and f["status"] != "removed":
            return f
    return None
