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
    """Top-level tenant authorization, created when a user installs the GitHub App."""

    github_installation_id = models.IntegerField(
        unique=True,
        help_text="Unique installation id supplied by GitHub during app setup.",
    )
    # AES-encrypted BYOK parameters (PRD §3.1, §4.1). Never store plaintext.
    encrypted_gemini_key = models.BinaryField(null=True, blank=True)
    encrypted_e2b_key = models.BinaryField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_gemini_key(self, plaintext: str) -> None:
        self.encrypted_gemini_key = encrypt_key(plaintext)

    def set_e2b_key(self, plaintext: str) -> None:
        self.encrypted_e2b_key = encrypt_key(plaintext)

    def get_gemini_key(self) -> str:
        """Decrypt the Gemini key. Call only inside a worker, never log the result."""
        return decrypt_key(self.encrypted_gemini_key)

    def get_e2b_key(self) -> str:
        """Decrypt the E2B key. Call only inside a worker, never log the result."""
        return decrypt_key(self.encrypted_e2b_key)

    @property
    def has_keys(self) -> bool:
        return bool(self.encrypted_gemini_key and self.encrypted_e2b_key)

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
