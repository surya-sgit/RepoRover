"""PR comment rendering for RepoRover (PRD §3.5, §6.2).

Agent A operates under structured output, but its strings still originate from
arbitrary commit content, so everything is sanitised before being assembled into
GitHub markdown. We neutralise comment-injection vectors (stray code fences,
hidden HTML, @mentions that would ping users) and bound length.
"""
from __future__ import annotations

import html
from typing import List

MAX_FIELD_LEN = 2000
BOT_MARKER = "<!-- reporover-bot -->"  # lets us detect our own comments


def sanitize(text: str, limit: int = MAX_FIELD_LEN) -> str:
    """Defang model/commit-derived text before embedding it in markdown."""
    if text is None:
        return ""
    text = str(text)
    # Strip triple backticks so model text can't break out of our fences.
    text = text.replace("```", "ʼʼʼ")
    # Escape HTML so embedded tags don't render / inject.
    text = html.escape(text, quote=False)
    # Avoid accidental @mentions / #refs pinging people.
    text = text.replace("@", "@​").replace("#", "#​")
    if len(text) > limit:
        text = text[:limit] + "…(truncated)"
    return text


def render_review_comment(
    filename: str,
    intent_summary: str,
    review_issues: List[dict],
    refactored_code: str,
    iteration: int = 0,
) -> str:
    """Intermediate comment: Agent A findings + Agent B proposed patch (PRD §3.5)."""
    lines = [BOT_MARKER, f"## 🤖 RepoRover Review — `{sanitize(filename, 200)}`"]
    if iteration > 0:
        lines.append(f"_Revision attempt #{iteration + 1}._")

    lines.append("")
    lines.append("### Summary")
    lines.append(sanitize(intent_summary))
    lines.append("")

    lines.append("### Issues Found")
    if review_issues:
        for issue in review_issues:
            sev = sanitize(issue.get("severity", "Info"), 20)
            line_no = issue.get("line_number", "?")
            desc = sanitize(issue.get("description", ""), 500)
            sugg = sanitize(issue.get("suggestion", ""), 500)
            lines.append(f"- **[{sev}] line {line_no}** — {desc} _Fix:_ {sugg}")
    else:
        lines.append("_No blocking issues detected._")
    lines.append("")

    lines.append("### Proposed Refactor")
    code = (refactored_code or "").replace("```", "ʼʼʼ")
    if len(code) > 8000:
        code = code[:8000] + "\n# …(truncated)"
    lines.append("```python")
    lines.append(code)
    lines.append("```")
    lines.append("")

    lines.append("---")
    lines.append(
        "**Reply with a command:** `/approve` to run in the sandbox · "
        "`/reject <feedback>` to revise · `/skip` to document without running."
    )
    return "\n".join(lines)


def render_final_comment(
    filename: str,
    execution_status: str,
    execution_logs: str,
    documentation_diff: str,
) -> str:
    """Final comment after sandbox verification / docs generation (PRD §3.5)."""
    status_icon = "✅" if execution_status == "SUCCESS" else "⚠️"
    lines = [
        BOT_MARKER,
        f"## {status_icon} RepoRover Result — `{sanitize(filename, 200)}`",
        "",
        f"**Sandbox status:** `{sanitize(execution_status, 40)}`",
        "",
        "<details><summary>Execution log</summary>",
        "",
        "```",
        (execution_logs or "").replace("```", "ʼʼʼ")[:4000],
        "```",
        "",
        "</details>",
        "",
        "### Documentation Update",
        sanitize(documentation_diff, 6000),
    ]
    return "\n".join(lines)
