"""Error propagation & BYOK quota fail-safes (PRD §5.2).

When a tenant's configured Gemini/E2B account returns an authentication,
credit-exhaustion, or rate-limit error, the platform must halt that PR's
processing, mark the session COMPLETED, and post a single transparent notice
back to the PR. This module centralises detection and the notice template.
"""
from __future__ import annotations

import re


class ProviderError(Exception):
    """A tenant BYOK provider (Gemini/E2B) failed in a way the user must resolve.

    Carries a short diagnostic string surfaced verbatim in the PR comment.
    """

    def __init__(self, message: str, diagnostic: str | None = None):
        super().__init__(message)
        self.diagnostic = diagnostic or message


# Substrings that indicate an auth / quota / rate-limit failure from a provider
# rather than a bug in the reviewed code.
_PROVIDER_SIGNALS = (
    "api key not valid",
    "invalid api key",
    "permission denied",
    "unauthenticated",
    "unauthorized",
    "401",
    "403",
    "quota",
    "rate limit",
    "rate-limit",
    "resource exhausted",
    "429",
    "insufficient credit",
    "billing",
)


def is_provider_error(exc: Exception) -> bool:
    """Heuristically classify an exception as a BYOK provider failure (PRD §5.2)."""
    text = str(exc).lower()
    return any(signal in text for signal in _PROVIDER_SIGNALS)


def extract_diagnostic(exc: Exception) -> str:
    """Pull a concise provider error code / subtext for the PR notice."""
    text = str(exc).strip()
    # Prefer an explicit HTTP-style code if present.
    code = re.search(r"\b(4\d{2}|5\d{2})\b", text)
    snippet = text.splitlines()[0][:300] if text else "Unknown provider error"
    if code:
        return f"{code.group(1)}: {snippet}"
    return snippet


def execution_paused_comment(diagnostic: str) -> str:
    """Render the unified 'Execution Paused' PR comment block (PRD §5.2)."""
    return (
        "### ⚠️ RepoRover Execution Paused\n\n"
        "The automated code review cycle could not complete due to an "
        "infrastructure authentication or usage quota error from your "
        "configured provider account.\n\n"
        f"**Diagnostic Log:** `{diagnostic}`\n\n"
        "*Please verify your credentials inside the RepoRover Central Web "
        "Dashboard to resume processing.*"
    )
