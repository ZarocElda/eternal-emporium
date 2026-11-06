import os
import unittest

from werkzeug.security import generate_password_hash

os.environ["DATABASE_URL"] = "postgresql://unused/test"
os.environ["SECRET_KEY"] = "test-only-secret"
os.environ["INITIALIZE_DATABASE"] = "false"

from app import (
    build_puzzle_configuration,
    credential_matches,
    event_slug,
    nonempty_lines,
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

    def test_puzzle_configuration_helpers(self):
        self.assertEqual(nonempty_lines(" first\n\n second "), ["first", "second"])
        puzzle_type, content, solution, hints = build_puzzle_configuration({
            "puzzle_type": "trivia",
            "instructions": "Choose carefully",
            "options": "A\nB\nC",
            "accepted_answers": "B\noption b",
            "hidden_location": "",
            "hint_1": "Look at the middle choice",
            "hint_2": "",
            "hint_3": "The answer is B",
        })
        self.assertEqual(puzzle_type, "trivia")
        self.assertEqual(content["options"], ["A", "B", "C"])
        self.assertEqual(solution["accepted_answers"], ["B", "option b"])
        self.assertEqual(len(hints), 2)

    def test_hotspot_configuration_validation(self):
        puzzle_type, _, solution, _ = build_puzzle_configuration({
            "puzzle_type": "image_hotspot",
            "instructions": "",
            "options": "",
            "hidden_location": "",
            "hotspot_x": "42.5",
            "hotspot_y": "63",
            "hotspot_radius": "9",
            "hint_1": "",
            "hint_2": "",
            "hint_3": "",
        })
        self.assertEqual(puzzle_type, "image_hotspot")
        self.assertEqual(solution["hotspot"]["x"], 42.5)
        with self.assertRaises(ValueError):
            build_puzzle_configuration({
                "puzzle_type": "image_hotspot", "instructions": "",
                "options": "", "hidden_location": "", "hotspot_x": "101",
                "hotspot_y": "20", "hotspot_radius": "8",
                "hint_1": "", "hint_2": "", "hint_3": "",
            })


if __name__ == "__main__":
    unittest.main()
