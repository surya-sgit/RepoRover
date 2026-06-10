"""Chat-ops slash command parsing (PRD §3.6)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

APPROVE = "approve"
REJECT = "reject"
SKIP = "skip"
VALID_COMMANDS = (APPROVE, REJECT, SKIP)


@dataclass
class SlashCommand:
    command: str            # one of VALID_COMMANDS
    feedback: str = ""      # text following /reject


def parse_command(body: str) -> Optional[SlashCommand]:
    """Parse a PR comment body into a SlashCommand, or None if not a command.

    Recognises a command only when the comment *starts* with it (ignoring
    leading whitespace), e.g. ``/approve`` or ``/reject use a context manager``.
    """
    if not body:
        return None
    text = body.strip()
    if not text.startswith("/"):
        return None

    head, _, rest = text[1:].partition(" ")
    cmd = head.strip().lower()
    if cmd not in VALID_COMMANDS:
        return None
    return SlashCommand(command=cmd, feedback=rest.strip())
