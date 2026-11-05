import os
import warnings
from dataclasses import dataclass
from typing import Optional


LEGACY_SECRET_KEY = "supersecretkey"


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppSettings:
    app_env: str
    database_url: Optional[str]
    secret_key: str
    initialize_database: bool
    run_db_migrations: bool
    legacy_schema_bootstrap: bool


def load_settings():
    app_env = os.getenv("APP_ENV", "production").strip().lower()
    secret_key = os.getenv("SECRET_KEY")

    if not secret_key:
        secret_key = LEGACY_SECRET_KEY
        warnings.warn(
            "SECRET_KEY is not set. Using the legacy key for compatibility; "
            "set a strong SECRET_KEY in every Railway environment.",
            RuntimeWarning,
            stacklevel=2,
        )

    return AppSettings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL"),
        secret_key=secret_key,
        initialize_database=env_flag("INITIALIZE_DATABASE", True),
        run_db_migrations=env_flag("RUN_DB_MIGRATIONS", False),
        legacy_schema_bootstrap=env_flag("LEGACY_SCHEMA_BOOTSTRAP", True),
    )
