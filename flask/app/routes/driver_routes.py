from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify, send_file, current_app
from flask_login import login_required, current_user
from datetime import datetime
from io import BytesIO
from app.models import (
    Account, Driver, db, LoginAttempts, PointChange, PointChangeDispute, Sponsor,
    DriverSponsor, NotificationPreferences, DriverRewardGoal, SponsorCompany
)
from app.services.achievement_service import AchievementService
from app.services.product_view_service import ProductViewService
from app.services.profile_audit_service import ProfileAuditService
from config import fernet
import bcrypt
import os
from werkzeug.utils import secure_filename
import pyotp

from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from sqlalchemy.orm import joinedload

bp = Blueprint("driver", __name__, url_prefix="/driver")

# =========================
# DRIVER ACCOUNT
# =========================
@bp.route("/account", methods=["GET", "POST"], endpoint="driver_account")
@login_required
def driver_account():
    account = Account.query.filter_by(AccountID=current_user.AccountID).first()
    driver  = Driver.query.filter_by(AccountID=current_user.AccountID).first()

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
            flash_category = category
            if flash_category == "error":
                flash_category = "danger"
            if flash_category not in {"success", "info", "warning", "danger"}:
                flash_category = "success"
            flash(message, flash_category)
            return redirect(url_for("driver.driver_account"))

        if action == "change_email":
            new_email = (request.form.get("new_email") or "").strip()
            confirm_email = (request.form.get("confirm_email") or "").strip()
            current_password = (request.form.get("current_password") or "").strip()
            mfa_code = (request.form.get("mfa_code") or "").strip()

            if not account:
                return _respond("Account not found.", "danger", 404)

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

            db.session.commit()

            try:
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
                    change_reason="Self-update email via driver account page"
                )
            except Exception as audit_exc:
                try:
                    current_app.logger.warning(f"Driver email change audit failed: {audit_exc}")
                except Exception:
                    pass

            try:
                from app.services.notification_service import NotificationService
                NotificationService.notify_driver_email_changed(old_email_value, new_email, account)
            except Exception as notify_exc:
                try:
                    current_app.logger.error(f"Failed to send email change notification: {notify_exc}")
                except Exception:
                    pass

            return _respond("Email updated successfully.", "success", 200, email=new_email)

        if action == 'upload_avatar':
            # avatar-only flow; do not touch other fields
            try:
                from app.services.s3_service import upload_avatar, delete_avatar

                file = request.files.get('profile_image')
                if file and getattr(file, 'filename', ''):
                    # Get old S3 key before updating (if it exists and is an S3 key)
                    old_profile_image_url = account.ProfileImageURL
                    old_s3_key = None
                    if old_profile_image_url and not old_profile_image_url.startswith('uploads/'):
                        # This is likely an S3 key (not a local path)
                        old_s3_key = old_profile_image_url

                    # Upload to S3
                    try:
                        s3_key = upload_avatar(file, account.AccountID)
                    except ValueError as e:
                        flash(f'Invalid file: {str(e)}', 'danger')
                        return redirect(url_for('driver.driver_account'))
                    except Exception as e:
                        current_app.logger.error(f"Error uploading to S3: {e}", exc_info=True)
                        flash('Failed to upload profile picture to S3.', 'danger')
                        return redirect(url_for('driver.driver_account'))

                    # Delete old avatar from S3 if it exists AND is different from the new one
                    if old_s3_key and old_s3_key != s3_key:
                        try:
                            delete_avatar(old_s3_key)
                        except Exception as e:
                            # Log but don't fail - old avatar cleanup is not critical
                            current_app.logger.warning(f"Failed to delete old avatar from S3: {e}")

                    # Update account with new S3 key
                    account.ProfileImageURL = s3_key
                    db.session.commit()
                    flash('Profile picture updated.', 'success')
                    return redirect(url_for('driver.driver_account'))
            except Exception as _e:
                db.session.rollback()
                current_app.logger.error(f"Error in upload_avatar: {_e}", exc_info=True)
                flash('Failed to update profile picture.', 'danger')
                return redirect(url_for('driver.driver_account'))
        if action == 'save_info':
            updated = False
            if account:
                if (v := (request.form.get("username") or "").strip()):
                    account.Username = v
                    updated = True
                if (v := request.form.get("first_name")) is not None:
                    account.FirstName = v
                    updated = True
                if (v := request.form.get("last_name")) is not None:
                    account.LastName = v
                    updated = True
                if (v := request.form.get("phone")):
                    account.phone_plain = v
                    updated = True
                account.WholeName = f"{account.FirstName or ''} {account.LastName or ''}".strip()
            if driver:
                if (v := request.form.get('age')) is not None and v != '':
                    try:
                        driver.Age = int(v)
                    except ValueError:
                        driver.Age = None
                    updated = True
                if (v := request.form.get('gender')) is not None:
                    vv = (v or '').strip().upper()
                    driver.Gender = 'M' if vv.startswith('M') else ('F' if vv.startswith('F') else None)
                    updated = True
                driver.ShippingStreet  = request.form.get('shipping_street')
                driver.ShippingCity    = request.form.get('shipping_city')
                driver.ShippingState   = request.form.get('shipping_state')
                driver.ShippingCountry = request.form.get('shipping_country')
                driver.ShippingPostal  = request.form.get('shipping_postal')
                if (v := request.form.get('license_number')):
                    driver.license_number_plain = v
                if (v := request.form.get('license_issue_date')):
                    driver.license_issue_date_plain = v
                if (v := request.form.get('license_expiration_date')):
                    driver.license_expiration_date_plain = v
                updated = True
            if updated:
                db.session.commit()
                return _respond("Personal info updated.", "success", 200)
            return _respond("No changes detected.", "info", 200)

        return _respond("Unsupported request.", "warning", 400)

    last_success = (
        LoginAttempts.query
        .filter_by(AccountID=current_user.AccountID, WasSuccessful=True)
        .order_by(LoginAttempts.AttemptedAt.desc())
        .first()
    )

    # Get environment-specific points balance
    driver_sponsor_id = session.get('driver_sponsor_id')
    env_points_balance = 0
    if driver_sponsor_id:
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if env:
            env_points_balance = env.PointsBalance or 0
    
    return render_template("driver_account_info.html", account=account, driver=driver, last_success=last_success, env_points_balance=env_points_balance)


@bp.route("/achievements", methods=["GET"])
@login_required
def driver_achievements():
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        return jsonify({"error": "Driver account not found."}), 403

    statuses = AchievementService.evaluate_driver_achievements(driver)
    db.session.commit()

    payload = []
    for status in statuses:
        achievement = status.achievement
        payload.append({
            "achievement_id": achievement.AchievementID,
            "code": achievement.Code,
            "title": achievement.Title,
            "description": achievement.Description,
            "is_points_based": bool(achievement.IsPointsBased),
            "points_threshold": achievement.PointsThreshold,
            "is_earned": status.is_earned,
            "earned_at": status.earned_at.isoformat() if status.earned_at else None,
        })

    return jsonify({"achievements": payload})


@bp.route("/recent-products", methods=["GET"])
@login_required
def driver_recent_products():
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        return jsonify({"error": "Driver account not found."}), 403

    recent = ProductViewService.get_recent_products(driver.DriverID)
    from urllib.parse import quote

    payload = []
    for product in recent:
        detail_path = f"/driver-catalog/product/{quote(product.external_item_id or '')}" if product.external_item_id else None
        payload.append({
            "external_item_id": product.external_item_id,
            "provider": product.provider,
            "title": product.title,
            "image_url": product.image_url,
            "points": product.points,
            "price": product.price,
            "currency": product.currency,
            "sponsor_id": product.sponsor_id,
            "sponsor_name": product.sponsor_name,
            "last_viewed": product.last_viewed.isoformat() if product.last_viewed else None,
            "product_id": product.product_id,
            "detail_path": detail_path,
        })

    return jsonify({"products": payload})


def _build_points_history_context(driver):
    sponsor = None
    sponsor_rate = None

    goal_info = None

    available_reasons: list[str] = []

    try:
        driver_sponsor_id = session.get('driver_sponsor_id')
        if driver_sponsor_id:
            env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
            if env:
                sponsor = Sponsor.query.filter_by(SponsorID=env.SponsorID).first()
                if sponsor:
                    sponsor_rate = sponsor.PointToDollarRate
                reasons_query = (
                    db.session.query(PointChange.Reason)
                    .filter(PointChange.DriverID == driver.DriverID)
                )
                if env:
                    reasons_query = reasons_query.filter(PointChange.SponsorID == env.SponsorID)
                reasons = {row[0] for row in reasons_query if row[0]}
                available_reasons = sorted(reasons)
                goal = DriverRewardGoal.query.filter_by(DriverSponsorID=env.DriverSponsorID).first()
                if goal:
                    target_points = goal.TargetPoints or 0
                    points_balance = env.PointsBalance or 0
                    remaining = max(target_points - points_balance, 0) if target_points else None
                    progress_pct = (
                        min(int(round((points_balance / target_points) * 100)), 100)
                        if target_points
                        else None
                    )
                    goal_info = {
                        "name": goal.TargetName or "",
                        "points": target_points,
                        "remaining": remaining,
                        "progress_pct": progress_pct,
                        "achieved": bool(target_points and points_balance >= target_points),
                    }
    except Exception:
        sponsor = None
        sponsor_rate = None
        goal_info = None
        available_reasons = []

    if not available_reasons:
        reasons_query = db.session.query(PointChange.Reason).filter(PointChange.DriverID == driver.DriverID)
        reasons = {row[0] for row in reasons_query if row[0]}
        available_reasons = sorted(reasons)

    query = (
        db.session.query(PointChange)
        .options(
            joinedload(PointChange.initiated_by),
            joinedload(PointChange.impersonated_by),
            joinedload(PointChange.disputes),
        )
        .filter_by(DriverID=driver.DriverID)
    )

    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")
    reason_filter = request.args.get("reason", "").strip()
    reason_exact = request.args.get("reason_exact", "").strip()
    txn_type = request.args.get("txn_type", "all").lower()

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            query = query.filter(PointChange.CreatedAt >= start_date)
        except ValueError:
            flash("Invalid start date format (use YYYY-MM-DD)", "warning")

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            query = query.filter(PointChange.CreatedAt <= end_date.replace(hour=23, minute=59, second=59))
        except ValueError:
            flash("Invalid end date format (use YYYY-MM-DD)", "warning")

    if reason_filter:
        query = query.filter(PointChange.Reason.ilike(f"%{reason_filter}%"))

    if reason_exact:
        query = query.filter(PointChange.Reason == reason_exact)

    if txn_type == "positive":
        query = query.filter(PointChange.DeltaPoints > 0)
    elif txn_type == "negative":
        query = query.filter(PointChange.DeltaPoints < 0)

    transactions = query.order_by(PointChange.CreatedAt.desc()).all()
    
    # Explicitly load disputes for all transactions to ensure they're available
    if transactions:
        point_change_ids = [t.PointChangeID for t in transactions]
        all_disputes = PointChangeDispute.query.filter(
            PointChangeDispute.PointChangeID.in_(point_change_ids)
        ).all()
        
        # Create a map of PointChangeID -> list of disputes
        disputes_map = {}
        for dispute in all_disputes:
            if dispute.PointChangeID not in disputes_map:
                disputes_map[dispute.PointChangeID] = []
            disputes_map[dispute.PointChangeID].append(dispute)
        
        # Attach disputes to each transaction and add a helper property
        for t in transactions:
            t._disputes_list = disputes_map.get(t.PointChangeID, [])
            # Add a helper property to easily check if dispute exists
            t._has_dispute = len(t._disputes_list) > 0
            # Get the most recent dispute status
            if t._disputes_list:
                # Sort by CreatedAt descending to get most recent
                from datetime import datetime as dt
                min_date = dt.min
                sorted_disputes = sorted(t._disputes_list, key=lambda d: d.CreatedAt or min_date, reverse=True)
                t._latest_dispute_status = sorted_disputes[0].Status.lower() if sorted_disputes[0].Status else None
            else:
                t._latest_dispute_status = None

    env_points_balance = 0
    try:
        driver_sponsor_id = session.get('driver_sponsor_id')
        if driver_sponsor_id:
            env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
            if env:
                env_points_balance = env.PointsBalance or 0
    except Exception:
        env_points_balance = 0

    return {
        "sponsor": sponsor,
        "sponsor_rate": sponsor_rate,
        "transactions": transactions,
        "env_points_balance": env_points_balance,
        "goal": goal_info,
        "available_reasons": available_reasons,
        "filters": {
            "start_date": start_date_str or "",
            "end_date": end_date_str or "",
            "reason": reason_filter,
            "reason_exact": reason_exact,
            "txn_type": txn_type,
        },
    }


# =========================
# DRIVER POINTS HISTORY
# =========================
@bp.route("/points-history")
@login_required
def points_history():
    """
    Show all point transactions for the logged-in driver with filters:
      - start_date / end_date (YYYY-MM-DD)
      - reason (substring)
      - txn_type: 'positive', 'negative', 'all'
    Also includes the sponsor's point-to-dollar rate.
    """
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        abort(403)

    context = _build_points_history_context(driver)

    return render_template(
        "driver/points_history.html",
        driver=driver,
        transactions=context["transactions"],
        sponsor_rate=context["sponsor_rate"],
        env_points_balance=context["env_points_balance"],
        goal=context["goal"],
        available_reasons=context["available_reasons"],
        filters=context["filters"],
    )


@bp.route("/points-goal", methods=["POST"])
@login_required
def save_points_goal():
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        abort(403)

    driver_sponsor_id = session.get("driver_sponsor_id")
    if not driver_sponsor_id:
        flash("Select an environment before setting a goal.", "warning")
        return redirect(url_for("driver.points_history"))

    env = (
        DriverSponsor.query
        .filter_by(DriverSponsorID=driver_sponsor_id, DriverID=driver.DriverID)
        .first()
    )
    if not env:
        flash("Unable to locate your sponsor environment. Please try again.", "danger")
        return redirect(url_for("driver.points_history"))

    goal = DriverRewardGoal.query.filter_by(DriverSponsorID=env.DriverSponsorID).first()

    if request.form.get("clear_goal"):
        if goal:
            db.session.delete(goal)
            db.session.commit()
            flash("Cleared your reward goal.", "success")
        else:
            flash("No reward goal to clear.", "info")
        return redirect(url_for("driver.points_history"))

    target_name = (request.form.get("target_name") or "").strip()
    target_points_raw = (request.form.get("target_points") or "").strip()

    target_points = None
    if target_points_raw:
        try:
            target_points = int(target_points_raw)
            if target_points < 0:
                raise ValueError
        except ValueError:
            flash("Target points must be a positive whole number.", "danger")
            return redirect(url_for("driver.points_history"))

    if not target_name and not target_points_raw:
        flash("Enter a goal name and target points before saving.", "info")
        return redirect(url_for("driver.points_history"))

    if target_points is None:
        flash("Enter how many points you need for the reward.", "warning")
        return redirect(url_for("driver.points_history"))

    if not goal:
        goal = DriverRewardGoal(DriverSponsorID=env.DriverSponsorID)
        db.session.add(goal)

    goal.TargetName = target_name or None
    goal.TargetPoints = target_points

    db.session.commit()
    flash("Reward goal saved!", "success")
    return redirect(url_for("driver.points_history"))


@bp.route("/point-dispute/<point_change_id>/submit", methods=["POST"], endpoint="submit_point_dispute")
@login_required
def submit_point_dispute(point_change_id):
    """Submit a dispute for a point change"""
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        flash("Access denied: Drivers only.", "danger")
        return redirect(url_for("driver.points_history"))
    
    # Get the point change
    point_change = PointChange.query.filter_by(PointChangeID=point_change_id, DriverID=driver.DriverID).first()
    if not point_change:
        flash("Point change not found or you don't have access to it.", "danger")
        return redirect(url_for("driver.points_history"))
    
    # Determine which sponsor this dispute should be associated with
    # Priority: 1) Driver's current sponsor environment, 2) Point change's SponsorID, 3) Any sponsor driver is associated with
    dispute_sponsor_id = None
    
    # Try to get from driver's current sponsor environment
    driver_sponsor_id = session.get('driver_sponsor_id')
    if driver_sponsor_id:
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id, DriverID=driver.DriverID).first()
        if env:
            dispute_sponsor_id = env.SponsorID
            current_app.logger.info(
                f"Using driver's current sponsor environment: SponsorID={dispute_sponsor_id} "
                f"from DriverSponsorID={driver_sponsor_id}"
            )
    
    # Fallback to point change's SponsorID if driver is associated with it
    if not dispute_sponsor_id and point_change.SponsorID:
        driver_sponsor = DriverSponsor.query.filter_by(
            DriverID=driver.DriverID,
            SponsorID=point_change.SponsorID
        ).first()
        if driver_sponsor:
            dispute_sponsor_id = point_change.SponsorID
            current_app.logger.info(
                f"Using point change's SponsorID: {dispute_sponsor_id} (driver is associated with this sponsor)"
            )
    
    # Last resort: find ANY sponsor the driver is associated with
    if not dispute_sponsor_id:
        any_driver_sponsor = DriverSponsor.query.filter_by(DriverID=driver.DriverID).first()
        if any_driver_sponsor:
            dispute_sponsor_id = any_driver_sponsor.SponsorID
            current_app.logger.warning(
                f"Using first available sponsor for driver: SponsorID={dispute_sponsor_id} "
                f"(point change had SponsorID={point_change.SponsorID} which driver is not associated with)"
            )
    
    if not dispute_sponsor_id:
        flash("Unable to determine which sponsor this dispute should be associated with.", "danger")
        return redirect(url_for("driver.points_history"))
    
    # Check if already disputed (any status - pending, approved, or denied)
    existing_dispute = PointChangeDispute.query.filter_by(
        PointChangeID=point_change_id
    ).first()
    if existing_dispute:
        if existing_dispute.Status.lower() == "pending":
            flash("A dispute is already pending for this transaction. Please wait for your sponsor to review it.", "warning")
        elif existing_dispute.Status.lower() == "approved":
            flash("This transaction has already been disputed and approved. Points have been restored.", "info")
        elif existing_dispute.Status.lower() == "denied":
            flash("This transaction has already been disputed and denied. You cannot dispute it again.", "warning")
        else:
            flash("This transaction has already been disputed.", "warning")
        return redirect(url_for("driver.points_history"))
    
    # Only allow disputes for negative point changes
    if point_change.DeltaPoints >= 0:
        flash("You can only dispute point deductions.", "warning")
        return redirect(url_for("driver.points_history"))
    
    driver_reason = (request.form.get("driver_reason") or "").strip()
    if not driver_reason:
        flash("Please provide a reason for disputing this transaction.", "danger")
        return redirect(url_for("driver.points_history"))
    
    try:
        # Verify the sponsor ID is set correctly
        if not point_change.SponsorID:
            flash("Unable to submit dispute: Point change has no associated sponsor.", "danger")
            return redirect(url_for("driver.points_history"))
        
        dispute = PointChangeDispute(
            PointChangeID=point_change.PointChangeID,
            DriverID=driver.DriverID,
            SponsorID=dispute_sponsor_id,  # Use the determined sponsor ID
            Status="pending",
            DriverReason=driver_reason,
            SubmittedByAccountID=current_user.AccountID,
        )
        db.session.add(dispute)
        db.session.commit()
        
        # Log for debugging
        driver_account = Account.query.get(driver.AccountID)
        current_app.logger.info(
            f"Dispute created: DisputeID={dispute.DisputeID}, "
            f"PointChangeID={point_change.PointChangeID}, "
            f"DriverID={driver.DriverID}, "
            f"Driver Name={driver_account.FirstName + ' ' + driver_account.LastName if driver_account else 'Unknown'}, "
            f"Driver Email={driver_account.Email if driver_account else 'Unknown'}, "
            f"PointChange.SponsorID={point_change.SponsorID}, "
            f"Dispute.SponsorID={dispute.SponsorID}, "
            f"Status={dispute.Status}"
        )
        
        # Verify driver-sponsor relationship for the dispute's sponsor
        driver_sponsor = DriverSponsor.query.filter_by(
            DriverID=driver.DriverID,
            SponsorID=dispute.SponsorID
        ).first()
        if driver_sponsor:
            current_app.logger.info(
                f"  Verified: Driver {driver.DriverID} is associated with Sponsor {dispute.SponsorID} via DriverSponsor"
            )
        else:
            current_app.logger.warning(
                f"  WARNING: Driver {driver.DriverID} is NOT associated with Sponsor {dispute.SponsorID} via DriverSponsor!"
            )
            # List all sponsors this driver is associated with
            all_driver_sponsors = DriverSponsor.query.filter_by(DriverID=driver.DriverID).all()
            current_app.logger.info(
                f"  Driver {driver.DriverID} is associated with {len(all_driver_sponsors)} sponsor(s): "
                f"{[ds.SponsorID for ds in all_driver_sponsors]}"
            )
        
        flash("Your dispute has been submitted and will be reviewed by your sponsor.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error submitting dispute: {str(e)}", exc_info=True)
        flash(f"Error submitting dispute: {str(e)}", "danger")
    
    return redirect(url_for("driver.points_history"))


@bp.route("/points-history/export", methods=["GET"])
@login_required
def points_history_export():
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        abort(403)

    context = _build_points_history_context(driver)
    transactions = context["transactions"]

    buffer = BytesIO()
    page_size = landscape(letter)
    pdf = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size

    margin = 48  # Slightly tighter margin for landscape
    y = height - margin

    pdf.setTitle("Points History")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(margin, y, "Points History")

    y -= 24
    pdf.setFont("Helvetica", 10)
    sponsor_rate = context["sponsor_rate"]
    env_points_balance = context["env_points_balance"]

    pdf.drawString(margin, y, f"Driver: {driver.Account.FirstName or ''} {driver.Account.LastName or ''}".strip())
    y -= 14
    pdf.drawString(margin, y, f"Current Balance: {env_points_balance} pts")
    y -= 14
    if sponsor_rate:
        pdf.drawString(margin, y, f"Point to Dollar Rate: ${float(sponsor_rate):.2f}")
        y -= 14

    filters = context["filters"]
    filter_line = []
    if filters["start_date"]:
        filter_line.append(f"Start: {filters['start_date']}")
    if filters["end_date"]:
        filter_line.append(f"End: {filters['end_date']}")
    if filters["reason"]:
        filter_line.append(f"Reason contains: {filters['reason']}")
    if filters["reason_exact"]:
        filter_line.append(f"Reason is: {filters['reason_exact']}")
    if filters["txn_type"] and filters["txn_type"] != "all":
        filter_line.append(f"Type: {filters['txn_type'].title()}")

    if filter_line:
        pdf.drawString(margin, y, "Filters: " + "; ".join(filter_line))
        y -= 18
    else:
        y -= 14

    def draw_table_header(current_y):
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(margin, current_y, "Date")
        pdf.drawString(margin + 100, current_y, "Change")
        pdf.drawString(margin + 180, current_y, "Source")
        pdf.drawString(margin + 360, current_y, "Balance")
        pdf.drawString(margin + 440, current_y, "Reason")
        pdf.setFont("Helvetica", 10)
        return current_y - 16

    y = draw_table_header(y)

    if not transactions:
        pdf.drawString(margin, y, "No point transactions found for the selected filters.")
    else:
        for txn in transactions:
            if y < margin:
                pdf.showPage()
                y = height - margin
                y = draw_table_header(y)

            date_str = txn.CreatedAt.strftime('%Y-%m-%d %H:%M') if txn.CreatedAt else '—'
            change = f"{txn.DeltaPoints:+d}"
            balance = str(txn.BalanceAfter)
            source = txn.actor_display_label if hasattr(txn, "actor_display_label") else "—"
            source = source.replace("Impersonation", "Imp.")
            source = source.replace(" → ", "→")
            if len(source) > 32:
                source = source[:29] + "..."
            reason = (txn.Reason or '—').replace('\n', ' ')
            if len(reason) > 110:
                reason = reason[:107] + '...'

            pdf.drawString(margin, y, date_str)
            pdf.drawString(margin + 100, y, change)
            pdf.drawString(margin + 180, y, source)
            pdf.drawString(margin + 360, y, balance)
            pdf.drawString(margin + 440, y, reason)
            y -= 14

    pdf.save()
    buffer.seek(0)

    filename = "points-history.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

# =========================
# Environment Selection (env-aware driver flows)
# =========================
@bp.route("/select-environment", methods=["GET"], endpoint="select_environment_page")
@login_required
def select_environment_page():
    # Only drivers should land here
    driver_id = session.get("driver_id")
    envs = (
        DriverSponsor.query
        .filter_by(DriverID=driver_id, Status="ACTIVE")
        .join(Sponsor, Sponsor.SponsorID == DriverSponsor.SponsorID)
        .add_columns(DriverSponsor.DriverSponsorID, Sponsor.Company)
        .all()
    )
    return render_template("driver_select_environment.html", envs=envs)

@bp.route("/select-environment", methods=["POST"], endpoint="select_environment_submit")
@login_required
def select_environment_submit():
    env_id = request.form.get("driver_sponsor_id")
    current_driver_id = session.get("driver_id")
    
    # Validate that the environment belongs to the current driver
    env = DriverSponsor.query.filter_by(
        DriverSponsorID=env_id, 
        DriverID=current_driver_id,
        Status="ACTIVE"
    ).first()
    
    if not env:
        return redirect(url_for("driver.select_environment_page"))

    # Set all necessary session variables (matching the new system)
    session['driver_sponsor_id'] = str(env.DriverSponsorID)
    session['driver_id'] = str(env.DriverID)
    session['sponsor_id'] = str(env.SponsorID)  # legacy helper
    
    # Store sponsor company name for navbar display
    from app.models import Sponsor
    sponsor = Sponsor.query.filter_by(SponsorID=env.SponsorID).first()
    if sponsor:
        session['sponsor_company'] = sponsor.Company
    
    session['driver_env_selection_pending'] = False

    return redirect(url_for("dashboard"))

@bp.post("/switch-environment")
@login_required
def switch_environment():
    env_id = request.form.get("driver_sponsor_id")
    current_driver_id = session.get("driver_id")
    
    # Validate that the environment belongs to the current driver and is active
    env = DriverSponsor.query.filter_by(
        DriverSponsorID=env_id, 
        DriverID=current_driver_id,
        Status="ACTIVE"
    ).first()
    
    if env:
        # Set all necessary session variables (matching the new system)
        session['driver_sponsor_id'] = str(env.DriverSponsorID)
        session['driver_id'] = str(env.DriverID)
        session['sponsor_id'] = str(env.SponsorID)  # legacy helper
        session['driver_env_selection_pending'] = False
        
        # Store sponsor company name for navbar display
        from app.models import Sponsor
        sponsor = Sponsor.query.filter_by(SponsorID=env.SponsorID).first()
        if sponsor:
            session['sponsor_company'] = sponsor.Company
    
    return redirect(request.referrer or url_for("dashboard"))


# =========================
# NOTIFICATION SETTINGS (driver preferences)
# =========================
@bp.route("/notification-settings", methods=["GET", "POST"], endpoint="notification_settings")
@login_required
def notification_settings():
    """Display and update driver notification preferences"""
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        abort(403)
    
    # Get or create notification preferences
    prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
    
    # Ensure AccountStatusChanges is always enabled (security requirement)
    if not prefs.AccountStatusChanges:
        prefs.AccountStatusChanges = True
        db.session.commit()
    
    if request.method == "POST":
        try:
            # Update notification type preferences
            prefs.PointChanges = request.form.get('point_changes') == 'on'
            prefs.OrderConfirmations = request.form.get('order_confirmations') == 'on'
            prefs.ApplicationUpdates = request.form.get('application_updates') == 'on'
            # New toggles
            prefs.TicketUpdates = request.form.get('ticket_updates') == 'on'
            prefs.RefundWindowAlerts = request.form.get('refund_window_alerts') == 'on'
            # AccountStatusChanges is always enabled for security - drivers cannot disable it
            prefs.AccountStatusChanges = True
            prefs.SensitiveInfoResets = request.form.get('sensitive_info_resets') == 'on'
            
            # Update quiet hours preferences
            prefs.QuietHoursEnabled = request.form.get('quiet_hours_enabled') == 'on'
            
            if prefs.QuietHoursEnabled:
                # Parse time strings from form
                quiet_hours_start_str = request.form.get('quiet_hours_start', '').strip()
                quiet_hours_end_str = request.form.get('quiet_hours_end', '').strip()
                
                if quiet_hours_start_str:
                    try:
                        from datetime import datetime
                        prefs.QuietHoursStart = datetime.strptime(quiet_hours_start_str, '%H:%M').time()
                    except ValueError:
                        flash("Invalid quiet hours start time format", "danger")
                        return redirect(url_for("driver.notification_settings"))
                
                if quiet_hours_end_str:
                    try:
                        from datetime import datetime
                        prefs.QuietHoursEnd = datetime.strptime(quiet_hours_end_str, '%H:%M').time()
                    except ValueError:
                        flash("Invalid quiet hours end time format", "danger")
                        return redirect(url_for("driver.notification_settings"))
            else:
                # Clear quiet hours if disabled
                prefs.QuietHoursStart = None
                prefs.QuietHoursEnd = None
            
            # Update low points alert preferences
            prefs.LowPointsAlertEnabled = request.form.get('low_points_alert_enabled') == 'on'
            
            if prefs.LowPointsAlertEnabled:
                # Parse threshold from form
                threshold_str = request.form.get('low_points_threshold', '').strip()
                if threshold_str:
                    try:
                        threshold = int(threshold_str)
                        if threshold < 0:
                            flash("Low points threshold must be a positive number", "danger")
                            return redirect(url_for("driver.notification_settings"))
                        prefs.LowPointsThreshold = threshold
                    except ValueError:
                        flash("Invalid low points threshold format", "danger")
                        return redirect(url_for("driver.notification_settings"))
                else:
                    flash("Low points threshold is required when alert is enabled", "danger")
                    return redirect(url_for("driver.notification_settings"))
            else:
                # Clear threshold if disabled
                prefs.LowPointsThreshold = None
            
            db.session.commit()
            flash("Notification preferences updated successfully!", "success")
            return redirect(url_for("driver.notification_settings"))
            
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating notification preferences: {str(e)}", "danger")
            return redirect(url_for("driver.notification_settings"))
    
    return render_template("driver/notification_settings.html", driver=driver, prefs=prefs)


@bp.route("/notification-settings/api/update", methods=["POST"])
@login_required
def update_notification_preference():
    """API endpoint to update individual notification preferences via AJAX"""
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        return jsonify({"success": False, "error": "Driver not found"}), 403
    
    try:
        data = request.get_json()
        preference_name = data.get('preference')
        value = data.get('value', False)
        
        if not preference_name:
            return jsonify({"success": False, "error": "Preference name required"}), 400
        
        # Get or create preferences
        prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
        
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


@bp.route("/sponsor-information", methods=["GET"], endpoint="sponsor_information")
@login_required
def sponsor_information():
    """Display sponsor information for the current environment."""
    # Get the current driver
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        flash("Driver profile not found.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get the current environment (DriverSponsor)
    driver_sponsor_id = session.get("driver_sponsor_id")
    if not driver_sponsor_id:
        flash("No active sponsor environment selected. Please select an environment first.", "warning")
        return redirect(url_for("driver.select_environment_page"))
    
    # Get the DriverSponsor environment
    env = (
        DriverSponsor.query
        .options(joinedload(DriverSponsor.sponsor))
        .filter_by(DriverSponsorID=driver_sponsor_id, DriverID=driver.DriverID)
        .first()
    )
    
    if not env:
        flash("Environment not found.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get the sponsor
    sponsor = env.sponsor
    if not sponsor:
        flash("Sponsor information not found.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get sponsor company information if available
    sponsor_company = None
    if sponsor.SponsorCompanyID:
        sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=sponsor.SponsorCompanyID).first()
    
    # Get sponsor account information
    sponsor_account = Account.query.filter_by(AccountID=sponsor.AccountID).first()
    
    # Prepare sponsor information for display
    sponsor_info = {
        'company_name': sponsor.Company or 'N/A',
        'point_to_dollar_rate': float(sponsor.PointToDollarRate) if sponsor.PointToDollarRate else 0.01,
        'min_points_per_txn': sponsor.MinPointsPerTxn or 1,
        'max_points_per_txn': sponsor.MaxPointsPerTxn or 1000,
        'billing_email': sponsor.BillingEmail,
        'billing_street': sponsor.BillingStreet,
        'billing_city': sponsor.BillingCity,
        'billing_state': sponsor.BillingState,
        'billing_country': sponsor.BillingCountry,
        'billing_postal': sponsor.BillingPostal,
        'sponsor_account_email': sponsor_account.Email if sponsor_account else None,
        'sponsor_account_name': sponsor_account.WholeName if sponsor_account else None,
        'features': sponsor.Features if sponsor.Features else {},
        'created_at': sponsor.CreatedAt,
    }
    
    # Add company-level information if available
    if sponsor_company:
        sponsor_info['company_point_rate'] = float(sponsor_company.PointToDollarRate) if sponsor_company.PointToDollarRate else None
        sponsor_info['company_name_official'] = sponsor_company.CompanyName
        sponsor_info['company_billing_email'] = sponsor_company.BillingEmail
        sponsor_info['company_billing_street'] = sponsor_company.BillingStreet
        sponsor_info['company_billing_city'] = sponsor_company.BillingCity
        sponsor_info['company_billing_state'] = sponsor_company.BillingState
        sponsor_info['company_billing_country'] = sponsor_company.BillingCountry
        sponsor_info['company_billing_postal'] = sponsor_company.BillingPostal
    
    return render_template(
        "driver/sponsor_information.html",
        sponsor_info=sponsor_info,
        sponsor=sponsor,
        sponsor_company=sponsor_company,
        env=env
    )
