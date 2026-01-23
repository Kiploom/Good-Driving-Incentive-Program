# app/routes/auth_reset.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, session
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_mail import Message
from ..models import Account, Driver, Sponsor, Admin, LoginAttempts
from ..extensions import db, mail
from ..services.password_security_service import PasswordSecurityService
from app.services.session_management_service import SessionManagementService
from flask_login import login_user
from datetime import datetime
import bcrypt
import re

bp_reset = Blueprint("auth_reset", __name__)

# -------------------------------------
# Helper: create & verify signed token
# -------------------------------------
def _generate_reset_token(email: str) -> str:
    s = URLSafeTimedSerializer(current_app.secret_key)
    return s.dumps(email, salt="password-reset")

def _verify_reset_token(token: str, max_age: int = 3600):
    s = URLSafeTimedSerializer(current_app.secret_key)
    try:
        email = s.loads(token, salt="password-reset", max_age=max_age)
        return email
    except (SignatureExpired, BadSignature):
        return None

# -------------------------------------
# Magic-link token helpers (users without MFA)
# -------------------------------------
def _generate_magic_token(email: str) -> str:
    s = URLSafeTimedSerializer(current_app.secret_key)
    return s.dumps(email, salt="magic-login")

def _verify_magic_token(token: str, max_age: int = 900):  # 15 minutes
    s = URLSafeTimedSerializer(current_app.secret_key)
    try:
        email = s.loads(token, salt="magic-login", max_age=max_age)
        return email
    except (SignatureExpired, BadSignature):
        return None

# -------------------------------------
# Password complexity reuse
# -------------------------------------
def _is_password_strong(pw: str) -> bool:
    if len(pw) < 8: return False
    if not re.search(r"[A-Z]", pw): return False
    if not re.search(r"[a-z]", pw): return False
    if not re.search(r"[0-9]", pw): return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", pw): return False
    return True

# -------------------------------------
# Forgot Password: request link
# -------------------------------------
@bp_reset.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    def _queue_message(category: str, message: str):
        messages = session.get("_forgot_messages", [])
        messages.append({"category": category, "message": message})
        session["_forgot_messages"] = messages

    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        user = Account.query.filter_by(Email=email).first() if email else None
        if not user:
            _queue_message("info", "If that email exists in our system, a reset link has been sent.")
            session["show_forgot_modal"] = True
            return redirect(url_for("auth.login_page"))

        token = _generate_reset_token(email)
        reset_link = url_for("auth_reset.reset_password", token=token, _external=True)

        sender = (
            current_app.config.get("MAIL_DEFAULT_SENDER")
            or current_app.config.get("MAIL_USERNAME")
            or "no-reply@team10.local"
        )

        msg = Message(
            subject="Password Reset Request",
            recipients=[email],
            body=f"Click the link to reset your password (valid 1 hour): {reset_link}",
            sender=sender,
        )
        try:
            mail.send(msg)
        except Exception as send_err:
            current_app.logger.exception("Failed to send password reset email: %s", send_err)
            _queue_message("error", "We were unable to send the reset email. Please try again later or contact support.")
            session["show_forgot_modal"] = True
            return redirect(url_for("auth.login_page"))
        _queue_message("info", "If that email exists in our system, a reset link has been sent.")
        session["show_forgot_modal"] = True
        return redirect(url_for("auth.login_page"))

    session["show_forgot_modal"] = True
    return redirect(url_for("auth.login_page"))

# -------------------------------------
# Magic-link request (only when MFA disabled) - for drivers, sponsors, and admins
# -------------------------------------
@bp_reset.route("/magic-link", methods=["GET", "POST"])
def magic_link_request():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        user = Account.query.filter_by(Email=email).first()
        # Respond generically for privacy
        msg_text = "If eligible, a magic login link has been sent."
        if not user:
            flash(msg_text, "info")
            return redirect(url_for("auth_reset.magic_link_request"))
        # Only allow magic link for drivers, sponsors, or admins without MFA
        if getattr(user, 'MFAEnabled', False):
            flash(msg_text, "info")
            return redirect(url_for("auth_reset.magic_link_request"))
        # Check if user is a driver, sponsor, or admin
        driver = Driver.query.filter_by(AccountID=user.AccountID).first()
        sponsor = Sponsor.query.filter_by(AccountID=user.AccountID).first()
        admin = Admin.query.filter_by(AccountID=user.AccountID).first()
        if not driver and not sponsor and not admin:
            flash(msg_text, "info")
            return redirect(url_for("auth_reset.magic_link_request"))

        token = _generate_magic_token(email)
        login_link = url_for("auth_reset.magic_link_login", token=token, _external=True)
        body = (
            "You requested a magic login link. It is valid for 15 minutes.\n\n"
            f"Login: {login_link}\n\nIf you did not request this, you can ignore this email."
        )
        msg = Message(subject="Your Magic Login Link", recipients=[email], body=body)
        mail.send(msg)
        flash(msg_text, "info")
        return redirect(url_for("auth_reset.magic_link_request"))
    return render_template("magic_link_request.html")


# -------------------------------------
# Magic-link consume (logs in user) - for drivers, sponsors, and admins
# -------------------------------------
@bp_reset.route("/magic-link/login/<token>", methods=["GET"])
def magic_link_login(token):
    email = _verify_magic_token(token)
    if not email:
        flash("Invalid or expired magic link.", "danger")
        return redirect(url_for("auth_reset.magic_link_request"))

    user = Account.query.filter_by(Email=email).first()
    if not user:
        flash("Invalid or expired magic link.", "danger")
        return redirect(url_for("auth_reset.magic_link_request"))
    # Ensure eligibility: driver, sponsor, or admin without MFA
    if getattr(user, 'MFAEnabled', False):
        flash("Magic link is not available for this account.", "danger")
        return redirect(url_for("auth_reset.magic_link_request"))
    # Check if user is a driver, sponsor, or admin
    driver = Driver.query.filter_by(AccountID=user.AccountID).first()
    sponsor = Sponsor.query.filter_by(AccountID=user.AccountID).first()
    admin = Admin.query.filter_by(AccountID=user.AccountID).first()
    if not driver and not sponsor and not admin:
        flash("Magic link is not available for this account.", "danger")
        return redirect(url_for("auth_reset.magic_link_request"))

    # Log in user and create tracked session
    login_user(user, remember=True)
    session.permanent = True  # Make session permanent to match CSRF token lifetime (31 days)
    SessionManagementService.create_session(user.AccountID, request)

    # Set role session (mirror of auth._set_role_session)
    session.pop("sponsor_id", None)
    session.pop("driver_id", None)
    session.pop("admin_id", None)
    # Use the sponsor, driver, and admin we already queried above
    if sponsor:
        session["sponsor_id"] = sponsor.SponsorID
    elif driver:
        session["driver_id"] = driver.DriverID
    elif admin:
        session["admin_id"] = admin.AdminID

    # Audit successful login
    db.session.add(LoginAttempts(
        AccountID=user.AccountID,
        AttemptedAt=datetime.utcnow(),
        IPAddress=request.remote_addr,
        WasSuccessful=True
    ))
    db.session.commit()
    flash("You have been securely logged in via magic link.", "success")
    return redirect(url_for("dashboard"))

# -------------------------------------
# Reset Password: form
# -------------------------------------
@bp_reset.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    email = _verify_reset_token(token)
    if not email:
        flash("Invalid or expired token. Please request a new reset link.", "danger")
        return redirect(url_for("auth_reset.forgot_password"))

    if request.method == "POST":
        pw = request.form.get("password")
        
        # SECURITY: Check password complexity
        is_strong, complexity_error = PasswordSecurityService.is_password_strong(pw)
        if not is_strong:
            flash(f"Password complexity error: {complexity_error}", "danger")
            return redirect(request.url)

        user = Account.query.filter_by(Email=email).first()
        if not user:
            flash("Account not found.", "danger")
            return redirect(url_for("auth_reset.forgot_password"))

        # SECURITY: Check if password is the same as current password
        if bcrypt.checkpw(pw.encode('utf-8'), user.PasswordHash.encode('utf-8')):
            flash("Cannot reset password: The new password is the same as your current password.", "danger")
            return redirect(request.url)

        # SECURITY: Check if password was recently used
        is_reused, reuse_error = PasswordSecurityService.check_password_reuse(user.AccountID, pw)
        if is_reused:
            flash(f"Cannot reset password: {reuse_error}", "danger")
            return redirect(request.url)

        # ✅ Hash new password
        user.PasswordHash = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        
        # SECURITY: Log password change for audit trail
        PasswordSecurityService.log_password_change(
            account_id=user.AccountID,
            new_password_hash=user.PasswordHash,
            change_reason='password_reset',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        
        db.session.commit()

        # Notify account of password reset via Ethereal Mail, with Flask-Mail fallback
        try:
            from app.services.notification_service import NotificationService
            sent_ok = NotificationService.notify_driver_password_changed(user)
            if not sent_ok:
                raise RuntimeError("ethereal_send_failed")
        except Exception as e:
            try:
                # Fallback to default Flask-Mail config
                current_app.logger.error(f"Ethereal send failed for password reset notice: {e}")
                msg = Message(
                    subject="Your Driver Rewards password was changed",
                    recipients=[user.Email],
                    body=(
                        "This is a confirmation that your account password was changed.\n\n"
                        "If you did not make this change, please reset your password immediately and contact support."
                    ),
                    sender=current_app.config.get('MAIL_DEFAULT_SENDER')
                )
                mail.send(msg)
            except Exception as e2:
                current_app.logger.error(f"Fallback mail send also failed: {e2}")

        flash("Password reset successful! Your password has been updated. You can now log in.", "success")
        return redirect(url_for("auth.login_page"))  # ✅ fixed endpoint

    return render_template("reset_password.html")

    @bp.route('/reset')
    def reset():
        return "Password reset page"