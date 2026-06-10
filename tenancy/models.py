"""Multi-tenant data models (PRD §4).

The database is a permission mapper and process-state coordinator ONLY. To
uphold the Zero-Retention guarantee (PRD §1), no repository source code is ever
stored here — only tenant config, encrypted BYOK keys, and review-session
metadata.
"""
from __future__ import annotations
import uuid
from django.db import models
from .crypto import decrypt_key, encrypt_key

class OrganizationConfig(models.Model):
    """Top-level tenant authorization with multi-LLM provider support (PRD §3.1, §4.1)."""

    class ProviderChoices(models.TextChoices):
        GEMINI = "gemini", "Google Gemini"
        OPENAI = "openai", "OpenAI"
        GROQ = "groq", "Groq"
        LOCAL = "local", "Local Setup / Ollama"

    github_installation_id = models.IntegerField(
        unique=True,
        help_text="Unique installation id supplied by GitHub during app setup.",
    )
    
    # Provider Settings
    llm_provider = models.CharField(
        max_length=20,
        choices=ProviderChoices.choices,
        default=ProviderChoices.GEMINI,
        help_text="Active LLM provider for processing reviews."
    )
    llm_model_name = models.CharField(
        max_length=100,
        default="gemini-2.5-flash",
        help_text="Target model execution string (e.g., llama3-70b-8192, gpt-4o, etc.)"
    )
    llm_base_url = models.URLField(
        null=True,
        blank=True,
        help_text="Custom endpoint wrapper URL (Required for Local Ollama, e.g., http://localhost:11434/v1)"
    )

    # Generic Encrypted Key Vault
    encrypted_llm_key = models.BinaryField(
        null=True, 
        blank=True, 
        help_text="AES-encrypted API key string matching the selected provider."
    )
    encrypted_e2b_key = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_llm_key(self, plaintext: str) -> None:
        self.encrypted_llm_key = encrypt_key(plaintext)

    def set_e2b_key(self, plaintext: str) -> None:
        self.encrypted_e2b_key = encrypt_key(plaintext)

    def get_llm_key(self) -> str:
        if not self.encrypted_llm_key:
            return ""
        return decrypt_key(self.encrypted_llm_key)

    def get_e2b_key(self) -> str:
        if not self.encrypted_e2b_key:
            return ""
        return decrypt_key(self.encrypted_e2b_key)

    @property
    def has_keys(self) -> bool:
        # Local loops like Ollama do not require an API key string to execute
        if self.llm_provider == self.ProviderChoices.LOCAL:
            return bool(self.encrypted_e2b_key)
        return bool(self.encrypted_llm_key and self.encrypted_e2b_key)

    def __str__(self) -> str:
        return f"OrganizationConfig(installation={self.github_installation_id})"


class RepoSettings(models.Model):
    """Per-repository behavioural configuration, edited via the central dashboard."""

    org_config = models.ForeignKey(
        OrganizationConfig,
        on_delete=models.CASCADE,
        related_name="repos",
    )
    repository_name = models.CharField(
        max_length=255,
        help_text='Full name, e.g. "owner/repository-name".',
    )
    ignored_directories = models.JSONField(
        default=list,
        blank=True,
        help_text='Directory globs skipped during AST parsing, e.g. ["tests/*"].',
    )
    max_concurrency = models.IntegerField(
        default=2,
        help_text="Maximum overlapping active review executions for this repo.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["org_config", "repository_name"],
                name="unique_repo_per_org",
            )
        ]

    def __str__(self) -> str:
        return self.repository_name


class ReviewSession(models.Model):
    """Coordinates non-blocking async state across disparate webhook invocations."""

    class Status(models.TextChoices):
        ANALYZING = "ANALYZING", "Analyzing"
        AWAITING_HUMAN = "AWAITING_HUMAN", "Awaiting human"
        EXECUTING = "EXECUTING", "Executing"
        COMPLETED = "COMPLETED", "Completed"

    # Statuses that count as "occupying a concurrency slot" (PRD §5.1).
    ACTIVE_STATUSES = (Status.ANALYZING, Status.EXECUTING)

    repo_settings = models.ForeignKey(
        RepoSettings,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    pr_number = models.IntegerField()
    commit_sha = models.CharField(
        max_length=64,
        help_text="Latest commit reviewed; actions only run on the latest SHA.",
    )
    langgraph_thread_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        help_text="Pointer key Celery workers use to recall checkpoint state.",
    )
    current_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ANALYZING,
    )
    active_jobs = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["repo_settings", "pr_number"]),
            models.Index(fields=["current_status"]),
        ]

    def __str__(self) -> str:
        return (
            f"ReviewSession(repo={self.repo_settings.repository_name}, "
            f"pr={self.pr_number}, status={self.current_status})"
        )
