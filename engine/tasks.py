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

from src.graph import get_app, get_conflict_app
from engine import services
from engine.errors import (
    ProviderError,
    is_provider_error,
    extract_diagnostic,
    execution_paused_comment,
)
from engine.github_comments import render_review_comment, render_final_comment, BOT_MARKER
from engine.slash import parse_command, APPROVE, REJECT, SKIP
from tenancy.models import OrganizationConfig, RepoSettings, ReviewSession

logger = logging.getLogger(__name__)

# Retry backoff (seconds) when a repo is at its concurrency cap (PRD §5.1).
CONCURRENCY_RETRY_DELAY = 30


# --------------------------------------------------------------------------- #
# Core Orchestration Helpers
# --------------------------------------------------------------------------- #

def _trigger_pr_fanout(gh, org, repo, pr_number: int, head_sha: str):
    """Helper: Spawns concurrent review tasks for all Python files in a PR."""
    pr_data = gh.get_pr_details(pr_number)
    
    # 1. Gather all Python files in the PR
    target_files = [
        f for f in pr_data["files"] 
        if f["filename"].endswith(".py") and f["status"] != "removed"
    ]

    if not target_files:
        gh.post_pr_comment(
            pr_number,
            f"{BOT_MARKER}\nRepoRover found no reviewable Python files in this PR.",
        )
        return

    # 2. Fan-out: Create a separate session & task for every file
    for target_file in target_files:
        session = ReviewSession.objects.create(
            repo_settings=repo,
            pr_number=pr_number,
            file_path=target_file["filename"], # Track specific file
            commit_sha=head_sha,
            current_status=ReviewSession.Status.ANALYZING,
            active_jobs=1,
        )
        process_file_review.delay(session.id, org.id, repo.id)


def _trigger_conflict_resolution(gh, org, repo, pr_number: int, target_file: str):
    """Helper: Initiates the dedicated Agent D Conflict Resolution flow."""
    pr_data = gh.get_pr_details(pr_number)
    
    conflict_content = gh.generate_conflict_markers(pr_data["base_branch"], pr_data["head_branch"], target_file)
    if not conflict_content:
        gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nCould not generate conflict markers for `{target_file}`. Are you sure this file currently has a merge conflict?")
        return
        
    latest_sha = gh.get_latest_commit_sha(pr_number)
    session = ReviewSession.objects.create(
        repo_settings=repo,
        pr_number=pr_number,
        file_path=target_file,
        commit_sha=latest_sha,
        current_status=ReviewSession.Status.ANALYZING,
        active_jobs=1,
    )

    repo_map = gh.get_repo_map(pr_data["files"], pr_data["head_branch"])
    expected_test_name = f"test_{target_file.split('/')[-1]}"
    alt_test_name = f"{target_file.split('/')[-1].replace('.py', '')}_test.py"
    
    existing_test_path = None
    existing_test_code = None
    for filepath, f_content in repo_map.items():
        if filepath.endswith(expected_test_name) or filepath.endswith(alt_test_name):
            existing_test_path = filepath
            existing_test_code = f_content
            break
    
    thread_id = str(session.langgraph_thread_id)
    config = services.tenant_runtime_config(org, thread_id)
    config["configurable"]["llm"] = services.get_tenant_llm(org)

    initial_state = {
        "repo_path": repo.repository_name,
        "file_path": target_file,
        "file_content": conflict_content,
        "original_code": conflict_content,
        "conflict_file_content": conflict_content,
        "repo_files": repo_map,
        "pr_description": f"Title: {pr_data['title']}\nDesc: {pr_data['description']}",
        "existing_test_path": existing_test_path,
        "existing_test_code": existing_test_code,
        "iteration_count": 0,
    }
    
    app = get_conflict_app()
    
    # Run Agent D -> Agent T -> pause before Executor
    for _ in app.stream(initial_state, config=config):
        pass
        
    snapshot = app.get_state(config)
    proposed_code = snapshot.values.get("refactored_code", "")
    
    gh.post_inline_pr_comment(
        pr_number, latest_sha, target_file,
        f"{BOT_MARKER}\n### Proposed Merge Resolution\n```python\n{proposed_code}\n```\n\nReply with `/commit_merge` to push this directly to the branch."
    )
    
    session.current_status = ReviewSession.Status.AWAITING_HUMAN
    session.save(update_fields=["current_status", "updated_at"])


# --------------------------------------------------------------------------- #
# Webhook Entry Points
# --------------------------------------------------------------------------- #

@shared_task(bind=True, max_retries=None)
def handle_pull_request(self, payload: dict):
    """Triggered on PR opened or synchronize."""
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
        return
    if not org.has_keys:
        return

    if services.at_capacity(repo):
        raise self.retry(countdown=CONCURRENCY_RETRY_DELAY)

    gh = services.build_connector(org, repo)
    
    # --- The Conflict Abort Switch ---
    if pr.get("mergeable") is False:
        gh.post_pr_comment(
            pr_number,
            f"{BOT_MARKER}\n🚨 **Merge Conflicts Detected.**\nI cannot perform a standard review. Reply with `/resolve` and I will attempt to autonomously merge the files and write tests to verify the resolution."
        )
        return
        
    _trigger_pr_fanout(gh, org, repo, pr_number, head_sha)


@shared_task
def process_file_review(session_id: int, org_id: int, repo_id: int):
    """Executes the Agents A -> B -> T loop for a single file concurrently."""
    session = ReviewSession.objects.get(id=session_id)
    org = OrganizationConfig.objects.get(id=org_id)
    repo = RepoSettings.objects.get(id=repo_id)
    
    gh = services.build_connector(org, repo)
    pr_number = session.pr_number
    filename = session.file_path

    try:
        pr_data = gh.get_pr_details(pr_number)
        repo_map = gh.get_repo_map(pr_data["files"], pr_data["head_branch"])
        
        content = repo_map.get(filename) or gh.get_file_content(
            filename, branch=pr_data["head_branch"]
        )
        
        # Test Discovery
        expected_test_name = f"test_{filename.split('/')[-1]}"
        alt_test_name = f"{filename.split('/')[-1].replace('.py', '')}_test.py"
        
        existing_test_path = None
        existing_test_code = None
        for filepath, f_content in repo_map.items():
            if filepath.endswith(expected_test_name) or filepath.endswith(alt_test_name):
                existing_test_path = filepath
                existing_test_code = f_content
                break

        llm_instance = services.get_tenant_llm(org)
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
            "existing_test_path": existing_test_path,
            "existing_test_code": existing_test_code,
        }
        config["configurable"]["llm"] = llm_instance
        app = get_app()
        
        # Runs reviewer -> refactorer -> test engineer, then pauses before executor_tool_node.
        for _ in app.stream(initial_state, config=config):
            pass

        _report_pause(gh, session, app, config, filename)

    except Exception as exc: 
        _handle_failure(gh, session, pr_number, exc)


# --------------------------------------------------------------------------- #
# Issue comment -> resume a paused review along a slash-command path
# --------------------------------------------------------------------------- #
@shared_task(bind=True)
def handle_review_comment(self, payload: dict):
    """Handles commands sent to INLINE review threads (e.g. /approve specific file or /resolve)."""
    if payload.get("action") != "created":
        return

    body = payload["comment"].get("body", "")
    if BOT_MARKER in body:
        return  
        
    cmd = parse_command(body)
    if cmd is None:
        return  

    installation_id = payload["installation"]["id"]
    repo_full_name = payload["repository"]["full_name"]
    pr_number = payload["pull_request"]["number"] 
    target_file = payload["comment"]["path"]      

    org, repo = services.resolve_tenant(installation_id, repo_full_name)
    if not org or not repo:
        return

    gh = services.build_connector(org, repo)

    # ----------------------------------------------------------------------- #
    # FRESH WORKFLOW: Resolve Merge Conflict
    # ----------------------------------------------------------------------- #
    if cmd.command == "resolve":
        _trigger_conflict_resolution(gh, org, repo, pr_number, target_file)
        return

    # ----------------------------------------------------------------------- #
    # RESUME WORKFLOW: Find the paused session for this specific file
    # ----------------------------------------------------------------------- #
    session = (
        ReviewSession.objects.filter(
            repo_settings=repo,
            pr_number=pr_number,
            file_path=target_file,
            current_status=ReviewSession.Status.AWAITING_HUMAN,
        )
        .order_by("-updated_at")
        .first()
    )
    
    if not session:
        return  

    try:
        latest_sha = gh.get_latest_commit_sha(pr_number)
    except Exception:  
        latest_sha = session.commit_sha
        
    if latest_sha != session.commit_sha:
        gh.post_inline_pr_comment(
            pr_number,
            latest_sha,
            target_file,
            f"{BOT_MARKER}\nThis command targets an outdated commit; a newer push has started a fresh review.",
        )
        return

    thread_id = str(session.langgraph_thread_id)
    config = services.tenant_runtime_config(org, thread_id)
    config["configurable"]["llm"] = services.get_tenant_llm(org)

    # Hybrid Approval Path (Agent D / Conflict Graph)
    if cmd.command == "commit_merge":
        app = get_conflict_app()
        snapshot = app.get_state(config)
        vals = snapshot.values
        pr_data = gh.get_pr_details(pr_number)
        
        # 1. Push the fixed code file
        gh.push_commit(
            pr_data["head_branch"], 
            vals["file_path"], 
            vals.get("refactored_code", ""), 
            f"RepoRover: Resolved merge conflict in {vals['file_path']}"
        )
        
        # 2. Strict Append Test Rule
        existing_test_path = vals.get("existing_test_path")
        if existing_test_path and vals.get("final_test_code"):
            gh.push_commit(
                pr_data["head_branch"], 
                existing_test_path, 
                vals["final_test_code"], 
                f"RepoRover: Updated tests for {vals['file_path']} conflict resolution"
            )
            
        gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nConflict resolved and successfully committed to the branch.")
        _complete(session)
        return

    # Standard Execution Path (Agent A->B->T Graph)
    app = get_app()
    snapshot = app.get_state(config)

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
                    "next_node": "refactorer_node",
                },
                as_node="executor_tool_node",
            )

        elif cmd.command == SKIP:
            app.update_state(
                config,
                {"execution_status": "SKIPPED_TO_DOCS", "execution_logs": "User skipped."},
                as_node="executor_tool_node",
            )

        for _ in app.stream(None, config=config):
            pass

        _report_pause(gh, session, app, config, target_file)

    except Exception as exc:  
        _handle_failure(gh, session, pr_number, exc)


@shared_task(bind=True)
def handle_issue_comment(self, payload: dict):
    """Handles commands sent to the global PR conversation thread."""
    if payload.get("action") != "created":
        return
        
    if "pull_request" not in payload.get("issue", {}):
        return  
        
    body = payload["comment"].get("body", "")
    if BOT_MARKER in body:
        return  

    cmd = parse_command(body)
    if cmd is None:
        return  

    installation_id = payload["installation"]["id"]
    repo_full_name = payload["repository"]["full_name"]
    pr_number = payload["issue"]["number"]

    org, repo = services.resolve_tenant(installation_id, repo_full_name)
    if not org or not repo:
        return

    gh = services.build_connector(org, repo)

    # ───────────────────────────────────────────────────────────────────
    # RESTORED: INTERCEPT AUTOMATED FRESH REVIEW TRIGGER
    # ───────────────────────────────────────────────────────────────────
    if cmd.command == "review":
        if services.at_capacity(repo):
            gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nRepo is currently at its concurrency capacity loop limit.")
            return

        latest_sha = gh.get_latest_commit_sha(pr_number)
        _trigger_pr_fanout(gh, org, repo, pr_number, latest_sha)
        return

    if cmd.command == "resolve":
        target_file = cmd.feedback.strip() if cmd.feedback else None
        if not target_file:
            gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nPlease provide the filename you wish to resolve, e.g., `/resolve src/utils.py`")
            return
            
        _trigger_conflict_resolution(gh, org, repo, pr_number, target_file)
        return


# --------------------------------------------------------------------------- #
# Shared reporting helpers
# --------------------------------------------------------------------------- #

def _report_pause(gh, session: ReviewSession, app, config, filename: str):
    """Inspect the graph: if finished, post final; if paused, post a new proposal inline."""
    snapshot = app.get_state(config)
    values = snapshot.values

    if not snapshot.next:
        gh.post_inline_pr_comment(
            session.pr_number,
            session.commit_sha,
            filename,
            render_final_comment(
                filename=filename,
                execution_status=values.get("execution_status", "UNKNOWN"),
                execution_logs=values.get("execution_logs", ""),
                documentation_diff=values.get("documentation_diff", ""),
            ),
        )
        _complete(session)
        return

    # Post an INLINE comment for the specific file
    gh.post_inline_pr_comment(
        session.pr_number,
        session.commit_sha,
        filename,
        render_review_comment(
            filename=filename,
            intent_summary=values.get("intent_summary", ""),
            review_issues=values.get("review_issues", []),
            refactored_code=values.get("refactored_code", ""),
            code_diff=values.get("code_diff", ""),
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
        except Exception:  
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