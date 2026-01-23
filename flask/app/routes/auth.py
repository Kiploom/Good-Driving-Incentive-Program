from flask import (
    Blueprint, request, jsonify, render_template,
    redirect, url_for, flash, session, current_app
)
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, SelectField,
    IntegerField, BooleanField
)
from wtforms.validators import (
    DataRequired, Email, Length, Regexp, Optional,
    NumberRange, ValidationError
)
from sqlalchemy.exc import IntegrityError
from app.extensions import db, bcrypt, mail
from app.models import (
    Account,
    Sponsor,
    SponsorCompany,
    Driver,
    Admin,
    LoginAttempts,
    EmailVerification,
    DriverSponsor,
    AccountType,
    AdminNotificationPreferences,
    Application,
)
from app.services.notification_service import NotificationService
from app.services.password_security_service import PasswordSecurityService
from app.services.session_management_service import SessionManagementService
from app.utils.sponsor_selection import select_primary_sponsor_for_company
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask_mail import Message
import uuid
import pyotp
from config import fernet

# ****************************************************
# ***** NEW IMPORTS FOR RECOVERY CODES (STORY 4) *****
# ****************************************************
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

bp = Blueprint("auth", __name__)

# ==============================
# HELPER FUNCTIONS
# ==============================

def _send_verification_email(recipient: str, subject: str, body: str) -> bool:
    """Send a verification email using the same transport as the forgot-password flow."""
    if not recipient:
        return False

    sender = (
        current_app.config.get("MAIL_DEFAULT_SENDER")
        or current_app.config.get("MAIL_USERNAME")
        or "no-reply@team10.local"
    )

    try:
        msg = Message(
            subject=subject,
            recipients=[recipient],
            body=body,
            sender=sender,
        )
        mail.send(msg)
        return True
    except Exception as exc:
        current_app.logger.exception("Failed to send verification email to %s: %s", recipient, exc)
        return False


def _ensure_account_type_id(code: str) -> str:
    """Fetch or create the AccountType row for the provided code."""
    normalized = (code or "").strip().upper()
    if normalized not in {"DRIVER", "SPONSOR", "ADMIN"}:
        raise ValueError(f"Unsupported account type code '{code}'")

    at = AccountType.query.filter_by(AccountTypeCode=normalized).first()
    if at:
        return at.AccountTypeID

    at = AccountType(AccountTypeCode=normalized, DisplayName=normalized.title())
    db.session.add(at)
    db.session.flush()
    return at.AccountTypeID


class DriverRegistrationForm(FlaskForm):
    """Registration form used for driver sign up via login register button."""

    first_name = StringField(
        "First Name",
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(r"^[a-zA-Z\s'-]+$", message="First name can only contain letters, spaces, hyphens, and apostrophes"),
        ],
    )
    last_name = StringField(
        "Last Name",
        validators=[
            DataRequired(),
            Length(min=1, max=100),
            Regexp(r"^[a-zA-Z\s'-]+$", message="Last name can only contain letters, spaces, hyphens, and apostrophes"),
        ],
    )
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=50),
            Regexp(r"^[a-zA-Z0-9_-]+$", message="Username can only contain letters, numbers, underscores, and hyphens"),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(min=8, max=128),
            Regexp(
                r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>]).*$",
                message="Password must include upper, lower, number, and special character",
            ),
        ],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    phone = StringField(
        "Phone",
        validators=[
            Optional(),
            Length(max=20),
            Regexp(r"^[\d\s\-\+\(\)]+$", message="Phone number contains invalid characters"),
        ],
    )
    sponsor_company_id = SelectField("Sponsor Company", validators=[DataRequired()], coerce=str)
    cdl_class = SelectField(
        "CDL Class",
        choices=[("", "Select"), ("A", "Class A"), ("B", "Class B"), ("C", "Class C")],
        validators=[Optional()],
    )
    experience_years = IntegerField("Years of Experience", validators=[Optional(), NumberRange(min=0, max=80)])
    experience_months = IntegerField(
        "Additional Months of Experience",
        validators=[Optional(), NumberRange(min=0, max=11)],
    )
    transmission = SelectField(
        "Preferred Transmission",
        choices=[("", "Select"), ("AUTOMATIC", "Automatic"), ("MANUAL", "Manual")],
        validators=[Optional()],
    )
    preferred_weekly_hours = IntegerField(
        "Preferred Weekly Hours",
        validators=[Optional(), NumberRange(min=0, max=100)],
    )
    violations_count = IntegerField(
        "Moving Violations (last 3 years)",
        validators=[Optional(), NumberRange(min=0, max=25)],
    )
    license_number = StringField(
        "License Number",
        validators=[
            Optional(),
            Length(max=50),
            Regexp(r"^[a-zA-Z0-9\s\-]+$", message="License number contains invalid characters"),
        ],
    )
    license_issue_date = StringField(
        "License Issue Date (YYYY-MM-DD)",
        validators=[
            Optional(),
            Regexp(r"^\d{4}-\d{2}-\d{2}$", message="Date must be in YYYY-MM-DD format"),
        ],
    )
    license_expiration_date = StringField(
        "License Expiration Date (YYYY-MM-DD)",
        validators=[
            Optional(),
            Regexp(r"^\d{4}-\d{2}-\d{2}$", message="Date must be in YYYY-MM-DD format"),
        ],
    )
    consent_data = BooleanField(
        "I agree to the data use policy",
        validators=[DataRequired(message="You must consent to data use to submit your application.")],
    )
    agree_terms = BooleanField(
        "I agree to the terms and conditions",
        validators=[DataRequired(message="You must agree to the terms to continue.")],
    )
    signature = StringField(
        "Signature",
        validators=[
            DataRequired(),
            Length(min=2, max=200),
        ],
    )

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError("Passwords do not match.")


def _notify_admins(subject: str, body: str):
    """Notify opted-in admins via Mailtrap/Flask-Mail."""
    try:
        # Get all admins with login suspicious activity notifications enabled
        admin_prefs = AdminNotificationPreferences.query.filter_by(
            LoginSuspiciousActivity=True
        ).all()
        
        if not admin_prefs:
            return
            
        recipients = []
        for prefs in admin_prefs:
            admin = Admin.query.filter_by(AdminID=prefs.AdminID).first()
            if admin:
                acct = Account.query.filter_by(AccountID=admin.AccountID).first()
                if acct and acct.Email:
                    recipients.append(acct.Email)
                    
        if not recipients:
            return
            
        msg = Message(subject=subject, recipients=recipients, body=body)
        mail.send(msg)
    except Exception as e:
        current_app.logger.error(f"Failed to notify admins: {e}")
        # Fail closed; do not break login flow
        pass


def _check_account_locked(account_id: str) -> tuple[bool, str | None]:
    """
    Check if an account is currently locked.
    Returns: (is_locked, lockout_message)
    """
    acct = Account.query.filter_by(AccountID=account_id).first()
    if not acct:
        return False, None
    
    # Check if account has a lockout that hasn't expired
    if acct.LockedUntil:
        now = datetime.utcnow()
        if acct.LockedUntil > now:
            # Still locked - calculate remaining time
            remaining = acct.LockedUntil - now
            minutes_remaining = int(remaining.total_seconds() / 60) + 1
            return True, f"Account locked due to too many failed login attempts. Please try again in {minutes_remaining} minute(s)."
        else:
            # Lockout expired - clear it
            acct.LockedUntil = None
            db.session.commit()
    
    return False, None


def _handle_failed_login_attempt(account_id: str, ip: str):
    """
    Handle a failed login attempt:
    - Record the attempt
    - Count recent failures
    - Lock account if 5+ failures in recent attempts
    """
    acct = Account.query.filter_by(AccountID=account_id).first()
    if not acct:
        return
    
    # Count recent failed attempts (last 15 minutes)
    # Note: The current failed attempt has already been recorded by _record_login_attempt
    window_start = datetime.utcnow() - timedelta(minutes=15)
    recent_failures = (LoginAttempts.query
        .filter(
            LoginAttempts.AccountID == account_id,
            LoginAttempts.WasSuccessful == False,
            LoginAttempts.AttemptedAt >= window_start
        )
        .count())
    
    # If we have 5 or more failed attempts, lock the account for 15 minutes
    if recent_failures >= 5:
        lockout_until = datetime.utcnow() + timedelta(minutes=15)
        acct.LockedUntil = lockout_until
        db.session.commit()
        current_app.logger.warning(
            f"Account {account_id} ({acct.Email}) locked until {lockout_until} "
            f"due to {recent_failures} failed login attempts"
        )
    
    # Notify admins
    _notify_admins(
        subject="Security Alert: Failed login attempt",
        body=f"Account: {acct.Email}\nIP: {ip}\nWhen: {datetime.utcnow()} UTC\nRecent failures (15m): {recent_failures}"
    )


def _record_login_attempt(account_id: str, success: bool, ip: str):
    """Central helper to record login attempts (success or failure)."""
    db.session.add(LoginAttempts(
        LoginAttemptID=str(uuid.uuid4()),
        AccountID=account_id,
        WasSuccessful=success,
        IPAddress=ip,
        AttemptedAt=datetime.utcnow()
    ))
    db.session.commit()

    if success:
        # Reset lockout on successful login
        acct = Account.query.filter_by(AccountID=account_id).first()
        if acct and acct.LockedUntil:
            acct.LockedUntil = None
            db.session.commit()
    else:
        # Handle failed login attempt (count failures and lock if needed)
        _handle_failed_login_attempt(account_id, ip)


def _set_role_session(acct):
    """Set canonical session['role'] from AccountType, and keep legacy IDs for compatibility."""
    # Clear legacy role keys
    session.pop("sponsor_id", None)
    session.pop("driver_id", None)
    session.pop("admin_id", None)

    # --- canonical role via AccountType ---
    role_code = None
    try:
        at = AccountType.query.filter_by(AccountTypeID=acct.AccountTypeID).first()
        if at and at.AccountTypeCode:
            role_code = at.AccountTypeCode.strip().upper()
    except Exception:
        role_code = None

    session["role"] = role_code  # 'DRIVER' | 'SPONSOR' | 'ADMIN' (or None)

    # --- keep legacy IDs populated so old code keeps working ---
    try:
        from app.models import Sponsor, Driver, Admin
        sponsor = Sponsor.query.filter_by(AccountID=acct.AccountID).first()
        driver  = Driver.query.filter_by(AccountID=acct.AccountID).first()
        admin   = Admin.query.filter_by(AccountID=acct.AccountID).first()
        if sponsor:
            session["sponsor_id"] = sponsor.SponsorID
        if driver:
            session["driver_id"] = driver.DriverID
        if admin:
            session["admin_id"] = admin.AdminID
    except Exception:
        pass


def _ensure_driver_environment():
    """
    After a driver logs in, ensure we have a specific environment chosen.

    - If driver has exactly one active environment: set session['driver_sponsor_id'] (and sponsor_id for legacy helpers).
    - If driver has multiple: redirect to selection page.
    - If none: clear driver_sponsor_id and continue (legacy flow can still work if not yet migrated).
    """
    # Only applies to driver sessions
    role = (session.get("role") or "").upper()
    if role != "DRIVER":
        return None

    # If a driver ID isn't present, nothing to do (e.g., account exists but no Driver row)
    if not session.get("driver_id"):
        return None

    # Don’t stomp an already-selected environment
    if session.get("driver_sponsor_id"):
        return None

    envs = (DriverSponsor.query
            .filter_by(DriverID=session["driver_id"], Status="ACTIVE")
            .all())

    if len(envs) == 1:
        session["driver_sponsor_id"] = envs[0].DriverSponsorID
        session["sponsor_id"] = envs[0].SponsorID
        session["driver_env_selection_pending"] = False
        return None
    elif len(envs) > 1:
        session.pop("driver_sponsor_id", None)
        session["driver_env_selection_pending"] = True
        return None
    else:
        session.pop("driver_sponsor_id", None)
        session["driver_env_selection_pending"] = False
        return None


# ------------------------------
# LOGIN PAGE
# ------------------------------
@bp.get("/")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    error = session.pop("_login_error", None)
    email = session.pop("_login_email", "")
    show_mfa_modal = session.pop("show_mfa_modal", False)
    mfa_error = session.pop("_mfa_error", None)
    show_forgot_modal = session.pop("show_forgot_modal", False)
    forgot_messages = session.pop("_forgot_messages", None)
    return render_template(
        "login.html",
        error=error,
        email=email,
        show_mfa_modal=show_mfa_modal,
        mfa_error=mfa_error,
        show_forgot_modal=show_forgot_modal,
        forgot_messages=forgot_messages or [],
    )

@bp.get("/account-deactivated")
def account_deactivated():
    """Display account deactivated page"""
    error = session.pop("_login_error", None)
    return render_template("account_deactivated.html", error=error)

@bp.get("/account-archived")
def account_archived():
    """Display account archived page (permanently closed)"""
    return render_template("account_archived.html")


# ------------------------------
# LOGIN HANDLER
# ------------------------------
@bp.post("/login")
def login_api():
    # Handle both JSON and form data
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form
    
    # Accept both "email" and "username" field names for flexibility
    email_or_username = (data.get("email") or data.get("username") or "").strip()  # Remove .lower() to preserve case for username
    password = data.get("password") or ""

    if not email_or_username or not password:
        session["_login_error"] = "Missing email/username or password"
        session["_login_email"] = email_or_username
        return redirect(url_for("auth.login_page"))

    # Try to find account by email first, then by username
    # Check if it looks like an email (contains @)
    if "@" in email_or_username:
        acct = Account.query.filter(Account.Email == email_or_username.lower()).first()
    else:
        acct = Account.query.filter(Account.Username == email_or_username).first()
    
    # Check if account exists and is locked
    if acct:
        is_locked, lockout_message = _check_account_locked(acct.AccountID)
        if is_locked:
            if request.is_json:
                return jsonify({"message": lockout_message}), 403
            session["_login_error"] = lockout_message
            session["_login_email"] = email_or_username
            return redirect(url_for("auth.login_page"))
    
    if not acct or not bcrypt.check_password_hash(acct.PasswordHash, password):
        if acct:
            _record_login_attempt(acct.AccountID, False, request.remote_addr)
        if request.is_json:
            return jsonify({"message": "Incorrect email/username or password"}), 401
        session["_login_error"] = "Incorrect email/username or password"
        session["_login_email"] = email_or_username
        return redirect(url_for("auth.login_page"))

    ev = EmailVerification.query.filter_by(AccountID=acct.AccountID).first()
    if ev and not ev.IsVerified:
        return redirect(url_for("users.verify_notice", email=acct.Email))
    
    # ---- ACCOUNT STATUS CHECK ----
    status_code = (acct.Status or '').upper()
    if status_code == 'I':
        # Inactive -> prompt to contact support
        if request.is_json:
            return jsonify({"message": "Your account has been deactivated. Please contact support."}), 403
        session["_login_error"] = "Your account has been deactivated. Please contact support."
        return redirect(url_for("auth.account_deactivated"))
    if status_code == 'H':
        # Archived -> permanently closed, no support messaging
        if request.is_json:
            return jsonify({"message": "Your account has been archived and is no longer accessible."}), 403
        return redirect(url_for("auth.account_archived"))

    # ---- DRIVER PENDING CHECK ----
    if (acct.AccountType or "").upper() == "DRIVER":
        driver_pending_message = "Your sponsor application is still pending approval. You will receive an email once a sponsor approves you."
        if status_code != 'A':
            if request.is_json:
                return jsonify({"message": driver_pending_message}), 403
            session["_login_error"] = driver_pending_message
            session["_login_email"] = email_or_username
            return redirect(url_for("auth.login_page"))
        drv = Driver.query.filter_by(AccountID=acct.AccountID).first()
        if drv:
            has_active_env = DriverSponsor.query.filter_by(DriverID=drv.DriverID, Status="ACTIVE").first()
            if not has_active_env:
                if request.is_json:
                    return jsonify({"message": driver_pending_message}), 403
                session["_login_error"] = driver_pending_message
                session["_login_email"] = email_or_username
                return redirect(url_for("auth.login_page"))

    # ---- MFA GATE ----
    if acct.MFAEnabled:
        session["pending_mfa_user"] = str(acct.AccountID)
        session["show_mfa_modal"] = True
        return redirect(url_for("auth.login_page"))

    # ---- No MFA -> normal login ----
    login_user(acct, remember=True)
    session.permanent = True  # Make session permanent to match CSRF token lifetime (31 days)
    _record_login_attempt(acct.AccountID, True, request.remote_addr)
    _set_role_session(acct)
    
    # SECURITY: Create session for tracking and auto-logout
    SessionManagementService.create_session(acct.AccountID, request)

    # Ensure driver environment selection (only affects driver logins)
    if not request.is_json:
        env_redirect = _ensure_driver_environment()
        if env_redirect:
            return env_redirect

    def _is_safe_next(val: str) -> bool:
        return bool(val) and val.startswith("/")
    next_url = request.form.get("next") or request.args.get("next")
    if _is_safe_next(next_url):
        return redirect(next_url)

    if request.is_json:
        return jsonify({"message": "Login successful"})
    return redirect(url_for("dashboard"))


# ------------------------------
# MFA CHALLENGE
# ------------------------------
@bp.post("/login/mfa")
def mfa_challenge_post():
    user_id = session.get("pending_mfa_user")
    if not user_id:
        return redirect(url_for("auth.login_page"))

    acct = Account.query.get(user_id)
    if not acct:
        flash("Session expired. Please log in again.", "error")
        return redirect(url_for("auth.login_page"))
    
    # Check if account is locked (safety check in case lockout occurred between password check and MFA)
    is_locked, lockout_message = _check_account_locked(acct.AccountID)
    if is_locked:
        session.pop("pending_mfa_user", None)
        session["_login_error"] = lockout_message
        return redirect(url_for("auth.login_page"))

    # ****************************************************
    # ***** FIX: MAKE RECOVERY CODES ONE-TIME USE *********
    # ****************************************************
    secret = fernet.decrypt(acct.MFASecretEnc.encode()).decode()
    totp = pyotp.TOTP(secret)
    # Normalize input: remove all whitespace and convert to lowercase
    code = (request.form.get("token") or "").replace(" ", "").replace("-", "").replace("_", "").strip().lower()

    verified = False
    
    # Recovery codes are 8 hex characters, TOTP codes are 6 digits
    # Check format first to avoid unnecessary TOTP verification attempts
    is_recovery_code_format = len(code) == 8 and all(c in '0123456789abcdef' for c in code)
    is_totp_format = len(code) == 6 and code.isdigit()
    
    if is_totp_format:
        # Try TOTP verification first for 6-digit codes
        if totp.verify(code, valid_window=1):
            verified = True
    elif is_recovery_code_format:
        # Try recovery codes for 8-character hex strings
        if acct.RecoveryCodes:
            for stored in list(acct.RecoveryCodes):
                if check_password_hash(stored, code):
                    verified = True
                    acct.RecoveryCodes.remove(stored)
                    db.session.commit()
                    break
    else:
        # Invalid format - try both as fallback (for backwards compatibility)
        if totp.verify(code, valid_window=1):
            verified = True
        elif acct.RecoveryCodes:
            for stored in list(acct.RecoveryCodes):
                if check_password_hash(stored, code):
                    verified = True
                    acct.RecoveryCodes.remove(stored)
                    db.session.commit()
                    break
    
    if not verified:
        session["show_mfa_modal"] = True
        session["_mfa_error"] = "Invalid MFA or recovery code."
        return redirect(url_for("auth.login_page"))

    # Successful login (after TOTP or recovery)
    login_user(acct, remember=True)
    session.permanent = True  # Make session permanent to match CSRF token lifetime (31 days)
    session.pop("pending_mfa_user", None)
    _set_role_session(acct)
    _record_login_attempt(acct.AccountID, True, request.remote_addr)
    
    # SECURITY: Create session for tracking and auto-logout
    SessionManagementService.create_session(acct.AccountID, request)

    # Ensure driver environment selection (only affects driver logins)
    env_redirect = _ensure_driver_environment()
    if env_redirect:
        return env_redirect

    return redirect(url_for("dashboard"))


# ------------------------------
# EMAIL VERIFICATION RESEND
# ------------------------------
@bp.post("/resend-verification")
def resend_verification():
    email = (request.form.get("email") or "").strip().lower()
    if not email:
        flash("Email is required.", "error")
        return redirect(url_for("auth.login_page"))

    acct = Account.query.filter_by(Email=email).first()
    if not acct:
        flash("Account not found.", "error")
        return redirect(url_for("users.verify_notice", email=email))

    MAX_PER_HOUR = 3
    WINDOW = timedelta(hours=1)
    now = datetime.utcnow()

    ev = EmailVerification.query.filter_by(AccountID=acct.AccountID).first()
    if ev and ev.IsVerified:
        flash("This email is already verified. You can log in now.", "success")
        return redirect(url_for("auth.login_page"))

    if not ev:
        ev = EmailVerification(
            AccountID=acct.AccountID,
            VerificationToken=str(uuid.uuid4()),
            SentAt=now,
            SendCount=0
        )
        db.session.add(ev)
        db.session.flush()

    prior_sent_at = ev.SentAt
    prior_count = ev.SendCount or 0

    if prior_sent_at and prior_sent_at >= (now - WINDOW):
        if prior_count >= MAX_PER_HOUR:
            flash("You’ve requested too many verification emails. Try again in about an hour.", "error")
            return redirect(url_for("users.verify_notice", email=email))
        ev.SendCount = prior_count + 1
    else:
        ev.SendCount = 1

    ev.VerificationToken = str(uuid.uuid4())
    ev.SentAt = now
    db.session.commit()

    verify_url = url_for("auth.verify_email", token=ev.VerificationToken, _external=True)
    sent = _send_verification_email(
        recipient=acct.Email,
        subject="Verify Your Email",
        body=(
            "Click to verify your email:\n\n"
            f"{verify_url}\n\n"
            "If you didn’t create an account, ignore this."
        ),
    )
    if sent:
        flash("Verification email sent!", "success")
    else:
        flash("Could not send email right now. Please try again shortly.", "error")

    return redirect(url_for("users.verify_notice", email=email))


# ------------------------------
# EMAIL VERIFY ENDPOINT
# ------------------------------
@bp.get("/verify/<token>")
def verify_email(token):
    ev = EmailVerification.query.filter_by(VerificationToken=token).first()
    if not ev:
        flash("Invalid or expired verification token.", "error")
        return redirect(url_for("auth.login_page"))

    ev.IsVerified = True
    ev.VerifiedAt = datetime.utcnow()
    db.session.commit()
    flash("Your email has been verified. You can now log in.", "success")
    return redirect(url_for("auth.login_page"))


# ------------------------------
# DRIVER REGISTRATION
# ------------------------------
@bp.route("/register", methods=["GET", "POST"])
def register_driver():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    form = DriverRegistrationForm()
    sponsor_companies = (
        SponsorCompany.query.filter(SponsorCompany.sponsors.any())
        .order_by(SponsorCompany.CompanyName.asc())
        .all()
    )
    form.sponsor_company_id.choices = [
        (sc.SponsorCompanyID, sc.CompanyName) for sc in sponsor_companies
    ]

    if form.validate_on_submit():
        # Check for existing account conflicts before attempting insert
        existing_email = Account.query.filter_by(Email=form.email.data.lower().strip()).first()
        existing_username = Account.query.filter_by(Username=form.username.data.strip()).first()
        if existing_email:
            form.email.errors.append("An account with that email already exists.")
        if existing_username:
            form.username.errors.append("That username is already taken.")

        if not form.errors:
            try:
                password_hash = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
                phone_enc = None
                if form.phone.data:
                    phone_enc = fernet.encrypt(form.phone.data.strip().encode()).decode()

                account = Account(
                    AccountType="DRIVER",
                    AccountTypeID=_ensure_account_type_id("DRIVER"),
                    Username=form.username.data.strip(),
                    Email=form.email.data.lower().strip(),
                    Phone=phone_enc,
                    PasswordHash=password_hash,
                    FirstName=form.first_name.data.strip(),
                    LastName=form.last_name.data.strip(),
                    WholeName=f"{form.first_name.data.strip()} {form.last_name.data.strip()}".strip(),
                    Status="P",  # Pending sponsor approval
                )
                db.session.add(account)
                db.session.flush()

                driver = Driver(
                    AccountID=account.AccountID,
                    Status="PENDING",
                )
                db.session.add(driver)
                db.session.flush()

                if form.license_number.data:
                    driver.license_number_plain = form.license_number.data.strip()
                if form.license_issue_date.data:
                    driver.license_issue_date_plain = form.license_issue_date.data.strip()
                if form.license_expiration_date.data:
                    driver.license_expiration_date_plain = form.license_expiration_date.data.strip()

                sponsor_company_id = form.sponsor_company_id.data
                sponsor = select_primary_sponsor_for_company(sponsor_company_id)
                if not sponsor:
                    raise ValueError("Selected sponsor company is unavailable. Please contact support.")
                if not sponsor.SponsorCompanyID:
                    current_app.logger.error(
                        "Sponsor %s is missing SponsorCompanyID during driver registration.",
                        sponsor.SponsorID,
                    )
                    raise ValueError("Selected sponsor is misconfigured. Please contact support.")

                # Track the driver's company assignment
                driver.SponsorCompanyID = sponsor.SponsorCompanyID

                app_row = Application(
                    AccountID=account.AccountID,
                    SponsorID=sponsor.SponsorID,
                    CDLClass=(form.cdl_class.data or None) if form.cdl_class.data else None,
                    ExperienceYears=form.experience_years.data if form.experience_years.data is not None else None,
                    ExperienceMonths=form.experience_months.data if form.experience_months.data is not None else None,
                    Transmission=(form.transmission.data or None) if form.transmission.data else None,
                    PreferredWeeklyHours=form.preferred_weekly_hours.data if form.preferred_weekly_hours.data is not None else None,
                    ViolationsCount3Y=form.violations_count.data if form.violations_count.data is not None else None,
                    IncidentsJSON={},
                    Suspensions5Y=False,
                    SuspensionsDetail=None,
                    ConsentedDataUse=True,
                    AgreedTerms=True,
                    ESignature=form.signature.data.strip(),
                    ESignedAt=datetime.utcnow(),
                    SubmittedAt=datetime.utcnow(),
                )
                db.session.add(app_row)

                env = DriverSponsor(
                    DriverID=driver.DriverID,
                    SponsorID=sponsor.SponsorID,
                    SponsorCompanyID=sponsor.SponsorCompanyID,
                    PointsBalance=0,
                    Status="PENDING",
                )
                db.session.add(env)

                token = str(uuid.uuid4())
                verification = EmailVerification(
                    AccountID=account.AccountID,
                    VerificationToken=token,
                    SentAt=datetime.utcnow(),
                    SendCount=1,
                    IsVerified=False,
                )
                db.session.add(verification)

                PasswordSecurityService.log_password_change(
                    account_id=account.AccountID,
                    new_password_hash=password_hash,
                    change_reason="initial_setup",
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                )

                db.session.commit()

                verify_url = url_for("auth.verify_email", token=token, _external=True)
                _send_verification_email(
                    recipient=account.Email,
                    subject="Verify Your Email",
                    body=(
                        "Welcome to Driver Rewards!\n\n"
                        "Click the link below to verify your email address:\n"
                        f"{verify_url}\n\n"
                        "You will receive an update once your sponsor reviews the application."
                    ),
                )

                try:
                    NotificationService.notify_sponsor_new_application(app_row.ApplicationID)
                    NotificationService.notify_driver_application_received(app_row.ApplicationID)
                except Exception as exc:
                    current_app.logger.error(f"Application notification failure: {exc}")

                return redirect(url_for("auth.register_complete", email=account.Email))

            except IntegrityError:
                current_app.logger.exception("Driver registration integrity error")
                db.session.rollback()
                form.email.errors.append("A driver with that email or username already exists.")
            except Exception as exc:
                current_app.logger.exception("Driver registration failed")
                db.session.rollback()
                flash("We couldn't process your registration right now. Please try again.", "error")

    return render_template("auth/register_driver.html", form=form, sponsor_companies=sponsor_companies)


@bp.route("/register/complete")
def register_complete():
    email = request.args.get("email")
    return render_template("auth/register_complete.html", email=email)


# ------------------------------
# LOGOUT HANDLER
# ------------------------------
@bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout_api():
    """Logs the user out, clears session, removes remember cookie.
    
    If the user was being impersonated by an admin or sponsor, this will clear the session
    and redirect to the login page, allowing the admin/sponsor to log back in as themselves.
    """
    try:
        # Check if we're ending an impersonation session
        is_impersonating = session.get('impersonating', False)
        original_admin_id = session.get('original_admin_account_id')
        original_sponsor_id = session.get('original_sponsor_account_id')
        
        if current_user.is_authenticated:
            _record_login_attempt(current_user.get_id(), True, request.remote_addr)
            
            # Log impersonation end if applicable
            if is_impersonating and original_admin_id:
                current_app.logger.info(
                    f"Admin impersonation ended. Admin AccountID: {original_admin_id}, "
                    f"Impersonated AccountID: {current_user.get_id()}"
                )
            elif is_impersonating and original_sponsor_id:
                current_app.logger.info(
                    f"Sponsor impersonation ended. Sponsor AccountID: {original_sponsor_id}, "
                    f"Impersonated Driver AccountID: {current_user.get_id()}"
                )

            # SECURITY: Revoke current session and clear client token
            session_token = session.get('session_token')
            if session_token:
                SessionManagementService.revoke_session(session_token)
                session.pop('session_token', None)

        logout_user()
    finally:
        # Clear all session data, including impersonation markers
        session.clear()

    # Always redirect to login page after logout
    # If it was an impersonation, the admin will need to log in again as themselves
    resp = redirect(url_for("auth.login_page"))
    cookie_name = current_app.config.get("REMEMBER_COOKIE_NAME", "remember_token")
    cookie_path = current_app.config.get("REMEMBER_COOKIE_PATH", "/")
    cookie_domain = current_app.config.get("REMEMBER_COOKIE_DOMAIN")
    resp.delete_cookie(cookie_name, path=cookie_path, domain=cookie_domain)
    return resp


# ------------------------------
# WHOAMI DEBUG ENDPOINT
# ------------------------------
@bp.get("/whoami")
def whoami():
    if not current_user.is_authenticated:
        return jsonify({"authenticated": False})

    return jsonify({
        "authenticated": True,
        "account_id": current_user.get_id(),
        "email": getattr(current_user, "Email", None),
        "sponsor_id": session.get("sponsor_id"),
        "driver_id": session.get("driver_id"),
        "driver_sponsor_id": session.get("driver_sponsor_id"),
        "admin_id": session.get("admin_id"),
        "role": session.get("role"),
    })


# ------------------------------
# MFA SETTINGS PAGE
# ------------------------------
@bp.get("/settings/mfa")
@login_required
def mfa_settings():
    return render_template("mfa_settings.html", account=current_user)


@bp.post("/settings/mfa/enable")
@login_required
def enable_mfa():
    password = request.form.get("current_password") or ""
    wants_json = request.is_json or request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest" \
        or request.accept_mimetypes.best == "application/json"

    if not bcrypt.check_password_hash(current_user.PasswordHash, password):
        message = "Incorrect current password."
        if wants_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "error")
        return redirect(url_for("auth.mfa_settings"))

    secret = pyotp.random_base32()
    enc_secret = fernet.encrypt(secret.encode()).decode()
    current_user.MFASecretEnc = enc_secret
    db.session.commit()

    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.Email,
        issuer_name="Driver Rewards"
    )
    if wants_json:
        return jsonify({
            "status": "pending",
            "message": "Scan the QR code and enter the verification code to finish enabling MFA.",
            "qr_uri": uri,
            "raw_secret": secret
        })
    return render_template(
        "mfa_enable_confirm.html",
        qr_uri=uri,
        raw_secret=secret
    )


@bp.post("/settings/mfa/confirm")
@login_required
def confirm_mfa():
    # Normalize + verify code
    code = (request.form.get("token") or "").strip().lower()
    wants_json = request.is_json or request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest" \
        or request.accept_mimetypes.best == "application/json"

    secret = fernet.decrypt(current_user.MFASecretEnc.encode()).decode()
    totp = pyotp.TOTP(secret)

    if not totp.verify(code, valid_window=1):
        message = "Invalid code. Try again."
        if wants_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "error")
        return redirect(url_for("auth.mfa_settings"))

    current_user.MFAEnabled = True

    # Generate 10 recovery codes (lowercase + hashed)
    raw_codes = [secrets.token_hex(4).lower() for _ in range(10)]
    current_user.RecoveryCodes = [generate_password_hash(c) for c in raw_codes]

    db.session.commit()

    if wants_json:
        return jsonify({
            "status": "success",
            "message": "MFA enabled successfully.",
            "codes": raw_codes
        })

    # Show recovery codes immediately
    return render_template("mfa_recovery_codes.html", codes=raw_codes)


@bp.post("/settings/mfa/disable")
@login_required
def disable_mfa():
    password = request.form.get("current_password") or ""
    wants_json = request.is_json or request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest" \
        or request.accept_mimetypes.best == "application/json"

    if not bcrypt.check_password_hash(current_user.PasswordHash, password):
        message = "Incorrect current password."
        if wants_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "error")
        return redirect(url_for("auth.mfa_settings"))

    current_user.MFAEnabled = False
    current_user.MFASecretEnc = None
    current_user.RecoveryCodes = None

    db.session.commit()
    success_message = "MFA disabled."
    if wants_json:
        return jsonify({"status": "success", "message": success_message})
    flash(success_message, "success")
    return redirect(url_for("auth.mfa_settings"))
