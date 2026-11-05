import unittest
from unittest.mock import patch

from config import env_flag, load_settings


class ConfigTests(unittest.TestCase):
    def test_env_flag_understands_common_values(self):
        with patch.dict("os.environ", {"FEATURE_FLAG": "yes"}):
            self.assertTrue(env_flag("FEATURE_FLAG"))

        with patch.dict("os.environ", {"FEATURE_FLAG": "off"}):
            self.assertFalse(env_flag("FEATURE_FLAG", True))

    def test_development_settings_are_isolated(self):
        environment = {
            "APP_ENV": "development",
            "DATABASE_URL": "postgresql://localhost/example_dev",
            "SECRET_KEY": "development-secret",
            "INITIALIZE_DATABASE": "false",
            "RUN_DB_MIGRATIONS": "true",
        }
        with patch.dict("os.environ", environment, clear=True):
            settings = load_settings()

        self.assertEqual(settings.app_env, "development")
        self.assertTrue(settings.database_url.endswith("example_dev"))
        self.assertFalse(settings.initialize_database)
        self.assertTrue(settings.run_db_migrations)


if __name__ == "__main__":
    unittest.main()
