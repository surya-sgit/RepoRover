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
    command: str            
    feedback: str = ""      

def parse_command(body: str) -> Optional[SlashCommand]:
    """Parse a PR comment body into a SlashCommand, or None if not a command.

    Ignores GitHub quote-replies (lines starting with '>') to ensure commands 
    typed at the bottom of a quote block are accurately recognized.
    """
    if not body:
        return None

    # 1. Normalize all weird line endings (Windows CRLF issues)
    body = body.replace('\r\n', '\n').replace('\r', '\n')

    # 2. Extract lines, strictly ignoring blockquotes and email reply headers
    valid_lines = []
    for line in body.split('\n'):
        stripped = line.strip()
        if stripped.startswith('>'):
            continue
        # Catch invisible email headers that GitHub sometimes injects
        if stripped.startswith('On ') and stripped.endswith('wrote:'):
            continue
        valid_lines.append(stripped)

    clean_text = '\n'.join(valid_lines).strip()
    
    if not clean_text:
        return None

    # 3. Bulletproof Regex: 
    # ^\s* -> allows invisible spaces before the slash
    # /([a-zA-Z_]+) -> captures the command word
    # (?:\s+(.*))? -> captures any optional feedback after the command
    match = re.search(r'^\s*/([a-zA-Z_]+)(?:\s+(.*))?', clean_text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    
    if match:
        cmd = match.group(1).lower()
        if cmd in VALID_COMMANDS:
            return SlashCommand(command=cmd, feedback=(match.group(2) or "").strip())

    return None