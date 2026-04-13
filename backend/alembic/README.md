# Alembic Migrations

Async Alembic setup wired to `backend.app.config.Settings.database_url`
(resolved via pydantic-settings from the `.env` / environment).

## Workflow

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Autogenerate a new migration from model changes
uv run alembic revision --autogenerate -m "describe change"

# Downgrade one step
uv run alembic downgrade -1

# Show current DB revision
uv run alembic current
```

Or via the project CLI (delegates to Alembic):

```bash
uv run python manage.py db upgrade
uv run python manage.py seed   # populate instruments + symbol_mappings
```

## Notes

- `env.py` uses `async_engine_from_config` and `asyncio.run(...)` — migrations run
  through an async connection against asyncpg.
- `target_metadata` is `backend.app.models.Base.metadata`; every model module must
  be imported in `backend/app/models/__init__.py` so autogenerate sees it.
- `price_history` is declared with `postgresql_partition_by = 'RANGE (timestamp)'`;
  autogenerate will not create partitions — migration `001_initial` creates the
  first three months of partitions explicitly.
- Immutability of `audit_log` is enforced by migration `002_audit_immutability`
  (trigger blocks UPDATE/DELETE + REVOKE on role `investiq_app`).
