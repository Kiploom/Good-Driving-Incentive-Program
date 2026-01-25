"""
CLI commands for app management (e.g. create first admin).
Run from project root: flask --app run:app create-admin
Or, with FLASK_APP=run:app: flask create-admin
"""

import click
from . import db
from .models import AccountType, Account, Admin
from .services.password_security_service import PasswordSecurityService


def _get_account_type_id(code: str) -> str:
    """Resolve AccountTypeID for ADMIN, creating the type if missing."""
    at = AccountType.query.filter_by(AccountTypeCode=code).first()
    if not at:
        at = AccountType(AccountTypeCode=code, DisplayName=code.title())
        db.session.add(at)
        db.session.flush()
    return at.AccountTypeID


@click.command("create-admin")
def create_admin_cmd():
    """Create the first admin user (when no admins exist yet)."""
    existing = Admin.query.first()
    if existing:
        click.echo("An admin already exists. Use the web signup at /admin or log in as admin and use /admin/create-admin.")
        raise SystemExit(1)

    click.echo("Create the first admin user.\n")

    email = click.prompt("Email", type=str)
    username = click.prompt("Username", type=str)
    password = click.prompt("Password", type=str, hide_input=True, confirmation_prompt=True)
    first_name = click.prompt("First name", type=str)
    last_name = click.prompt("Last name", type=str)
    role = click.prompt("Role (optional, default: Admin)", type=str, default="Admin", show_default=False)
    role = (role or "").strip() or "Admin"

    is_strong, err = PasswordSecurityService.is_password_strong(password)
    if not is_strong:
        click.echo(f"Password validation failed: {err}")
        raise SystemExit(1)

    email = email.strip().lower()
    username = username.strip()
    if not email or not username:
        click.echo("Email and username are required.")
        raise SystemExit(1)

    dup = Account.query.filter((Account.Email == email) | (Account.Username == username)).first()
    if dup:
        click.echo(f"An account with that email or username already exists (AccountID={dup.AccountID}).")
        raise SystemExit(1)

    try:
        acc = Account(
            AccountType="ADMIN",
            AccountTypeID=_get_account_type_id("ADMIN"),
            Username=username,
            Email=email,
            Phone=None,
            PasswordHash=PasswordSecurityService.hash_password(password),
            FirstName=first_name.strip(),
            LastName=last_name.strip(),
            WholeName=f"{first_name.strip()} {last_name.strip()}".strip(),
            Status="A",
        )
        db.session.add(acc)
        db.session.flush()

        ad = Admin(AccountID=acc.AccountID, Role=role)
        db.session.add(ad)

        PasswordSecurityService.log_password_change(
            account_id=acc.AccountID,
            new_password_hash=acc.PasswordHash,
            change_reason="cli_create_admin",
            ip_address=None,
            user_agent="flask create-admin",
        )

        db.session.commit()
        click.echo(f"Admin created successfully. AccountID={acc.AccountID}, AdminID={ad.AdminID}.")
        click.echo("You can log in at the login page with this email/username and password.")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error creating admin: {e}")
        raise SystemExit(1)
