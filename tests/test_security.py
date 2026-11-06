import os
import unittest

from werkzeug.security import generate_password_hash

os.environ["DATABASE_URL"] = "postgresql://unused/test"
os.environ["SECRET_KEY"] = "test-only-secret"
os.environ["INITIALIZE_DATABASE"] = "false"

from app import (
    credential_matches,
    event_slug,
    parse_event_datetime,
    role_can_manage_events,
    valid_elevated_password,
)


class SecurityTests(unittest.TestCase):
    def test_elevated_password_requirements(self):
        self.assertTrue(valid_elevated_password("Clan7!"))
        self.assertFalse(valid_elevated_password("12345"))
        self.assertFalse(valid_elevated_password("password"))

    def test_hashed_and_legacy_credentials_remain_compatible(self):
        password = "Clan7!"
        self.assertTrue(
            credential_matches(generate_password_hash(password), password)
        )
        self.assertTrue(credential_matches("1234", "1234"))
        self.assertFalse(credential_matches("1234", "9999"))

    def test_only_owner_and_store_manager_can_manage_events(self):
        self.assertTrue(role_can_manage_events("owner"))
        self.assertTrue(role_can_manage_events("store_manager"))
        self.assertFalse(role_can_manage_events("admin"))
        self.assertFalse(role_can_manage_events("user"))

    def test_event_form_helpers(self):
        self.assertEqual(event_slug("Fourth Anniversary: The Vault!"), "fourth-anniversary-the-vault")
        self.assertIsNotNone(parse_event_datetime("2027-02-01T19:30"))
        self.assertIsNone(parse_event_datetime("not-a-date"))


if __name__ == "__main__":
    unittest.main()
