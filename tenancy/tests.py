from cryptography.fernet import Fernet

from django.test import SimpleTestCase, TestCase, override_settings

from tenancy.crypto import encrypt_key, decrypt_key, VaultError
from tenancy.models import OrganizationConfig, RepoSettings, ReviewSession

_KEY = Fernet.generate_key().decode()


@override_settings(FERNET_KEY=_KEY)
class CryptoTests(SimpleTestCase):
    def test_round_trip(self):
        ct = encrypt_key("e2b_secret_123")
        self.assertIsInstance(ct, bytes)
        self.assertEqual(decrypt_key(ct), "e2b_secret_123")

    def test_round_trip_memoryview(self):
        ct = encrypt_key("gem_key")
        self.assertEqual(decrypt_key(memoryview(ct)), "gem_key")

    def test_wrong_key_fails(self):
        ct = encrypt_key("secret")
        with override_settings(FERNET_KEY=Fernet.generate_key().decode()):
            with self.assertRaises(VaultError):
                decrypt_key(ct)


@override_settings(FERNET_KEY=_KEY)
class ConcurrencyModelTests(TestCase):
    def setUp(self):
        self.org = OrganizationConfig.objects.create(github_installation_id=1)
        self.repo = RepoSettings.objects.create(
            org_config=self.org, repository_name="o/r", max_concurrency=2
        )

    def _session(self, status):
        return ReviewSession.objects.create(
            repo_settings=self.repo, pr_number=1, commit_sha="abc",
            current_status=status,
        )

    def test_active_statuses_count_toward_cap(self):
        from engine.services import active_session_count, at_capacity

        self._session(ReviewSession.Status.ANALYZING)
        self.assertEqual(active_session_count(self.repo), 1)
        self.assertFalse(at_capacity(self.repo))

        self._session(ReviewSession.Status.EXECUTING)
        self.assertEqual(active_session_count(self.repo), 2)
        self.assertTrue(at_capacity(self.repo))

    def test_awaiting_and_completed_free_the_slot(self):
        from engine.services import active_session_count

        self._session(ReviewSession.Status.AWAITING_HUMAN)
        self._session(ReviewSession.Status.COMPLETED)
        self.assertEqual(active_session_count(self.repo), 0)

    def test_key_vault_helpers(self):
        self.org.set_gemini_key("g-key")
        self.org.set_e2b_key("e-key")
        self.org.save()
        self.org.refresh_from_db()
        self.assertTrue(self.org.has_keys)
        self.assertEqual(self.org.get_gemini_key(), "g-key")
        self.assertEqual(self.org.get_e2b_key(), "e-key")
