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
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

def get_tenant_llm(org: OrganizationConfig):
    """
    Dynamic factory initializing any cloud provider or local pipeline 
    conforming to OpenAI or Google GenAI standard schemas.
    """
    api_key = org.get_llm_key()
    model_name = org.llm_model_name
    
    # 1. Google Gemini Route
    if org.llm_provider == OrganizationConfig.ProviderChoices.GEMINI:
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0.1
        )
        
    # 2. OpenAI Native Route
    elif org.llm_provider == OrganizationConfig.ProviderChoices.OPENAI:
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            temperature=0.1
        )
        
    # 3. Groq Infrastructure Route
    elif org.llm_provider == OrganizationConfig.ProviderChoices.GROQ:
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            temperature=0.1
        )
        
    # 4. Local Setup / Ollama Route
    elif org.llm_provider == OrganizationConfig.ProviderChoices.LOCAL:
        # Default local setups fall back to standard local host loops if blank
        base_url = org.llm_base_url or "http://localhost:11434/v1"
        return ChatOpenAI(
            model=model_name,
            api_key="local-placeholder",  # Ollama requires a non-empty key placeholder
            base_url=base_url,
            temperature=0.1
        )
        
    else:
        raise ValueError(f"Unsupported model provider: {org.llm_provider}")
    
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


def tenant_runtime_config(org, thread_id):
    """
    Builds the state dictionary metadata configuration that LangGraph 
    injects directly into the agent node executors context loop (PRD §3.1).
    """
    return {
        "configurable": {
            "thread_id": thread_id,
            
            # --- FIXED FIELDS FOR THE MULTI-LLM PIPELINE ---
            "llm_provider": org.llm_provider,
            "llm_model_name": org.llm_model_name,
            "llm_base_url": org.llm_base_url,
            "llm_key": org.get_llm_key(),       # Resolves any active provider key cleanly
            "e2b_api_key": org.get_e2b_key(),   # Resolves sandbox execution credentials
            
            # Legacy fallback strings to maintain structural compatibility with other components
            "gemini_api_key": org.get_llm_key(),
            "gemini_model": org.llm_model_name,
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
