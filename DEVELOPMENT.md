# Eternal Emporium development setup

Development must use a PostgreSQL database that is separate from Railway's
live database. Do not copy `.env` files, passwords, or production database URLs
between environments.

## Environment

1. Copy `.env.example` to `.env` locally, or add the same variables to a
   separate Railway development environment.
2. Replace `DATABASE_URL` with the development database URL.
3. Replace `SECRET_KEY` with a long, random value unique to development.
4. Leave `DISCORD_WEBHOOK_URL` empty so test purchases do not notify staff.

`INITIALIZE_DATABASE=true` permits startup database preparation.
`RUN_DB_MIGRATIONS=true` applies new files in `migrations/` once and records
their checksums in `schema_migrations`. Applied migration files must never be
edited; add a new numbered migration instead.

`LEGACY_SCHEMA_BOOTSTRAP=true` keeps the existing table setup working during
the migration transition. It will be removed only after the current schema is
fully represented by versioned migrations.

## Tests

Install development dependencies and run:

```sh
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The Phase 1 tests disable all database initialization and do not connect to
Railway or PostgreSQL.
