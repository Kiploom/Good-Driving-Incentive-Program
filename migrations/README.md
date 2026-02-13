# Database Migrations

Alembic migrations for the Good-Driving-Incentive-Program Flask app. Stored at project root for visibility outside the flask folder.

## Structure

- `env.py` – Alembic environment (uses Flask app context)
- `alembic.ini` – Alembic config
- `script.py.mako` – Template for new migration files
- `versions/` – Migration scripts (run in order by revision)

## Generate a new migration

After changing SQLAlchemy models, generate a migration:

```bash
python scripts/update_migrations.py
# or with a custom message:
python scripts/update_migrations.py -m "Add LockedUntil to Account"
```

This runs `flask db migrate` and writes a new file to `versions/`. **Review the generated file** before applying.

## Apply migrations

```bash
cd flask
flask --app run:app db upgrade
```

## Requirements

- Database must be reachable (DB_HOST, DB_USER, etc. in `flask/.env`)
- Run from project root; virtualenv should be activated

## Models location

All models live in a single file: `flask/app/models.py`. Section headers in that file guide where to add new models. Run `python scripts/update_migrations.py` after changing models.
