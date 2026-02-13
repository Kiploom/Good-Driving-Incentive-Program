# How to Start the App Locally

This guide covers running the Good-Driving-Incentive-Program Flask backend on your machine.

---

## Quick Start (Returning Users)

If you've already set up the app and just want to pull latest changes and run it:

```bash
git pull
source venv/bin/activate        # Linux/macOS
# venv/Scripts/activate  # Windows Bash
# .\venv\Scripts\Activate.ps1  # Windows PowerShell

pip install -r requirements.txt
cd flask && flask --app run:app db upgrade
python run.py
```

App runs at **http://localhost:5000**

---

## Full Setup (First-Time / New Users)

## Prerequisites

- **Python 3.10+** (3.11 recommended)
- **MySQL** 8.x (or access to a MySQL/MariaDB database)
- **Git**

## Step 1: Clone the Repository

```bash
git clone https://github.com/your-org/Good-Driving-Incentive-Program.git
cd Good-Driving-Incentive-Program
```

## Step 2: Create a Virtual Environment

```bash
# Create venv
python -m venv venv

# Activate (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Activate (Windows CMD)
.\venv\Scripts\activate.bat

# Activate (Linux/macOS)
source venv/bin/activate
```

## Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 4: Configure Environment Variables

Create a `.env` file in the `flask` directory:

```bash
# From project root (create empty file if it doesn't exist)
# Linux/macOS:
touch flask/.env

# Windows PowerShell:
New-Item flask\.env -ItemType File
```

Edit `flask/.env` and set the required variables (see table below). At minimum you need:

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_HOST` | MySQL host | `localhost` or your RDS host |
| `DB_USER` | Database user | `root` |
| `DB_PASSWORD` | Database password | `your_password` |
| `DB_NAME` | Database name | `gooddriver` |
| `DB_PORT` | MySQL port | `3306` |
| `SECRET_KEY` | Flask session secret | Random 32+ char string |
| `ENCRYPTION_KEY` | Fernet key for encrypted fields | Use `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

Optional but recommended for full functionality:

- `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_OAUTH_TOKEN`, `EBAY_MARKETPLACE_ID` – for eBay catalog
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET_NAME` – for profile images
- `ETHEREAL_MAIL_*` or `MAIL_*` – for email (verification, password reset)

## Step 5: Set Up the Database

1. Create the database:

```sql
CREATE DATABASE gooddriver CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. Run migrations:

```bash
cd flask
flask db upgrade
# Or, if FLASK_APP is not set:
flask --app run:app db upgrade
```

### Why run migrations?

Your Flask app uses SQLAlchemy models (e.g. `Account`, `Driver`, `DriverNotification`) that expect specific tables and columns in the database. The database schema does not update automatically when the code changes.

**Migrations** are versioned scripts that apply schema changes (create tables, add columns, etc.) to the database. When you run `flask db upgrade`:

- Pending migrations are applied in order
- New tables are created (e.g. `DriverNotification` for in-app notifications)
- New columns or indexes are added
- The database stays in sync with what the app expects

**When to run it:** After pulling new code (someone may have added migrations), when setting up a new database, or after cloning the repo. If the database is already up to date, the command simply reports that nothing needs to be done.

**Generating migrations:** After changing models, run `python scripts/update_migrations.py -m "Describe your change"` from project root. This creates a new migration in `migrations/versions/`. Review it, then run `flask db upgrade` to apply.

## Step 6: Start the Application

From the project root:

```bash
cd flask
python run.py
```

Or using Flask CLI:

```bash
cd flask
set FLASK_APP=run:app    # Windows CMD
$env:FLASK_APP="run:app" # Windows PowerShell
export FLASK_APP=run:app # Linux/macOS

flask run
```

The app will start at **http://localhost:5000** (or http://127.0.0.1:5000).

## Step 7: Create the First Admin User

If no admin exists yet, create one:

**Option A – Web signup:** Visit http://localhost:5000/admin and fill out the form.

**Option B – CLI:**

```bash
cd flask
flask --app run:app create-admin
```

Follow the prompts for email, username, password, etc.

## Summary

| Step | Command |
|------|---------|
| Activate venv | `.\venv\Scripts\Activate.ps1` (Windows) or `source venv/bin/activate` (Linux/macOS) |
| Install deps | `pip install -r requirements.txt` |
| Migrate DB | `cd flask && flask --app run:app db upgrade` |
| Start app | `cd flask && python run.py` |
| Create admin | `cd flask && flask --app run:app create-admin` |

## Troubleshooting

- **Database connection errors:** See [TROUBLESHOOTING_DB.md](TROUBLESHOOTING_DB.md)
- **Import errors:** Ensure you run commands from the `flask` directory or that `FLASK_APP=run:app` is set
- **Port in use:** Change port in `run.py` or use `flask run --port 5001`
