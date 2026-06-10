from django.contrib import admin

from .models import OrganizationConfig, RepoSettings, ReviewSession


@admin.register(OrganizationConfig)
class OrganizationConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "github_installation_id", "has_keys", "created_at")
    # Never expose encrypted key material in the admin UI.
    exclude = ("encrypted_gemini_key", "encrypted_e2b_key")
    readonly_fields = ("created_at",)


@admin.register(RepoSettings)
class RepoSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "repository_name", "org_config", "max_concurrency")
    list_filter = ("org_config",)
    search_fields = ("repository_name",)


@admin.register(ReviewSession)
class ReviewSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "repo_settings",
        "pr_number",
        "commit_sha",
        "current_status",
        "active_jobs",
        "updated_at",
    )
    list_filter = ("current_status",)
    search_fields = ("pr_number", "commit_sha")
    readonly_fields = ("langgraph_thread_id", "updated_at")
