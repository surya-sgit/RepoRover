import hashlib
import hmac
import json
from unittest import mock

from django.test import SimpleTestCase, RequestFactory, override_settings

from webhooks.views import github_webhook, _signature_valid

SECRET = "test-webhook-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@override_settings(GITHUB_WEBHOOK_SECRET=SECRET)
class WebhookSignatureTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _post(self, payload, event, sign=True):
        body = json.dumps(payload).encode()
        headers = {"X-GitHub-Event": event}
        if sign:
            headers["X-Hub-Signature-256"] = _sign(body)
        return self.factory.post(
            "/webhooks/github/",
            data=body,
            content_type="application/json",
            headers=headers,
        )

    def test_signature_helper(self):
        body = b'{"a":1}'
        self.assertTrue(_signature_valid(SECRET, body, _sign(body)))
        self.assertFalse(_signature_valid(SECRET, body, "sha256=deadbeef"))
        self.assertFalse(_signature_valid(SECRET, body, ""))

    def test_rejects_bad_signature(self):
        req = self._post({"action": "opened"}, "pull_request", sign=False)
        resp = github_webhook(req)
        self.assertEqual(resp.status_code, 401)

    @mock.patch("webhooks.views.handle_pull_request")
    def test_enqueues_pull_request(self, task):
        payload = {"action": "opened", "pull_request": {"number": 1}}
        resp = github_webhook(self._post(payload, "pull_request"))
        self.assertEqual(resp.status_code, 200)
        task.delay.assert_called_once()

    @mock.patch("webhooks.views.handle_pull_request")
    def test_ignores_unsupported_pr_action(self, task):
        payload = {"action": "closed", "pull_request": {"number": 1}}
        resp = github_webhook(self._post(payload, "pull_request"))
        self.assertEqual(resp.status_code, 200)
        task.delay.assert_not_called()

    @mock.patch("webhooks.views.handle_issue_comment")
    def test_enqueues_slash_command_comment(self, task):
        payload = {
            "action": "created",
            "issue": {"number": 7, "pull_request": {"url": "x"}},
            "comment": {"body": "/approve"},
        }
        resp = github_webhook(self._post(payload, "issue_comment"))
        self.assertEqual(resp.status_code, 200)
        task.delay.assert_called_once()

    @mock.patch("webhooks.views.handle_issue_comment")
    def test_ignores_non_command_comment(self, task):
        payload = {
            "action": "created",
            "issue": {"number": 7, "pull_request": {"url": "x"}},
            "comment": {"body": "looks good to me"},
        }
        resp = github_webhook(self._post(payload, "issue_comment"))
        self.assertEqual(resp.status_code, 200)
        task.delay.assert_not_called()
