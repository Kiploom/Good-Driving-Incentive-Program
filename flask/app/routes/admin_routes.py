from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session, make_response
from flask_login import login_required, current_user, login_user, logout_user
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.pdfgen import canvas
from io import BytesIO, StringIO
from collections import defaultdict
from sqlalchemy import and_, or_, func, text, case
from sqlalchemy.orm import aliased
from sqlalchemy.exc import IntegrityError
from app.models import db, Account, Admin, Sponsor, SponsorCompany, Application, PointChange, LoginAttempts, Driver, DriverSponsor, AdminNotificationPreferences, SponsorProfileAudit, Orders, OrderLineItem, Products, AccountType, EmailVerification, BulkImportLog, BulkImportError
from app.services.password_security_service import PasswordSecurityService
from app.services.profile_audit_service import ProfileAuditService
from app.services.session_management_service import SessionManagementService
from app.services.invoice_service import InvoiceService
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, IntegerField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Length, Regexp, NumberRange, Optional, Email as EmailValidator
import bcrypt
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import uuid
import csv
import json
from config import fernet
from flask_mail import Message
import pyotp

bp = Blueprint("admin", __name__, url_prefix="/admin")


# -------------------------------------------------------------------
# Admin Account Page (unchanged behavior)
# -------------------------------------------------------------------
@bp.route("/account", methods=["GET", "POST"], endpoint="admin_account")
@login_required
def admin_account():
    account = Account.query.filter_by(AccountID=current_user.AccountID).first()
    admin   = Admin.query.filter_by(AccountID=current_user.AccountID).first()

    if request.method == "POST":
        action = (request.form.get('action') or '').strip()
        wants_json = (
            request.is_json
            or request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest"
            or (request.accept_mimetypes.best == "application/json" if request.accept_mimetypes else False)
        )

        def _json_response(message: str, status: str = "success", code: int = 200, **extra):
            payload = {"status": status, "message": message}
            if extra:
                payload.update(extra)
            return jsonify(payload), code

        def _respond(message: str, category: str = "success", code: int = 200, **extra):
            if wants_json:
                status = "success"
                if category in {"danger", "error"}:
                    status = "error"
                elif category in {"warning", "info"}:
                    status = category
                return _json_response(message, status=status, code=code, **extra)
            flash(message, "danger" if category == "error" else category)
            return redirect(url_for("admin.admin_account"))

        def _log_profile_changes(old_account_snapshot=None, old_admin_snapshot=None, change_reason="Self-update via admin account page"):
            try:
                if account and old_account_snapshot:
                    ProfileAuditService.audit_account_changes(
                        account=account,
                        old_data=old_account_snapshot,
                        new_data={
                            'FirstName': account.FirstName,
                            'LastName': account.LastName,
                            'Email': account.Email,
                            'Phone': account.phone_plain if hasattr(account, 'phone_plain') else None
                        },
                        changed_by_account_id=current_user.AccountID,
                        change_reason=change_reason
                    )
                if admin and old_admin_snapshot:
                    ProfileAuditService.audit_admin_profile_changes(
                        admin=admin,
                        old_data=old_admin_snapshot,
                        new_data={
                            'Role': admin.Role
                        },
                        changed_by_account_id=current_user.AccountID,
                        change_reason=change_reason
                    )
            except Exception as exc:
                current_app.logger.warning(f"Audit logging failed: {exc}")

        if action == 'upload_avatar':
            try:
                from app.services.s3_service import upload_avatar, delete_avatar

                file = request.files.get('profile_image')
                if file and getattr(file, 'filename', '') and account:
                    old_profile_image_url = account.ProfileImageURL
                    old_s3_key = None
                    if old_profile_image_url and not old_profile_image_url.startswith('uploads/'):
                        old_s3_key = old_profile_image_url

                    try:
                        s3_key = upload_avatar(file, account.AccountID)
                    except ValueError as exc:
                        return _respond(f'Invalid file: {exc}', 'danger', 400)
                    except Exception as exc:
                        current_app.logger.error(f"Error uploading to S3: {exc}", exc_info=True)
                        return _respond('Failed to upload profile picture to S3.', 'danger', 500)

                    if old_s3_key:
                        try:
                            delete_avatar(old_s3_key)
                        except Exception as exc:
                            current_app.logger.warning(f"Failed to delete old avatar from S3: {exc}")

                    account.ProfileImageURL = s3_key
                    try:
                        db.session.commit()
                    except Exception as exc:
                        db.session.rollback()
                        current_app.logger.error(f"Failed to save avatar changes: {exc}", exc_info=True)
                        return _respond('Failed to update profile picture.', 'danger', 500)
                    return _respond('Profile picture updated.', 'success', 200)
                return _respond('No profile image selected.', 'warning', 400)
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error(f"Error in upload_avatar: {exc}", exc_info=True)
                return _respond('Failed to update profile picture.', 'danger', 500)

        if action == "change_email":
            if not account:
                return _respond("Account not found.", "danger", 404)

            new_email = (request.form.get("new_email") or "").strip()
            confirm_email = (request.form.get("confirm_email") or "").strip()
            current_password = (request.form.get("current_password") or "").strip()
            mfa_code = (request.form.get("mfa_code") or "").strip()

            if not new_email:
                return _respond("Please enter a new email address.", "error", 400)

            if confirm_email and new_email.lower() != confirm_email.lower():
                return _respond("Email addresses do not match.", "error", 400)

            current_email = (account.Email or "").strip()
            if new_email.lower() == current_email.lower():
                return _respond("That email is already associated with your account.", "info", 200, email=current_email)

            if not current_password:
                return _respond("Please confirm the change with your current password.", "error", 400)

            if not bcrypt.checkpw(current_password.encode("utf-8"), account.PasswordHash.encode("utf-8")):
                return _respond("Current password is incorrect.", "error", 400)

            if getattr(account, "MFAEnabled", False):
                if not mfa_code:
                    return _respond("Enter your MFA code to change your email.", "error", 400)
                try:
                    secret = fernet.decrypt(account.MFASecretEnc.encode()).decode()
                    totp = pyotp.TOTP(secret)
                    if not totp.verify(mfa_code, valid_window=1):
                        return _respond("Invalid MFA code. Please try again.", "error", 400)
                except Exception:
                    return _respond("MFA verification could not be completed. Try again.", "error", 400)

            old_account_snapshot = {
                'FirstName': account.FirstName,
                'LastName': account.LastName,
                'Email': account.Email,
                'Phone': account.phone_plain if hasattr(account, 'phone_plain') else None
            }
            old_email_value = current_email

            account.Email = new_email

            try:
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                current_app.logger.error(f"Failed to update admin email: {exc}", exc_info=True)
                return _respond("Failed to update email. Please try again.", "danger", 500)

            _log_profile_changes(old_account_snapshot, None, "Self-update email via admin account page")

            try:
                from app.services.notification_service import NotificationService
                recipients = [addr for addr in {old_email_value, new_email} if addr]
                if recipients:
                    NotificationService.send_simple_email(
                        recipients=recipients,
                        subject="Driver Rewards email change",
                        body=(
                            "Hello,\n\n"
                            "Your Driver Rewards administrator email address was changed.\n"
                            f"Previous email: {old_email_value or '(unknown)'}\n"
                            f"New email: {new_email or '(unknown)'}\n\n"
                            "If you did not make this change, please contact support immediately.\n"
                            "Driver Rewards Security Team"
                        )
                    )
            except Exception as notify_exc:
                current_app.logger.warning(f"Failed to send admin email change notification: {notify_exc}")

            return _respond("Email updated successfully.", "success", 200, email=new_email)

        if action == 'save_info':
            if not account:
                return _respond("Account not found.", "danger", 404)

            old_account_snapshot = {
                'FirstName': account.FirstName,
                'LastName': account.LastName,
                'Email': account.Email,
                'Phone': account.phone_plain if hasattr(account, 'phone_plain') else None
            } if account else None

            old_admin_snapshot = {
                'Role': admin.Role
            } if admin else None

            personal_updated = False
            admin_updated = False

            username_value = (request.form.get("username") or "").strip()
            if account and username_value and username_value != (account.Username or ""):
                account.Username = username_value
                personal_updated = True

            first_name_value = request.form.get("first_name")
            if account and first_name_value is not None and first_name_value != (account.FirstName or ""):
                account.FirstName = first_name_value
                personal_updated = True

            last_name_value = request.form.get("last_name")
            if account and last_name_value is not None and last_name_value != (account.LastName or ""):
                account.LastName = last_name_value
                personal_updated = True

            email_value = (request.form.get("email") or "").strip()
            if account and email_value and email_value != (account.Email or ""):
                account.Email = email_value
                personal_updated = True

            phone_value = request.form.get("phone")
            if account and phone_value is not None and phone_value != (account.phone_plain or ""):
                account.phone_plain = phone_value
                personal_updated = True

            if personal_updated and account:
                account.WholeName = f"{account.FirstName or ''} {account.LastName or ''}".strip()

            role_value = request.form.get("role")
            if admin and role_value is not None and role_value != (admin.Role or ""):
                admin.Role = role_value
                admin_updated = True

            if personal_updated or admin_updated:
                try:
                    db.session.commit()
                except Exception as exc:
                    db.session.rollback()
                    current_app.logger.error(f"Failed to update admin info: {exc}", exc_info=True)
                    return _respond("Failed to update account info. Please try again.", "danger", 500)

                _log_profile_changes(
                    old_account_snapshot if personal_updated else None,
                    old_admin_snapshot if admin_updated else None,
                    "Self-update via admin account page"
                )

                if personal_updated and admin_updated:
                    message = "Personal and admin info updated."
                elif personal_updated:
                    message = "Personal info updated."
                else:
                    message = "Admin info updated."

                return _respond(message, "success", 200)

            return _respond("No changes detected.", "info", 200)

        if action == 'change_password':
            if not account:
                return _respond("Account not found.", "danger", 404)

            current_password = request.form.get("current_password")
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")

            if current_password or new_password or confirm_password:
                if not all([current_password, new_password, confirm_password]):
                    return _respond("All password fields are required for password change.", "danger", 400)

                if not bcrypt.checkpw(current_password.encode('utf-8'), account.PasswordHash.encode('utf-8')):
                    return _respond("Password change failed: Current password is incorrect.", "danger", 400)

                if new_password != confirm_password:
                    return _respond("Password change failed: New passwords do not match.", "danger", 400)

                is_strong, complexity_error = PasswordSecurityService.is_password_strong(new_password)
                if not is_strong:
                    return _respond(f"Password change failed: {complexity_error}", "danger", 400)

                if bcrypt.checkpw(new_password.encode('utf-8'), account.PasswordHash.encode('utf-8')):
                    return _respond("Password change failed: The new password is the same as your current password.", "danger", 400)

                is_reused, reuse_error = PasswordSecurityService.check_password_reuse(account.AccountID, new_password)
                if is_reused:
                    return _respond(f"Password change failed: {reuse_error}", "danger", 400)

                new_password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
                account.PasswordHash = new_password_hash

                PasswordSecurityService.log_password_change(
                    account_id=account.AccountID,
                    new_password_hash=new_password_hash,
                    change_reason='self_change',
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent')
                )

                try:
                    db.session.commit()
                except Exception as exc:
                    db.session.rollback()
                    current_app.logger.error(f"Failed to update admin password: {exc}", exc_info=True)
                    return _respond("Password change failed due to a server error.", "danger", 500)

                return _respond("Password change successful! Your password has been updated.", "success", 200)

            return _respond("No password changes detected.", "info", 200)

        return _respond("Unsupported request.", "warning", 400)

    last_success = (
        LoginAttempts.query
        .filter_by(AccountID=current_user.AccountID, WasSuccessful=True)
        .order_by(LoginAttempts.AttemptedAt.desc())
        .first()
    )

    return render_template(
        "admin_account_info.html",
        account=account,
        admin=admin,
        last_success=last_success
    )


# -------------------------------------------------------------------
# AUDIT LOG HUB (menu)
# -------------------------------------------------------------------
@bp.route("/audit-log", methods=["GET"], endpoint="audit_log")
@login_required
def audit_log():
    """Simple hub that links to individual audit logs."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get all sponsors for the dropdown (distinct to avoid duplicates)
    # First get distinct company names, then get the sponsor objects
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsors = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:  # Only add non-empty company names
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsors.append(sponsor)
    
    # Check if a company is selected
    selected_company = request.args.get("company_filter", "").strip()
    selected_sponsor = None
    if selected_company:
        selected_sponsor = Sponsor.query.filter_by(Company=selected_company).first()
    
    return render_template("admin_audit_log.html", sponsors=sponsors, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Applications Audit Log (moved UI here)
#   URL: /admin/audit-log/applications
# -------------------------------------------------------------------
@bp.route("/audit-log/applications", methods=["GET"], endpoint="audit_applications")
@login_required
def audit_applications():
    """Lists driver applications with optional filters."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    q      = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().lower()  # "", pending, accepted, rejected, reviewed
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    Reviewer = aliased(Account)  # reviewer account (DecisionByAccountID)

    qry = (
        db.session.query(Application, Account, Sponsor, Reviewer)
        .join(Account, Account.AccountID == Application.AccountID)                   # applicant
        .join(Sponsor, Sponsor.SponsorID == Application.SponsorID)                   # sponsor
        .outerjoin(Reviewer, Reviewer.AccountID == Application.DecisionByAccountID)  # reviewer (optional)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(like),
                Account.LastName.ilike(like),
                Account.Email.ilike(like),
                Sponsor.Company.ilike(like),
            )
        )

    if status == "pending":
        qry = qry.filter(Application.ReviewedAt.is_(None), Application.Decision.is_(None))
    elif status == "accepted":
        qry = qry.filter(Application.Decision == "accepted")
    elif status == "rejected":
        qry = qry.filter(Application.Decision == "rejected")
    elif status == "reviewed":
        qry = qry.filter(Application.ReviewedAt.is_not(None))

    # Sponsor filtering
    # Company filtering
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)

    # Date range filtering
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(Application.SubmittedAt >= date_from_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            # Add one day to include the entire end date
            from datetime import timedelta
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(Application.SubmittedAt < date_to_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(
            Application.SubmittedAt.is_(None),
            Application.SubmittedAt.asc(),
        )
    else:  # default to desc
        qry = qry.order_by(
            Application.SubmittedAt.is_(None),
            Application.SubmittedAt.desc(),
        )

    rows = qry.all()
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    return render_template("audit_application.html", rows=rows, q=q, status=status, 
                         company_filter=company_filter, date_from=date_from, date_to=date_to, sort_order=sort_order,
                         selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Point Changes Audit Log
#   URL: /admin/audit-log/point-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/point-changes", methods=["GET"], endpoint="audit_point_changes")
@login_required
def audit_point_changes():
    """Lists point changes with optional filters."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    q = (request.args.get("q") or "").strip()
    company_filter = (request.args.get("company_filter") or "").strip()
    change_type = (request.args.get("change_type") or "").strip()  # "", "positive", "negative"
    reason_filter = (request.args.get("reason") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    # Create aliases for joins
    InitiatorAccount = aliased(Account)  # who initiated the change
    DriverAccount = aliased(Account)     # driver's account info

    qry = (
        db.session.query(PointChange, DriverAccount, InitiatorAccount, Sponsor, Driver)
        .join(Driver, PointChange.DriverID == Driver.DriverID)
        .join(DriverAccount, Driver.AccountID == DriverAccount.AccountID)
        .join(Sponsor, PointChange.SponsorID == Sponsor.SponsorID)
        .outerjoin(InitiatorAccount, InitiatorAccount.AccountID == PointChange.InitiatedByAccountID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                DriverAccount.FirstName.ilike(like),
                DriverAccount.LastName.ilike(like),
                DriverAccount.Email.ilike(like),
                Sponsor.Company.ilike(like),
                PointChange.Reason.ilike(like),
            )
        )

    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)

    if change_type == "positive":
        qry = qry.filter(PointChange.DeltaPoints > 0)
    elif change_type == "negative":
        qry = qry.filter(PointChange.DeltaPoints < 0)

    # Reason filtering
    if reason_filter:
        if reason_filter == "Other":
            # Filter for reasons not in the default lists
            default_positive_reasons = [
                "Safety bonus (no incidents)",
                "On-time delivery streak", 
                "Positive customer feedback",
                "Monthly performance bonus",
                "Training completed",
                "Referral bonus (driver hired)",
                "Holiday bonus",
                "Extra shift / route coverage",
                "Fuel efficiency target met",
                "Special project completion",
                "Attendance milestone"
            ]
            default_negative_reasons = [
                "Late delivery",
                "Missed pickup",
                "Customer complaint",
                "Safety violation (minor)",
                "Safety violation (major)",
                "Equipment misuse / damage",
                "Policy non-compliance",
                "No-show / unapproved absence",
                "Excessive idling / fuel waste",
                "Paperwork error / missing docs",
                "Uniform/branding issue"
            ]
            all_default_reasons = default_positive_reasons + default_negative_reasons + ["Manual adjustment (correction)", "Points Payment"]
            qry = qry.filter(~PointChange.Reason.in_(all_default_reasons))
            # Also exclude order-related reasons that would normalize to "Points Payment"
            qry = qry.filter(~PointChange.Reason.like("Order #ORD-% - Points Payment"))
        elif reason_filter == "Points Payment":
            # Filter for order-related reasons that normalize to "Points Payment"
            qry = qry.filter(PointChange.Reason.like("Order #ORD-% - Points Payment"))
        else:
            qry = qry.filter(PointChange.Reason.ilike(f"%{reason_filter}%"))

    # Date range filtering
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if date_to:
        try:
            from datetime import datetime, timedelta
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            # Add one day to include the entire end date
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(PointChange.CreatedAt < date_to_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(PointChange.CreatedAt.asc())
    else:  # default to desc
        qry = qry.order_by(PointChange.CreatedAt.desc())

    rows = qry.all()
    
    # Get unique sponsors for filter dropdown
    sponsors = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = [sponsor[0] for sponsor in sponsors if sponsor[0]]
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    # Get unique reasons for filter dropdown and normalize order-related reasons
    reasons = db.session.query(PointChange.Reason).distinct().filter(PointChange.Reason.is_not(None)).all()
    reason_list = []
    
    for reason_tuple in reasons:
        reason = reason_tuple[0]
        if reason and reason.startswith("Order #ORD-") and reason.endswith("- Points Payment"):
            # Normalize order-related reasons to "Points Payment"
            normalized_reason = "Points Payment"
        else:
            normalized_reason = reason
        
        # Filter out "Speeding" from the reason list
        if normalized_reason and normalized_reason.lower() != "speeding" and normalized_reason not in reason_list:
            reason_list.append(normalized_reason)
    
    # Define the default reason lists
    default_positive_reasons = [
        "Safety bonus (no incidents)",
        "On-time delivery streak", 
        "Positive customer feedback",
        "Monthly performance bonus",
        "Training completed",
        "Referral bonus (driver hired)",
        "Holiday bonus",
        "Extra shift / route coverage",
        "Fuel efficiency target met",
        "Special project completion",
        "Attendance milestone",
        "Points Payment"
    ]
    
    default_negative_reasons = [
        "Late delivery",
        "Missed pickup",
        "Customer complaint",
        "Safety violation (minor)",
        "Safety violation (major)",
        "Equipment misuse / damage",
        "Policy non-compliance",
        "No-show / unapproved absence",
        "Excessive idling / fuel waste",
        "Paperwork error / missing docs",
        "Uniform/branding issue"
    ]
    
    return render_template("audit_point_changes.html", rows=rows, q=q, company_filter=company_filter, 
                         change_type=change_type, reason_filter=reason_filter, date_from=date_from, 
                         date_to=date_to, sort_order=sort_order, sponsors=sponsor_list, reasons=reason_list,
                         default_positive_reasons=default_positive_reasons, 
                         default_negative_reasons=default_negative_reasons, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Login Activity Audit Log
#   URL: /admin/audit-log/login-activity
# -------------------------------------------------------------------
@bp.route("/audit-log/login-activity", methods=["GET"], endpoint="audit_login_activity")
@login_required
def audit_login_activity():
    """Lists login attempts with optional filters."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    q = (request.args.get("q") or "").strip()
    success_filter = (request.args.get("success") or "").strip()  # "", "true", "false"
    ip_filter = (request.args.get("ip") or "").strip()
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    qry = (
        db.session.query(LoginAttempts, Account)
        .join(Account, LoginAttempts.AccountID == Account.AccountID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(like),
                Account.LastName.ilike(like),
                Account.Email.ilike(like),
                Account.Username.ilike(like),
            )
        )

    if success_filter == "true":
        qry = qry.filter(LoginAttempts.WasSuccessful == True)
    elif success_filter == "false":
        qry = qry.filter(LoginAttempts.WasSuccessful == False)

    if ip_filter:
        qry = qry.filter(LoginAttempts.IPAddress.ilike(f"%{ip_filter}%"))

    # Company filtering - only show login attempts for drivers of the selected company
    if company_filter:
        qry = (
            qry.join(Driver, Driver.AccountID == Account.AccountID)
            .join(SponsorCompany, SponsorCompany.SponsorCompanyID == Driver.SponsorCompanyID)
            .filter(SponsorCompany.CompanyName == company_filter)
        )

    # Date range filtering
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(LoginAttempts.AttemptedAt >= date_from_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if date_to:
        try:
            from datetime import datetime, timedelta
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            # Add one day to include the entire end date
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(LoginAttempts.AttemptedAt < date_to_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(LoginAttempts.AttemptedAt.asc())
    else:  # default to desc
        qry = qry.order_by(LoginAttempts.AttemptedAt.desc())

    rows = qry.all()
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    return render_template("audit_login_activity.html", rows=rows, q=q, success_filter=success_filter, 
                         ip_filter=ip_filter, date_from=date_from, date_to=date_to, sort_order=sort_order,
                         selected_sponsor=selected_sponsor)


# =========================
# ADMIN NOTIFICATION SETTINGS
# =========================
@bp.route("/notification-settings", methods=["GET", "POST"], endpoint="notification_settings")
@login_required
def notification_settings():
    """Display and update admin notification preferences"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Admin account not found", "danger")
        return redirect(url_for("dashboard"))
    
    # Get or create notification preferences
    prefs = AdminNotificationPreferences.get_or_create_for_admin(admin.AdminID)
    
    if request.method == "POST":
        try:
            # Update notification type preferences
            prefs.LoginSuspiciousActivity = request.form.get('login_suspicious_activity') == 'on'
            
            
            db.session.commit()
            flash("Notification preferences updated successfully!", "success")
            return redirect(url_for("admin.notification_settings"))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating notification preferences: {str(e)}", "danger")
            return redirect(url_for("admin.notification_settings"))
    
    return render_template("admin/notification_settings.html", admin=admin, prefs=prefs)


@bp.route("/notification-settings/api/update", methods=["POST"])
@login_required
def update_notification_preference():
    """API endpoint to update individual notification preferences via AJAX"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return jsonify({"success": False, "error": "Admin not found"}), 403
    
    try:
        data = request.get_json()
        preference_name = data.get('preference')
        value = data.get('value', False)
        
        if not preference_name:
            return jsonify({"success": False, "error": "Preference name required"}), 400
        
        # Get or create preferences
        prefs = AdminNotificationPreferences.get_or_create_for_admin(admin.AdminID)
        
        # Update the specific preference
        if hasattr(prefs, preference_name):
            setattr(prefs, preference_name, value)
            db.session.commit()
            return jsonify({"success": True, "message": "Preference updated"})
        else:
            return jsonify({"success": False, "error": "Invalid preference name"}), 400
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# -------------------------------------------------------------------
# Sponsor Profile Changes Audit Log
#   URL: /admin/audit-log/sponsor-profile-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/sponsor-profile-changes", methods=["GET"], endpoint="audit_sponsor_profile_changes")
@login_required
def audit_sponsor_profile_changes():
    """Lists sponsor profile changes with optional filters."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    q = (request.args.get("q") or "").strip()
    company_filter = (request.args.get("company_filter") or "").strip()
    field_filter = (request.args.get("field") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    # Import the audit model
    from app.models import SponsorProfileAudit

    # Create aliases for joins
    SponsorAccount = aliased(Account)  # sponsor's account info
    ChangedByAccount = aliased(Account)  # who made the change

    qry = (
        db.session.query(SponsorProfileAudit, Sponsor, SponsorAccount, ChangedByAccount)
        .join(Sponsor, SponsorProfileAudit.SponsorID == Sponsor.SponsorID)
        .join(SponsorAccount, SponsorProfileAudit.AccountID == SponsorAccount.AccountID)
        .outerjoin(ChangedByAccount, SponsorProfileAudit.ChangedByAccountID == ChangedByAccount.AccountID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                SponsorAccount.FirstName.ilike(like),
                SponsorAccount.LastName.ilike(like),
                SponsorAccount.Email.ilike(like),
                Sponsor.Company.ilike(like),
                SponsorProfileAudit.FieldName.ilike(like),
            )
        )

    if company_filter:
        qry = qry.join(Sponsor, Sponsor.SponsorID == SponsorProfileAudit.SponsorID).filter(Sponsor.Company == company_filter)

    if field_filter:
        qry = qry.filter(SponsorProfileAudit.FieldName == field_filter)

    # Date range filtering
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(SponsorProfileAudit.ChangedAt >= date_from_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            # Add one day to include the entire end date
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(SponsorProfileAudit.ChangedAt < date_to_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(SponsorProfileAudit.ChangedAt.asc())
    else:  # default to desc
        qry = qry.order_by(SponsorProfileAudit.ChangedAt.desc())

    rows = qry.all()
    
    # Get unique sponsors for filter dropdown (avoid duplicates)
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:  # Only add non-empty company names
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))
    
    # Get unique fields for filter dropdown
    fields = db.session.query(SponsorProfileAudit.FieldName).distinct().order_by(SponsorProfileAudit.FieldName).all()
    field_list = [field[0] for field in fields]
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    return render_template("audit_sponsor_profile_changes.html", rows=rows, q=q, 
                         company_filter=company_filter, field_filter=field_filter, 
                         date_from=date_from, date_to=date_to, sort_order=sort_order,
                         sponsors=sponsor_list, fields=field_list, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Admin Profile Changes Audit Log
#   URL: /admin/audit-log/admin-profile-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/admin-profile-changes", methods=["GET"], endpoint="audit_admin_profile_changes")
@login_required
def audit_admin_profile_changes():
    """Lists admin profile changes with optional filters."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    q = (request.args.get("q") or "").strip()
    admin_filter = (request.args.get("admin_filter") or "").strip()
    field_filter = (request.args.get("field") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    # Import the audit model
    from app.models import AdminProfileAudit

    # Create aliases for joins
    AdminAccount = aliased(Account)  # admin's account info
    ChangedByAccount = aliased(Account)  # who made the change

    qry = (
        db.session.query(AdminProfileAudit, Admin, AdminAccount, ChangedByAccount)
        .join(Admin, AdminProfileAudit.AdminID == Admin.AdminID)
        .join(AdminAccount, AdminProfileAudit.AccountID == AdminAccount.AccountID)
        .outerjoin(ChangedByAccount, AdminProfileAudit.ChangedByAccountID == ChangedByAccount.AccountID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                AdminAccount.FirstName.ilike(like),
                AdminAccount.LastName.ilike(like),
                AdminAccount.Email.ilike(like),
                AdminProfileAudit.FieldName.ilike(like),
            )
        )

    if admin_filter:
        qry = qry.filter(AdminProfileAudit.AdminID == admin_filter)

    if field_filter:
        qry = qry.filter(AdminProfileAudit.FieldName == field_filter)

    # Date range filtering
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(AdminProfileAudit.ChangedAt >= date_from_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            # Add one day to include the entire end date
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(AdminProfileAudit.ChangedAt < date_to_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(AdminProfileAudit.ChangedAt.asc())
    else:  # default to desc
        qry = qry.order_by(AdminProfileAudit.ChangedAt.desc())

    rows = qry.all()
    
    # Get unique admins for filter dropdown
    admins = db.session.query(Admin.AdminID, AdminAccount.FirstName, AdminAccount.LastName).join(
        AdminAccount, Admin.AccountID == AdminAccount.AccountID
    ).distinct().order_by(AdminAccount.FirstName, AdminAccount.LastName).all()
    admin_list = [(admin[0], f"{admin[1]} {admin[2]}") for admin in admins]
    
    # Get unique fields for filter dropdown
    fields = db.session.query(AdminProfileAudit.FieldName).distinct().order_by(AdminProfileAudit.FieldName).all()
    field_list = [field[0] for field in fields]
    
    return render_template("audit_admin_profile_changes.html", rows=rows, q=q, 
                         admin_filter=admin_filter, field_filter=field_filter, 
                         date_from=date_from, date_to=date_to, sort_order=sort_order,
                         admins=admin_list, fields=field_list)
    
# -------------------------------------------------------------------
# Driver Profile Changes Audit Log
#   URL: /admin/audit-log/driver-profile-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/driver-profile-changes", methods=["GET"], endpoint="audit_driver_profile_changes")
@login_required
def audit_driver_profile_changes():
    """Lists driver profile changes with optional filters."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    q = (request.args.get("q") or "").strip()
    company_filter = (request.args.get("company_filter") or "").strip()
    field_filter = (request.args.get("field") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    # Import the audit model
    from app.models import DriverProfileAudit

    # Create aliases for joins
    DriverAccount = aliased(Account)  # driver's account info
    ChangedByAccount = aliased(Account)  # who made the change

    qry = (
        db.session.query(DriverProfileAudit, Driver, DriverAccount, ChangedByAccount, Sponsor)
        .join(Driver, DriverProfileAudit.DriverID == Driver.DriverID)
        .join(DriverAccount, DriverProfileAudit.AccountID == DriverAccount.AccountID)
        .outerjoin(ChangedByAccount, DriverProfileAudit.ChangedByAccountID == ChangedByAccount.AccountID)
        .outerjoin(Sponsor, DriverProfileAudit.SponsorID == Sponsor.SponsorID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                DriverAccount.FirstName.ilike(like),
                DriverAccount.LastName.ilike(like),
                DriverAccount.Email.ilike(like),
                DriverProfileAudit.FieldName.ilike(like),
                Sponsor.Company.ilike(like),
            )
        )

    if company_filter:
        qry = qry.join(Sponsor, Sponsor.SponsorID == DriverProfileAudit.SponsorID).filter(Sponsor.Company == company_filter)

    if field_filter:
        qry = qry.filter(DriverProfileAudit.FieldName == field_filter)

    # Date range filtering
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(DriverProfileAudit.ChangedAt >= date_from_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter
    
    if date_to:
        try:
            from datetime import datetime, timedelta
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            # Add one day to include the entire end date
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(DriverProfileAudit.ChangedAt < date_to_obj)
        except ValueError:
            pass  # Invalid date format, ignore filter

    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(DriverProfileAudit.ChangedAt.asc())
    else:  # default to desc
        qry = qry.order_by(DriverProfileAudit.ChangedAt.desc())

    rows = qry.all()
    
    # Get unique sponsors for filter dropdown (avoid duplicates)
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:  # Only add non-empty company names
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))
    
    # Get unique fields for filter dropdown
    fields = db.session.query(DriverProfileAudit.FieldName).distinct().order_by(DriverProfileAudit.FieldName).all()
    field_list = [field[0] for field in fields]
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    return render_template("audit_driver_profile_changes.html", rows=rows, q=q, 
                         company_filter=company_filter, field_filter=field_filter, 
                         date_from=date_from, date_to=date_to, sort_order=sort_order,
                         sponsors=sponsor_list, fields=field_list, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Admin Point Settings Audit Log
#   URL: /admin/audit-log/point-settings-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/point-settings-changes", methods=["GET"], endpoint="audit_point_settings_changes")
@login_required
def audit_point_settings_changes():
    """Audit log for point conversion rate and per-transaction limit changes."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get filter parameters
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    field_filter = request.args.get("field_filter", "").strip()
    company_filter = request.args.get("company_filter", "").strip()
    sort_order = request.args.get("sort", "desc").strip()
    
    # Build query for sponsor profile audit data
    # Create aliases for the Account table to join both the sponsor account and the changed-by account
    SponsorAccount = aliased(Account)
    ChangedByAccount = aliased(Account)
    
    qry = (
        db.session.query(SponsorProfileAudit, Sponsor, SponsorAccount, ChangedByAccount)
        .join(Sponsor, Sponsor.SponsorID == SponsorProfileAudit.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == SponsorProfileAudit.AccountID)
        .outerjoin(ChangedByAccount, ChangedByAccount.AccountID == SponsorProfileAudit.ChangedByAccountID)
        .filter(SponsorProfileAudit.FieldName.in_([
            'PointToDollarRate', 'MinPointsPerTxn', 'MaxPointsPerTxn'
        ]))
    )
    
    # Date filtering
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(SponsorProfileAudit.ChangedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(SponsorProfileAudit.ChangedAt <= date_to_obj)
        except ValueError:
            pass
    
    # Field filtering
    if field_filter:
        qry = qry.filter(SponsorProfileAudit.FieldName == field_filter)
    
    # Company filtering
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)
    
    # Search functionality
    if q:
        search_filter = or_(
            Sponsor.Company.ilike(f"%{q}%"),
            SponsorAccount.FirstName.ilike(f"%{q}%"),
            SponsorAccount.LastName.ilike(f"%{q}%"),
            SponsorAccount.Email.ilike(f"%{q}%"),
            SponsorProfileAudit.FieldName.ilike(f"%{q}%"),
            SponsorProfileAudit.OldValue.ilike(f"%{q}%"),
            SponsorProfileAudit.NewValue.ilike(f"%{q}%"),
            SponsorProfileAudit.ChangeReason.ilike(f"%{q}%")
        )
        qry = qry.filter(search_filter)
    
    # Order by most recent first or least recent first
    if sort_order == "asc":
        qry = qry.order_by(SponsorProfileAudit.ChangedAt.asc())
    else:
        qry = qry.order_by(SponsorProfileAudit.ChangedAt.desc())
    
    rows = qry.all()
    
    # Get distinct companies for dropdown
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsors = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsors.append(sponsor)
    
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    return render_template("audit_point_settings_changes.html", rows=rows, 
                         q=q, date_from=date_from, date_to=date_to, field_filter=field_filter,
                         company_filter=company_filter, selected_sponsor=selected_sponsor, 
                         sponsors=sponsors, sort_order=sort_order)


# ============================================================================
# ANALYTICS SYSTEM
# ============================================================================

# -------------------------------------------------------------------
# Analytics Hub
#   URL: /admin/analytics
# -------------------------------------------------------------------
@bp.route("/analytics", methods=["GET"], endpoint="analytics")
@login_required
def analytics():
    """Analytics hub page with different report tools."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get all sponsors for the dropdown (distinct to avoid duplicates)
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsors = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:  # Only add non-empty company names
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsors.append(sponsor)
    
    # Check if a company is selected
    selected_company = request.args.get("company_filter", "").strip()
    selected_sponsor = None
    if selected_company:
        selected_sponsor = Sponsor.query.filter_by(Company=selected_company).first()
    
    return render_template("admin_analytics.html", sponsors=sponsors, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Driver Performance Analytics
#   URL: /admin/analytics/driver-performance
# -------------------------------------------------------------------
@bp.route("/analytics/driver-performance", methods=["GET"], endpoint="analytics_driver_performance")
@login_required
def analytics_driver_performance():
    """Driver performance analytics with metrics and trends."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_filter = (request.args.get("driver_filter") or "").strip()
    
    # Build query for driver performance data
    qry = (
        db.session.query(Driver, Account, SponsorCompany, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == Driver.SponsorCompanyID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
    )
    
    # Company filtering
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    # Driver filtering - search by name or email
    if driver_filter:
        search_term = f"%{driver_filter}%"
        # Use case-insensitive search (ILIKE works in SQLAlchemy, translates to appropriate SQL)
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(search_term),
                Account.LastName.ilike(search_term),
                Account.Email.ilike(search_term),
                func.concat(Account.FirstName, ' ', Account.LastName).ilike(search_term)
            )
        )
    
    # Date filtering - only apply if PointChange exists (don't exclude drivers without point changes)
    # If both date filters are set, combine them; otherwise apply individually
    if date_from or date_to:
        date_conditions = []
        
        if date_from:
            try:
                from datetime import datetime
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
                date_conditions.append(PointChange.CreatedAt >= date_from_obj)
            except ValueError:
                pass
        
        if date_to:
            try:
                from datetime import datetime
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
                date_conditions.append(PointChange.CreatedAt <= date_to_obj)
            except ValueError:
                pass
        
        # If we have date conditions, apply them but also include rows with no PointChange
        if date_conditions:
            # Combine all date conditions with AND, then OR with NULL
            combined_condition = and_(*date_conditions) if len(date_conditions) > 1 else date_conditions[0]
            qry = qry.filter(
                or_(
                    combined_condition,
                    PointChange.CreatedAt.is_(None)
                )
            )
    
    # Order by most recent first, N/A dates last
    # Use CASE to put NULL dates at the end (1), then order by CreatedAt DESC
    # This ensures rows with dates come first (sorted DESC), then rows without dates
    qry = qry.order_by(
        case((PointChange.CreatedAt.is_(None), 1), else_=0).asc(),
        PointChange.CreatedAt.desc()
    )
    
    rows = qry.all()
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    # Get unique sponsors for filter dropdown
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))
    
    return render_template("analytics_driver_performance.html", rows=rows, 
                         company_filter=company_filter, date_from=date_from, date_to=date_to,
                         driver_filter=driver_filter,
                         sponsors=sponsor_list, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Driver Performance Analytics PDF Export
#   URL: /admin/analytics/driver-performance/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/driver-performance/pdf", methods=["GET"], endpoint="analytics_driver_performance_pdf")
@login_required
def analytics_driver_performance_pdf():
    """Generate a PDF version of the driver performance analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    # Get filter parameters (same as regular report)
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_filter = (request.args.get("driver_filter") or "").strip()
    
    # Build query (same as regular report)
    qry = (
        db.session.query(Driver, Account, SponsorCompany, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == Driver.SponsorCompanyID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
    )
    
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    if driver_filter:
        search_term = f"%{driver_filter}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(search_term),
                Account.LastName.ilike(search_term),
                Account.Email.ilike(search_term),
                func.concat(Account.FirstName, ' ', Account.LastName).ilike(search_term)
            )
        )
    
    if date_from or date_to:
        date_conditions = []
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
                date_conditions.append(PointChange.CreatedAt >= date_from_obj)
            except ValueError:
                pass
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
                date_conditions.append(PointChange.CreatedAt <= date_to_obj)
            except ValueError:
                pass
        if date_conditions:
            combined_condition = and_(*date_conditions) if len(date_conditions) > 1 else date_conditions[0]
            qry = qry.filter(
                or_(
                    combined_condition,
                    PointChange.CreatedAt.is_(None)
                )
            )
    
    qry = qry.order_by(
        case((PointChange.CreatedAt.is_(None), 1), else_=0).asc(),
        PointChange.CreatedAt.desc()
    )
    
    rows = qry.all()
    
    # Generate PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#111827'),
        spaceAfter=30,
        alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#374151'),
        spaceAfter=10,
    )
    
    elements.append(Paragraph("Driver Performance Analytics Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Records:</b> {len(rows)}", styles['Normal']))
    
    filter_info = "Filters: "
    filters = []
    if company_filter:
        filters.append(f"Company: {company_filter}")
    if driver_filter:
        filters.append(f"Driver: {driver_filter}")
    if date_from:
        filters.append(f"From: {date_from}")
    if date_to:
        filters.append(f"To: {date_to}")
    
    if filters:
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>{filter_info}{'; '.join(filters)}</b>", styles['Normal']))
    else:
        elements.append(Paragraph("<b>Filters: None (All records)</b>", styles['Normal']))
    
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("Driver Performance Data", heading_style))
    
    if rows:
        # Create a smaller font style for table content
        small_style = ParagraphStyle(
            'TableContent',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
        )
        
        # Use Paragraph for header to ensure consistent formatting
        table_data = [[
            Paragraph('<b>Driver Name</b>', small_style),
            Paragraph('<b>Email</b>', small_style),
            Paragraph('<b>Company</b>', small_style),
            Paragraph('<b>Points Change</b>', small_style),
            Paragraph('<b>Balance After</b>', small_style),
            Paragraph('<b>Reason</b>', small_style),
            Paragraph('<b>Date</b>', small_style)
        ]]
        
        for driver, account, sponsor_company, point_change in rows:
            driver_name = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
            email = account.Email or "N/A"
            company = sponsor_company.CompanyName if sponsor_company else "N/A"
            points = f"{point_change.DeltaPoints}" if point_change and point_change.DeltaPoints is not None else "N/A"
            balance = f"{point_change.BalanceAfter}" if point_change and point_change.BalanceAfter is not None else "N/A"
            # Use Paragraph for reason to allow text wrapping
            reason = point_change.Reason if point_change and point_change.Reason else "N/A"
            reason_para = Paragraph(reason, small_style) if reason != "N/A" else "N/A"
            date_str = point_change.CreatedAt.strftime('%m/%d/%Y %H:%M') if point_change and point_change.CreatedAt else "N/A"
            
            # Use Paragraph for longer text fields to allow wrapping
            driver_name_para = Paragraph(driver_name, small_style)
            email_para = Paragraph(email, small_style)
            company_para = Paragraph(company, small_style)
            
            table_data.append([driver_name_para, email_para, company_para, points, balance, reason_para, date_str])
        
        # Adjusted column widths for landscape letter (11" x 8.5") minus margins (1" total) = 10" usable width
        # Distribute more space to Email, Company, and Reason columns which tend to be longer
        # Total: 1.3 + 2.2 + 1.9 + 0.8 + 0.9 + 2.5 + 1.1 = 10.7" (slightly over, will auto-adjust proportionally)
        table = Table(table_data, colWidths=[1.3*inch, 2.2*inch, 1.9*inch, 0.8*inch, 0.9*inch, 2.5*inch, 1.1*inch])
        
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('FONTSIZE', (0, 1), (-1, -1), 8),  # Smaller font for data rows
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No records found matching the current filters.", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_performance_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    return response


# -------------------------------------------------------------------
# Driver Performance Analytics CSV Export
#   URL: /admin/analytics/driver-performance/csv
# -------------------------------------------------------------------
@bp.route("/analytics/driver-performance/csv", methods=["GET"], endpoint="analytics_driver_performance_csv")
@login_required
def analytics_driver_performance_csv():
    """Generate a CSV version of the driver performance analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    # Get filter parameters (same as regular report)
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_filter = (request.args.get("driver_filter") or "").strip()
    
    # Build query (same as regular report)
    qry = (
        db.session.query(Driver, Account, SponsorCompany, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == Driver.SponsorCompanyID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
    )
    
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    if driver_filter:
        search_term = f"%{driver_filter}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(search_term),
                Account.LastName.ilike(search_term),
                Account.Email.ilike(search_term),
                func.concat(Account.FirstName, ' ', Account.LastName).ilike(search_term)
            )
        )
    
    if date_from or date_to:
        date_conditions = []
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
                date_conditions.append(PointChange.CreatedAt >= date_from_obj)
            except ValueError:
                pass
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
                date_conditions.append(PointChange.CreatedAt <= date_to_obj)
            except ValueError:
                pass
        if date_conditions:
            combined_condition = and_(*date_conditions) if len(date_conditions) > 1 else date_conditions[0]
            qry = qry.filter(
                or_(
                    combined_condition,
                    PointChange.CreatedAt.is_(None)
                )
            )
    
    qry = qry.order_by(
        case((PointChange.CreatedAt.is_(None), 1), else_=0).asc(),
        PointChange.CreatedAt.desc()
    )
    
    rows = qry.all()
    
    # Generate CSV
    output = BytesIO()
    header = "Driver Name|Email|Company|Points Change|Balance After|Reason|Date\n"
    output.write(header.encode('utf-8'))
    
    for driver, account, sponsor_company, point_change in rows:
        driver_name = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
        email = account.Email or "N/A"
        company = sponsor_company.CompanyName if sponsor_company else "N/A"
        points = point_change.DeltaPoints if point_change and point_change.DeltaPoints is not None else "N/A"
        balance = point_change.BalanceAfter if point_change and point_change.BalanceAfter is not None else "N/A"
        reason = (point_change.Reason or "N/A").replace("|", " ").replace("\n", " ")
        date_str = point_change.CreatedAt.strftime('%Y-%m-%d %H:%M') if point_change and point_change.CreatedAt else "N/A"
        
        row = f"{driver_name}|{email}|{company}|{points}|{balance}|{reason}|{date_str}\n"
        output.write(row.encode('utf-8'))
    
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_performance_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return response


# -------------------------------------------------------------------
# Sponsor Analytics
#   URL: /admin/analytics/sponsor-analytics
# -------------------------------------------------------------------
@bp.route("/analytics/sponsor-analytics", methods=["GET"], endpoint="analytics_sponsor_analytics")
@login_required
def analytics_sponsor_analytics():
    """Sponsor analytics with company metrics and comparisons."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    # Build query for sponsor analytics data
    qry = (
        db.session.query(Sponsor, Account, SponsorCompany, Driver, PointChange)
        .join(Account, Account.AccountID == Sponsor.AccountID)
        .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == Sponsor.SponsorCompanyID)
        .outerjoin(
            DriverSponsor,
            and_(
                DriverSponsor.SponsorID == Sponsor.SponsorID,
                DriverSponsor.Status == "ACTIVE",
            ),
        )
        .outerjoin(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
    )
    
    # Company filtering
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    # Date filtering
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    rows = qry.all()
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    # Get unique sponsors for filter dropdown
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))
    
    return render_template("analytics_sponsor_analytics.html", rows=rows, 
                         company_filter=company_filter, date_from=date_from, date_to=date_to,
                         sponsors=sponsor_list, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Sponsor Analytics PDF Export
#   URL: /admin/analytics/sponsor-analytics/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/sponsor-analytics/pdf", methods=["GET"], endpoint="analytics_sponsor_analytics_pdf")
@login_required
def analytics_sponsor_analytics_pdf():
    """Generate a PDF version of the sponsor analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    qry = (
        db.session.query(Sponsor, Account, SponsorCompany, Driver, PointChange)
        .join(Account, Account.AccountID == Sponsor.AccountID)
        .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == Sponsor.SponsorCompanyID)
        .outerjoin(
            DriverSponsor,
            and_(
                DriverSponsor.SponsorID == Sponsor.SponsorID,
                DriverSponsor.Status == "ACTIVE",
            ),
        )
        .outerjoin(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
    )
    
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    rows = qry.all()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#111827'),
        spaceAfter=30,
        alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#374151'),
        spaceAfter=10,
    )
    
    elements.append(Paragraph("Sponsor Analytics Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Records:</b> {len(rows)}", styles['Normal']))
    
    filter_info = "Filters: "
    filters = []
    if company_filter:
        filters.append(f"Company: {company_filter}")
    if date_from:
        filters.append(f"From: {date_from}")
    if date_to:
        filters.append(f"To: {date_to}")
    
    if filters:
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>{filter_info}{'; '.join(filters)}</b>", styles['Normal']))
    else:
        elements.append(Paragraph("<b>Filters: None (All records)</b>", styles['Normal']))
    
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("Sponsor Performance Data", heading_style))
    
    if rows:
        # Create a smaller font style for table content
        small_style = ParagraphStyle(
            'TableContent',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
        )
        
        # Use Paragraph for header
        table_data = [[
            Paragraph('<b>Company</b>', small_style),
            Paragraph('<b>Contact Name</b>', small_style),
            Paragraph('<b>Email</b>', small_style),
            Paragraph('<b>Point Rate</b>', small_style),
            Paragraph('<b>Min Points</b>', small_style),
            Paragraph('<b>Max Points</b>', small_style),
            Paragraph('<b>Points Issued</b>', small_style),
            Paragraph('<b>Last Activity</b>', small_style)
        ]]
        
        for sponsor, account, sponsor_company, driver, point_change in rows:
            company = sponsor_company.CompanyName if sponsor_company else sponsor.Company
            contact = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
            email = account.Email or "N/A"
            rate = f"${sponsor.PointToDollarRate:.2f}"
            min_pts = sponsor.MinPointsPerTxn or "N/A"
            max_pts = sponsor.MaxPointsPerTxn or "N/A"
            points = f"{point_change.DeltaPoints}" if point_change and point_change.DeltaPoints is not None else "N/A"
            date_str = point_change.CreatedAt.strftime('%m/%d/%Y %H:%M') if point_change and point_change.CreatedAt else "N/A"
            
            # Use Paragraph for text fields to allow wrapping
            company_para = Paragraph(company, small_style)
            contact_para = Paragraph(contact, small_style)
            email_para = Paragraph(email, small_style)
            
            table_data.append([company_para, contact_para, email_para, rate, str(min_pts), str(max_pts), points, date_str])
        
        # Adjusted column widths: 1.8 + 1.5 + 2.0 + 0.9 + 0.8 + 0.8 + 1.0 + 1.2 = 10.0"
        table = Table(table_data, colWidths=[1.8*inch, 1.5*inch, 2.0*inch, 0.9*inch, 0.8*inch, 0.8*inch, 1.0*inch, 1.2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No records found matching the current filters.", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=sponsor_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    return response


# -------------------------------------------------------------------
# Sponsor Analytics CSV Export
#   URL: /admin/analytics/sponsor-analytics/csv
# -------------------------------------------------------------------
@bp.route("/analytics/sponsor-analytics/csv", methods=["GET"], endpoint="analytics_sponsor_analytics_csv")
@login_required
def analytics_sponsor_analytics_csv():
    """Generate a CSV version of the sponsor analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    qry = (
        db.session.query(Sponsor, Account, SponsorCompany, Driver, PointChange)
        .join(Account, Account.AccountID == Sponsor.AccountID)
        .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == Sponsor.SponsorCompanyID)
        .outerjoin(
            DriverSponsor,
            and_(
                DriverSponsor.SponsorID == Sponsor.SponsorID,
                DriverSponsor.Status == "ACTIVE",
            ),
        )
        .outerjoin(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
    )
    
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    rows = qry.all()
    
    output = BytesIO()
    header = "Company|Contact Name|Email|Point Rate|Min Points|Max Points|Points Issued|Last Activity\n"
    output.write(header.encode('utf-8'))
    
    for sponsor, account, sponsor_company, driver, point_change in rows:
        company = sponsor_company.CompanyName if sponsor_company else sponsor.Company
        contact = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
        email = account.Email or "N/A"
        rate = f"{sponsor.PointToDollarRate:.2f}"
        min_pts = sponsor.MinPointsPerTxn or "N/A"
        max_pts = sponsor.MaxPointsPerTxn or "N/A"
        points = point_change.DeltaPoints if point_change and point_change.DeltaPoints is not None else "N/A"
        date_str = point_change.CreatedAt.strftime('%Y-%m-%d %H:%M') if point_change and point_change.CreatedAt else "N/A"
        
        row = f"{company}|{contact}|{email}|{rate}|{min_pts}|{max_pts}|{points}|{date_str}\n"
        output.write(row.encode('utf-8'))
    
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=sponsor_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return response


# -------------------------------------------------------------------
# Financial Analytics
#   URL: /admin/analytics/financial-analytics
# -------------------------------------------------------------------
@bp.route("/analytics/financial-analytics", methods=["GET"], endpoint="analytics_financial_analytics")
@login_required
def analytics_financial_analytics():
    """Financial analytics with point values, costs, and ROI calculations."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    # Build query for financial analytics data
    # Only include purchases and refunds (exclude manual adjustments and dispute resolutions)
    qry = (
        db.session.query(Sponsor, PointChange, Driver, Account)
        .join(PointChange, PointChange.SponsorID == Sponsor.SponsorID)
        .join(Driver, Driver.DriverID == PointChange.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .filter(
            or_(
                # Purchases
                PointChange.Reason.like("Order #% - Points Payment"),
                PointChange.Reason.like("Re-order #% - Points Payment"),
                # Refunds
                PointChange.Reason.like("Refund for Order #%"),
                PointChange.Reason.like("Order #% - Cancellation Refund")
            )
        )
    )
    
    # Company filtering
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)
    
    # Date filtering
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    rows = qry.all()
    
    # Get selected sponsor info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()
    
    # Get unique sponsors for filter dropdown
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))
    
    return render_template("analytics_financial_analytics.html", rows=rows, 
                         company_filter=company_filter, date_from=date_from, date_to=date_to,
                         sponsors=sponsor_list, selected_sponsor=selected_sponsor)


# -------------------------------------------------------------------
# Financial Analytics PDF Export
#   URL: /admin/analytics/financial-analytics/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/financial-analytics/pdf", methods=["GET"], endpoint="analytics_financial_analytics_pdf")
@login_required
def analytics_financial_analytics_pdf():
    """Generate a PDF version of the financial analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    qry = (
        db.session.query(Sponsor, PointChange, Driver, Account)
        .join(PointChange, PointChange.SponsorID == Sponsor.SponsorID)
        .join(Driver, Driver.DriverID == PointChange.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .filter(
            or_(
                PointChange.Reason.like("Order #% - Points Payment"),
                PointChange.Reason.like("Re-order #% - Points Payment"),
                PointChange.Reason.like("Refund for Order #%"),
                PointChange.Reason.like("Order #% - Cancellation Refund")
            )
        )
    )
    
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    rows = qry.all()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#111827'),
        spaceAfter=30,
        alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#374151'),
        spaceAfter=10,
    )
    
    elements.append(Paragraph("Financial Analytics Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Transactions:</b> {len(rows)}", styles['Normal']))
    
    # Calculate totals
    total_points = sum(pc.DeltaPoints for _, pc, _, _ in rows if pc and pc.DeltaPoints)
    total_value = sum(pc.DeltaPoints * sponsor.PointToDollarRate for sponsor, pc, _, _ in rows if pc and pc.DeltaPoints)
    elements.append(Paragraph(f"<b>Total Points:</b> {total_points:,}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Dollar Value:</b> ${total_value:,.2f}", styles['Normal']))
    
    filter_info = "Filters: "
    filters = []
    if company_filter:
        filters.append(f"Company: {company_filter}")
    if date_from:
        filters.append(f"From: {date_from}")
    if date_to:
        filters.append(f"To: {date_to}")
    
    if filters:
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>{filter_info}{'; '.join(filters)}</b>", styles['Normal']))
    else:
        elements.append(Paragraph("<b>Filters: None (All transactions)</b>", styles['Normal']))
    
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("Financial Transaction Data", heading_style))
    
    if rows:
        # Create a smaller font style for table content
        small_style = ParagraphStyle(
            'TableContent',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
        )
        
        # Use Paragraph for header
        table_data = [[
            Paragraph('<b>Company</b>', small_style),
            Paragraph('<b>Driver Name</b>', small_style),
            Paragraph('<b>Driver Email</b>', small_style),
            Paragraph('<b>Points Change</b>', small_style),
            Paragraph('<b>Point Rate</b>', small_style),
            Paragraph('<b>Dollar Value</b>', small_style),
            Paragraph('<b>Reason</b>', small_style),
            Paragraph('<b>Date</b>', small_style)
        ]]
        
        for sponsor, point_change, driver, account in rows:
            company = sponsor.Company
            driver_name = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
            driver_email = account.Email if account.Email else "N/A"
            points = point_change.DeltaPoints if point_change.DeltaPoints is not None else 0
            rate = f"${sponsor.PointToDollarRate:.2f}"
            dollar_value = points * sponsor.PointToDollarRate
            reason = point_change.Reason if point_change.Reason else "N/A"
            date_str = point_change.CreatedAt.strftime('%m/%d/%Y %H:%M') if point_change.CreatedAt else "N/A"
            
            # Use Paragraph for text fields to allow wrapping
            company_para = Paragraph(company, small_style)
            driver_name_para = Paragraph(driver_name, small_style)
            driver_email_para = Paragraph(driver_email, small_style)
            reason_para = Paragraph(reason, small_style) if reason != "N/A" else "N/A"
            
            table_data.append([company_para, driver_name_para, driver_email_para, str(points), rate, f"${dollar_value:.2f}", reason_para, date_str])
        
        # Adjusted column widths for landscape letter (11" x 8.5") minus margins (1" total) = 10" usable width
        # Total: 1.4 + 1.3 + 1.8 + 0.8 + 0.8 + 1.0 + 2.0 + 0.9 = 10.0"
        table = Table(table_data, colWidths=[1.4*inch, 1.3*inch, 1.8*inch, 0.8*inch, 0.8*inch, 1.0*inch, 2.0*inch, 0.9*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No transactions found matching the current filters.", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=financial_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    return response


# -------------------------------------------------------------------
# Financial Analytics CSV Export
#   URL: /admin/analytics/financial-analytics/csv
# -------------------------------------------------------------------
@bp.route("/analytics/financial-analytics/csv", methods=["GET"], endpoint="analytics_financial_analytics_csv")
@login_required
def analytics_financial_analytics_csv():
    """Generate a CSV version of the financial analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    company_filter = (request.args.get("company_filter") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    qry = (
        db.session.query(Sponsor, PointChange, Driver, Account)
        .join(PointChange, PointChange.SponsorID == Sponsor.SponsorID)
        .join(Driver, Driver.DriverID == PointChange.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .filter(
            or_(
                PointChange.Reason.like("Order #% - Points Payment"),
                PointChange.Reason.like("Re-order #% - Points Payment"),
                PointChange.Reason.like("Refund for Order #%"),
                PointChange.Reason.like("Order #% - Cancellation Refund")
            )
        )
    )
    
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    rows = qry.all()
    
    output = BytesIO()
    header = "Company|Driver Name|Driver Email|Points Change|Point Rate|Dollar Value|Reason|Date\n"
    output.write(header.encode('utf-8'))
    
    for sponsor, point_change, driver, account in rows:
        company = sponsor.Company
        driver_name = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
        driver_email = account.Email if account.Email else "N/A"
        points = point_change.DeltaPoints if point_change.DeltaPoints is not None else 0
        rate = f"{sponsor.PointToDollarRate:.2f}"
        dollar_value = points * sponsor.PointToDollarRate
        reason = (point_change.Reason or "N/A").replace("|", " ").replace("\n", " ")
        date_str = point_change.CreatedAt.strftime('%Y-%m-%d %H:%M') if point_change.CreatedAt else "N/A"
        
        row = f"{company}|{driver_name}|{driver_email}|{points}|{rate}|{dollar_value:.2f}|{reason}|{date_str}\n"
        output.write(row.encode('utf-8'))
    
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=financial_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return response


# -------------------------------------------------------------------
# Invoice Center
#   URL: /admin/analytics/invoices
# -------------------------------------------------------------------
@bp.route("/analytics/invoices", methods=["GET"], endpoint="analytics_invoices")
@login_required
def analytics_invoices():
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    company_filter = (request.args.get("company_filter") or "").strip()
    invoice_month = (request.args.get("invoice_month") or "").strip()
    if invoice_month:
        try:
            datetime.strptime(invoice_month, "%Y-%m")
        except ValueError:
            invoice_month = ""
    current_month_value = datetime.utcnow().strftime("%Y-%m")
    if not invoice_month:
        invoice_month = current_month_value

    selected_sponsor = None
    if company_filter:
        selected_sponsor = Sponsor.query.filter_by(Company=company_filter).first()

    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))

    try:
        month_display = datetime.strptime(invoice_month, "%Y-%m").strftime("%B %Y")
    except ValueError:
        month_display = invoice_month

    return render_template(
        "analytics_invoices.html",
        company_filter=company_filter,
        selected_month=invoice_month,
        selected_month_display=month_display,
        current_month=current_month_value,
        sponsors=sponsor_list,
        selected_sponsor=selected_sponsor,
    )


# -------------------------------------------------------------------
# Invoice Log
#   URL: /admin/analytics/invoices/log
# -------------------------------------------------------------------
@bp.route("/analytics/invoices/log", methods=["GET"], endpoint="analytics_invoice_log")
@login_required
def analytics_invoice_log():
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    company_filter = (request.args.get("company_filter") or "").strip()
    start_month = (request.args.get("start_month") or "").strip()
    end_month = (request.args.get("end_month") or "").strip()

    def _normalize_month(value: str) -> str:
        if not value:
            return ""
        try:
            datetime.strptime(value, "%Y-%m")
            return value
        except ValueError:
            return ""

    start_month = _normalize_month(start_month)
    end_month = _normalize_month(end_month)

    if start_month and end_month and start_month > end_month:
        start_month, end_month = end_month, start_month

    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))

    try:
        invoice_log = InvoiceService.get_invoice_log(
            company_filter or None,
            start_month or None,
            end_month or None,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        invoice_log = []

    return render_template(
        "analytics_invoice_log.html",
        company_filter=company_filter,
        sponsors=sponsor_list,
        start_month=start_month,
        end_month=end_month,
        invoice_log=invoice_log,
    )


@bp.route("/analytics/invoices/<invoice_id>", methods=["GET"], endpoint="analytics_invoice_detail")
@login_required
def analytics_invoice_detail(invoice_id):
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    try:
        invoice_payload = InvoiceService.get_invoice_by_id(invoice_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.analytics_invoice_log"))
    except Exception:
        current_app.logger.exception("Failed to load invoice %s", invoice_id)
        flash("Unable to load invoice.", "danger")
        return redirect(url_for("admin.analytics_invoice_log"))

    statuses = ["PENDING", "PAID"]
    return render_template("analytics_invoice_detail.html", invoice_payload=invoice_payload, statuses=statuses)
@bp.route("/analytics/invoices/<invoice_id>/status", methods=["POST"], endpoint="analytics_invoice_update_status")
@login_required
def analytics_invoice_update_status(invoice_id):
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    status = (request.form.get("status") or "").strip()

    try:
        InvoiceService.update_invoice_status(invoice_id, status, current_user.AccountID)
        flash("Invoice status updated.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    except Exception:
        current_app.logger.exception("Failed to update invoice status %s", invoice_id)
        flash("Unable to update invoice status.", "danger")

    return redirect(url_for("admin.analytics_invoice_detail", invoice_id=invoice_id))


@bp.route("/analytics/invoices/<invoice_id>/pdf", methods=["GET"], endpoint="analytics_invoice_pdf")
@login_required
def analytics_invoice_pdf(invoice_id):
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    try:
        invoice_payload = InvoiceService.get_invoice_by_id(invoice_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.analytics_invoice_log"))
    except Exception:
        current_app.logger.exception("Failed to build invoice PDF %s", invoice_id)
        flash("Unable to generate invoice PDF.", "danger")
        return redirect(url_for("admin.analytics_invoice_log"))

    invoice = invoice_payload["invoice"]
    sponsor = invoice_payload["sponsor"]
    orders = invoice_payload["orders"]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=22,
        alignment=1,
        spaceAfter=18,
    )
    meta_style = ParagraphStyle(
        'InvoiceMeta',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=6,
    )

    elements.append(Paragraph("Sponsor Invoice", title_style))

    elements.append(Paragraph(f"<b>Company:</b> {sponsor['company']}", meta_style))
    elements.append(Paragraph(f"<b>Invoice Month:</b> {invoice['invoice_month']}", meta_style))
    elements.append(Paragraph(f"<b>Period:</b> {invoice['period_start'][:10]} → {invoice['period_end'][:10]}", meta_style))
    generated_at = invoice['generated_at'] or "Draft"
    elements.append(Paragraph(f"<b>Generated At:</b> {generated_at}", meta_style))
    elements.append(Paragraph(f"<b>Total Orders:</b> {invoice['total_orders']}", meta_style))
    elements.append(Paragraph(f"<b>Total Points:</b> {invoice['total_points']:,}", meta_style))
    elements.append(Paragraph(f"<b>Total Amount:</b> ${invoice['total_amount']:,.2f}", meta_style))
    elements.append(Paragraph(f"<b>Status:</b> {invoice.get('status', 'PENDING')}", meta_style))
    elements.append(Spacer(1, 0.2 * inch))

    order_heading_style = ParagraphStyle(
        'InvoiceOrderHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=12,
        spaceAfter=6,
    )

    order_meta_label_style = ParagraphStyle(
        'InvoiceOrderMetaLabel',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#6b7280'),
    )

    order_meta_value_style = ParagraphStyle(
        'InvoiceOrderMetaValue',
        parent=styles['Normal'],
        fontSize=11,
    )

    line_item_header_style = ParagraphStyle(
        'InvoiceLineItemHeader',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#111827'),
        leading=14,
    )

    elements.append(Paragraph("Orders", order_heading_style))

    def wrap_text(text: str | None, width: int = 50):
        if not text:
            return ""
        text = str(text)
        if len(text) <= width:
            return text
        lines = []
        current = ""
        for word in text.split():
            if len(current) + len(word) + 1 > width:
                lines.append(current.strip())
                current = ""
            current += word + " "
        if current:
            lines.append(current.strip())
        return "\n".join(lines)

    for order in orders:
        order_number = order["order_number"] or "—"
        order_date = order["order_created_at"][:10] if order["order_created_at"] else "—"
        driver_name = order["driver_name"] or "—"
        driver_email = wrap_text(order["driver_email"] or "—")

        elements.append(Paragraph(f"Order {order_number}", order_heading_style))

        order_meta_table = Table(
            [
                [
                    Paragraph("<b>Date</b>", order_meta_label_style),
                    Paragraph(order_date, order_meta_value_style),
                    Paragraph("<b>Driver</b>", order_meta_label_style),
                    Paragraph(driver_name, order_meta_value_style),
                ],
                [
                    Paragraph("<b>Driver Email</b>", order_meta_label_style),
                    Paragraph(driver_email, order_meta_value_style),
                    Paragraph("<b>Order Points</b>", order_meta_label_style),
                    Paragraph(f"{order['total_points']:,}", order_meta_value_style),
                ],
                [
                    Paragraph("<b>Order Amount</b>", order_meta_label_style),
                    Paragraph(f"${order['total_amount']:,.2f}", order_meta_value_style),
                    "", ""
                ],
            ],
            colWidths=[1.2*inch, 2.0*inch, 1.2*inch, 2.6*inch],
        )
        order_meta_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(order_meta_table)

        line_items = order.get("line_items", [])
        if line_items:
            item_table_data = [
                ["Item", "Qty", "Unit Pts", "Line Pts", "Line Amount"]
            ]
            for item in line_items:
                title = wrap_text(item["title"] or "—")
                item_table_data.append([
                    title,
                    str(item["quantity"]),
                    str(item["unit_points"]),
                    f"{item['line_total_points']:,}",
                    f"${item['line_total_amount']:,.2f}",
                ])
            item_table = Table(
                item_table_data,
                colWidths=[3.8*inch, 0.7*inch, 0.9*inch, 1.0*inch, 1.1*inch]
            )
            item_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#e5e7eb')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ]))
            elements.append(item_table)
        else:
            elements.append(Paragraph("No line items for this order.", line_item_header_style))

        elements.append(Spacer(1, 0.15 * inch))

    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(f"<b>Total Invoice Amount:</b> ${invoice['total_amount']:,.2f}", styles['Heading3']))

    doc.build(elements)

    buffer.seek(0)
    response = make_response(buffer.read())
    filename = f"invoice_{invoice['invoice_month']}_{sponsor['company'].replace(' ', '_')}.pdf"
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@bp.route("/analytics/invoices/<invoice_id>/csv", methods=["GET"], endpoint="analytics_invoice_csv")
@login_required
def analytics_invoice_csv(invoice_id):
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))

    try:
        invoice_payload = InvoiceService.get_invoice_by_id(invoice_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.analytics_invoice_log"))
    except Exception:
        current_app.logger.exception("Failed to build invoice CSV %s", invoice_id)
        flash("Unable to generate invoice CSV.", "danger")
        return redirect(url_for("admin.analytics_invoice_log"))

    invoice = invoice_payload["invoice"]
    sponsor = invoice_payload["sponsor"]
    orders = invoice_payload["orders"]

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(["Invoice Month", invoice["invoice_month"]])
    writer.writerow(["Company", sponsor["company"]])
    writer.writerow(["Period", f"{invoice['period_start'][:10]} → {invoice['period_end'][:10]}"])
    writer.writerow(["Generated At", invoice["generated_at"] or "Draft"])
    writer.writerow(["Total Orders", invoice["total_orders"]])
    writer.writerow(["Total Points", invoice["total_points"]])
    writer.writerow(["Total Amount", f"{invoice['total_amount']:.2f}"])
    writer.writerow(["Status", invoice.get("status", "PENDING")])
    writer.writerow([])

    writer.writerow([
        "Order Date",
        "Order Number",
        "Driver Name",
        "Driver Email",
        "Item",
        "Quantity",
        "Unit Points",
        "Line Points",
        "Line Amount"
    ])

    for order in orders:
        order_date = order["order_created_at"][:10] if order["order_created_at"] else ""
        driver_name = order["driver_name"] or ""
        driver_email = order["driver_email"] or ""
        if order.get("line_items"):
            for item in order["line_items"]:
                writer.writerow([
                    order_date,
                    order["order_number"] or "",
                    driver_name,
                    driver_email,
                    item["title"] or "",
                    item["quantity"],
                    item["unit_points"],
                    item["line_total_points"],
                    f"{item['line_total_amount']:.2f}",
                ])
        else:
            writer.writerow([
                order_date,
                order["order_number"] or "",
                driver_name,
                driver_email,
                "",
                "",
                "",
                order["total_points"],
                f"{order['total_amount']:.2f}",
            ])

    output.seek(0)
    response = make_response(output.getvalue())
    filename = f"invoice_{invoice['invoice_month']}_{sponsor['company'].replace(' ', '_')}.csv"
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


# -------------------------------------------------------------------
# Sponsor Invoice APIs
# -------------------------------------------------------------------
@bp.route("/analytics/invoices/latest", methods=["GET"], endpoint="analytics_invoice_latest")
@login_required
def analytics_invoice_latest():
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return jsonify({"ok": False, "error": "Access denied: Admins only."}), 403

    sponsor_id = (request.args.get("sponsor_id") or "").strip()
    if not sponsor_id:
        return jsonify({"ok": False, "error": "Missing sponsor_id parameter."}), 400

    invoice_month = (request.args.get("month") or "").strip() or None

    try:
        invoice_payload = InvoiceService.get_invoice_for_month(sponsor_id, invoice_month)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Failed to load latest invoice for sponsor %s", sponsor_id)
        return jsonify({"ok": False, "error": "Unable to load invoice."}), 500

    if not invoice_payload:
        return jsonify({"ok": True, "invoice": None, "orders": [], "sponsor": None}), 200

    return jsonify({"ok": True, **invoice_payload}), 200


@bp.route("/analytics/invoices/generate", methods=["POST"], endpoint="analytics_generate_invoice")
@login_required
def analytics_generate_invoice():
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return jsonify({"ok": False, "error": "Access denied: Admins only."}), 403

    payload = request.get_json(silent=True) or {}
    sponsor_id = (payload.get("sponsor_id") or "").strip()
    notes = (payload.get("notes") or "").strip() or None
    invoice_month = (payload.get("month") or "").strip() or None

    if not sponsor_id:
        return jsonify({"ok": False, "error": "Missing sponsor_id."}), 400

    try:
        invoice_payload = InvoiceService.generate_invoice_for_month(
            sponsor_id=sponsor_id,
            invoice_month=invoice_month,
            generated_by_account_id=current_user.AccountID,
            notes=notes,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Failed to generate invoice for sponsor %s", sponsor_id)
        db.session.rollback()
        return jsonify({"ok": False, "error": "Unable to generate invoice."}), 500

    return jsonify({"ok": True, **invoice_payload}), 201


# -------------------------------------------------------------------
# Driver-Sponsor Relationships Analytics
#   URL: /admin/analytics/driver-sponsor-relationships
# -------------------------------------------------------------------
@bp.route("/analytics/driver-sponsor-relationships", methods=["GET"], endpoint="analytics_driver_sponsor_relationships")
@login_required
def analytics_driver_sponsor_relationships():
    """Driver-sponsor relationships analytics with sorting capabilities."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get sorting parameters
    sort_by = request.args.get("sort_by", "sponsor_company")  # Default sort by sponsor company
    sort_order = request.args.get("sort_order", "asc")  # Default ascending order
    
    # Get filter parameters
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    
    # Build query for driver-sponsor relationships
    # Use LEFT JOIN for Sponsor and SponsorAccount since sponsor accounts may not exist
    SponsorAccount = aliased(Account)
    qry = (
        db.session.query(DriverSponsor, Driver, Account, Sponsor, SponsorAccount, SponsorCompany)
        .join(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(SponsorCompany, SponsorCompany.SponsorCompanyID == DriverSponsor.SponsorCompanyID)
        .outerjoin(Sponsor, Sponsor.SponsorID == DriverSponsor.SponsorID)
        .outerjoin(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    # Apply filtering
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    if driver_name_filter:
        # Search for driver name in both first and last name
        driver_name_search = f"%{driver_name_filter}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(driver_name_search),
                Account.LastName.ilike(driver_name_search),
                db.func.concat(Account.FirstName, ' ', Account.LastName).ilike(driver_name_search)
            )
        )
    
    # Apply sorting
    if sort_by == "sponsor_company":
        if sort_order == "asc":
            qry = qry.order_by(SponsorCompany.CompanyName.asc())
        else:
            qry = qry.order_by(SponsorCompany.CompanyName.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            qry = qry.order_by(Account.FirstName.asc(), Account.LastName.asc())
        else:
            qry = qry.order_by(Account.FirstName.desc(), Account.LastName.desc())
    elif sort_by == "points_balance":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.PointsBalance.asc())
        else:
            qry = qry.order_by(DriverSponsor.PointsBalance.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.Status.asc())
        else:
            qry = qry.order_by(DriverSponsor.Status.desc())
    elif sort_by == "created_at":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.CreatedAt.asc())
        else:
            qry = qry.order_by(DriverSponsor.CreatedAt.desc())
    
    relationships = qry.all()
    
    # Get selected sponsor company info for title
    selected_sponsor = None
    if company_filter:
        selected_sponsor = SponsorCompany.query.filter_by(CompanyName=company_filter).first()
    
    # Get unique sponsor companies for filter dropdown
    sponsor_companies = SponsorCompany.query.order_by(SponsorCompany.CompanyName).all()
    sponsor_list = [(company.SponsorCompanyID, company.CompanyName) for company in sponsor_companies]
    
    return render_template("analytics_driver_sponsor_relationships.html", 
                         relationships=relationships,
                         company_filter=company_filter,
                         driver_name_filter=driver_name_filter,
                         sponsors=sponsor_list, 
                         selected_sponsor=selected_sponsor,
                         sort_by=sort_by,
                         sort_order=sort_order)


# -------------------------------------------------------------------
# Driver-Sponsor Relationships PDF Export
#   URL: /admin/analytics/driver-sponsor-relationships/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/driver-sponsor-relationships/pdf", methods=["GET"], endpoint="analytics_driver_sponsor_relationships_pdf")
@login_required
def analytics_driver_sponsor_relationships_pdf():
    """Generate a PDF version of the driver-sponsor relationships report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    sort_by = request.args.get("sort_by", "sponsor_company")
    sort_order = request.args.get("sort_order", "asc")
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    
    SponsorAccount = aliased(Account)
    qry = (
        db.session.query(DriverSponsor, Driver, Account, Sponsor, SponsorAccount, SponsorCompany)
        .join(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(SponsorCompany, SponsorCompany.SponsorCompanyID == DriverSponsor.SponsorCompanyID)
        .outerjoin(Sponsor, Sponsor.SponsorID == DriverSponsor.SponsorID)
        .outerjoin(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(driver_name_search),
                Account.LastName.ilike(driver_name_search),
                db.func.concat(Account.FirstName, ' ', Account.LastName).ilike(driver_name_search)
            )
        )
    
    # Apply sorting (same as main route)
    if sort_by == "sponsor_company":
        if sort_order == "asc":
            qry = qry.order_by(SponsorCompany.CompanyName.asc())
        else:
            qry = qry.order_by(SponsorCompany.CompanyName.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            qry = qry.order_by(Account.FirstName.asc(), Account.LastName.asc())
        else:
            qry = qry.order_by(Account.FirstName.desc(), Account.LastName.desc())
    elif sort_by == "points_balance":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.PointsBalance.asc())
        else:
            qry = qry.order_by(DriverSponsor.PointsBalance.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.Status.asc())
        else:
            qry = qry.order_by(DriverSponsor.Status.desc())
    elif sort_by == "created_at":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.CreatedAt.asc())
        else:
            qry = qry.order_by(DriverSponsor.CreatedAt.desc())
    
    relationships = qry.all()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#111827'),
        spaceAfter=30,
        alignment=1
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#374151'),
        spaceAfter=10,
    )
    
    elements.append(Paragraph("Driver-Sponsor Relationships Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Relationships:</b> {len(relationships)}", styles['Normal']))
    
    filter_info = "Filters: "
    filters = []
    if company_filter:
        filters.append(f"Company: {company_filter}")
    if driver_name_filter:
        filters.append(f"Driver: {driver_name_filter}")
    
    if filters:
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>{filter_info}{'; '.join(filters)}</b>", styles['Normal']))
    else:
        elements.append(Paragraph("<b>Filters: None (All relationships)</b>", styles['Normal']))
    
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("Driver-Sponsor Relationships", heading_style))
    
    if relationships:
        # Create a smaller font style for table content
        small_style = ParagraphStyle(
            'TableContent',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
        )
        
        # Use Paragraph for header
        table_data = [[
            Paragraph('<b>Company</b>', small_style),
            Paragraph('<b>Driver Name</b>', small_style),
            Paragraph('<b>Driver Email</b>', small_style),
            Paragraph('<b>Points Balance</b>', small_style),
            Paragraph('<b>Status</b>', small_style),
            Paragraph('<b>Created Date</b>', small_style)
        ]]
        
        for driver_sponsor, driver, account, sponsor, sponsor_account, sponsor_company in relationships:
            company = sponsor_company.CompanyName
            driver_name = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
            email = account.Email or "N/A"
            balance = driver_sponsor.PointsBalance or 0
            status = driver_sponsor.Status or "N/A"
            date_str = driver_sponsor.CreatedAt.strftime('%m/%d/%Y') if driver_sponsor.CreatedAt else "N/A"
            
            # Use Paragraph for text fields to allow wrapping
            company_para = Paragraph(company, small_style)
            driver_name_para = Paragraph(driver_name, small_style)
            email_para = Paragraph(email, small_style)
            
            table_data.append([company_para, driver_name_para, email_para, str(balance), status, date_str])
        
        # Adjusted column widths: 2.2 + 1.8 + 2.3 + 1.3 + 1.2 + 1.2 = 10.0"
        table = Table(table_data, colWidths=[2.2*inch, 1.8*inch, 2.3*inch, 1.3*inch, 1.2*inch, 1.2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No relationships found matching the current filters.", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_sponsor_relationships_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    return response


# -------------------------------------------------------------------
# Driver-Sponsor Relationships CSV Export
#   URL: /admin/analytics/driver-sponsor-relationships/csv
# -------------------------------------------------------------------
@bp.route("/analytics/driver-sponsor-relationships/csv", methods=["GET"], endpoint="analytics_driver_sponsor_relationships_csv")
@login_required
def analytics_driver_sponsor_relationships_csv():
    """Generate a CSV version of the driver-sponsor relationships report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    sort_by = request.args.get("sort_by", "sponsor_company")
    sort_order = request.args.get("sort_order", "asc")
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    
    SponsorAccount = aliased(Account)
    qry = (
        db.session.query(DriverSponsor, Driver, Account, Sponsor, SponsorAccount, SponsorCompany)
        .join(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(SponsorCompany, SponsorCompany.SponsorCompanyID == DriverSponsor.SponsorCompanyID)
        .outerjoin(Sponsor, Sponsor.SponsorID == DriverSponsor.SponsorID)
        .outerjoin(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(driver_name_search),
                Account.LastName.ilike(driver_name_search),
                db.func.concat(Account.FirstName, ' ', Account.LastName).ilike(driver_name_search)
            )
        )
    
    # Apply sorting (same as main route)
    if sort_by == "sponsor_company":
        if sort_order == "asc":
            qry = qry.order_by(SponsorCompany.CompanyName.asc())
        else:
            qry = qry.order_by(SponsorCompany.CompanyName.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            qry = qry.order_by(Account.FirstName.asc(), Account.LastName.asc())
        else:
            qry = qry.order_by(Account.FirstName.desc(), Account.LastName.desc())
    elif sort_by == "points_balance":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.PointsBalance.asc())
        else:
            qry = qry.order_by(DriverSponsor.PointsBalance.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.Status.asc())
        else:
            qry = qry.order_by(DriverSponsor.Status.desc())
    elif sort_by == "created_at":
        if sort_order == "asc":
            qry = qry.order_by(DriverSponsor.CreatedAt.asc())
        else:
            qry = qry.order_by(DriverSponsor.CreatedAt.desc())
    
    relationships = qry.all()
    
    output = BytesIO()
    header = "Company|Driver Name|Driver Email|Points Balance|Status|Created Date\n"
    output.write(header.encode('utf-8'))
    
    for driver_sponsor, driver, account, sponsor, sponsor_account, sponsor_company in relationships:
        company = sponsor_company.CompanyName
        driver_name = f"{account.FirstName} {account.LastName}" if account.FirstName or account.LastName else "N/A"
        email = account.Email or "N/A"
        balance = driver_sponsor.PointsBalance or 0
        status = driver_sponsor.Status or "N/A"
        date_str = driver_sponsor.CreatedAt.strftime('%Y-%m-%d') if driver_sponsor.CreatedAt else "N/A"
        
        row = f"{company}|{driver_name}|{email}|{balance}|{status}|{date_str}\n"
        output.write(row.encode('utf-8'))
    
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_sponsor_relationships_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return response


# -------------------------------------------------------------------
# Driver-Sponsor Relationship Management
#   URL: /admin/manage-driver-sponsor-relations
# -------------------------------------------------------------------
@bp.route("/manage-driver-sponsor-relations", methods=["GET", "POST"], endpoint="manage_driver_sponsor_relations")
@login_required
def manage_driver_sponsor_relations():
    """Manage driver-sponsor relationships - assign, reassign, or remove."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "assign":
            # Assign a driver to a sponsor company
            driver_id = request.form.get("driver_id")
            sponsor_company_id = request.form.get("sponsor_company_id")
            sponsor_id = request.form.get("sponsor_id")  # Optional - for companies with sponsor accounts
            points_balance = int(request.form.get("points_balance", 0))
            
            if not driver_id or not sponsor_company_id:
                flash("Driver and sponsor company must be selected.", "danger")
                return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Validate driver exists
            driver = Driver.query.filter_by(DriverID=driver_id).first()
            if not driver:
                flash("Error: Driver not found.", "danger")
                return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Validate sponsor company exists
            sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=sponsor_company_id).first()
            if not sponsor_company:
                flash("Error: Sponsor company not found.", "danger")
                return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Handle SponsorID - if provided, use it; otherwise, find first sponsor for this company or create a placeholder
            sponsor = None
            if sponsor_id:
                sponsor = Sponsor.query.filter_by(SponsorID=sponsor_id, SponsorCompanyID=sponsor_company_id).first()
                if not sponsor:
                    flash("Error: Selected sponsor account does not belong to the selected company.", "danger")
                    return redirect(url_for("admin.manage_driver_sponsor_relations"))
            else:
                # Find first sponsor account for this company
                sponsor = Sponsor.query.filter_by(SponsorCompanyID=sponsor_company_id).first()
                if not sponsor:
                    # Company has no sponsor accounts - we need a SponsorID, so create a placeholder sponsor account
                    # First, create a system account for the company
                    from app.models import AccountType
                    account_type = AccountType.query.filter_by(AccountTypeCode="SPONSOR").first()
                    if not account_type:
                        flash("Error: SPONSOR account type not found. Please contact system administrator.", "danger")
                        return redirect(url_for("admin.manage_driver_sponsor_relations"))
                    
                    # Create a placeholder account
                    placeholder_account = Account(
                        AccountTypeID=account_type.AccountTypeID,
                        Username=f"system_{sponsor_company.CompanyName.lower().replace(' ', '_')}",
                        AccountType="SPONSOR",
                        Email=f"system@{sponsor_company.CompanyName.lower().replace(' ', '')}.placeholder",
                        PasswordHash=bcrypt.hashpw("placeholder".encode(), bcrypt.gensalt()).decode(),
                        FirstName="System",
                        LastName="Placeholder",
                        Status="I"  # Inactive
                    )
                    db.session.add(placeholder_account)
                    db.session.flush()
                    
                    # Create placeholder sponsor
                    sponsor = Sponsor(
                        AccountID=placeholder_account.AccountID,
                        Company=sponsor_company.CompanyName,
                        SponsorCompanyID=sponsor_company_id,
                        PointToDollarRate=sponsor_company.PointToDollarRate,
                        MinPointsPerTxn=sponsor_company.MinPointsPerTxn,
                        MaxPointsPerTxn=sponsor_company.MaxPointsPerTxn
                    )
                    db.session.add(sponsor)
                    db.session.flush()
            
            # Check if relationship already exists for this driver and sponsor
            existing = DriverSponsor.query.filter_by(
                DriverID=driver_id, 
                SponsorID=sponsor.SponsorID
            ).first()
            
            if existing:
                # If relationship exists, reactivate it instead of creating a new one
                if existing.Status == "ACTIVE":
                    flash("This driver-sponsor relationship already exists.", "warning")
                    return redirect(url_for("admin.manage_driver_sponsor_relations"))
                else:
                    # Reactivate the existing relationship
                    existing.Status = "ACTIVE"
                    existing.PointsBalance = points_balance
                    existing.SponsorCompanyID = sponsor_company_id
                    try:
                        db.session.commit()
                        flash("Driver successfully reactivated with sponsor company.", "success")
                    except Exception as e:
                        db.session.rollback()
                        flash(f"Error reactivating driver-sponsor relationship: {str(e)}", "danger")
                    return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Create new relationship
            new_relationship = DriverSponsor(
                DriverID=driver_id,
                SponsorID=sponsor.SponsorID,
                SponsorCompanyID=sponsor_company_id,
                PointsBalance=points_balance,
                Status="ACTIVE"
            )
            
            try:
                db.session.add(new_relationship)
                db.session.commit()
                flash("Driver successfully assigned to sponsor company.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error assigning driver to sponsor company: {str(e)}", "danger")
        
        elif action == "reassign":
            # Reassign a driver from one sponsor company to another
            driver_sponsor_id = request.form.get("driver_sponsor_id")
            new_sponsor_company_id = request.form.get("reassign_sponsor_company_id")
            new_sponsor_id = request.form.get("new_sponsor_id")  # Optional
            new_points_balance = int(request.form.get("new_points_balance", 0))
            
            if not driver_sponsor_id or not new_sponsor_company_id:
                flash("Driver-sponsor relationship and new sponsor company must be selected.", "danger")
                return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Validate new sponsor company exists
            new_sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=new_sponsor_company_id).first()
            if not new_sponsor_company:
                flash("Error: Sponsor company not found.", "danger")
                return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Handle SponsorID - if provided, use it; otherwise, find first sponsor for this company or create a placeholder
            new_sponsor = None
            if new_sponsor_id:
                new_sponsor = Sponsor.query.filter_by(SponsorID=new_sponsor_id, SponsorCompanyID=new_sponsor_company_id).first()
                if not new_sponsor:
                    flash("Error: Selected sponsor account does not belong to the selected company.", "danger")
                    return redirect(url_for("admin.manage_driver_sponsor_relations"))
            else:
                # Find first sponsor account for this company
                new_sponsor = Sponsor.query.filter_by(SponsorCompanyID=new_sponsor_company_id).first()
                if not new_sponsor:
                    # Company has no sponsor accounts - create a placeholder sponsor account
                    from app.models import AccountType
                    account_type = AccountType.query.filter_by(AccountTypeCode="SPONSOR").first()
                    if not account_type:
                        flash("Error: SPONSOR account type not found. Please contact system administrator.", "danger")
                        return redirect(url_for("admin.manage_driver_sponsor_relations"))
                    
                    # Create a placeholder account
                    placeholder_account = Account(
                        AccountTypeID=account_type.AccountTypeID,
                        Username=f"system_{new_sponsor_company.CompanyName.lower().replace(' ', '_')}",
                        AccountType="SPONSOR",
                        Email=f"system@{new_sponsor_company.CompanyName.lower().replace(' ', '')}.placeholder",
                        PasswordHash=bcrypt.hashpw("placeholder".encode(), bcrypt.gensalt()).decode(),
                        FirstName="System",
                        LastName="Placeholder",
                        Status="I"  # Inactive
                    )
                    db.session.add(placeholder_account)
                    db.session.flush()
                    
                    # Create placeholder sponsor
                    new_sponsor = Sponsor(
                        AccountID=placeholder_account.AccountID,
                        Company=new_sponsor_company.CompanyName,
                        SponsorCompanyID=new_sponsor_company_id,
                        PointToDollarRate=new_sponsor_company.PointToDollarRate,
                        MinPointsPerTxn=new_sponsor_company.MinPointsPerTxn,
                        MaxPointsPerTxn=new_sponsor_company.MaxPointsPerTxn
                    )
                    db.session.add(new_sponsor)
                    db.session.flush()
            
            # Get existing relationship
            existing = DriverSponsor.query.get(driver_sponsor_id)
            if not existing:
                flash("Driver-sponsor relationship not found.", "danger")
                return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Check if new relationship already exists
            new_existing = DriverSponsor.query.filter_by(
                DriverID=existing.DriverID,
                SponsorID=new_sponsor_id
            ).first()
            
            if new_existing:
                # If relationship exists, reactivate it instead of updating the old one
                if new_existing.Status == "ACTIVE":
                    flash("Driver is already assigned to this sponsor.", "warning")
                    return redirect(url_for("admin.manage_driver_sponsor_relations"))
                else:
                    # Reactivate the existing relationship instead of updating the old one
                    new_existing.Status = "ACTIVE"
                    new_existing.PointsBalance = new_points_balance
                    new_existing.SponsorCompanyID = new_sponsor.SponsorCompanyID
                    # Mark the old relationship as inactive
                    existing.Status = "INACTIVE"
                    try:
                        db.session.commit()
                        flash("Driver successfully reassigned and existing relationship reactivated.", "success")
                    except Exception as e:
                        db.session.rollback()
                        flash(f"Error reassigning driver: {str(e)}", "danger")
                    return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            # Update the relationship
            try:
                existing.SponsorID = new_sponsor.SponsorID
                existing.SponsorCompanyID = new_sponsor_company_id
                existing.PointsBalance = new_points_balance
                existing.Status = "ACTIVE"
                db.session.commit()
                flash("Driver successfully reassigned to new sponsor company.", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error reassigning driver: {str(e)}", "danger")
        
        elif action == "remove":
            # Mark a driver-sponsor relationship as inactive (soft delete)
            driver_sponsor_id = request.form.get("driver_sponsor_id")
            driver_id = request.form.get("remove_driver_id")
            sponsor_id = request.form.get("remove_sponsor_id")
            
            # Debug logging
            current_app.logger.info(f"Remove action - driver_sponsor_id: {driver_sponsor_id}, driver_id: {driver_id}, sponsor_id: {sponsor_id}")
            current_app.logger.info(f"All form data: {dict(request.form)}")
            
            # Determine which ID to use
            id_to_use = driver_sponsor_id if driver_sponsor_id else None
            if not id_to_use and driver_id and sponsor_id:
                # Need to look up the DriverSponsorID
                temp_existing = DriverSponsor.query.filter_by(
                    DriverID=driver_id,
                    SponsorID=sponsor_id
                ).first()
                if temp_existing:
                    id_to_use = temp_existing.DriverSponsorID
                    current_app.logger.info(f"Found DriverSponsorID {id_to_use} from DriverID and SponsorID")
            
            if not id_to_use:
                flash("Driver-sponsor relationship not found. Please ensure both company and driver are selected.", "danger")
                return redirect(url_for("admin.manage_driver_sponsor_relations"))
            
            try:
                # Query fresh to check current status
                existing = DriverSponsor.query.get(id_to_use)
                if not existing:
                    flash("Driver-sponsor relationship not found.", "danger")
                    return redirect(url_for("admin.manage_driver_sponsor_relations"))
                
                old_status = existing.Status
                current_app.logger.info(f"DriverSponsor {existing.DriverSponsorID} - Current status: '{old_status}', changing to 'INACTIVE'")
                
                # Use raw SQL UPDATE to force the change
                result = db.session.execute(
                    text("UPDATE DriverSponsor SET Status = :status WHERE DriverSponsorID = :id"),
                    {"status": "INACTIVE", "id": id_to_use}
                )
                current_app.logger.info(f"Raw SQL UPDATE executed, rows affected: {result.rowcount}")
                
                db.session.commit()
                current_app.logger.info(f"Successfully committed - DriverSponsor {id_to_use} marked as INACTIVE")
                
                # Verify the change persisted
                verification = DriverSponsor.query.get(id_to_use)
                if verification:
                    current_app.logger.info(f"Verification - Status in DB: '{verification.Status}'")
                else:
                    current_app.logger.error("Verification query returned None!")
                
                flash("Driver-sponsor relationship successfully marked as inactive.", "success")
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error marking relationship as inactive: {str(e)}", exc_info=True)
                flash(f"Error marking relationship as inactive: {str(e)}", "danger")
        
        return redirect(url_for("admin.manage_driver_sponsor_relations"))
    
    # GET request - show the management page
    # Create alias for sponsor accounts to avoid naming conflicts
    SponsorAccount = aliased(Account)
    
    # Get all drivers
    drivers = db.session.query(Driver, Account).join(Account, Account.AccountID == Driver.AccountID).all()
    
    # Get all sponsor companies
    sponsor_companies = SponsorCompany.query.order_by(SponsorCompany.CompanyName).all()
    
    # Get all sponsors (for optional selection)
    sponsors = db.session.query(Sponsor, Account).join(Account, Account.AccountID == Sponsor.AccountID).all()
    
    # Get all existing relationships - use LEFT JOIN for SponsorAccount since sponsor might not exist
    relationships = (
        db.session.query(DriverSponsor, Driver, Account, Sponsor, SponsorAccount, SponsorCompany)
        .join(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(SponsorCompany, SponsorCompany.SponsorCompanyID == DriverSponsor.SponsorCompanyID)
        .outerjoin(Sponsor, Sponsor.SponsorID == DriverSponsor.SponsorID)
        .outerjoin(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
        .order_by(SponsorCompany.CompanyName, Account.FirstName, Account.LastName)
        .all()
    )
    
    return render_template("manage_driver_sponsor_relations.html",
                         drivers=drivers,
                         sponsor_companies=sponsor_companies,
                         sponsors=sponsors,
                         relationships=relationships)


# -------------------------------------------------------------------
# Sales Analytics Report
#   URL: /admin/analytics/sales-report
# -------------------------------------------------------------------
@bp.route("/analytics/sales-report", methods=["GET"], endpoint="analytics_sales_report")
@login_required
def analytics_sales_report():
    """Sales analytics report showing submitted orders and sales data."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get filter parameters
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    status_filter = (request.args.get("status_filter") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    
    # Get sorting parameters
    sort_by = request.args.get("sort_by", "created_at")  # Default sort by creation date
    sort_order = request.args.get("sort_order", "desc")  # Default descending (newest first)
    
    # Build query for sales data
    DriverAccount = aliased(Account)
    SponsorAccount = aliased(Account)
    
    qry = (
        db.session.query(Orders, Driver, DriverAccount, Sponsor, SponsorAccount)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(Sponsor, Sponsor.SponsorID == Orders.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    # Apply filtering
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        qry = qry.filter(
            or_(
                DriverAccount.FirstName.ilike(driver_name_search),
                DriverAccount.LastName.ilike(driver_name_search),
                db.func.concat(DriverAccount.FirstName, ' ', DriverAccount.LastName).ilike(driver_name_search)
            )
        )
    
    if status_filter:
        qry = qry.filter(Orders.Status == status_filter)
    
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(Orders.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(Orders.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    # Apply sorting
    if sort_by == "created_at":
        if sort_order == "asc":
            qry = qry.order_by(Orders.CreatedAt.asc())
        else:
            qry = qry.order_by(Orders.CreatedAt.desc())
    elif sort_by == "sponsor_company":
        if sort_order == "asc":
            qry = qry.order_by(Sponsor.Company.asc())
        else:
            qry = qry.order_by(Sponsor.Company.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            qry = qry.order_by(DriverAccount.FirstName.asc(), DriverAccount.LastName.asc())
        else:
            qry = qry.order_by(DriverAccount.FirstName.desc(), DriverAccount.LastName.desc())
    elif sort_by == "total_points":
        if sort_order == "asc":
            qry = qry.order_by(Orders.TotalPoints.asc())
        else:
            qry = qry.order_by(Orders.TotalPoints.desc())
    elif sort_by == "total_amount":
        if sort_order == "asc":
            qry = qry.order_by(Orders.TotalAmount.asc())
        else:
            qry = qry.order_by(Orders.TotalAmount.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            qry = qry.order_by(Orders.Status.asc())
        else:
            qry = qry.order_by(Orders.Status.desc())
    
    orders = qry.all()
    
    # Calculate summary statistics
    total_orders = len(orders)
    total_points = sum(order.TotalPoints for order, _, _, _, _ in orders if order.TotalPoints)
    
    # Calculate total amount with fallback to point-to-dollar conversion
    total_amount = 0
    for order, _, _, sponsor, _ in orders:
        if order.TotalAmount and order.TotalAmount > 0:
            total_amount += float(order.TotalAmount)
        else:
            # Fallback: calculate from points using sponsor's rate
            total_amount += float(order.TotalPoints) * float(sponsor.PointToDollarRate)
    
    # Count by status
    status_counts = {}
    for order, _, _, _, _ in orders:
        status = order.Status or "Unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Get unique sponsors for filter dropdown
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))
    
    # Get unique order statuses for filter dropdown
    distinct_statuses = db.session.query(Orders.Status).distinct().order_by(Orders.Status).all()
    status_list = [status_tuple[0] for status_tuple in distinct_statuses if status_tuple[0]]
    
    return render_template("analytics_sales_report.html",
                         orders=orders,
                         company_filter=company_filter,
                         driver_name_filter=driver_name_filter,
                         status_filter=status_filter,
                         date_from=date_from,
                         date_to=date_to,
                         sponsors=sponsor_list,
                         status_list=status_list,
                         sort_by=sort_by,
                         sort_order=sort_order,
                         total_orders=total_orders,
                         total_points=total_points,
                         total_amount=total_amount,
                         status_counts=status_counts)


# -------------------------------------------------------------------
# Sales Analytics Report PDF Generation
#   URL: /admin/analytics/sales-report/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/sales-report/pdf", methods=["GET"], endpoint="analytics_sales_report_pdf")
@login_required
def analytics_sales_report_pdf():
    """Generate a PDF version of the sales analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    # Get filter parameters (same as regular report)
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    status_filter = (request.args.get("status_filter") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")
    
    # Build query for sales data (same as regular report)
    DriverAccount = aliased(Account)
    SponsorAccount = aliased(Account)
    
    qry = (
        db.session.query(Orders, Driver, DriverAccount, Sponsor, SponsorAccount)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(Sponsor, Sponsor.SponsorID == Orders.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    # Apply filtering
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        qry = qry.filter(
            or_(
                DriverAccount.FirstName.ilike(driver_name_search),
                DriverAccount.LastName.ilike(driver_name_search),
                db.func.concat(DriverAccount.FirstName, ' ', DriverAccount.LastName).ilike(driver_name_search)
            )
        )
    
    if status_filter:
        qry = qry.filter(Orders.Status == status_filter)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(Orders.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(Orders.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    # Apply sorting
    if sort_by == "created_at":
        if sort_order == "asc":
            qry = qry.order_by(Orders.CreatedAt.asc())
        else:
            qry = qry.order_by(Orders.CreatedAt.desc())
    elif sort_by == "sponsor_company":
        if sort_order == "asc":
            qry = qry.order_by(Sponsor.Company.asc())
        else:
            qry = qry.order_by(Sponsor.Company.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            qry = qry.order_by(DriverAccount.FirstName.asc(), DriverAccount.LastName.asc())
        else:
            qry = qry.order_by(DriverAccount.FirstName.desc(), DriverAccount.LastName.desc())
    elif sort_by == "total_points":
        if sort_order == "asc":
            qry = qry.order_by(Orders.TotalPoints.asc())
        else:
            qry = qry.order_by(Orders.TotalPoints.desc())
    elif sort_by == "total_amount":
        if sort_order == "asc":
            qry = qry.order_by(Orders.TotalAmount.asc())
        else:
            qry = qry.order_by(Orders.TotalAmount.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            qry = qry.order_by(Orders.Status.asc())
        else:
            qry = qry.order_by(Orders.Status.desc())
    
    orders = qry.all()
    
    # Calculate summary statistics
    total_orders = len(orders)
    total_points = sum(order.TotalPoints for order, _, _, _, _ in orders if order.TotalPoints)
    
    # Calculate total amount with fallback to point-to-dollar conversion
    total_amount = 0
    for order, _, _, sponsor, _ in orders:
        if order.TotalAmount and order.TotalAmount > 0:
            total_amount += float(order.TotalAmount)
        else:
            total_amount += float(order.TotalPoints) * float(sponsor.PointToDollarRate)
    
    # Count by status
    status_counts = {}
    for order, _, _, _, _ in orders:
        status = order.Status or "Unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Generate PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#111827'),
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#374151'),
        spaceAfter=10,
    )
    
    # Title
    elements.append(Paragraph("Sales Analytics Summary Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Report info
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Orders:</b> {total_orders}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Points:</b> {total_points:,}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Amount:</b> ${total_amount:,.2f}", styles['Normal']))
    
    # Add filter information
    filter_info = "Filters: "
    filters = []
    if company_filter:
        filters.append(f"Company: {company_filter}")
    if driver_name_filter:
        filters.append(f"Driver: {driver_name_filter}")
    if status_filter:
        filters.append(f"Status: {status_filter}")
    if date_from:
        filters.append(f"From: {date_from}")
    if date_to:
        filters.append(f"To: {date_to}")
    
    if filters:
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>{filter_info}{'; '.join(filters)}</b>", styles['Normal']))
    else:
        elements.append(Paragraph("<b>Filters: None (All orders)</b>", styles['Normal']))
    
    elements.append(Spacer(1, 0.2*inch))
    
    # Status breakdown
    if status_counts:
        elements.append(Paragraph("Status Breakdown", heading_style))
        status_data = [['Status', 'Count']]
        for status, count in status_counts.items():
            status_data.append([status, str(count)])
        
        status_table = Table(status_data, colWidths=[3*inch, 1*inch])
        status_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb'))
        ]))
        elements.append(status_table)
        elements.append(Spacer(1, 0.3*inch))
    
    # Orders table
    elements.append(Paragraph("Orders Details", heading_style))
    
    if orders:
        # Table header - reduced columns by combining some info
        table_data = [['Date & Order #', 'Company & Driver', 'Points & Amount', 'Status & Email']]
        
        # Add rows with stacked information
        for order, driver, driver_account, sponsor, sponsor_account in orders:
            # Stack date and order number vertically using Paragraph for line breaks
            date_str = order.CreatedAt.strftime('%m/%d/%Y') if order.CreatedAt else 'N/A'
            order_num = order.OrderNumber
            date_order = Paragraph(f"{date_str}<br/>{order_num}", styles['Normal'])
            
            # Stack company and driver vertically
            company = sponsor.Company[:30]  # Limit length
            driver_name = f"{driver_account.FirstName} {driver_account.LastName}"
            company_driver = Paragraph(f"{company}<br/>{driver_name}", styles['Normal'])
            
            # Stack points and amount vertically
            points = f"{order.TotalPoints:,}"
            if order.TotalAmount and order.TotalAmount > 0:
                amount = f"${order.TotalAmount:,.2f}"
            else:
                amount = f"${order.TotalPoints * sponsor.PointToDollarRate:,.2f}"
            points_amount = Paragraph(f"{points}<br/>{amount}", styles['Normal'])
            
            # Stack status and email vertically
            status = order.Status or 'Unknown'
            email = driver_account.Email
            status_email = Paragraph(f"{status}<br/>{email}", styles['Normal'])
            
            table_data.append([date_order, company_driver, points_amount, status_email])
        
        # Create table with balanced column widths
        table = Table(table_data, colWidths=[2.2*inch, 2.8*inch, 2.2*inch, 3.3*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No orders found matching the current filters.", styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    
    # Create response
    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=sales_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    
    return response


# -------------------------------------------------------------------
# Sales Analytics Report CSV Export
#   URL: /admin/analytics/sales-report/csv
# -------------------------------------------------------------------
@bp.route("/analytics/sales-report/csv", methods=["GET"], endpoint="analytics_sales_report_csv")
@login_required
def analytics_sales_report_csv():
    """Generate a CSV version of the sales analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    # Get filter parameters (same as regular report)
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    status_filter = (request.args.get("status_filter") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")
    
    # Build query for sales data (same as regular report)
    DriverAccount = aliased(Account)
    SponsorAccount = aliased(Account)
    
    qry = (
        db.session.query(Orders, Driver, DriverAccount, Sponsor, SponsorAccount)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(Sponsor, Sponsor.SponsorID == Orders.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    # Apply filtering
    if company_filter:
        qry = qry.filter(Sponsor.Company == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        qry = qry.filter(
            or_(
                DriverAccount.FirstName.ilike(driver_name_search),
                DriverAccount.LastName.ilike(driver_name_search),
                db.func.concat(DriverAccount.FirstName, ' ', DriverAccount.LastName).ilike(driver_name_search)
            )
        )
    
    if status_filter:
        qry = qry.filter(Orders.Status == status_filter)
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(Orders.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(Orders.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    # Apply sorting
    if sort_by == "created_at":
        if sort_order == "asc":
            qry = qry.order_by(Orders.CreatedAt.asc())
        else:
            qry = qry.order_by(Orders.CreatedAt.desc())
    elif sort_by == "sponsor_company":
        if sort_order == "asc":
            qry = qry.order_by(Sponsor.Company.asc())
        else:
            qry = qry.order_by(Sponsor.Company.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            qry = qry.order_by(DriverAccount.FirstName.asc(), DriverAccount.LastName.asc())
        else:
            qry = qry.order_by(DriverAccount.FirstName.desc(), DriverAccount.LastName.desc())
    elif sort_by == "total_points":
        if sort_order == "asc":
            qry = qry.order_by(Orders.TotalPoints.asc())
        else:
            qry = qry.order_by(Orders.TotalPoints.desc())
    elif sort_by == "total_amount":
        if sort_order == "asc":
            qry = qry.order_by(Orders.TotalAmount.asc())
        else:
            qry = qry.order_by(Orders.TotalAmount.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            qry = qry.order_by(Orders.Status.asc())
        else:
            qry = qry.order_by(Orders.Status.desc())
    
    orders = qry.all()
    
    # Generate CSV
    output = BytesIO()
    
    # Write header
    header = "Order Date|Order Number|Sponsor Company|Driver|Total Points|Total Amount|Status|Driver Email\n"
    output.write(header.encode('utf-8'))
    
    # Write data rows
    for order, driver, driver_account, sponsor, sponsor_account in orders:
        date_str = order.CreatedAt.strftime('%Y-%m-%d %H:%M') if order.CreatedAt else 'N/A'
        order_num = order.OrderNumber
        company = sponsor.Company
        driver_name = f"{driver_account.FirstName} {driver_account.LastName}"
        points = order.TotalPoints or 0
        
        if order.TotalAmount and order.TotalAmount > 0:
            amount = float(order.TotalAmount)
        else:
            amount = float(points) * float(sponsor.PointToDollarRate)
        
        status = order.Status or 'Unknown'
        driver_email = driver_account.Email
        
        row = f"{date_str}|{order_num}|{company}|{driver_name}|{points}|{amount:.2f}|{status}|{driver_email}\n"
        output.write(row.encode('utf-8'))
    
    # Create response
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=sales_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response


# -------------------------------------------------------------------
# Sales Analytics Detailed Report (Line Items)
#   URL: /admin/analytics/sales-detailed
# -------------------------------------------------------------------
@bp.route("/analytics/sales-detailed", methods=["GET"], endpoint="analytics_sales_detailed")
@login_required
def analytics_sales_detailed():
    """Detailed sales analytics report showing individual line items."""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get filter parameters
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    status_filter = (request.args.get("status_filter") or "").strip()
    order_number_filter = (request.args.get("order_number_filter") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    
    # Get sorting parameters
    sort_by = request.args.get("sort_by", "created_at")  # Default sort by creation date
    sort_order = request.args.get("sort_order", "desc")  # Default descending (newest first)
    
    # Build query for line items with all related data
    DriverAccount = aliased(Account)
    SponsorAccount = aliased(Account)
    
    line_items_qry = (
        db.session.query(OrderLineItem, Orders, Driver, DriverAccount, Sponsor, SponsorAccount)
        .join(Orders, Orders.OrderID == OrderLineItem.OrderID)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(Sponsor, Sponsor.SponsorID == Orders.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    # Apply filtering
    if company_filter:
        line_items_qry = line_items_qry.filter(Sponsor.Company == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        line_items_qry = line_items_qry.filter(
            or_(
                DriverAccount.FirstName.ilike(driver_name_search),
                DriverAccount.LastName.ilike(driver_name_search),
                db.func.concat(DriverAccount.FirstName, ' ', DriverAccount.LastName).ilike(driver_name_search)
            )
        )
    
    if status_filter:
        line_items_qry = line_items_qry.filter(Orders.Status == status_filter)
    
    if order_number_filter:
        order_number_search = f"%{order_number_filter}%"
        line_items_qry = line_items_qry.filter(Orders.OrderNumber.ilike(order_number_search))
    
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            line_items_qry = line_items_qry.filter(Orders.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            line_items_qry = line_items_qry.filter(Orders.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    # Apply sorting for line items
    if sort_by == "created_at":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Orders.CreatedAt.asc())
        else:
            line_items_qry = line_items_qry.order_by(Orders.CreatedAt.desc())
    elif sort_by == "sponsor_company":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Sponsor.Company.asc())
        else:
            line_items_qry = line_items_qry.order_by(Sponsor.Company.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(DriverAccount.FirstName.asc(), DriverAccount.LastName.asc())
        else:
            line_items_qry = line_items_qry.order_by(DriverAccount.FirstName.desc(), DriverAccount.LastName.desc())
    elif sort_by == "line_points":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.LineTotalPoints.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.LineTotalPoints.desc())
    elif sort_by == "unit_points":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.UnitPoints.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.UnitPoints.desc())
    elif sort_by == "quantity":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.Quantity.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.Quantity.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Orders.Status.asc())
        else:
            line_items_qry = line_items_qry.order_by(Orders.Status.desc())
    
    line_items_data = line_items_qry.all()
    
    # Calculate summary statistics for line items
    total_line_items = len(line_items_data)
    total_points = sum(line_item.LineTotalPoints for line_item, _, _, _, _, _ in line_items_data if line_item.LineTotalPoints)
    
    # Calculate total amount with fallback to point-to-dollar conversion
    total_amount = 0
    for line_item, order, _, _, sponsor, _ in line_items_data:
        if order.TotalAmount and order.TotalAmount > 0:
            # Calculate proportional amount for this line item
            line_proportion = line_item.LineTotalPoints / order.TotalPoints if order.TotalPoints > 0 else 0
            total_amount += float(order.TotalAmount) * line_proportion
        else:
            # Fallback: calculate from points using sponsor's rate
            total_amount += float(line_item.LineTotalPoints) * float(sponsor.PointToDollarRate)
    
    # Count by status
    status_counts = {}
    for _, order, _, _, _, _ in line_items_data:
        status = order.Status or "Unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Get unique sponsors for filter dropdown
    distinct_companies = db.session.query(Sponsor.Company).distinct().order_by(Sponsor.Company).all()
    sponsor_list = []
    for company_tuple in distinct_companies:
        company_name = company_tuple[0]
        if company_name:
            sponsor = Sponsor.query.filter_by(Company=company_name).first()
            if sponsor:
                sponsor_list.append((sponsor.SponsorID, sponsor.Company))
    
    # Get unique order statuses for filter dropdown
    distinct_statuses = db.session.query(Orders.Status).distinct().order_by(Orders.Status).all()
    status_list = [status_tuple[0] for status_tuple in distinct_statuses if status_tuple[0]]
    
    return render_template("analytics_sales_detailed.html",
                         line_items_data=line_items_data,
                         company_filter=company_filter,
                         driver_name_filter=driver_name_filter,
                         status_filter=status_filter,
                         order_number_filter=order_number_filter,
                         date_from=date_from,
                         date_to=date_to,
                         sponsors=sponsor_list,
                         status_list=status_list,
                         sort_by=sort_by,
                         sort_order=sort_order,
                         total_line_items=total_line_items,
                         total_points=total_points,
                         total_amount=total_amount,
                         status_counts=status_counts)


# -------------------------------------------------------------------
# Sales Analytics Detailed Report PDF Generation
#   URL: /admin/analytics/sales-detailed/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/sales-detailed/pdf", methods=["GET"], endpoint="analytics_sales_detailed_pdf")
@login_required
def analytics_sales_detailed_pdf():
    """Generate a PDF version of the detailed sales analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    # Get filter parameters (same as regular report)
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    status_filter = (request.args.get("status_filter") or "").strip()
    order_number_filter = (request.args.get("order_number_filter") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")
    
    # Build query for line items with all related data
    DriverAccount = aliased(Account)
    SponsorAccount = aliased(Account)
    
    line_items_qry = (
        db.session.query(OrderLineItem, Orders, Driver, DriverAccount, Sponsor, SponsorAccount)
        .join(Orders, Orders.OrderID == OrderLineItem.OrderID)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(Sponsor, Sponsor.SponsorID == Orders.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    # Apply filtering
    if company_filter:
        line_items_qry = line_items_qry.filter(Sponsor.Company == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        line_items_qry = line_items_qry.filter(
            or_(
                DriverAccount.FirstName.ilike(driver_name_search),
                DriverAccount.LastName.ilike(driver_name_search),
                db.func.concat(DriverAccount.FirstName, ' ', DriverAccount.LastName).ilike(driver_name_search)
            )
        )
    
    if status_filter:
        line_items_qry = line_items_qry.filter(Orders.Status == status_filter)
    
    if order_number_filter:
        order_number_search = f"%{order_number_filter}%"
        line_items_qry = line_items_qry.filter(Orders.OrderNumber.ilike(order_number_search))
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            line_items_qry = line_items_qry.filter(Orders.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            line_items_qry = line_items_qry.filter(Orders.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    # Apply sorting for line items
    if sort_by == "created_at":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Orders.CreatedAt.asc())
        else:
            line_items_qry = line_items_qry.order_by(Orders.CreatedAt.desc())
    elif sort_by == "sponsor_company":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Sponsor.Company.asc())
        else:
            line_items_qry = line_items_qry.order_by(Sponsor.Company.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(DriverAccount.FirstName.asc(), DriverAccount.LastName.asc())
        else:
            line_items_qry = line_items_qry.order_by(DriverAccount.FirstName.desc(), DriverAccount.LastName.desc())
    elif sort_by == "line_points":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.LineTotalPoints.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.LineTotalPoints.desc())
    elif sort_by == "unit_points":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.UnitPoints.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.UnitPoints.desc())
    elif sort_by == "quantity":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.Quantity.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.Quantity.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Orders.Status.asc())
        else:
            line_items_qry = line_items_qry.order_by(Orders.Status.desc())
    
    line_items_data = line_items_qry.all()
    
    # Calculate summary statistics for line items
    total_line_items = len(line_items_data)
    total_points = sum(line_item.LineTotalPoints for line_item, _, _, _, _, _ in line_items_data if line_item.LineTotalPoints)
    
    # Calculate total amount with fallback to point-to-dollar conversion
    total_amount = 0
    for line_item, order, _, _, sponsor, _ in line_items_data:
        if order.TotalAmount and order.TotalAmount > 0:
            line_proportion = line_item.LineTotalPoints / order.TotalPoints if order.TotalPoints > 0 else 0
            total_amount += float(order.TotalAmount) * line_proportion
        else:
            total_amount += float(line_item.LineTotalPoints) * float(sponsor.PointToDollarRate)
    
    # Count by status
    status_counts = {}
    for _, order, _, _, _, _ in line_items_data:
        status = order.Status or "Unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Generate PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#111827'),
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#374151'),
        spaceAfter=10,
    )
    
    # Title
    elements.append(Paragraph("Sales Analytics Detailed Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Report info
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Line Items:</b> {total_line_items:,}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Points:</b> {total_points:,}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Amount:</b> ${total_amount:,.2f}", styles['Normal']))
    
    # Add filter information
    filter_info = "Filters: "
    filters = []
    if company_filter:
        filters.append(f"Company: {company_filter}")
    if driver_name_filter:
        filters.append(f"Driver: {driver_name_filter}")
    if status_filter:
        filters.append(f"Status: {status_filter}")
    if order_number_filter:
        filters.append(f"Order: {order_number_filter}")
    if date_from:
        filters.append(f"From: {date_from}")
    if date_to:
        filters.append(f"To: {date_to}")
    
    if filters:
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>{filter_info}{'; '.join(filters)}</b>", styles['Normal']))
    else:
        elements.append(Paragraph("<b>Filters: None (All line items)</b>", styles['Normal']))
    
    elements.append(Spacer(1, 0.2*inch))
    
    # Status breakdown
    if status_counts:
        elements.append(Paragraph("Status Breakdown", heading_style))
        status_data = [['Status', 'Count']]
        for status, count in status_counts.items():
            status_data.append([status, str(count)])
        
        status_table = Table(status_data, colWidths=[3*inch, 1*inch])
        status_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb'))
        ]))
        elements.append(status_table)
        elements.append(Spacer(1, 0.3*inch))
    
    # Line items table - grouped by order
    elements.append(Paragraph("Line Items Details", heading_style))
    
    if line_items_data:
        # Group line items by order number
        orders_grouped = defaultdict(list)
        for line_item, order, driver, driver_account, sponsor, sponsor_account in line_items_data:
            orders_grouped[order.OrderID].append({
                'line_item': line_item,
                'order': order,
                'driver': driver,
                'driver_account': driver_account,
                'sponsor': sponsor,
                'sponsor_account': sponsor_account
            })
        
        # Process each order group
        for order_id, items in orders_grouped.items():
            # Get order header info
            first_item = items[0]
            order = first_item['order']
            sponsor = first_item['sponsor']
            driver_account = first_item['driver_account']
            sponsor_account = first_item['sponsor_account']
            
            # Order header
            date_str = order.CreatedAt.strftime('%m/%d/%Y') if order.CreatedAt else 'N/A'
            elements.append(Spacer(1, 0.2*inch))
            
            # Order section header
            order_header_style = ParagraphStyle(
                'OrderHeader',
                parent=styles['Normal'],
                fontSize=12,
                textColor=colors.HexColor('#111827'),
                spaceAfter=8,
                fontWeight='bold'
            )
            order_subheader_style = ParagraphStyle(
                'OrderSubheader',
                parent=styles['Normal'],
                fontSize=10,
                textColor=colors.HexColor('#6b7280'),
                spaceAfter=12
            )
            
            # Calculate order totals
            order_total_points = sum(item['line_item'].LineTotalPoints for item in items if item['line_item'].LineTotalPoints)
            order_total_amount = 0
            for item in items:
                line_total_points = item['line_item'].LineTotalPoints if item['line_item'].LineTotalPoints else 0
                order_total_amount += float(line_total_points) * float(item['sponsor'].PointToDollarRate)
            
            elements.append(Paragraph(f"Order: {order.OrderNumber}", order_header_style))
            order_info = f"Date: {date_str} | Company: {sponsor.Company} | Driver: {driver_account.FirstName} {driver_account.LastName} | Status: {order.Status}"
            elements.append(Paragraph(order_info, order_subheader_style))
            
            # Table header for this order's line items
            table_data = [['Product', 'Qty', 'Unit Price', 'Total Points', 'Total Amount']]
            
            # Add line items for this order
            for item in items:
                line_item = item['line_item']
                sponsor = item['sponsor']
                
                # Product info
                product_name = line_item.Title[:40] if line_item.Title else 'N/A'
                product = Paragraph(product_name, styles['Normal'])
                
                # Quantity
                quantity = str(line_item.Quantity) if line_item.Quantity else '0'
                
                # Unit price (points)
                unit_points = f"{line_item.UnitPoints:,}" if line_item.UnitPoints else '0'
                
                # Total points
                total_points_str = f"{line_item.LineTotalPoints:,}" if line_item.LineTotalPoints else '0'
                
                # Total dollar amount
                line_dollar_amount = float(line_item.LineTotalPoints if line_item.LineTotalPoints else 0) * float(sponsor.PointToDollarRate)
                total_amount_str = f"${line_dollar_amount:,.2f}"
                
                table_data.append([product, quantity, f"{unit_points} pts", total_points_str, total_amount_str])
            
            # Add order total row
            table_data.append([
                Paragraph("<b>Order Total:</b>", styles['Normal']),
                "",
                "",
                Paragraph(f"<b>{order_total_points:,} pts</b>", styles['Normal']),
                Paragraph(f"<b>${order_total_amount:,.2f}</b>", styles['Normal'])
            ])
            
            # Create table for this order
            table = Table(table_data, colWidths=[3.0*inch, 0.8*inch, 1.5*inch, 1.5*inch, 1.2*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f9fafb')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#374151')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'CENTER'),  # Quantity center aligned
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),  # Numbers right aligned
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.white),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e5e7eb')),  # Total row background
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 1), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(table)
    else:
        elements.append(Paragraph("No line items found matching the current filters.", styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    
    # Create response
    buffer.seek(0)
    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=sales_detailed_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    
    return response


# -------------------------------------------------------------------
# Sales Analytics Detailed Report CSV Export
#   URL: /admin/analytics/sales-detailed/csv
# -------------------------------------------------------------------
@bp.route("/analytics/sales-detailed/csv", methods=["GET"], endpoint="analytics_sales_detailed_csv")
@login_required
def analytics_sales_detailed_csv():
    """Generate a CSV version of the detailed sales analytics report with current filters"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return "Access denied: Admins only.", 403
    
    # Get filter parameters (same as regular report)
    company_filter = (request.args.get("company_filter") or "").strip()
    driver_name_filter = (request.args.get("driver_name_filter") or "").strip()
    status_filter = (request.args.get("status_filter") or "").strip()
    order_number_filter = (request.args.get("order_number_filter") or "").strip()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")
    
    # Build query for line items with all related data
    DriverAccount = aliased(Account)
    SponsorAccount = aliased(Account)
    
    line_items_qry = (
        db.session.query(OrderLineItem, Orders, Driver, DriverAccount, Sponsor, SponsorAccount)
        .join(Orders, Orders.OrderID == OrderLineItem.OrderID)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(Sponsor, Sponsor.SponsorID == Orders.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == Sponsor.AccountID)
    )
    
    # Apply filtering
    if company_filter:
        line_items_qry = line_items_qry.filter(Sponsor.Company == company_filter)
    
    if driver_name_filter:
        driver_name_search = f"%{driver_name_filter}%"
        line_items_qry = line_items_qry.filter(
            or_(
                DriverAccount.FirstName.ilike(driver_name_search),
                DriverAccount.LastName.ilike(driver_name_search),
                db.func.concat(DriverAccount.FirstName, ' ', DriverAccount.LastName).ilike(driver_name_search)
            )
        )
    
    if status_filter:
        line_items_qry = line_items_qry.filter(Orders.Status == status_filter)
    
    if order_number_filter:
        order_number_search = f"%{order_number_filter}%"
        line_items_qry = line_items_qry.filter(Orders.OrderNumber.ilike(order_number_search))
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            line_items_qry = line_items_qry.filter(Orders.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            line_items_qry = line_items_qry.filter(Orders.CreatedAt <= date_to_obj)
        except ValueError:
            pass
    
    # Apply sorting for line items
    if sort_by == "created_at":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Orders.CreatedAt.asc())
        else:
            line_items_qry = line_items_qry.order_by(Orders.CreatedAt.desc())
    elif sort_by == "sponsor_company":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Sponsor.Company.asc())
        else:
            line_items_qry = line_items_qry.order_by(Sponsor.Company.desc())
    elif sort_by == "driver_name":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(DriverAccount.FirstName.asc(), DriverAccount.LastName.asc())
        else:
            line_items_qry = line_items_qry.order_by(DriverAccount.FirstName.desc(), DriverAccount.LastName.desc())
    elif sort_by == "line_points":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.LineTotalPoints.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.LineTotalPoints.desc())
    elif sort_by == "unit_points":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.UnitPoints.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.UnitPoints.desc())
    elif sort_by == "quantity":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(OrderLineItem.Quantity.asc())
        else:
            line_items_qry = line_items_qry.order_by(OrderLineItem.Quantity.desc())
    elif sort_by == "status":
        if sort_order == "asc":
            line_items_qry = line_items_qry.order_by(Orders.Status.asc())
        else:
            line_items_qry = line_items_qry.order_by(Orders.Status.desc())
    
    line_items_data = line_items_qry.all()
    
    # Generate CSV
    output = BytesIO()
    
    # Write header
    header = "Order Date|Order Number|Sponsor Company|Driver|Product Title|Unit Points|Quantity|Line Total Points|Line Amount|Order Status\n"
    output.write(header.encode('utf-8'))
    
    # Write data rows
    for line_item, order, driver, driver_account, sponsor, sponsor_account in line_items_data:
        date_str = order.CreatedAt.strftime('%Y-%m-%d %H:%M') if order.CreatedAt else 'N/A'
        order_num = order.OrderNumber
        company = sponsor.Company
        driver_name = f"{driver_account.FirstName} {driver_account.LastName}"
        product_name = line_item.Title if line_item.Title else 'N/A'
        unit_points = str(line_item.UnitPoints) if line_item.UnitPoints else '0'
        quantity = str(line_item.Quantity) if line_item.Quantity else '0'
        total_points = str(line_item.LineTotalPoints) if line_item.LineTotalPoints else '0'
        
        # Calculate line amount
        line_amount = float(line_item.LineTotalPoints) * float(sponsor.PointToDollarRate)
        
        status = order.Status or 'Unknown'
        
        row = f"{date_str}|{order_num}|{company}|{driver_name}|{product_name}|{unit_points}|{quantity}|{total_points}|{line_amount:.2f}|{status}\n"
        output.write(row.encode('utf-8'))
    
    # Create response
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=sales_detailed_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response

# Add this code to the end of flask/app/routes/admin_routes.py

# -------------------------------------------------------------------
# User Management Page
#   URL: /admin/users
# -------------------------------------------------------------------
@bp.route("/users", methods=["GET"], endpoint="manage_users")
@login_required
def manage_users():
    """Admin page to view and manage all user accounts"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get filter parameters
    status_filter = request.args.get("status", "").strip().upper() if request.args.get("status") else None
    account_type_filter = request.args.get("account_type", "").strip().upper() if request.args.get("account_type") else None
    search_query = request.args.get("search", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25
    
    # Build query
    query = Account.query
    
    # Apply status filter
    if status_filter:
        query = query.filter(func.upper(Account.Status) == status_filter)
    
    # Apply account type filter
    if account_type_filter:
        query = query.filter(func.upper(Account.AccountType) == account_type_filter)
    
    # Apply search query
    if search_query:
        query = query.filter(
            or_(
                Account.Email.ilike(f"%{search_query}%"),
                Account.Username.ilike(f"%{search_query}%"),
                Account.FirstName.ilike(f"%{search_query}%"),
                Account.LastName.ilike(f"%{search_query}%")
            )
        )
    
    # Order by creation date
    query = query.order_by(Account.CreatedAt.desc())
    
    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    accounts = pagination.items
    
    # Enrich accounts with role-specific information
    enriched_accounts = []
    for account in accounts:
        account_data = {
            "AccountID": account.AccountID,
            "Username": account.Username,
            "Email": account.Email,
            "AccountType": account.AccountType,
            "Status": account.Status,
            "FirstName": account.FirstName,
            "LastName": account.LastName,
            "ProfileImageURL": account.ProfileImageURL,
            "CreatedAt": account.CreatedAt,
            "UpdatedAt": account.UpdatedAt,
            "RoleSpecificInfo": None
        }
        
        # Get role-specific info
        if account.AccountType == "DRIVER":
            driver = Driver.query.filter_by(AccountID=account.AccountID).first()
            if driver:
                account_data["RoleSpecificInfo"] = "Driver profile connected"
        elif account.AccountType == "SPONSOR":
            sponsor = Sponsor.query.filter_by(AccountID=account.AccountID).first()
            if sponsor:
                company_name = sponsor.Company or "Sponsor company"
                account_data["RoleSpecificInfo"] = f"{company_name} (Sponsor profile)"
        elif account.AccountType == "ADMIN":
            admin_obj = Admin.query.filter_by(AccountID=account.AccountID).first()
            if admin_obj:
                account_data["RoleSpecificInfo"] = f"Admin (Role: {admin_obj.Role or 'Administrator'})"
        
        enriched_accounts.append(account_data)
    
    # Get counts for status filter buttons
    # Use func.upper() for case-insensitive matching to handle any case variations in the database
    total_users = Account.query.count()
    active_users = Account.query.filter(func.upper(Account.Status) == 'A').count()
    inactive_users = Account.query.filter(func.upper(Account.Status) == 'I').count()
    pending_users = Account.query.filter(func.upper(Account.Status) == 'P').count()
    archived_users = Account.query.filter(func.upper(Account.Status) == 'H').count()
    
    return render_template("admin/manage_users.html",
                         accounts=enriched_accounts,
                         pagination=pagination,
                         status_filter=status_filter,
                         account_type_filter=account_type_filter,
                         search_query=search_query,
                         total_users=total_users,
                         active_users=active_users,
                         inactive_users=inactive_users,
                         pending_users=pending_users,
                         archived_users=archived_users)


@bp.route("/users/<account_id>/status", methods=["POST"], endpoint="change_user_status")
@login_required
def change_user_status(account_id):
    """Change the status of a user account"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("admin.manage_users"))
    
    try:
        new_status = (request.form.get("status") or "").strip().upper()
        current_app.logger.info(f"[manage_users] change_user_status called for {account_id} -> '{new_status}'")
        if new_status not in ['A', 'I', 'H']:
            flash("Invalid status. Must be A (Active), I (Inactive), or H (Archived)", "danger")
            return redirect(url_for("admin.manage_users"))
        
        # Get the account
        account = Account.query.get(account_id)
        if not account:
            flash("Account not found", "danger")
            return redirect(url_for("admin.manage_users"))
        
        # Prevent admins from deactivating themselves
        if account.AccountID == current_user.AccountID:
            flash("You cannot change your own account status", "warning")
            return redirect(url_for("admin.manage_users"))
        
        old_status = account.Status
        account.Status = new_status
        account.UpdatedAt = datetime.utcnow()
        account.UpdatedByAccountID = current_user.AccountID
        
        db.session.commit()
        # Verify persistence
        db.session.refresh(account)
        if (account.Status or '').upper() != new_status:
            current_app.logger.error(
                f"[manage_users] DB did not persist status {new_status} for {account_id}; current value: {account.Status}"
            )
            flash("Failed to archive user due to database constraint. Please run the archived-status migration and try again.", "danger")
            return redirect(url_for("admin.manage_users"))
        current_app.logger.info(f"[manage_users] status persisted for {account_id}: {old_status} -> {new_status}")
        
        # Log the status change
        current_app.logger.info(
            f"Admin {admin.AdminID} changed account {account_id} (Email: {account.Email}) status "
            f"from {old_status} to {new_status}"
        )
        
        status_names = {'A': 'Active', 'I': 'Inactive', 'H': 'Archived', 'P': 'Pending'}
        flash(f"Account status updated to {status_names.get(new_status, new_status)} successfully", "success")

        # Send driver notification if this account is a driver (respect driver prefs)
        try:
            drv = Driver.query.filter_by(AccountID=account.AccountID).first()
            if drv:
                from app.models import NotificationPreferences
                prefs = NotificationPreferences.get_or_create_for_driver(drv.DriverID)
                if prefs and prefs.AccountStatusChanges and prefs.EmailEnabled:
                    from app.services.notification_service import NotificationService
                    actor = "Admin"
                    NotificationService.notify_driver_account_status_change(account, new_status, changed_by=actor)
        except Exception as _e:
            current_app.logger.error(f"Failed to notify driver about status change: {_e}")
        return redirect(url_for("admin.manage_users"))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error changing user status: {str(e)}")
        flash(f"Error changing user status: {str(e)}", "danger")
        return redirect(url_for("admin.manage_users"))



# --- New: user details API for modal ---
@bp.route("/users/<account_id>/details", methods=["GET"], endpoint="get_user_details")
@login_required
def get_user_details(account_id):
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return jsonify({"error": "Access denied"}), 403
    acct = Account.query.get(account_id)
    if not acct:
        return jsonify({"error": "Not found"}), 404
    linked = {}
    if acct.AccountType == "DRIVER":
        drv = Driver.query.filter_by(AccountID=acct.AccountID).first()
        linked = {"DriverID": drv.DriverID} if drv else {}
    elif acct.AccountType == "SPONSOR":
        sp = Sponsor.query.filter_by(AccountID=acct.AccountID).first()
        if sp:
            linked = {"SponsorID": sp.SponsorID, "Company": sp.Company}
    elif acct.AccountType == "ADMIN":
        ad = Admin.query.filter_by(AccountID=acct.AccountID).first()
        if ad:
            linked = {"AdminID": ad.AdminID, "Role": ad.Role}
    return jsonify({
        "AccountID": acct.AccountID,
        "Email": acct.Email,
        "Username": acct.Username,
        "AccountType": acct.AccountType,
        "Status": acct.Status,
        "FirstName": acct.FirstName,
        "LastName": acct.LastName,
        "WholeName": acct.WholeName,
        "CreatedAt": acct.CreatedAt.isoformat() if acct.CreatedAt else None,
        "UpdatedAt": acct.UpdatedAt.isoformat() if acct.UpdatedAt else None,
        "Linked": linked,
    })

# --- New: permissions API ---
@bp.route("/permissions", methods=["GET"], endpoint="get_permissions")
@login_required
def get_permissions():
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return jsonify({"error": "Access denied"}), 403
    # Static permissions map; replace with DB-driven if available
    permissions = {
        "ADMIN": [
            "manage_users", "view_reports", "configure_catalog", "manage_support",
            "issue_points", "refund_orders", "change_account_status"
        ],
        "SPONSOR": [
            "view_catalog", "award_points", "view_driver_orders", "create_tickets"
        ],
        "DRIVER": [
            "browse_catalog", "place_orders", "view_points_balance", "create_tickets"
        ],
    }
    return jsonify({"roles": permissions})


# -------------------------------------------------------------------
# Impersonate User
#   URL: /admin/users/<account_id>/impersonate
# -------------------------------------------------------------------
@bp.route("/users/<account_id>/impersonate", methods=["POST"], endpoint="impersonate_user")
@login_required
def impersonate_user(account_id):
    """Allow admin to impersonate another user"""
    # Verify current user is an admin
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        return jsonify({"success": False, "error": "Access denied: Admins only."}), 403
    
    # Get the target account to impersonate
    target_account = Account.query.get(account_id)
    if not target_account:
        return jsonify({"success": False, "error": "User not found"}), 404
    
    # Prevent impersonating yourself
    if target_account.AccountID == current_user.AccountID:
        return jsonify({"success": False, "error": "You cannot impersonate yourself"}), 400
    
    # Prevent impersonating inactive or archived accounts
    status_code = (target_account.Status or '').upper()
    if status_code == 'I':
        return jsonify({"success": False, "error": "Cannot impersonate inactive accounts"}), 400
    if status_code == 'H':
        return jsonify({"success": False, "error": "Cannot impersonate archived accounts"}), 400
    
    try:
        # Store the original admin's account ID in session before impersonating
        # This allows us to know we're impersonating and return to login after logout
        original_admin_account_id = current_user.AccountID
        current_app.logger.info(f"Starting impersonation: Admin {original_admin_account_id} -> User {account_id}")
        
        # Store impersonation markers before logout
        preserved_session = dict(session)
        
        # Log out the current admin user (this clears Flask-Login session data)
        logout_user()
        
        # Restore preserved session values and impersonation markers
        session.update(preserved_session)
        session['impersonating'] = True
        session['original_admin_account_id'] = original_admin_account_id
        session.modified = True
        
        # Log in as the target user (this will set Flask-Login session data for the new user)
        login_user(target_account, remember=False)
        session.permanent = True  # Make session permanent to match CSRF token lifetime (31 days)
        current_app.logger.info(f"Logged in as target user: {target_account.AccountID}")
        
        # Set up the role session for the impersonated user
        from app.routes.auth import _set_role_session, _ensure_driver_environment
        _set_role_session(target_account)
        current_app.logger.info(f"Set role session for account type: {target_account.AccountType}")
        
        # SECURITY: Create session for tracking and auto-logout (same as regular login)
        SessionManagementService.create_session(target_account.AccountID, request)
        current_app.logger.info(f"Created session for impersonated user: {target_account.AccountID}")
        
        # Ensure driver environment if needed (for driver accounts)
        env_redirect = _ensure_driver_environment()
        if env_redirect:
            # If we need to redirect for environment selection, return that URL
            redirect_url = env_redirect.location if hasattr(env_redirect, 'location') else str(env_redirect)
            current_app.logger.info(f"Redirecting to driver environment selection: {redirect_url}")
            return jsonify({
                "success": True,
                "redirect_url": redirect_url
            })
        
        # Log the impersonation
        current_app.logger.info(
            f"Admin {admin.AdminID} (AccountID: {original_admin_account_id}) successfully impersonated "
            f"user {target_account.AccountID} (Email: {target_account.Email})"
        )
        
        # Ensure session is saved before redirect
        session.permanent = True
        
        redirect_url = url_for("dashboard")
        current_app.logger.info(f"Impersonation successful, redirecting to: {redirect_url}")
        
        return jsonify({
            "success": True,
            "redirect_url": redirect_url
        })
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"Error during impersonation: {str(e)}\n{error_trace}")
        return jsonify({"success": False, "error": f"Impersonation failed: {str(e)}"}), 500


# ============================================================================
# ADMIN ACCOUNT CREATION ROUTES
# ============================================================================

# -------------------------------------------------------------------
# Account Management Hub
# -------------------------------------------------------------------
@bp.route("/account-management", methods=["GET"], endpoint="account_management")
@login_required
def account_management():
    """Account management hub for admins"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    return render_template("admin/account_management.html")


# Helper functions for account creation
def _get_account_type_code(code: str) -> str:
    """Get account type code"""
    # Map single-letter codes from CSV to full codes
    code_mapping = {
        'D': 'DRIVER',
        'S': 'SPONSOR',
        'O': 'ADMIN'  # Organization = Admin
    }
    
    # If it's a single letter, map it
    if len(code) == 1:
        code = code_mapping.get(code.upper())
    
    valid_codes = ["DRIVER", "SPONSOR", "ADMIN"]
    if code not in valid_codes:
        raise RuntimeError(f"AccountType '{code}' is not valid. Valid codes: {valid_codes}")
    return code

def _hash_password(raw: str) -> str:
    """Hash a password"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def _get_account_type_id(code: str) -> str:
    """Resolve AccountTypeID from an AccountType code, creating it if missing"""
    code_norm = _get_account_type_code(code)
    at = AccountType.query.filter_by(AccountTypeCode=code_norm).first()
    if not at:
        at = AccountType(AccountTypeCode=code_norm, DisplayName=code_norm.title())
        db.session.add(at)
        db.session.flush()
    return at.AccountTypeID


# Form classes for admin account creation
class AdminDriverRegistrationForm(FlaskForm):
    """Driver registration form for admins"""
    Username = StringField('Username', validators=[
        DataRequired(), 
        Length(min=3, max=50),
        Regexp(r'^[a-zA-Z0-9_-]+$', message='Username can only contain letters, numbers, underscores, and hyphens')
    ])
    Email = StringField('Email', validators=[DataRequired(), EmailValidator()])
    Password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, max=128),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).*$', 
               message='Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character')
    ])
    FirstName = StringField('First Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='First name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    LastName = StringField('Last Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='Last name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    Phone = StringField('Phone', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^[\d\s\-\+\(\)]+$', message='Phone number contains invalid characters')
    ])

class AdminSponsorRegistrationForm(FlaskForm):
    """Sponsor registration form for admins"""
    Username = StringField('Username', validators=[
        DataRequired(), 
        Length(min=3, max=50),
        Regexp(r'^[a-zA-Z0-9_-]+$', message='Username can only contain letters, numbers, underscores, and hyphens')
    ])
    Email = StringField('Email', validators=[DataRequired(), EmailValidator()])
    Password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, max=128),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).*$', 
               message='Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character')
    ])
    FirstName = StringField('First Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='First name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    LastName = StringField('Last Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='Last name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    Phone = StringField('Phone', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^[\d\s\-\+\(\)]+$', message='Phone number contains invalid characters')
    ])
    Company = StringField('Company', validators=[
        DataRequired(),
        Length(min=1, max=200),
        Regexp(r'^[a-zA-Z0-9\s\.,\-\'&]+$', message='Company name contains invalid characters')
    ])
    BillingEmail = StringField('Billing Email', validators=[Optional(), EmailValidator()])

class AdminAdminRegistrationForm(FlaskForm):
    """Admin registration form for admins"""
    Username = StringField('Username', validators=[
        DataRequired(), 
        Length(min=3, max=50),
        Regexp(r'^[a-zA-Z0-9_-]+$', message='Username can only contain letters, numbers, underscores, and hyphens')
    ])
    Email = StringField('Email', validators=[DataRequired(), EmailValidator()])
    Password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, max=128),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).*$', 
               message='Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character')
    ])
    FirstName = StringField('First Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='First name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    LastName = StringField('Last Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='Last name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    Phone = StringField('Phone', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^[\d\s\-\+\(\)]+$', message='Phone number contains invalid characters')
    ])
    Role = StringField('Role', validators=[
        Optional(),
        Length(max=100),
        Regexp(r'^[a-zA-Z0-9\s\-\_]+$', message='Role contains invalid characters')
    ])


# -------------------------------------------------------------------
# Admin Create Driver Account
# -------------------------------------------------------------------
@bp.route("/create-driver", methods=["GET", "POST"], endpoint="admin_create_driver")
@login_required
def admin_create_driver():
    """Admin-only route to create driver accounts"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    form = AdminDriverRegistrationForm()
    if form.validate_on_submit():
        try:
            phone_raw = form.Phone.data
            phone_enc = fernet.encrypt(phone_raw.encode()).decode() if phone_raw else None

            acc = Account(
                AccountType=_get_account_type_code("DRIVER"),
                AccountTypeID=_get_account_type_id("DRIVER"),
                Username=form.Username.data.strip(),
                Email=form.Email.data.lower().strip(),
                Phone=phone_enc,
                PasswordHash=_hash_password(form.Password.data),
                FirstName=form.FirstName.data.strip(),
                LastName=form.LastName.data.strip(),
                WholeName=f"{form.FirstName.data.strip()} {form.LastName.data.strip()}".strip(),
                Status='A',
            )
            db.session.add(acc)
            db.session.flush()

            # Log initial password creation
            PasswordSecurityService.log_password_change(
                account_id=acc.AccountID,
                new_password_hash=acc.PasswordHash,
                change_reason='admin_created_account',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            token = str(uuid.uuid4())
            ev = EmailVerification(AccountID=acc.AccountID, VerificationToken=token, SentAt=datetime.utcnow())
            db.session.add(ev)
            db.session.commit()

            verify_url = url_for("auth.verify_email", token=token, _external=True)
            msg = Message(
                subject="Verify Your Email - Driver Rewards",
                recipients=[acc.Email],
                body=f"Welcome to Driver Rewards!\n\nYour account has been created by an administrator.\n\nClick to verify your email:\n{verify_url}\n\nIf you didn't expect this, please contact support."
            )
            from ..extensions import mail
            mail.send(msg)

            flash("Driver account created successfully!", "success")
            return redirect(url_for("admin.admin_create_driver"))

        except IntegrityError as e:
            db.session.rollback()
            flash(f"Could not create driver: {e.orig}", "error")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
    elif request.method == "POST":
        # Form did not validate; surface errors
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "error")

    return render_template("admin/create_driver.html", form=form)


# -------------------------------------------------------------------
# Admin Create Sponsor Account
# -------------------------------------------------------------------
@bp.route("/create-sponsor", methods=["GET", "POST"], endpoint="admin_create_sponsor")
@login_required
def admin_create_sponsor():
    """Admin-only route to create sponsor accounts"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    form = AdminSponsorRegistrationForm()
    if form.validate_on_submit():
        password = form.Password.data
        # Check password complexity
        is_strong, complexity_error = PasswordSecurityService.is_password_strong(password)
        if not is_strong:
            flash(f"Password complexity error: {complexity_error}", "error")
            return render_template("admin/create_sponsor.html", form=form, error=f"Password complexity error: {complexity_error}")
        try:
            phone_raw = form.Phone.data
            phone_enc = fernet.encrypt(phone_raw.encode()).decode() if phone_raw else None

            acc = Account(
                AccountType=_get_account_type_code("SPONSOR"),
                AccountTypeID=_get_account_type_id("SPONSOR"),
                Username=form.Username.data,
                Email=form.Email.data,
                Phone=phone_enc,
                PasswordHash=_hash_password(password),
                FirstName=form.FirstName.data,
                LastName=form.LastName.data,
                WholeName=f"{form.FirstName.data} {form.LastName.data}".strip(),
                Status='A',
            )
            db.session.add(acc)
            db.session.flush()

            # Create or find SponsorCompany
            company_name = form.Company.data or "Unnamed Sponsor"
            sponsor_company = SponsorCompany.query.filter_by(CompanyName=company_name).first()
            if not sponsor_company:
                sponsor_company = SponsorCompany(CompanyName=company_name)
                db.session.add(sponsor_company)
                db.session.flush()
            
            sp = Sponsor(
                AccountID=acc.AccountID,
                Company=company_name,
                SponsorCompanyID=sponsor_company.SponsorCompanyID,
                BillingEmail=form.BillingEmail.data or form.Email.data,
                IsAdmin=False,
            )
            db.session.add(sp)

            # Log initial password creation
            PasswordSecurityService.log_password_change(
                account_id=acc.AccountID,
                new_password_hash=acc.PasswordHash,
                change_reason='admin_created_account',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            token = str(uuid.uuid4())
            ev = EmailVerification(AccountID=acc.AccountID, VerificationToken=token, SentAt=datetime.utcnow())
            db.session.add(ev)
            db.session.commit()

            verify_url = url_for("auth.verify_email", token=token, _external=True)
            msg = Message(
                subject="Verify Your Email - Driver Rewards",
                recipients=[acc.Email],
                body=f"Welcome to Driver Rewards!\n\nYour sponsor account has been created by an administrator.\n\nClick to verify your email:\n{verify_url}\n\nIf you didn't expect this, please contact support."
            )
            from ..extensions import mail
            mail.send(msg)

            flash("Sponsor account created successfully!", "success")
            return redirect(url_for("admin.admin_create_sponsor"))

        except IntegrityError as e:
            db.session.rollback()
            flash(f"Could not create sponsor: {e.orig}", "error")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
    elif request.method == "POST":
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "error")
    
    return render_template("admin/create_sponsor.html", form=form)


# -------------------------------------------------------------------
# Admin Create Admin Account
# -------------------------------------------------------------------
@bp.route("/create-admin", methods=["GET", "POST"], endpoint="admin_create_admin")
@login_required
def admin_create_admin():
    """Admin-only route to create admin accounts"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    form = AdminAdminRegistrationForm()
    if form.validate_on_submit():
        password = form.Password.data
        # Check password complexity
        is_strong, complexity_error = PasswordSecurityService.is_password_strong(password)
        if not is_strong:
            flash(f"Password complexity error: {complexity_error}", "error")
            return render_template("admin/create_admin.html", form=form, error=f"Password complexity error: {complexity_error}")
        try:
            phone_raw = form.Phone.data
            phone_enc = fernet.encrypt(phone_raw.encode()).decode() if phone_raw else None

            acc = Account(
                AccountType=_get_account_type_code("ADMIN"),
                AccountTypeID=_get_account_type_id("ADMIN"),
                Username=form.Username.data,
                Email=form.Email.data,
                Phone=phone_enc,
                PasswordHash=_hash_password(password),
                FirstName=form.FirstName.data,
                LastName=form.LastName.data,
                WholeName=f"{form.FirstName.data} {form.LastName.data}".strip(),
                Status='A',
            )
            db.session.add(acc)
            db.session.flush()

            ad = Admin(AccountID=acc.AccountID, Role=form.Role.data or "Admin")
            db.session.add(ad)

            # Log initial password creation
            PasswordSecurityService.log_password_change(
                account_id=acc.AccountID,
                new_password_hash=acc.PasswordHash,
                change_reason='admin_created_account',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            token = str(uuid.uuid4())
            ev = EmailVerification(AccountID=acc.AccountID, VerificationToken=token, SentAt=datetime.utcnow())
            db.session.add(ev)
            db.session.commit()

            verify_url = url_for("auth.verify_email", token=token, _external=True)
            msg = Message(
                subject="Verify Your Email - Driver Rewards",
                recipients=[acc.Email],
                body=f"Welcome to Driver Rewards!\n\nYour admin account has been created by an administrator.\n\nClick to verify your email:\n{verify_url}\n\nIf you didn't expect this, please contact support."
            )
            from ..extensions import mail
            mail.send(msg)

            flash("Admin account created successfully!", "success")
            return redirect(url_for("admin.admin_create_admin"))

        except IntegrityError as e:
            db.session.rollback()
            flash(f"Could not create admin: {e.orig}", "error")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
    elif request.method == "POST":
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "error")
    
    return render_template("admin/create_admin.html", form=form)


# -------------------------------------------------------------------
# Bulk Import Users from pipe-delimited file
# -------------------------------------------------------------------
@bp.route("/bulk-import-users", methods=["GET", "POST"], endpoint="bulk_import_users")
@login_required
def bulk_import_users():
    """Admin-only route to bulk import user accounts (Driver, Sponsor) and organizations from a pipe-delimited file"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        action = request.form.get("action")
        if action == "bulk_import":
            csv_file = request.files.get("csv_file")
            
            if not csv_file or not csv_file.filename:
                flash("Please select a pipe-delimited .txt or .csv file to upload.", "danger")
                return redirect(url_for("admin.bulk_import_users"))
            
            allowed_extensions = ('.txt', '.csv')
            if not csv_file.filename.lower().endswith(allowed_extensions):
                flash("Please upload a pipe-delimited .txt or .csv file.", "danger")
                return redirect(url_for("admin.bulk_import_users"))
            
            # Process pipe-delimited file (both .txt and .csv files should be pipe-delimited)
            try:
                # Read the uploaded file
                csv_content = csv_file.read().decode('utf-8')
                csv_reader = csv.reader(csv_content.splitlines(), delimiter='|')
                
                success_count = 0
                error_count = 0
                errors = []
                total_rows_processed = 0
                bulk_import_log = None
                
                # Create bulk import log record
                try:
                    bulk_import_log = BulkImportLog(
                        UploadedByAccountID=current_user.AccountID,
                        UploadedByRole="admin",
                        SponsorCompanyID=None,  # Admin uploads aren't tied to a specific company
                        FileName=csv_file.filename,
                        TotalRows=0,
                        SuccessCount=0,
                        ErrorCount=0,
                        ImportSummary=None
                    )
                    db.session.add(bulk_import_log)
                    db.session.flush()  # Get BulkImportLogID
                except Exception as e:
                    current_app.logger.error(f"Failed to create BulkImportLog: {str(e)}")
                
                # Generate a default password for all users
                default_password = "TempPassword123!"
                
                for row_num, row in enumerate(csv_reader, start=1):
                    # Skip empty rows
                    if not row or all(not cell.strip() for cell in row):
                        continue
                    
                    total_rows_processed += 1
                    user_type = row[0].strip().upper()
                    
                    # Handle Organization (O) type - only 2 columns
                    if user_type == 'O':
                        if len(row) < 2:
                            error_count += 1
                            error_msg = "Organization format requires 2 columns (O|company name)"
                            errors.append(f"Row {row_num}: {error_msg}")
                            if bulk_import_log:
                                try:
                                    error_log = BulkImportError(
                                        BulkImportLogID=bulk_import_log.BulkImportLogID,
                                        RowNumber=row_num,
                                        CSVRowData='|'.join(row),
                                        ErrorMessage=error_msg
                                    )
                                    db.session.add(error_log)
                                except Exception as e:
                                    current_app.logger.error(f"Failed to log error: {str(e)}")
                            continue
                        
                        company_name = row[1].strip()
                        if not company_name:
                            error_count += 1
                            error_msg = "Company name is required"
                            errors.append(f"Row {row_num}: {error_msg}")
                            if bulk_import_log:
                                try:
                                    error_log = BulkImportError(
                                        BulkImportLogID=bulk_import_log.BulkImportLogID,
                                        RowNumber=row_num,
                                        CSVRowData='|'.join(row),
                                        ErrorMessage=error_msg
                                    )
                                    db.session.add(error_log)
                                except Exception as e:
                                    current_app.logger.error(f"Failed to log error: {str(e)}")
                            continue
                        
                        # Check if company already exists
                        existing_company = SponsorCompany.query.filter_by(CompanyName=company_name).first()
                        if existing_company:
                            error_count += 1
                            error_msg = f"Company '{company_name}' already exists"
                            errors.append(f"Row {row_num}: {error_msg}")
                            if bulk_import_log:
                                try:
                                    error_log = BulkImportError(
                                        BulkImportLogID=bulk_import_log.BulkImportLogID,
                                        RowNumber=row_num,
                                        CSVRowData='|'.join(row),
                                        ErrorMessage=error_msg
                                    )
                                    db.session.add(error_log)
                                except Exception as e:
                                    current_app.logger.error(f"Failed to log error: {str(e)}")
                            continue
                        
                        try:
                            # Create new SponsorCompany
                            sponsor_company = SponsorCompany(CompanyName=company_name)
                            db.session.add(sponsor_company)
                            db.session.commit()
                            success_count += 1
                        
                        except IntegrityError as e:
                            db.session.rollback()
                            error_count += 1
                            error_msg = f"Database error - {str(e)}"
                            errors.append(f"Row {row_num}: {error_msg}")
                            if bulk_import_log:
                                try:
                                    error_log = BulkImportError(
                                        BulkImportLogID=bulk_import_log.BulkImportLogID,
                                        RowNumber=row_num,
                                        CSVRowData='|'.join(row),
                                        ErrorMessage=error_msg
                                    )
                                    db.session.add(error_log)
                                except Exception as e:
                                    current_app.logger.error(f"Failed to log error: {str(e)}")
                        except Exception as e:
                            db.session.rollback()
                            error_count += 1
                            error_msg = f"Error - {str(e)}"
                            errors.append(f"Row {row_num}: {error_msg}")
                            if bulk_import_log:
                                try:
                                    error_log = BulkImportError(
                                        BulkImportLogID=bulk_import_log.BulkImportLogID,
                                        RowNumber=row_num,
                                        CSVRowData='|'.join(row),
                                        ErrorMessage=error_msg
                                    )
                                    db.session.add(error_log)
                                except Exception as e:
                                    current_app.logger.error(f"Failed to log error: {str(e)}")
                        
                        continue
                    
                    # Validate user type
                    if user_type not in ['D', 'S']:
                        error_count += 1
                        error_msg = f"Invalid user type '{user_type}'. Only 'D' (Driver), 'S' (Sponsor), and 'O' (Organization) are allowed."
                        errors.append(f"Row {row_num}: {error_msg}")
                        if bulk_import_log:
                            try:
                                error_log = BulkImportError(
                                    BulkImportLogID=bulk_import_log.BulkImportLogID,
                                    RowNumber=row_num,
                                    CSVRowData='|'.join(row),
                                    ErrorMessage=error_msg
                                )
                                db.session.add(error_log)
                            except Exception as e:
                                current_app.logger.error(f"Failed to log error: {str(e)}")
                        continue
                    
                    # Handle user types (D/S) - 5 columns required
                    if len(row) != 5:
                        error_count += 1
                        error_msg = f"Invalid format (expected 5 columns, got {len(row)})"
                        errors.append(f"Row {row_num}: {error_msg}")
                        if bulk_import_log:
                            try:
                                error_log = BulkImportError(
                                    BulkImportLogID=bulk_import_log.BulkImportLogID,
                                    RowNumber=row_num,
                                    CSVRowData='|'.join(row),
                                    ErrorMessage=error_msg
                                )
                                db.session.add(error_log)
                            except Exception as e:
                                current_app.logger.error(f"Failed to log error: {str(e)}")
                        continue
                    
                    org_name, first_name, last_name, email = [cell.strip() for cell in row[1:5]]
                    
                    # Validate required fields
                    if not user_type or not first_name or not last_name or not email:
                        error_count += 1
                        error_msg = "Missing required fields"
                        errors.append(f"Row {row_num}: {error_msg}")
                        if bulk_import_log:
                            try:
                                error_log = BulkImportError(
                                    BulkImportLogID=bulk_import_log.BulkImportLogID,
                                    RowNumber=row_num,
                                    CSVRowData='|'.join(row),
                                    ErrorMessage=error_msg
                                )
                                db.session.add(error_log)
                            except Exception as e:
                                current_app.logger.error(f"Failed to log error: {str(e)}")
                        continue
                    
                    # Validate email format
                    if '@' not in email:
                        error_count += 1
                        error_msg = "Invalid email format"
                        errors.append(f"Row {row_num}: {error_msg}")
                        if bulk_import_log:
                            try:
                                error_log = BulkImportError(
                                    BulkImportLogID=bulk_import_log.BulkImportLogID,
                                    RowNumber=row_num,
                                    CSVRowData='|'.join(row),
                                    ErrorMessage=error_msg
                                )
                                db.session.add(error_log)
                            except Exception as e:
                                current_app.logger.error(f"Failed to log error: {str(e)}")
                        continue
                    
                    # Check if email already exists
                    existing_account = Account.query.filter_by(Email=email.lower()).first()
                    if existing_account:
                        error_count += 1
                        error_msg = f"Email {email} already exists"
                        errors.append(f"Row {row_num}: {error_msg}")
                        if bulk_import_log:
                            try:
                                error_log = BulkImportError(
                                    BulkImportLogID=bulk_import_log.BulkImportLogID,
                                    RowNumber=row_num,
                                    CSVRowData='|'.join(row),
                                    ErrorMessage=error_msg
                                )
                                db.session.add(error_log)
                            except Exception as e:
                                current_app.logger.error(f"Failed to log error: {str(e)}")
                        continue
                    
                    try:
                        # Generate username if not provided (use email prefix)
                        username = email.split('@')[0].lower()
                        # Ensure username is unique
                        counter = 1
                        original_username = username
                        while Account.query.filter_by(Username=username).first():
                            username = f"{original_username}{counter}"
                            counter += 1
                        
                        # Create Account
                        acc = Account(
                            AccountType=_get_account_type_code(user_type),
                            AccountTypeID=_get_account_type_id(user_type),
                            Username=username,
                            Email=email.lower(),
                            Phone=None,
                            PasswordHash=_hash_password(default_password),
                            FirstName=first_name,
                            LastName=last_name,
                            WholeName=f"{first_name} {last_name}".strip(),
                            Status='A',
                        )
                        db.session.add(acc)
                        db.session.flush()
                        
                        # Log initial password creation
                        PasswordSecurityService.log_password_change(
                            account_id=acc.AccountID,
                            new_password_hash=acc.PasswordHash,
                            change_reason='admin_bulk_import',
                            ip_address=request.remote_addr,
                            user_agent=request.headers.get('User-Agent')
                        )
                        
                        # Create email verification token
                        token = str(uuid.uuid4())
                        ev = EmailVerification(AccountID=acc.AccountID, VerificationToken=token, SentAt=datetime.utcnow())
                        db.session.add(ev)
                        
                        # Create specific user type records
                        if user_type == 'D':  # Driver
                            driver = Driver(
                                AccountID=acc.AccountID,
                                SponsorCompanyID=None,  # Will be linked once assigned
                                Status='ACTIVE'
                            )
                            db.session.add(driver)
                            db.session.flush()  # Need DriverID for DriverSponsor
                            
                            # Auto-assign to oldest active sponsor (with active account)
                            oldest_sponsor = (
                                db.session.query(Sponsor)
                                .join(Account, Account.AccountID == Sponsor.AccountID)
                                .filter(Account.Status.in_(['A', 'a', 'P', 'p']))  # Active or Pending
                                .order_by(Sponsor.CreatedAt.asc())
                                .first()
                            )
                            
                            if oldest_sponsor:
                                # Create DriverSponsor relationship
                                if not oldest_sponsor.SponsorCompanyID:
                                    db.session.rollback()
                                    error_count += 1
                                    error_msg = "Assigned sponsor is missing organization configuration. Cannot create driver."
                                    errors.append(f"Row {row_num}: {error_msg}")
                                    if bulk_import_log:
                                        try:
                                            error_log = BulkImportError(
                                                BulkImportLogID=bulk_import_log.BulkImportLogID,
                                                RowNumber=row_num,
                                                CSVRowData='|'.join(row),
                                                ErrorMessage=error_msg
                                            )
                                            db.session.add(error_log)
                                        except Exception as e:
                                            current_app.logger.error(f"Failed to log error: {str(e)}")
                                    continue

                                driver.SponsorCompanyID = oldest_sponsor.SponsorCompanyID

                                driver_sponsor = DriverSponsor(
                                    DriverID=driver.DriverID,
                                    SponsorID=oldest_sponsor.SponsorID,
                                    SponsorCompanyID=oldest_sponsor.SponsorCompanyID,
                                    PointsBalance=0,
                                    Status='ACTIVE'
                                )
                                db.session.add(driver_sponsor)
                            else:
                                # No active sponsors exist - log error
                                db.session.rollback()
                                error_count += 1
                                error_msg = "No active sponsors found. Cannot create driver without a sponsor assignment."
                                errors.append(f"Row {row_num}: {error_msg}")
                                if bulk_import_log:
                                    try:
                                        error_log = BulkImportError(
                                            BulkImportLogID=bulk_import_log.BulkImportLogID,
                                            RowNumber=row_num,
                                            CSVRowData='|'.join(row),
                                            ErrorMessage=error_msg
                                        )
                                        db.session.add(error_log)
                                    except Exception as e:
                                        current_app.logger.error(f"Failed to log error: {str(e)}")
                                continue
                        
                        elif user_type == 'S':  # Sponsor
                            if not org_name:
                                error_count += 1
                                error_msg = "Organization name required for Sponsor"
                                errors.append(f"Row {row_num}: {error_msg}")
                                db.session.rollback()
                                if bulk_import_log:
                                    try:
                                        error_log = BulkImportError(
                                            BulkImportLogID=bulk_import_log.BulkImportLogID,
                                            RowNumber=row_num,
                                            CSVRowData='|'.join(row),
                                            ErrorMessage=error_msg
                                        )
                                        db.session.add(error_log)
                                    except Exception as e:
                                        current_app.logger.error(f"Failed to log error: {str(e)}")
                                continue
                            
                            # Create or find SponsorCompany
                            sponsor_company = SponsorCompany.query.filter_by(CompanyName=org_name).first()
                            if not sponsor_company:
                                error_count += 1
                                error_msg = f"Organization '{org_name}' does not exist. Create it first using O flag."
                                errors.append(f"Row {row_num}: {error_msg}")
                                db.session.rollback()
                                if bulk_import_log:
                                    try:
                                        error_log = BulkImportError(
                                            BulkImportLogID=bulk_import_log.BulkImportLogID,
                                            RowNumber=row_num,
                                            CSVRowData='|'.join(row),
                                            ErrorMessage=error_msg
                                        )
                                        db.session.add(error_log)
                                    except Exception as e:
                                        current_app.logger.error(f"Failed to log error: {str(e)}")
                                continue
                            
                            sponsor = Sponsor(
                                AccountID=acc.AccountID,
                                Company=org_name,
                                SponsorCompanyID=sponsor_company.SponsorCompanyID,
                                BillingEmail=email,
                                IsAdmin=False
                            )
                            db.session.add(sponsor)
                        
                        # Commit this user
                        db.session.commit()
                        success_count += 1
                        
                        # Send verification email
                        try:
                            account_type_label = "Driver" if user_type == 'D' else "Sponsor"
                            verify_url = url_for("auth.verify_email", token=token, _external=True)
                            msg = Message(
                                subject="Your Driver Rewards Account",
                                recipients=[acc.Email],
                                body=f"""Welcome to Driver Rewards!

Your {account_type_label.lower()} account has been created by an administrator.

Your temporary credentials:
Email: {email}
Password: {default_password}

Please click the link below to verify your email and change your password:
{verify_url}

If you didn't expect this email, please contact support."""
                            )
                            from ..extensions import mail
                            mail.send(msg)
                        except Exception as e:
                            current_app.logger.error(f"Failed to send email to {email}: {str(e)}")
                    
                    except IntegrityError as e:
                        db.session.rollback()
                        error_count += 1
                        error_msg = f"Database error - {str(e)}"
                        errors.append(f"Row {row_num}: {error_msg}")
                        if bulk_import_log:
                            try:
                                error_log = BulkImportError(
                                    BulkImportLogID=bulk_import_log.BulkImportLogID,
                                    RowNumber=row_num,
                                    CSVRowData='|'.join(row),
                                    ErrorMessage=error_msg
                                )
                                db.session.add(error_log)
                            except Exception as e:
                                current_app.logger.error(f"Failed to log error: {str(e)}")
                    except Exception as e:
                        db.session.rollback()
                        error_count += 1
                        error_msg = f"Error - {str(e)}"
                        errors.append(f"Row {row_num}: {error_msg}")
                        if bulk_import_log:
                            try:
                                error_log = BulkImportError(
                                    BulkImportLogID=bulk_import_log.BulkImportLogID,
                                    RowNumber=row_num,
                                    CSVRowData='|'.join(row),
                                    ErrorMessage=error_msg
                                )
                                db.session.add(error_log)
                            except Exception as e:
                                current_app.logger.error(f"Failed to log error: {str(e)}")
                
                # Update bulk import log with final statistics
                if bulk_import_log:
                    try:
                        bulk_import_log.TotalRows = total_rows_processed
                        bulk_import_log.SuccessCount = success_count
                        bulk_import_log.ErrorCount = error_count
                        
                        # Create summary
                        summary = {
                            "total_rows": total_rows_processed,
                            "successful": success_count,
                            "failed": error_count,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        bulk_import_log.ImportSummary = json.dumps(summary)
                        
                        db.session.commit()
                    except Exception as e:
                        current_app.logger.error(f"Failed to update BulkImportLog: {str(e)}")
                        db.session.rollback()
                
                # Final summary message
                if success_count > 0:
                    flash(f"Successfully imported {success_count} record(s)!", "success")
                if error_count > 0:
                    error_msg = f"Failed to import {error_count} record(s). "
                    if len(errors) <= 5:
                        error_msg += "Errors: " + "; ".join(errors)
                    else:
                        error_msg += f"First 5 errors: {'; '.join(errors[:5])}"
                    flash(error_msg, "warning")
                
                if success_count == 0 and error_count == 0:
                    flash("No valid rows found in the import file.", "warning")
            
            except Exception as e:
                flash(f"Error reading import file: {str(e)}", "danger")
                current_app.logger.error(f"Bulk import error: {str(e)}", exc_info=True)
                # Try to mark the bulk import log as failed
                if 'bulk_import_log' in locals() and bulk_import_log:
                    try:
                        bulk_import_log.ErrorCount = error_count if 'error_count' in locals() else 0
                        bulk_import_log.SuccessCount = success_count if 'success_count' in locals() else 0
                        bulk_import_log.TotalRows = total_rows_processed if 'total_rows_processed' in locals() else 0
                        summary = {
                            "error": str(e),
                            "timestamp": datetime.utcnow().isoformat()
                        }
                        bulk_import_log.ImportSummary = json.dumps(summary)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
    
    return render_template("admin/bulk_import_users.html")


# -------------------------------------------------------------------
# Bulk Import Audit Log (Admin-only - all companies)
# -------------------------------------------------------------------
@bp.route("/bulk-import-audit-log", methods=["GET"], endpoint="bulk_import_audit_log")
@login_required
def bulk_import_audit_log():
    """View bulk import logs for all sponsor companies (admin only)"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get filter parameters
    q = request.args.get("q", "").strip()
    company_filter = request.args.get("company_filter", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()
    
    # Build query for bulk import logs - ALL companies
    qry = (
        db.session.query(BulkImportLog, Account, SponsorCompany)
        .join(Account, Account.AccountID == BulkImportLog.UploadedByAccountID)
        .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == BulkImportLog.SponsorCompanyID)
    )
    
    # Company filtering
    if company_filter:
        qry = qry.filter(SponsorCompany.CompanyName == company_filter)
    
    # Date filtering
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(BulkImportLog.ImportedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(BulkImportLog.ImportedAt < date_to_obj)
        except ValueError:
            pass
    
    # Search filtering
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(like),
                Account.LastName.ilike(like),
                BulkImportLog.FileName.ilike(like),
                SponsorCompany.CompanyName.ilike(like)
            )
        )
    
    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(BulkImportLog.ImportedAt.asc())
    else:
        qry = qry.order_by(BulkImportLog.ImportedAt.desc())
    
    logs = qry.all()
    
    # Get list of companies for filter dropdown
    companies = SponsorCompany.query.order_by(SponsorCompany.CompanyName.asc()).all()
    
    return render_template(
        "admin_bulk_import_audit_log.html",
        logs=logs, q=q, company_filter=company_filter,
        date_from=date_from, date_to=date_to, 
        sort_order=sort_order, companies=companies
    )


# -------------------------------------------------------------------
# Bulk Import Error Details (Admin-only)
# -------------------------------------------------------------------
@bp.route("/bulk-import-errors/<log_id>", methods=["GET"], endpoint="bulk_import_error_details")
@login_required
def bulk_import_error_details(log_id):
    """View detailed errors for a specific bulk import log (admin only)"""
    admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
    if not admin:
        flash("Access denied: Admins only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get the log - admins can view all
    bulk_log = BulkImportLog.query.filter_by(BulkImportLogID=log_id).first()
    
    if not bulk_log:
        flash("Import log not found.", "danger")
        return redirect(url_for("admin.bulk_import_audit_log"))
    
    # Get company info if exists
    company_name = None
    if bulk_log.SponsorCompanyID:
        sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=bulk_log.SponsorCompanyID).first()
        if sponsor_company:
            company_name = sponsor_company.CompanyName
    
    # Get errors for this log
    errors = BulkImportError.query.filter_by(BulkImportLogID=log_id).order_by(BulkImportError.RowNumber.asc()).all()
    
    return render_template(
        "admin_bulk_import_errors.html",
        bulk_log=bulk_log,
        errors=errors,
        company_name=company_name
    )