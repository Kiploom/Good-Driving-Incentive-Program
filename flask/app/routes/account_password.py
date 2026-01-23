from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
import bcrypt

from app.models import Account, db
from app.services.password_security_service import PasswordSecurityService

bp = Blueprint("account_password", __name__, url_prefix="/account/password")


def _wants_json_response() -> bool:
    """Determine if the current request prefers a JSON response."""
    if request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest":
        return True
    accept = request.accept_mimetypes
    if not accept:
        return False
    best = accept.best_match(["application/json", "text/html"])
    if best == "application/json":
        return accept[best] >= accept["text/html"]
    return False


def _json(message: str, status: str = "success", code: int = 200, **extra):
    payload = {"status": status, "message": message}
    if extra:
        payload.update(extra)
    return jsonify(payload), code


def _account_redirect_route(account_type: str) -> str:
    account_type = (account_type or "").upper()
    if account_type == "DRIVER":
        return "driver.driver_account"
    if account_type == "SPONSOR":
        return "sponsor.sponsor_account"
    if account_type == "ADMIN":
        return "admin.admin_account"
    return "dashboard"


@bp.route("/change", methods=["GET", "POST"])
@login_required
def change_password():
    account = Account.query.get(current_user.AccountID)
    wants_json = _wants_json_response()
    if not account:
        if wants_json:
            return _json("Account not found.", status="error", code=404)
        flash("Account not found.", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        current_password = (request.form.get("current_password") or "").strip()
        new_password = (request.form.get("new_password") or "").strip()
        confirm_password = (request.form.get("confirm_password") or "").strip()

        if not current_password or not new_password or not confirm_password:
            if wants_json:
                return _json("All password fields are required.", status="error", code=400)
            flash("All password fields are required.", "danger")
            return redirect(request.url)

        if not bcrypt.checkpw(current_password.encode("utf-8"), account.PasswordHash.encode("utf-8")):
            if wants_json:
                return _json("Current password is incorrect.", status="error", code=400)
            flash("Current password is incorrect.", "danger")
            return redirect(request.url)

        if new_password != confirm_password:
            if wants_json:
                return _json("New passwords do not match.", status="error", code=400)
            flash("New passwords do not match.", "danger")
            return redirect(request.url)

        is_strong, complexity_error = PasswordSecurityService.is_password_strong(new_password)
        if not is_strong:
            if wants_json:
                return _json(f"Password change failed: {complexity_error}", status="error", code=400)
            flash(f"Password change failed: {complexity_error}", "danger")
            return redirect(request.url)

        if bcrypt.checkpw(new_password.encode("utf-8"), account.PasswordHash.encode("utf-8")):
            message = "Password change failed: The new password is the same as your current password."
            if wants_json:
                return _json(message, status="error", code=400)
            flash(message, "danger")
            return redirect(request.url)

        is_reused, reuse_error = PasswordSecurityService.check_password_reuse(account.AccountID, new_password)
        if is_reused:
            if wants_json:
                return _json(f"Password change failed: {reuse_error}", status="error", code=400)
            flash(f"Password change failed: {reuse_error}", "danger")
            return redirect(request.url)

        new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        account.PasswordHash = new_hash
        db.session.commit()

        PasswordSecurityService.log_password_change(
            account_id=account.AccountID,
            new_password_hash=new_hash,
            change_reason='self_change',
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        if (account.AccountType or "").upper() == "DRIVER":
            try:
                from app.services.notification_service import NotificationService
                NotificationService.notify_driver_password_changed(account)
            except Exception as exc:
                current_app.logger.error(f"Failed to send driver password change notification: {exc}")

        success_message = "Password changed successfully!"
        if wants_json:
            return _json(success_message, status="success")
        flash(success_message, "success")
        return redirect(url_for(_account_redirect_route(account.AccountType)))

    return render_template("account_change_password.html", account=account)
