"""Chat-ops slash command parsing (PRD §3.6)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

APPROVE = "approve"
REJECT = "reject"
SKIP = "skip"
REVIEW = "review"
RESOLVE = "resolve"
COMMIT_MERGE = "commit_merge"

VALID_COMMANDS = (APPROVE, REJECT, SKIP, REVIEW, RESOLVE, COMMIT_MERGE)


@dataclass
class SlashCommand:
    command: str            # one of VALID_COMMANDS
    feedback: str = ""      # text following the command (e.g., /reject bad loop)


def parse_command(body: str) -> Optional[SlashCommand]:
    """Parse a PR comment body into a SlashCommand, or None if not a command.

    Ignores GitHub quote-replies (lines starting with '>') to ensure commands 
    typed at the bottom of a quote block are accurately recognized.
    """
    if not body:
        return None

    # 1. Strip out all GitHub quote lines
    clean_lines = [line.strip() for line in body.split('\n') if not line.strip().startswith('>')]
    clean_text = '\n'.join(clean_lines).strip()
    
    if not clean_text:
        return None

    # 2. Extract command using regex (matches /command at the start of the clean text)
    match = re.search(r'^/(\w+)(?:\s+(.*))?', clean_text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    
    if match:
        cmd = match.group(1).lower()
        if cmd in VALID_COMMANDS:
            return SlashCommand(command=cmd, feedback=(match.group(2) or "").strip())
            
    return None