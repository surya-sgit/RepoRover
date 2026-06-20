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
import re
import logging

from celery import shared_task
from django.db import transaction
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
            file_path=target_file["filename"],
            commit_sha=head_sha,
            current_status=ReviewSession.Status.ANALYZING,
            active_jobs=1,
        )
        process_file_review.delay(session.id)


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


@shared_task(bind=True)
def process_file_review(self, session_id: int, command: str = None, feedback: str = None):
    """Executes or Resumes the Agents A -> B -> T loop for a single file context."""
    session = ReviewSession.objects.select_related('repo_settings__org_config').get(id=session_id)
    repo = session.repo_settings
    org = repo.org_config
    
    gh = services.build_connector(org, repo)
    pr_number = session.pr_number
    filename = session.file_path

    try:
        llm_instance = services.get_tenant_llm(org)
        thread_id = str(session.langgraph_thread_id)
        config = services.tenant_runtime_config(org, thread_id)
        config["configurable"]["llm"] = llm_instance
        
        # Determine active graph deployment mapping
        if command == "commit_merge":
            app = get_conflict_app()
        else:
            app = get_app()

        # ===================================================================
        # PHASE 1: INITIAL PAUSE TRIGGER (Fresh Review)
        # ===================================================================
        # If command is None (from fanout) or "review"
        if command in (None, "review"):
            pr_data = gh.get_pr_details(pr_number)
            repo_map = gh.get_repo_map(pr_data["files"], pr_data["head_branch"])
            content = repo_map.get(filename) or gh.get_file_content(filename, branch=pr_data["head_branch"])
            
            expected_test_name = f"test_{filename.split('/')[-1]}"
            alt_test_name = f"{filename.split('/')[-1].replace('.py', '')}_test.py"
            
            existing_test_path, existing_test_code = None, None
            for filepath, f_content in repo_map.items():
                if filepath.endswith(expected_test_name) or filepath.endswith(alt_test_name):
                    existing_test_path = filepath
                    existing_test_code = f_content
                    break

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
            
            for _ in app.stream(initial_state, config=config): pass
            _report_pause(gh, session, app, config, filename)
            
            # CRITICAL: Return here so it does not fall into Phase 2
            return

        # ===================================================================
        # PHASE 2: RESUME GRAPH WORKFLOWS (Approve/Reject/Skip Engine)
        # ===================================================================
        snapshot = app.get_state(config)

        if command == "commit_merge":
            vals = snapshot.values
            pr_data = gh.get_pr_details(pr_number)
            
            gh.push_commit(
                pr_data["head_branch"], vals["file_path"], vals.get("refactored_code", ""), 
                f"RepoRover: Resolved merge conflict in {vals['file_path']}"
            )
            
            if vals.get("existing_test_path") and vals.get("final_test_code"):
                gh.push_commit(
                    pr_data["head_branch"], vals["existing_test_path"], vals["final_test_code"], 
                    f"RepoRover: Updated tests for {vals['file_path']} conflict resolution"
                )
                
            gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nConflict resolved and successfully committed to the branch.")
            session.current_status = 'COMPLETED'
            session.save(update_fields=["current_status", "updated_at"])
            return

        elif command == "approve":
            # State implementation for entering E2B Sandbox node loop
            app.update_state(config, {"execution_status": "APPROVED"}, as_node="executor_tool_node")

        elif command == "reject":
            app.update_state(
                config,
                {
                    "execution_status": "FAILURE",
                    "execution_logs": f"HUMAN REJECTION: {feedback}",
                    "iteration_count": snapshot.values.get("iteration_count", 0),
                    "next_node": "refactorer_node",
                },
                as_node="executor_tool_node",
            )

        elif command == "skip":
            app.update_state(
                config,
                {"execution_status": "SKIPPED_TO_DOCS", "execution_logs": "User skipped."},
                as_node="executor_tool_node",
            )

        # Stream resumption through the rest of the node graph steps
        for _ in app.stream(None, config=config): pass

        # Re-evaluate final state status context
        updated_snapshot = app.get_state(config)
        if updated_snapshot.values.get("next_node") == "refactorer_node" or updated_snapshot.next:
            session.current_status = 'AWAITING_HUMAN'
            session.save(update_fields=["current_status", "updated_at"])
            _report_pause(gh, session, app, config, filename)
        else:
            session.current_status = 'COMPLETED'
            session.save(update_fields=["current_status", "updated_at"])

    except Exception as exc: 
        _handle_failure(gh, session, pr_number, exc)

# --------------------------------------------------------------------------- #
# Issue comment -> resume a paused review along a slash-command path
# --------------------------------------------------------------------------- #

def parse_command(body: str):
    """
    Parses commands while ignoring GitHub quote-replies (lines starting with '>').
    Returns a tuple of (command_name, feedback_string).
    """
    clean_lines = [line.strip() for line in body.split('\n') if not line.strip().startswith('>')]
    clean_text = '\n'.join(clean_lines).strip()
    
    if not clean_text:
        return None, None
        
    match = re.search(r'^/(approve|reject|resolve|skip|commit_merge|review)(?:\s+(.*))?', clean_text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    if match:
        return match.group(1).lower(), (match.group(2) or "").strip()
    return None, None

@shared_task(bind=True)
def handle_issue_comment(self, payload: dict):
    """Unified handler for both global PR timeline comments and inline review threads."""
    if payload.get("action") != "created":
        return
        
    pr_number = payload.get("issue", {}).get("number") or payload.get("pull_request", {}).get("number")
    if not pr_number:
        return
        
    body = payload["comment"].get("body", "")
    
    # Ignore webhooks triggered by bots/apps to prevent infinite loops
    sender_type = payload.get("sender", {}).get("type", "")
    if sender_type == "Bot":
        return  

    cmd_name, feedback = parse_command(body)
    
    # --- TEMPORARY DEBUGGING PRINT ---
    print(f"DEBUG: Extracted Command -> {cmd_name} | Feedback -> {feedback}")
    if not cmd_name:
        return  

    installation_id = payload["installation"]["id"]
    repo_full_name = payload["repository"]["full_name"]

    org, repo = services.resolve_tenant(installation_id, repo_full_name)
    if not org or not repo:
        return

    gh = services.build_connector(org, repo)

    # 1. Context Scoping
    is_inline = "comment" in payload and "path" in payload["comment"]
    inline_file = payload["comment"]["path"] if is_inline else None

    # 2. Handle Fresh Workflow Intercepts First
    if cmd_name == "review":
        if services.at_capacity(repo):
            gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nRepo is currently at concurrency loop capacity limit.")
            return
        latest_sha = gh.get_latest_commit_sha(pr_number)
        _trigger_pr_fanout(gh, org, repo, pr_number, latest_sha)
        return

    if cmd_name == "resolve":
        target = inline_file or (feedback.strip() if feedback else None)
        if not target:
            gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nPlease specify a filename: `/resolve path/to/file.py`")
            return
        _trigger_conflict_resolution(gh, org, repo, pr_number, target)
        return

    # Guard Rails against Global Conflict Commits
    if cmd_name == "commit_merge" and not is_inline:
        gh.post_pr_comment(pr_number, f"{BOT_MARKER}\nThe `/commit_merge` command must be executed directly inside an inline conflict thread.")
        return

    # 3. Target Pending Sessions
    if is_inline:
        sessions = ReviewSession.objects.filter(
            repo_settings=repo, pr_number=pr_number, file_path=inline_file, current_status='AWAITING_HUMAN'
        )
    else:
        sessions = ReviewSession.objects.filter(
            repo_settings=repo, pr_number=pr_number, current_status='AWAITING_HUMAN'
        )

    if not sessions.exists():
        return

    # 4. Enforce Stale Commit Check Across All Target Sessions
    try:
        latest_sha = gh.get_latest_commit_sha(pr_number)
    except Exception:
        latest_sha = None

    for s in sessions:
        if latest_sha and latest_sha != s.commit_sha:
            msg = f"{BOT_MARKER}\nCommand rejected for `{s.file_path}`. This session targets an outdated commit."
            if is_inline:
                gh.post_inline_pr_comment(pr_number, latest_sha, inline_file, msg)
            else:
                gh.post_pr_comment(pr_number, msg)
            return

    session_count = sessions.count()

    # 5. Enforce Global Rejection Feedback Rule
    if cmd_name == "reject" and not is_inline and session_count > 1:
        feedback_lines = [line for line in feedback.split('\n') if line.strip()]
        if len(feedback_lines) < session_count:
            gh.post_pr_comment(
                pr_number, 
                f"{BOT_MARKER}\nYou are globally rejecting {session_count} files. Please provide separate reasons for rejection for each file (one per line), or reply directly to their inline threads."
            )
            return

    # 6. Process Valid Sessions Loop
    # Perform a single bulk database update to avoid gevent socket collisions
    sessions.update(current_status='EXECUTING')

    # Now dispatch the Celery tasks in memory
    for idx, s in enumerate(sessions):
        # Distribute parsed feedback if bulk rejecting
        current_feedback = feedback
        if cmd_name == "reject" and not is_inline and session_count > 1:
            current_feedback = feedback_lines[idx]

        # Route to execution engine
        process_file_review.delay(s.id, command=cmd_name, feedback=current_feedback)
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