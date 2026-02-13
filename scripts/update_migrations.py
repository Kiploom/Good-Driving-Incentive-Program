#!/usr/bin/env python3
"""
Update database migrations from current SQLAlchemy models.

Compares models in flask/app/models.py (the single consolidated models file)
with the database and generates a new migration script in migrations/versions/.

Run from project root (with venv activated and deps installed):
    python scripts/update_migrations.py
    python scripts/update_migrations.py -m "Add new column to Account"

Uses Flask-Migrate's autogenerate. Requires: venv activated, pip install -r requirements.txt,
database reachable (DB_* in flask/.env).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
FLASK_DIR = PROJECT_ROOT / "flask"


def main():
    parser = argparse.ArgumentParser(
        description="Generate a new migration from current SQLAlchemy models."
    )
    parser.add_argument(
        "-m",
        "--message",
        default="Auto-generated migration",
        help="Migration message/description",
    )
    args = parser.parse_args()

    if not (FLASK_DIR / "run.py").exists():
        print(f"[ERROR] Flask app not found at {FLASK_DIR}", file=sys.stderr)
        sys.exit(1)

    if not (PROJECT_ROOT / "migrations" / "env.py").exists():
        print("[ERROR] migrations/env.py not found. Migrations folder may be incomplete.", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    env["FLASK_APP"] = "run:app"

    cmd = ["flask", "db", "migrate", "-m", args.message]

    try:
        result = subprocess.run(
            cmd,
            cwd=str(FLASK_DIR),
            env=env,
            check=False,
        )
        if result.returncode != 0:
            sys.exit(result.returncode)
        print("\nMigration generated. Review migrations/versions/ before running 'flask db upgrade'.")
    except FileNotFoundError:
        print("[ERROR] 'flask' CLI not found. Activate your venv and run:", file=sys.stderr)
        print("  pip install flask-migrate", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
