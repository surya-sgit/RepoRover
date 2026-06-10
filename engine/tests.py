from django.test import SimpleTestCase

from engine.slash import parse_command, APPROVE, REJECT, SKIP
from engine.errors import (
    ProviderError,
    is_provider_error,
    extract_diagnostic,
    execution_paused_comment,
)
from engine.github_comments import sanitize, render_review_comment, render_final_comment


class SlashParserTests(SimpleTestCase):
    def test_approve(self):
        self.assertEqual(parse_command("/approve").command, APPROVE)

    def test_reject_with_feedback(self):
        cmd = parse_command("/reject use a context manager")
        self.assertEqual(cmd.command, REJECT)
        self.assertEqual(cmd.feedback, "use a context manager")

    def test_skip(self):
        self.assertEqual(parse_command("  /skip  ").command, SKIP)

    def test_non_command(self):
        self.assertIsNone(parse_command("lgtm"))
        self.assertIsNone(parse_command("/bogus"))
        self.assertIsNone(parse_command(""))


class ProviderErrorTests(SimpleTestCase):
    def test_classification(self):
        self.assertTrue(is_provider_error(Exception("429 rate limit")))
        self.assertTrue(is_provider_error(Exception("API key not valid")))
        self.assertFalse(is_provider_error(Exception("NameError: x")))

    def test_diagnostic_extraction(self):
        self.assertIn("401", extract_diagnostic(Exception("401 Unauthorized")))

    def test_paused_comment(self):
        body = execution_paused_comment("403: quota exceeded")
        self.assertIn("Execution Paused", body)
        self.assertIn("403: quota exceeded", body)

    def test_provider_error_carries_diagnostic(self):
        err = ProviderError("boom", diagnostic="429: too many")
        self.assertEqual(err.diagnostic, "429: too many")


class CommentRenderingTests(SimpleTestCase):
    def test_sanitize_neutralizes_fences_and_mentions(self):
        out = sanitize("```evil @user #1")
        self.assertNotIn("```", out)
        self.assertNotIn("@user", out)

    def test_review_comment_contains_commands(self):
        body = render_review_comment(
            filename="main.py",
            intent_summary="does things",
            review_issues=[{"severity": "Critical", "line_number": 3,
                            "description": "bug", "suggestion": "fix"}],
            refactored_code="print('hi')",
            iteration=0,
        )
        self.assertIn("/approve", body)
        self.assertIn("Critical", body)

    def test_final_comment_shows_status(self):
        body = render_final_comment("main.py", "SUCCESS", "ran ok", "## Docs")
        self.assertIn("SUCCESS", body)
        self.assertIn("Docs", body)
