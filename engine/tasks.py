"""Celery orchestration tasks — the glue between webhooks and the agent graph.

Two entry points mirror the two webhook events (PRD §3.3):

* ``handle_pull_request`` — opened/synchronize: open a review job, run Agents
  A→B, pause before the sandbox, and post the proposal to the PR (PRD §3.5).
* ``handle_issue_comment`` — a slash-command reply that resumes the paused graph
  along the /approve, /reject, or /skip path (PRD §3.6).

All heavy work (hydration, LLM, sandbox) lives here, off the request thread, so
the webhook view can return HTTP 200 within GitHub's 10s budget.
"""
from __future__ import annotations

import logging

from celery import shared_task

from src.graph import get_app
from engine import services
from engine.errors import (
    ProviderError,
    is_provider_error,
    extract_diagnostic,
    execution_paused_comment,
)
from engine.github_comments import render_review_comment, render_final_comment, BOT_MARKER
from engine.slash import parse_command, APPROVE, REJECT, SKIP
from tenancy.models import ReviewSession

logger = logging.getLogger(__name__)

# Retry backoff (seconds) when a repo is at its concurrency cap (PRD §5.1).
CONCURRENCY_RETRY_DELAY = 30


# --------------------------------------------------------------------------- #
# Pull request -> start a review job
# --------------------------------------------------------------------------- #
@shared_task(bind=True, max_retries=None)
def handle_pull_request(self, payload: dict):
    action = payload.get("action")
    if action not in ("opened", "synchronize"):
        return

    installation_id = payload["installation"]["id"]
    repo_full_name = payload["repository"]["full_name"]
    pr = payload["pull_request"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]

    org, repo = services.resolve_tenant(installation_id, repo_full_name)
    if not org or not repo:
        logger.info("No tenant config for %s (installation %s); ignoring.",
                    repo_full_name, installation_id)
        return
    if not org.has_keys:
        logger.info("Tenant %s has no BYOK keys configured; ignoring.", repo_full_name)
        return

    # --- Concurrency governance (PRD §5.1): FIFO-style delayed retry at cap. ---
    if services.at_capacity(repo):
        logger.info("Repo %s at concurrency cap; requeueing PR #%s.",
                    repo_full_name, pr_number)
        raise self.retry(countdown=CONCURRENCY_RETRY_DELAY)

    session = ReviewSession.objects.create(
        repo_settings=repo,
        pr_number=pr_number,
        commit_sha=head_sha,
        current_status=ReviewSession.Status.ANALYZING,
        active_jobs=1,
    )

    _start_review(session, org, repo)


def _start_review(session: ReviewSession, org, repo):
    """Run Agents A→B to the pre-sandbox pause and post the proposal."""
    gh = services.build_connector(org, repo)
    pr_number = session.pr_number

    try:
        pr_data = gh.get_pr_details(pr_number)
        target = services.select_target_file(pr_data)
        if not target:
            gh.post_pr_comment(
                pr_number,
                f"{BOT_MARKER}\nRepoRover found no reviewable Python files in this PR.",
            )
            _complete(session)
            return

        repo_map = gh.get_repo_map(pr_data["files"], pr_data["head_branch"])
        filename = target["filename"]
        content = repo_map.get(filename) or gh.get_file_content(
            filename, branch=pr_data["head_branch"]
        )

        thread_id = str(session.langgraph_thread_id)
        config = services.tenant_runtime_config(org, thread_id)
        initial_state = {
            "repo_path": repo.repository_name,
            "file_path": filename,
            "file_content": content,
            "original_code": content,
            "repo_files": repo_map,
            "pr_description": f"Title: {pr_data['title']}\nDesc: {pr_data['description']}",
            "iteration_count": 0,
        }

        app = get_app()
        # Runs reviewer -> refactorer, then pauses before executor_tool_node.
        for _ in app.stream(initial_state, config=config):
            pass

        _report_pause(gh, session, app, config, filename)

    except Exception as exc:  # noqa: BLE001 - provider failures handled below
        _handle_failure(gh, session, pr_number, exc)


# --------------------------------------------------------------------------- #
# Issue comment -> resume a paused review along a slash-command path
# --------------------------------------------------------------------------- #
@shared_task(bind=True)
def handle_issue_comment(self, payload: dict):
    if payload.get("action") != "created":
        return
    if "pull_request" not in payload.get("issue", {}):
        return  # comment on a plain issue, not a PR

    body = payload["comment"].get("body", "")
    if BOT_MARKER in body:
        return  # ignore our own comments
    cmd = parse_command(body)
    if cmd is None:
        return  # not a slash command

    installation_id = payload["installation"]["id"]
    repo_full_name = payload["repository"]["full_name"]
    pr_number = payload["issue"]["number"]

    org, repo = services.resolve_tenant(installation_id, repo_full_name)
    if not org or not repo:
        return

    gh = services.build_connector(org, repo)

    # ───────────────────────────────────────────────────────────────────
    # INTERCEPT AUTOMATED FRESH REVIEW TRIGGER
    # ───────────────────────────────────────────────────────────────────
    if cmd.command == "review":
        if services.at_capacity(repo):
            gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nRepo is currently at its concurrency capacity loop limit.")
            return

        latest_sha = gh.get_latest_commit_sha(pr_number)
        
        # Spawn an entirely new review session record mapping the current head state
        session = ReviewSession.objects.create(
            repo_settings=repo,
            pr_number=pr_number,
            commit_sha=latest_sha,
            current_status=ReviewSession.Status.ANALYZING,
            active_jobs=1,
        )
        
        _start_review(session, org, repo)
        return
    # ───────────────────────────────────────────────────────────────────

    # The existing lookups for AWAITING_HUMAN continue safely down here...
    session = (
        ReviewSession.objects.filter(
            repo_settings=repo,
            pr_number=pr_number,
            current_status=ReviewSession.Status.AWAITING_HUMAN,
        )
        .order_by("-updated_at")
        .first()
    )
    if not session:
        return  # nothing is awaiting input on this PR

    gh = services.build_connector(org, repo)

    # Guard against acting on stale code (PRD §4.3): a newer push supersedes
    # this paused session.
    try:
        latest_sha = gh.get_latest_commit_sha(pr_number)
    except Exception:  # noqa: BLE001
        latest_sha = session.commit_sha
    if latest_sha != session.commit_sha:
        gh.post_pr_comment(
            pr_number,
            f"{BOT_MARKER}\nThis command targets an outdated commit; a newer push "
            "has started a fresh review.",
        )
        return

    thread_id = str(session.langgraph_thread_id)
    config = services.tenant_runtime_config(org, thread_id)
    app = get_app()
    snapshot = app.get_state(config)
    filename = snapshot.values.get("file_path", "")

    try:
        if cmd.command == APPROVE:
            session.current_status = ReviewSession.Status.EXECUTING
            session.save(update_fields=["current_status", "updated_at"])

        elif cmd.command == REJECT:
            app.update_state(
                config,
                {
                    "execution_status": "FAILURE",
                    "execution_logs": f"HUMAN REJECTION: {cmd.feedback}",
                    "iteration_count": snapshot.values.get("iteration_count", 0),
                },
                as_node="executor_tool_node",
            )

        elif cmd.command == SKIP:
            app.update_state(
                config,
                {"execution_status": "SKIPPED_TO_DOCS", "execution_logs": "User skipped."},
                as_node="executor_tool_node",
            )

        # Resume: run from the pause to the next stop (final or another pause).
        for _ in app.stream(None, config=config):
            pass

        _report_pause(gh, session, app, config, filename)

    except Exception as exc:  # noqa: BLE001
        _handle_failure(gh, session, pr_number, exc)


# --------------------------------------------------------------------------- #
# Shared reporting helpers
# --------------------------------------------------------------------------- #
def _report_pause(gh, session: ReviewSession, app, config, filename: str):
    """Inspect the graph: if finished, post final; if paused, post a new proposal."""
    snapshot = app.get_state(config)
    values = snapshot.values

    if not snapshot.next:
        # Graph reached END — sandbox/docs complete.
        gh.post_pr_comment(
            session.pr_number,
            render_final_comment(
                filename=filename,
                execution_status=values.get("execution_status", "UNKNOWN"),
                execution_logs=values.get("execution_logs", ""),
                documentation_diff=values.get("documentation_diff", ""),
            ),
        )
        _complete(session)
        return

    # Paused again before the sandbox (initial proposal or a post-retry revision).
    gh.post_pr_comment(
        session.pr_number,
        render_review_comment(
            filename=filename,
            intent_summary=values.get("intent_summary", ""),
            review_issues=values.get("review_issues", []),
            refactored_code=values.get("refactored_code", ""),
            iteration=values.get("iteration_count", 0),
        ),
    )
    session.current_status = ReviewSession.Status.AWAITING_HUMAN
    session.save(update_fields=["current_status", "updated_at"])


def _handle_failure(gh, session: ReviewSession, pr_number: int, exc: Exception):
    """Route provider/BYOK failures to the §5.2 notice; re-raise unknown bugs."""
    if isinstance(exc, ProviderError) or is_provider_error(exc):
        diagnostic = exc.diagnostic if isinstance(exc, ProviderError) else extract_diagnostic(exc)
        logger.warning("Provider error for PR #%s: %s", pr_number, diagnostic)
        try:
            gh.post_pr_comment(pr_number, execution_paused_comment(diagnostic))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to post Execution Paused notice.")
        _complete(session)
        return
    logger.exception("Unexpected error processing PR #%s", pr_number)
    _complete(session)
    raise exc


def _complete(session: ReviewSession):
    session.current_status = ReviewSession.Status.COMPLETED
    session.active_jobs = 0
    session.save(update_fields=["current_status", "active_jobs", "updated_at"])
