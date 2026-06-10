"""GitHub webhook intake (PRD §3.3).

A single endpoint that must, within GitHub's 10-second delivery budget:
  1. Verify the HMAC-SHA256 payload signature.
  2. Accept only ``pull_request`` (opened/synchronize) and ``issue_comment``
     (created) events.
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

    # 1. Authenticate the payload before trusting any of it.
    if not secret or not _signature_valid(secret, request.body, signature):
        return HttpResponse("Invalid signature", status=401)

    event = request.headers.get("X-GitHub-Event", "")
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("Malformed JSON payload")

    # 2. Filter to the two supported events; everything else is acknowledged
    #    and dropped (a 200 keeps GitHub from retrying).
    if event == "pull_request" and payload.get("action") in ("opened", "synchronize"):
        handle_pull_request.delay(payload)
        return JsonResponse({"status": "queued", "event": "pull_request"})

    if event == "issue_comment" and payload.get("action") == "created":
        # Only enqueue if the comment is one of our slash commands and is on a PR.
        body = payload.get("comment", {}).get("body", "")
        is_pr = "pull_request" in payload.get("issue", {})
        if is_pr and parse_command(body) is not None:
            handle_issue_comment.delay(payload)
            return JsonResponse({"status": "queued", "event": "issue_comment"})
        return JsonResponse({"status": "ignored", "reason": "not a command"})

    # 3. Acknowledge unsupported events without doing work.
    return JsonResponse({"status": "ignored", "event": event})
