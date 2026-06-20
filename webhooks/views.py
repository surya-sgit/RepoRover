"""GitHub webhook intake (PRD §3.3).

A single endpoint that must, within GitHub's 10-second delivery budget:
  1. Verify the HMAC-SHA256 payload signature.
  2. Accept only ``pull_request`` (opened/synchronize) and ``issue_comment``
     / ``pull_request_review_comment`` (created) events.
  3. Enqueue the work onto Celery (Redis) and return HTTP 200 immediately.

No hydration, LLM, or sandbox work happens inline.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from engine.slash import parse_command
from engine.tasks import handle_pull_request, handle_issue_comment

logger = logging.getLogger(__name__)


def _signature_valid(secret: str, body: bytes, header: str) -> bool:
    """Constant-time verification of the X-Hub-Signature-256 header."""
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


@csrf_exempt
@require_POST
def github_webhook(request):
    secret = settings.GITHUB_WEBHOOK_SECRET
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not secret or not _signature_valid(secret, request.body, signature):
        return HttpResponse("Invalid signature", status=401)

    event = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("Malformed JSON payload")

    action = payload.get("action", "unknown")
    
    # ---------------------------------------------------------
    # DIAGNOSTIC TRAP: Log all incoming events explicitly
    # ---------------------------------------------------------
    if event in ("issue_comment", "pull_request_review_comment"):
        print(f"\n--- INCOMING WEBHOOK: {event} | ACTION: {action} ---")

    # Handles Fresh PR Opens/Syncs
    if event == "pull_request" and action in ("opened", "synchronize"):
        handle_pull_request.delay(payload)
        return JsonResponse({"status": "queued", "event": "pull_request"})

    # Handles general PR timeline conversation entries (Global / Fallbacks)
    if event == "issue_comment" and action == "created":
        body = payload.get("comment", {}).get("body", "")
        is_pr = "pull_request" in payload.get("issue", {})
        cmd = parse_command(body)
        
        print(f"[Issue Comment Check] Is PR: {is_pr} | Parsed Command: {cmd}")
        
        if is_pr and cmd is not None:
            handle_issue_comment.delay(payload)
            return JsonResponse({"status": "queued", "event": "issue_comment"})
            
        return JsonResponse({"status": "ignored", "reason": f"is_pr={is_pr}, cmd={cmd}"})

    # Handles INLINE file-specific review comments (Granular)
    if event == "pull_request_review_comment" and action == "created":
        body = payload.get("comment", {}).get("body", "")
        cmd = parse_command(body)
        
        print(f"[Inline Comment Check] Parsed Command: {cmd}")
        
        if cmd is not None:
            handle_issue_comment.delay(payload)
            return JsonResponse({"status": "queued", "event": "pull_request_review_comment"})
            
        return JsonResponse({"status": "ignored", "reason": f"cmd={cmd}"})

    return JsonResponse({"status": "ignored", "event": event})