from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session, make_response
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy.orm import joinedload, aliased
from sqlalchemy import or_
from math import ceil
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from io import BytesIO, StringIO
import csv

# merged imports
from app.models import (
    Account,
    Sponsor,
    SponsorCompany,
    Driver,
    PointChange,
    PointChangeDispute,
    Application,
    SponsorNotificationPreferences,
    SponsorProfileAudit,
    DriverSponsor,
    AccountType,
    EmailVerification,
    BulkImportLog,
    BulkImportError,
    LoginAttempts,
    Orders,
)
from app.extensions import db  # Ensure db.session available
from app.services.password_security_service import PasswordSecurityService
from app.services.profile_audit_service import ProfileAuditService
from app.services.session_management_service import SessionManagementService
from app.services.invoice_service import InvoiceService
import bcrypt
import pyotp
import uuid  # for creating unique PointChangeIDs
import os
from werkzeug.utils import secure_filename
import csv
import json
from flask_mail import Message
from sqlalchemy.exc import IntegrityError
from config import fernet
from app.utils.point_change_actor import derive_point_change_actor_metadata

bp = Blueprint("sponsor", __name__, url_prefix="/sponsor")


# -------------------------------------------------------------------
# Driver Management - Sponsor can set driver account status (A/I/H)
# -------------------------------------------------------------------
@bp.route("/drivers", methods=["GET"], endpoint="manage_drivers")
@login_required
def manage_drivers():
    """List drivers for this sponsor and allow status updates (A/I/H)."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))

    # Only drivers tied to this sponsor via DriverSponsor
    q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip().upper()
    points_mode = (request.args.get("points_mode") or "any").strip().lower()
    points_min = request.args.get("points_min", type=int)
    points_max = request.args.get("points_max", type=int)

    if points_min is not None and points_min < 0:
        points_min = 0
    if points_max is not None and points_max < 0:
        points_max = 0
    if points_min is not None and points_max is not None and points_max < points_min:
        points_min, points_max = points_max, points_min

    # Join DriverSponsor to get drivers for this sponsor
    drivers_q = (
        db.session.query(Driver, Account, DriverSponsor)
        .join(Account, Driver.AccountID == Account.AccountID)
        .join(DriverSponsor, Driver.DriverID == DriverSponsor.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )

    if status_filter:
        drivers_q = drivers_q.filter(db.func.upper(Account.Status) == status_filter)
    if q:
        like = f"%{q}%"
        drivers_q = drivers_q.filter(
            or_(Account.Email.ilike(like), Account.Username.ilike(like), Account.FirstName.ilike(like), Account.LastName.ilike(like))
        )
    if points_mode in {"at_least", "between"} and points_min is not None:
        drivers_q = drivers_q.filter(DriverSponsor.PointsBalance >= points_min)
    if points_mode in {"at_most", "between"} and points_max is not None:
        drivers_q = drivers_q.filter(DriverSponsor.PointsBalance <= points_max)

    drivers = drivers_q.order_by(Account.CreatedAt.desc()).all()

    # Counts
    total = (
        db.session.query(Account)
        .join(Driver, Driver.AccountID == Account.AccountID)
        .join(DriverSponsor, Driver.DriverID == DriverSponsor.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .count()
    )
    count_a = drivers_q.filter(db.func.upper(Account.Status) == 'A').count()
    count_i = drivers_q.filter(db.func.upper(Account.Status) == 'I').count()
    count_h = drivers_q.filter(db.func.upper(Account.Status) == 'H').count()

    # Calculate max from all drivers for this sponsor (before points filter)
    base_query = (
        db.session.query(DriverSponsor.PointsBalance)
        .join(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .join(Account, Driver.AccountID == Account.AccountID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    max_points_balance = base_query.order_by(DriverSponsor.PointsBalance.desc()).limit(1).scalar() or 0
    # Use actual max with small buffer, minimum 1000
    points_ceiling = max(max_points_balance + 100, 1000)

    return render_template(
        "sponsor/manage_drivers.html",
        drivers=drivers,
        q=q,
        status_filter=status_filter,
        total=total,
        count_a=count_a,
        count_i=count_i,
        count_h=count_h,
        points_mode=points_mode,
        points_min=points_min,
        points_max=points_max,
        points_ceiling=points_ceiling,
    )


# -------------------------------------------------------------------
# Sponsor Driver Roster CSV Export
#   URL: /sponsor/drivers/export-csv
# -------------------------------------------------------------------
@bp.route("/drivers/export-csv", methods=["GET"], endpoint="export_drivers_csv")
@login_required
def export_drivers_csv():
    """Export driver roster as CSV with applied filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get filters from query parameters (same as manage_drivers)
    q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "").strip().upper()
    points_mode = (request.args.get("points_mode") or "any").strip().lower()
    points_min = request.args.get("points_min", type=int)
    points_max = request.args.get("points_max", type=int)

    if points_min is not None and points_min < 0:
        points_min = 0
    if points_max is not None and points_max < 0:
        points_max = 0
    if points_min is not None and points_max is not None and points_max < points_min:
        points_min, points_max = points_max, points_min
    
    # Build the same query as manage_drivers
    drivers_q = (
        db.session.query(Driver, Account, DriverSponsor)
        .join(Account, Driver.AccountID == Account.AccountID)
        .join(DriverSponsor, Driver.DriverID == DriverSponsor.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    
    if status_filter:
        drivers_q = drivers_q.filter(db.func.upper(Account.Status) == status_filter)
    if q:
        like = f"%{q}%"
        drivers_q = drivers_q.filter(
            or_(Account.Email.ilike(like), Account.Username.ilike(like), Account.FirstName.ilike(like), Account.LastName.ilike(like))
        )
    if points_mode in {"at_least", "between"} and points_min is not None:
        drivers_q = drivers_q.filter(DriverSponsor.PointsBalance >= points_min)
    if points_mode in {"at_most", "between"} and points_max is not None:
        drivers_q = drivers_q.filter(DriverSponsor.PointsBalance <= points_max)
    
    drivers = drivers_q.order_by(Account.CreatedAt.desc()).all()
    
    # Create CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow([
        "Email",
        "Username",
        "First Name",
        "Last Name",
        "Status",
        "Points Balance",
        "Account Created",
        "Driver ID"
    ])
    
    # Write data rows
    for driver, account, driver_sponsor in drivers:
        status_display = "Active" if account.Status and account.Status.upper() == 'A' else \
                        "Inactive" if account.Status and account.Status.upper() == 'I' else \
                        "Archived" if account.Status and account.Status.upper() == 'H' else \
                        account.Status or "Unknown"
        
        writer.writerow([
            account.Email or "",
            account.Username or "",
            account.FirstName or "",
            account.LastName or "",
            status_display,
            driver_sponsor.PointsBalance if driver_sponsor else 0,
            account.CreatedAt.strftime('%Y-%m-%d %H:%M:%S') if account.CreatedAt else "",
            driver.DriverID or ""
        ])
    
    output.seek(0)
    response = make_response(output.getvalue())
    
    # Generate filename with filter info
    filename_parts = ["driver_roster"]
    if status_filter:
        filename_parts.append(status_filter.lower())
    if q:
        # Sanitize search query for filename
        safe_q = "".join(c for c in q[:20] if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        if safe_q:
            filename_parts.append(safe_q)
    filename = "_".join(filename_parts) + ".csv"
    
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


@bp.route("/challenges/manage", methods=["GET"], endpoint="challenges_manage")
@login_required
def challenges_manage():
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor and session.get("admin_id"):
        sponsor_id = request.args.get("sponsor_id")
        if sponsor_id:
            sponsor = Sponsor.query.filter_by(SponsorID=sponsor_id).first()

    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))

    return render_template("sponsor/challenges.html", sponsor=sponsor)


@bp.route("/drivers/<driver_id>/status", methods=["POST"], endpoint="change_driver_status")
@login_required
def change_driver_status(driver_id: str):
    """Allow sponsors to set driver account status to A/I/H. Never other sponsors/admins."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))

    try:
        # Validate driver belongs to this sponsor
        ds = DriverSponsor.query.filter_by(DriverID=driver_id, SponsorID=sponsor.SponsorID).first()
        if not ds:
            flash("Driver not found for your sponsorship.", "danger")
            return redirect(url_for("sponsor.manage_drivers"))

        driver = Driver.query.filter_by(DriverID=driver_id).first()
        if not driver:
            flash("Driver not found.", "danger")
            return redirect(url_for("sponsor.manage_drivers"))

        account = Account.query.filter_by(AccountID=driver.AccountID).first()
        if not account:
            flash("Driver account not found.", "danger")
            return redirect(url_for("sponsor.manage_drivers"))

        new_status = (request.form.get("status") or "").strip().upper()
        if new_status not in ['A', 'I', 'H']:
            flash("Invalid status. Must be A (Active), I (Inactive), or H (Archived)", "danger")
            return redirect(url_for("sponsor.manage_drivers"))

        old_status = account.Status
        account.Status = new_status
        account.UpdatedAt = datetime.utcnow()
        account.UpdatedByAccountID = current_user.AccountID
        db.session.commit()

        # Verify persisted
        db.session.refresh(account)
        if (account.Status or '').upper() != new_status:
            current_app.logger.error(
                f"[sponsor] DB did not persist status {new_status} for driver {driver_id}; current value: {account.Status}"
            )
            flash("Failed to update driver due to database constraint.", "danger")
            return redirect(url_for("sponsor.manage_drivers"))

        status_names = {'A': 'Active', 'I': 'Inactive', 'H': 'Archived'}
        flash(f"Driver status updated to {status_names.get(new_status, new_status)}", "success")

        # Email the driver about the change (respect driver prefs)
        try:
            from app.models import NotificationPreferences
            prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
            if prefs and prefs.AccountStatusChanges and prefs.EmailEnabled:
                from app.services.notification_service import NotificationService
                actor = sponsor.Company or "Sponsor"
                NotificationService.notify_driver_account_status_change(account, new_status, changed_by=actor)
        except Exception as _e:
            current_app.logger.error(f"Failed to notify driver about status change (sponsor): {_e}")
        return redirect(url_for("sponsor.manage_drivers"))

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error changing driver status: {str(e)}")
        flash(f"Error changing driver status: {str(e)}", "danger")
        return redirect(url_for("sponsor.manage_drivers"))


# -------------------------------------------------------------------
# Export Driver Profile as PDF
#   URL: /sponsor/drivers/<driver_id>/export-pdf
# -------------------------------------------------------------------
@bp.route("/drivers/<driver_id>/export-pdf", methods=["GET"], endpoint="export_driver_profile_pdf")
@login_required
def export_driver_profile_pdf(driver_id):
    """Export driver profile as PDF for sponsor's organization only."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Verify driver belongs to this sponsor
    ds = DriverSponsor.query.filter_by(DriverID=driver_id, SponsorID=sponsor.SponsorID).first()
    if not ds:
        flash("Driver not found for your sponsorship.", "danger")
        return redirect(url_for("sponsor.manage_drivers"))
    
    driver = Driver.query.filter_by(DriverID=driver_id).first()
    if not driver:
        flash("Driver not found.", "danger")
        return redirect(url_for("sponsor.manage_drivers"))
    
    account = Account.query.filter_by(AccountID=driver.AccountID).first()
    if not account:
        flash("Driver account not found.", "danger")
        return redirect(url_for("sponsor.manage_drivers"))
    
    try:
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
        
        # Title
        title_style = ParagraphStyle(
            'DriverProfileTitle',
            parent=styles['Heading1'],
            fontSize=20,
            alignment=1,
            spaceAfter=20,
        )
        elements.append(Paragraph("Driver Profile", title_style))
        
        # Meta style
        meta_style = ParagraphStyle(
            'DriverMeta',
            parent=styles['Normal'],
            fontSize=11,
            spaceAfter=8,
        )
        
        # Section heading style
        section_style = ParagraphStyle(
            'DriverSection',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=16,
            spaceAfter=10,
            textColor=colors.HexColor('#1f2937'),
        )
        
        # Personal Information
        elements.append(Paragraph("Personal Information", section_style))
        elements.append(Paragraph(f"<b>Name:</b> {account.FirstName or ''} {account.LastName or ''}", meta_style))
        elements.append(Paragraph(f"<b>Email:</b> {account.Email or 'N/A'}", meta_style))
        elements.append(Paragraph(f"<b>Username:</b> {account.Username or 'N/A'}", meta_style))
        elements.append(Paragraph(f"<b>Phone:</b> {account.phone_plain or 'N/A'}", meta_style))
        elements.append(Paragraph(f"<b>Account Status:</b> {account.Status or 'N/A'}", meta_style))
        elements.append(Paragraph(f"<b>Account Created:</b> {account.CreatedAt.strftime('%Y-%m-%d %H:%M:%S') if account.CreatedAt else 'N/A'}", meta_style))
        elements.append(Spacer(1, 0.1 * inch))
        
        # Driver Information
        elements.append(Paragraph("Driver Information", section_style))
        elements.append(Paragraph(f"<b>Age:</b> {driver.Age if driver.Age else 'N/A'}", meta_style))
        gender_display = {'M': 'Male', 'F': 'Female'}.get((driver.Gender or '').upper(), 'N/A')
        elements.append(Paragraph(f"<b>Gender:</b> {gender_display}", meta_style))
        elements.append(Paragraph(f"<b>Points Balance:</b> {ds.PointsBalance:,}", meta_style))
        elements.append(Spacer(1, 0.1 * inch))
        
        # Shipping Address
        elements.append(Paragraph("Shipping Address", section_style))
        if driver.ShippingStreet or driver.ShippingCity:
            shipping = []
            if driver.ShippingStreet:
                shipping.append(driver.ShippingStreet)
            if driver.ShippingCity:
                city_state = driver.ShippingCity
                if driver.ShippingState:
                    city_state += f", {driver.ShippingState}"
                if driver.ShippingPostal:
                    city_state += f" {driver.ShippingPostal}"
                shipping.append(city_state)
            if driver.ShippingCountry:
                shipping.append(driver.ShippingCountry)
            elements.append(Paragraph("<b>Address:</b> " + "<br/>".join(shipping), meta_style))
        else:
            elements.append(Paragraph("<b>Address:</b> N/A", meta_style))
        elements.append(Spacer(1, 0.1 * inch))
        
        # License Information
        elements.append(Paragraph("License Information", section_style))
        elements.append(Paragraph(f"<b>License Number:</b> {driver.license_number_plain or 'N/A'}", meta_style))
        elements.append(Paragraph(f"<b>Issue Date:</b> {driver.license_issue_date_plain or 'N/A'}", meta_style))
        elements.append(Paragraph(f"<b>Expiration Date:</b> {driver.license_expiration_date_plain or 'N/A'}", meta_style))
        elements.append(Spacer(1, 0.1 * inch))
        
        # Footer
        footer_style = ParagraphStyle(
            'DriverFooter',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#6b7280'),
            alignment=1,
        )
        elements.append(Spacer(1, 0.3 * inch))
        elements.append(Paragraph(f"Generated by {sponsor.Company or 'Sponsor'} on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", footer_style))
        
        doc.build(elements)
        buffer.seek(0)
        
        # Create response
        driver_name = f"{account.FirstName or ''}_{account.LastName or ''}".strip() or "driver"
        filename = f"driver_profile_{driver_name}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
        filename = secure_filename(filename)
        
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        return response
        
    except Exception as e:
        current_app.logger.error(f"Error generating driver profile PDF: {str(e)}", exc_info=True)
        flash(f"Error generating PDF: {str(e)}", "danger")
        return redirect(url_for("sponsor.manage_drivers"))


# -------------------------------------------------------------------
# Impersonate Driver
#   URL: /sponsor/drivers/<account_id>/impersonate
# -------------------------------------------------------------------
@bp.route("/drivers/<account_id>/impersonate", methods=["POST"], endpoint="impersonate_driver")
@login_required
def impersonate_driver(account_id):
    """Allow sponsor to impersonate a driver in their organization"""
    # Verify current user is a sponsor
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return jsonify({"success": False, "error": "Access denied: Sponsors only."}), 403
    
    # Get the target account to impersonate
    target_account = Account.query.get(account_id)
    if not target_account:
        return jsonify({"success": False, "error": "Driver not found"}), 404
    
    # Verify the driver belongs to this sponsor's organization
    driver = Driver.query.filter_by(AccountID=target_account.AccountID).first()
    if not driver:
        return jsonify({"success": False, "error": "Account is not a driver"}), 400
    
    # Check if driver is linked to this sponsor via DriverSponsor
    driver_sponsor = DriverSponsor.query.filter_by(
        DriverID=driver.DriverID,
        SponsorID=sponsor.SponsorID
    ).first()
    
    if not driver_sponsor:
        return jsonify({"success": False, "error": "You can only impersonate drivers in your organization"}), 403
    
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
        # Store the original sponsor's account ID in session before impersonating
        original_sponsor_account_id = current_user.AccountID
        current_app.logger.info(f"Starting sponsor impersonation: Sponsor {original_sponsor_account_id} -> Driver {account_id}")
        
        # Store impersonation markers before logout
        # Preserve existing session keys before logout
        preserved_session = dict(session)
        
        # Log out the current sponsor user (this clears Flask-Login session data)
        logout_user()
        
        # Restore preserved session values and impersonation markers
        session.update(preserved_session)
        session['impersonating'] = True
        session['original_sponsor_account_id'] = original_sponsor_account_id
        session.modified = True
        
        # Log in as the target driver (this will set Flask-Login session data for the new user)
        login_user(target_account, remember=False)
        session.permanent = True  # Make session permanent to match CSRF token lifetime (31 days)
        current_app.logger.info(f"Logged in as target driver: {target_account.AccountID}")
        
        # Set up the role session for the impersonated driver
        from app.routes.auth import _set_role_session, _ensure_driver_environment
        _set_role_session(target_account)
        current_app.logger.info(f"Set role session for account type: {target_account.AccountType}")
        
        # SECURITY: Create session for tracking and auto-logout (same as regular login)
        SessionManagementService.create_session(target_account.AccountID, request)
        current_app.logger.info(f"Created session for impersonated driver: {target_account.AccountID}")
        
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
            f"Sponsor {sponsor.SponsorID} (AccountID: {original_sponsor_account_id}) successfully impersonated "
            f"driver {target_account.AccountID} (Email: {target_account.Email})"
        )
        
        # Ensure session is saved before redirect
        session.permanent = True
        
        redirect_url = url_for("dashboard")
        current_app.logger.info(f"Sponsor impersonation successful, redirecting to: {redirect_url}")
        
        return jsonify({
            "success": True,
            "redirect_url": redirect_url
        })
    
    except Exception as e:
        db.session.rollback()
        import traceback
        error_trace = traceback.format_exc()
        current_app.logger.error(f"Error during sponsor impersonation: {str(e)}\n{error_trace}")
        return jsonify({"success": False, "error": f"Impersonation failed: {str(e)}"}), 500


# -------------------------------------------------------------------
# Point Dispute Management
#   URL: /sponsor/disputes
# -------------------------------------------------------------------
@bp.route("/disputes", methods=["GET"], endpoint="manage_disputes")
@login_required
def manage_disputes():
    """View and manage point change disputes"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    
    # Handle admin impersonation
    if not sponsor and session.get("admin_id"):
        sponsor_id = request.args.get("sponsor_id")
        if sponsor_id:
            sponsor = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
    
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))
    
    status_filter = (request.args.get("status") or "pending").strip().lower()
    
    # Query disputes for this sponsor using DriverSponsor relationship
    # This is the authoritative source - drivers belong to sponsors via DriverSponsor
    # We use UNION to combine both direct SponsorID match and DriverSponsor relationship
    # to catch all disputes, even if SponsorID on dispute doesn't match
    
    # Primary query: via DriverSponsor relationship (most reliable)
    query_via_driver_sponsor = (
        db.session.query(PointChangeDispute)
        .options(
            joinedload(PointChangeDispute.point_change),
            joinedload(PointChangeDispute.driver).joinedload(Driver.Account),
            joinedload(PointChangeDispute.submitted_by),
        )
        .join(DriverSponsor, 
              (PointChangeDispute.DriverID == DriverSponsor.DriverID) &
              (DriverSponsor.SponsorID == sponsor.SponsorID))
    )
    
    # Secondary query: direct SponsorID match (fallback)
    query_via_sponsor_id = (
        db.session.query(PointChangeDispute)
        .options(
            joinedload(PointChangeDispute.point_change),
            joinedload(PointChangeDispute.driver).joinedload(Driver.Account),
            joinedload(PointChangeDispute.submitted_by),
        )
        .filter(PointChangeDispute.SponsorID == sponsor.SponsorID)
    )
    
    # Get results from both queries and combine (using set to avoid duplicates)
    disputes_via_ds = query_via_driver_sponsor.all()
    disputes_via_id = query_via_sponsor_id.all()
    
    # Log detailed info about what we found
    current_app.logger.info(
        f"Sponsor {sponsor.SponsorID} (Company: {sponsor.Company}) querying disputes: "
        f"Found {len(disputes_via_ds)} via DriverSponsor, "
        f"{len(disputes_via_id)} via SponsorID"
    )
    
    # Log details about disputes found via DriverSponsor
    for d in disputes_via_ds:
        current_app.logger.info(
            f"  Dispute via DriverSponsor: ID={d.DisputeID}, DriverID={d.DriverID}, "
            f"Status={d.Status}, PointChangeID={d.PointChangeID}, "
            f"Dispute.SponsorID={d.SponsorID}"
        )
    
    # Log details about disputes found via SponsorID
    for d in disputes_via_id:
        current_app.logger.info(
            f"  Dispute via SponsorID: ID={d.DisputeID}, DriverID={d.DriverID}, "
            f"Status={d.Status}, PointChangeID={d.PointChangeID}, "
            f"Dispute.SponsorID={d.SponsorID}"
        )
    
    # Also check what drivers belong to this sponsor
    driver_sponsors = DriverSponsor.query.filter_by(SponsorID=sponsor.SponsorID).all()
    current_app.logger.info(f"Sponsor {sponsor.SponsorID} has {len(driver_sponsors)} driver relationships")
    for ds in driver_sponsors[:5]:  # Log first 5
        driver = Driver.query.get(ds.DriverID)
        account = Account.query.get(driver.AccountID) if driver else None
        current_app.logger.info(
            f"  DriverSponsor: DriverID={ds.DriverID}, "
            f"Driver Name={account.FirstName + ' ' + account.LastName if account else 'Unknown'}, "
            f"Email={account.Email if account else 'Unknown'}"
        )
    
    # Combine and deduplicate by DisputeID
    all_disputes_dict = {}
    for d in disputes_via_ds:
        all_disputes_dict[d.DisputeID] = d
    for d in disputes_via_id:
        if d.DisputeID not in all_disputes_dict:
            all_disputes_dict[d.DisputeID] = d
    
    # Convert back to list for filtering
    all_disputes_list = list(all_disputes_dict.values())
    
    current_app.logger.info(f"Total disputes after deduplication: {len(all_disputes_list)}")
    
    # Create a query-like object for filtering
    # We'll filter the list manually since we've already loaded the data
    query = all_disputes_list
    
    # Filter the list by status
    if status_filter == "pending":
        query = [d for d in query if d.Status and d.Status.lower() == "pending"]
    elif status_filter == "resolved":
        query = [d for d in query if d.Status and d.Status.lower() in ["approved", "denied"]]
    elif status_filter in ["approved", "denied"]:
        query = [d for d in query if d.Status and d.Status.lower() == status_filter]
    # If status_filter is "all", show all disputes (no additional filter)
    
    # Sort by CreatedAt descending
    disputes = sorted(query, key=lambda d: d.CreatedAt or datetime.min, reverse=True)
    
    # Debug: Get ALL disputes to see what's in the database
    all_disputes_in_db = db.session.query(PointChangeDispute).all()
    
    # Also check point changes for this sponsor to see if there's a mismatch
    sponsor_point_changes = PointChange.query.filter_by(SponsorID=sponsor.SponsorID).limit(5).all()
    
    # Debug logging
    current_app.logger.info(
        f"Sponsor {sponsor.SponsorID} (Company: {sponsor.Company}, AccountID: {current_user.AccountID}) viewing disputes: "
        f"status_filter={status_filter}, found {len(disputes)} disputes"
    )
    current_app.logger.info(f"Total disputes in database: {len(all_disputes_in_db)}")
    current_app.logger.info(f"Sample point changes for this sponsor: {len(sponsor_point_changes)}")
    for pc in sponsor_point_changes[:3]:
        current_app.logger.info(
            f"  PointChange {pc.PointChangeID}: SponsorID={pc.SponsorID}, DriverID={pc.DriverID}, DeltaPoints={pc.DeltaPoints}"
        )
    
    for d in all_disputes_in_db:
        # Get the point change to check its SponsorID
        pc = d.point_change if hasattr(d, 'point_change') else PointChange.query.get(d.PointChangeID)
        pc_sponsor_id = pc.SponsorID if pc else "N/A"
        current_app.logger.info(
            f"  ALL Dispute {d.DisputeID}: Status={d.Status}, "
            f"Dispute.SponsorID={d.SponsorID}, PointChange.SponsorID={pc_sponsor_id}, "
            f"DriverID={d.DriverID}, PointChangeID={d.PointChangeID}, "
            f"CreatedAt={d.CreatedAt}, Match={d.SponsorID == sponsor.SponsorID}"
        )
    
    for d in disputes:
        current_app.logger.info(
            f"  FILTERED Dispute {d.DisputeID}: Status={d.Status}, "
            f"SponsorID={d.SponsorID}, PointChangeID={d.PointChangeID}"
        )
    
    return render_template(
        "sponsor/manage_disputes.html",
        sponsor=sponsor,
        disputes=disputes,
        status_filter=status_filter,
        all_disputes_count=len(all_disputes_in_db),  # For debugging
    )


@bp.route("/disputes/<dispute_id>/approve", methods=["POST"], endpoint="approve_dispute")
@login_required
def approve_dispute(dispute_id):
    """Approve a dispute and reverse the point change"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    # Try to find dispute - first by direct SponsorID match, then via DriverSponsor
    dispute = (
        db.session.query(PointChangeDispute)
        .filter(
            PointChangeDispute.DisputeID == dispute_id,
            db.func.lower(PointChangeDispute.Status) == "pending"
        )
        .first()
    )
    
    if not dispute:
        flash("Dispute not found or already resolved.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    # Verify sponsor has access to this dispute via DriverSponsor relationship
    driver_sponsor = DriverSponsor.query.filter_by(
        DriverID=dispute.DriverID,
        SponsorID=sponsor.SponsorID
    ).first()
    
    if not driver_sponsor:
        current_app.logger.warning(
            f"Sponsor {sponsor.SponsorID} attempted to approve dispute {dispute_id} "
            f"for driver {dispute.DriverID}, but driver is not associated with this sponsor"
        )
        flash("You don't have permission to resolve this dispute.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    current_app.logger.info(
        f"Approving dispute {dispute_id}: SponsorID={sponsor.SponsorID}, "
        f"Dispute.SponsorID={dispute.SponsorID}, DriverID={dispute.DriverID}"
    )
    
    point_change = dispute.point_change
    if not point_change:
        flash("Associated point change not found.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    sponsor_notes = (request.form.get("sponsor_notes") or "").strip()
    
    # Get the driver-sponsor relationship
    env = DriverSponsor.query.filter_by(
        DriverID=dispute.DriverID,
        SponsorID=sponsor.SponsorID
    ).first()
    
    if not env:
        current_app.logger.error(
            f"Cannot approve dispute {dispute_id}: Driver {dispute.DriverID} not found in sponsor {sponsor.SponsorID}'s environment"
        )
        flash("Error: Driver environment not found. Cannot restore points.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    try:
        reversal_points = 0
        balance_after = env.PointsBalance or 0
        
        # Only reverse if the original change was negative (points were deducted)
        if point_change.DeltaPoints < 0:
            # Reverse the points: add back the absolute value of what was deducted
            reversal_points = abs(point_change.DeltaPoints)
            env.PointsBalance = (env.PointsBalance or 0) + reversal_points
            balance_after = env.PointsBalance
            
            # Create a new PointChange to record the reversal
            actor_meta = derive_point_change_actor_metadata(current_user)
            reversal_pc = PointChange(
                DriverID=dispute.DriverID,
                SponsorID=sponsor.SponsorID,
                DeltaPoints=reversal_points,
                TransactionID=None,
                InitiatedByAccountID=current_user.AccountID,
                BalanceAfter=balance_after,
                Reason=f"Dispute approved: Reversal of {abs(point_change.DeltaPoints)} points",
                ActorRoleCode=actor_meta["actor_role_code"],
                ActorLabel=actor_meta["actor_label"],
                ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
                ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
            )
            db.session.add(reversal_pc)
            
            # Notify driver about the reversal
            try:
                from app.services.notification_service import NotificationService
                NotificationService.notify_driver_points_change(
                    driver_id=dispute.DriverID,
                    delta_points=reversal_points,
                    reason=f"Dispute approved: Points restored",
                    balance_after=balance_after,
                    sponsor_id=sponsor.SponsorID
                )
            except Exception as e:
                current_app.logger.error(f"Failed to send dispute approval notification: {e}")
        
        # Update dispute status
        dispute.Status = "approved"
        dispute.SponsorNotes = sponsor_notes
        dispute.ResolvedByAccountID = current_user.AccountID
        dispute.ResolvedAt = datetime.utcnow()
        
        # Refresh to ensure we have the latest state
        db.session.flush()
        db.session.commit()
        
        # Verify the update persisted
        db.session.refresh(dispute)
        if dispute.Status.lower() != "approved":
            current_app.logger.error(
                f"Dispute status update failed! Expected 'approved', got '{dispute.Status}'"
            )
            flash("Error: Dispute status was not updated correctly. Please try again.", "danger")
        else:
            current_app.logger.info(
                f"Dispute {dispute_id} successfully approved. Status={dispute.Status}, "
                f"Points restored: {reversal_points}, New balance: {balance_after}"
            )
            if reversal_points > 0:
                flash(f"Dispute approved. {reversal_points} points have been restored to the driver. New balance: {balance_after} points.", "success")
            else:
                flash("Dispute approved.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error approving dispute: {str(e)}", exc_info=True)
        flash(f"Error approving dispute: {str(e)}", "danger")
    
    return redirect(url_for("sponsor.manage_disputes"))


@bp.route("/disputes/<dispute_id>/deny", methods=["POST"], endpoint="deny_dispute")
@login_required
def deny_dispute(dispute_id):
    """Deny a dispute"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    # Try to find dispute - first by direct SponsorID match, then via DriverSponsor
    dispute = (
        db.session.query(PointChangeDispute)
        .filter(
            PointChangeDispute.DisputeID == dispute_id,
            db.func.lower(PointChangeDispute.Status) == "pending"
        )
        .first()
    )
    
    if not dispute:
        flash("Dispute not found or already resolved.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    # Verify sponsor has access to this dispute via DriverSponsor relationship
    driver_sponsor = DriverSponsor.query.filter_by(
        DriverID=dispute.DriverID,
        SponsorID=sponsor.SponsorID
    ).first()
    
    if not driver_sponsor:
        current_app.logger.warning(
            f"Sponsor {sponsor.SponsorID} attempted to deny dispute {dispute_id} "
            f"for driver {dispute.DriverID}, but driver is not associated with this sponsor"
        )
        flash("You don't have permission to resolve this dispute.", "danger")
        return redirect(url_for("sponsor.manage_disputes"))
    
    sponsor_notes = (request.form.get("sponsor_notes") or "").strip()
    
    try:
        dispute.Status = "denied"
        dispute.SponsorNotes = sponsor_notes
        dispute.ResolvedByAccountID = current_user.AccountID
        dispute.ResolvedAt = datetime.utcnow()
        
        # Refresh to ensure we have the latest state
        db.session.flush()
        db.session.commit()
        
        # Verify the update persisted
        db.session.refresh(dispute)
        if dispute.Status.lower() != "denied":
            current_app.logger.error(
                f"Dispute status update failed! Expected 'denied', got '{dispute.Status}'"
            )
            flash("Error: Dispute status was not updated correctly. Please try again.", "danger")
        else:
            current_app.logger.info(f"Dispute {dispute_id} successfully denied. Status={dispute.Status}")
            flash("Dispute denied.", "info")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error denying dispute: {str(e)}", exc_info=True)
        flash(f"Error denying dispute: {str(e)}", "danger")
    
    return redirect(url_for("sponsor.manage_disputes"))


# -----------------------------
# Sponsor Account Info Page
# -----------------------------
@bp.route("/account", methods=["GET", "POST"], endpoint="sponsor_account")
@login_required
def sponsor_account():
    account = Account.query.filter_by(AccountID=current_user.AccountID).first()
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()

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
            return redirect(url_for("sponsor.sponsor_account"))

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
                'Phone': account.phone_plain if hasattr(account, 'phone_plain') else None,
            }
            old_email_value = current_email
            account.Email = new_email

            try:
                db.session.commit()
            except Exception as commit_exc:
                db.session.rollback()
                current_app.logger.error(f"Sponsor email change commit failed: {commit_exc}", exc_info=True)
                return _respond("Failed to update email. Please try again.", "danger", 500)

            try:
                ProfileAuditService.audit_account_changes(
                    account=account,
                    old_data=old_account_snapshot,
                    new_data={
                        'FirstName': account.FirstName,
                        'LastName': account.LastName,
                        'Email': account.Email,
                        'Phone': account.phone_plain if hasattr(account, 'phone_plain') else None,
                    },
                    changed_by_account_id=current_user.AccountID,
                    change_reason="Self-update email via sponsor account page",
                )
            except Exception as audit_exc:
                try:
                    current_app.logger.warning(f"Sponsor email change audit failed: {audit_exc}")
                except Exception:
                    pass

            return _respond("Email updated successfully.", "success", 200, email=new_email, old_email=old_email_value)

        if action == "upload_avatar":
            if not account:
                return _respond("Account not found.", "danger", 404)
            try:
                from app.services.s3_service import upload_avatar, delete_avatar
            except Exception as svc_exc:
                current_app.logger.error(f"Sponsor avatar service import failed: {svc_exc}", exc_info=True)
                return _respond("Unable to update profile picture right now.", "danger", 500)

            file = request.files.get('profile_image')
            if not (file and getattr(file, 'filename', '')):
                return _respond("Please choose an image to upload.", "warning", 400)

            old_profile_image_url = account.ProfileImageURL
            old_s3_key = None
            if old_profile_image_url and not old_profile_image_url.startswith('uploads/'):
                old_s3_key = old_profile_image_url

            try:
                s3_key = upload_avatar(file, account.AccountID)
            except ValueError as e:
                return _respond(f"Invalid file: {str(e)}", "danger", 400)
            except Exception as e:
                current_app.logger.error(f"Error uploading sponsor avatar to S3: {e}", exc_info=True)
                return _respond("Failed to upload profile picture.", "danger", 500)

            if old_s3_key:
                try:
                    delete_avatar(old_s3_key)
                except Exception as e:
                    current_app.logger.warning(f"Failed to delete old sponsor avatar from S3: {e}")

            account.ProfileImageURL = s3_key
            try:
                db.session.commit()
            except Exception as commit_exc:
                db.session.rollback()
                current_app.logger.error(f"Sponsor avatar commit failed: {commit_exc}", exc_info=True)
                return _respond("Failed to update profile picture.", "danger", 500)

            return _respond("Profile picture updated.", "success", 200)

        if action == "save_info":
            if not (account or sponsor):
                return _respond("Account not found.", "danger", 404)

            old_account_snapshot = {
                'FirstName': account.FirstName if account else None,
                'LastName': account.LastName if account else None,
                'Email': account.Email if account else None,
                'Phone': account.phone_plain if account and hasattr(account, 'phone_plain') else None,
            } if account else {}

            old_sponsor_snapshot = {
                'Company': sponsor.Company if sponsor else None,
                'BillingEmail': sponsor.BillingEmail if sponsor else None,
                'BillingStreet': sponsor.BillingStreet if sponsor else None,
                'BillingCity': sponsor.BillingCity if sponsor else None,
                'BillingState': sponsor.BillingState if sponsor else None,
                'BillingCountry': sponsor.BillingCountry if sponsor else None,
                'BillingPostal': sponsor.BillingPostal if sponsor else None,
            } if sponsor else {}

            updated_account = False
            updated_sponsor = False

            if account:
                username_val = (request.form.get("username") or "").strip()
                if username_val and username_val != (account.Username or "").strip():
                    account.Username = username_val
                    updated_account = True

                first_name_val = request.form.get("first_name")
                if first_name_val is not None and first_name_val != (account.FirstName or ""):
                    account.FirstName = first_name_val
                    updated_account = True

                last_name_val = request.form.get("last_name")
                if last_name_val is not None and last_name_val != (account.LastName or ""):
                    account.LastName = last_name_val
                    updated_account = True

                phone_val = request.form.get("phone")
                current_phone = account.phone_plain if hasattr(account, 'phone_plain') else None
                if phone_val is not None and phone_val != (current_phone or ""):
                    account.phone_plain = phone_val
                    updated_account = True

                # Recompute WholeName regardless of changes to ensure consistency
                account.WholeName = f"{account.FirstName or ''} {account.LastName or ''}".strip()

            if sponsor:
                def _update_sponsor_field(attr: str, value):
                    nonlocal updated_sponsor
                    current_value = getattr(sponsor, attr)
                    normalized_current = (current_value or "").strip() if isinstance(current_value, str) else current_value
                    normalized_new = (value or "").strip() if isinstance(value, str) else value
                    if normalized_new == "":
                        normalized_new = None
                    if normalized_current != normalized_new:
                        setattr(sponsor, attr, normalized_new)
                        updated_sponsor = True

                _update_sponsor_field("BillingEmail", request.form.get("billing_email"))
                _update_sponsor_field("BillingStreet", request.form.get("billing_street"))
                _update_sponsor_field("BillingCity", request.form.get("billing_city"))
                _update_sponsor_field("BillingState", request.form.get("billing_state"))
                _update_sponsor_field("BillingCountry", request.form.get("billing_country"))
                _update_sponsor_field("BillingPostal", request.form.get("billing_postal"))
                # Company name updates are intentionally ignored

            if not (updated_account or updated_sponsor):
                return _respond("No changes detected.", "info", 200)

            try:
                db.session.commit()
            except Exception as commit_exc:
                db.session.rollback()
                current_app.logger.error(f"Sponsor profile save commit failed: {commit_exc}", exc_info=True)
                return _respond("Failed to update account info. Please try again.", "danger", 500)

            try:
                if updated_account and account:
                    ProfileAuditService.audit_account_changes(
                        account=account,
                        old_data=old_account_snapshot,
                        new_data={
                            'FirstName': account.FirstName,
                            'LastName': account.LastName,
                            'Email': account.Email,
                            'Phone': account.phone_plain if hasattr(account, 'phone_plain') else None,
                        },
                        changed_by_account_id=current_user.AccountID,
                        change_reason="Self-update via sponsor account page",
                    )
                if updated_sponsor and sponsor:
                    ProfileAuditService.audit_sponsor_profile_changes(
                        sponsor=sponsor,
                        old_data=old_sponsor_snapshot,
                        new_data={
                            'Company': sponsor.Company,
                            'BillingEmail': sponsor.BillingEmail,
                            'BillingStreet': sponsor.BillingStreet,
                            'BillingCity': sponsor.BillingCity,
                            'BillingState': sponsor.BillingState,
                            'BillingCountry': sponsor.BillingCountry,
                            'BillingPostal': sponsor.BillingPostal,
                        },
                        changed_by_account_id=current_user.AccountID,
                        change_reason="Self-update via sponsor account page",
                    )
            except Exception as audit_exc:
                try:
                    current_app.logger.warning(f"Sponsor profile audit logging failed: {audit_exc}")
                except Exception:
                    pass

            return _respond("Personal info updated.", "success", 200)

        return _respond("Unsupported request.", "warning", 400)

    last_success = (
        LoginAttempts.query
        .filter_by(AccountID=current_user.AccountID, WasSuccessful=True)
        .order_by(LoginAttempts.AttemptedAt.desc())
        .first()
    )

    return render_template("sponsor_account_info.html", account=account, sponsor=sponsor, last_success=last_success)


# -----------------------------
# Legacy Redirect (for compatibility)
# -----------------------------
@bp.route("/view", methods=["GET"], endpoint="view_sponsor_account")
@login_required
def _legacy_view_redirect():
    return redirect(url_for("sponsor.sponsor_account"))


# -----------------------------
# Sponsor Points Settings Page
# -----------------------------
@bp.route("/points-settings", methods=["GET", "POST"], endpoint="points_settings")
@login_required
def points_settings():
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Only sponsors can view this page.", "danger")
        return redirect(url_for("home.dashboard"))

    # Ensure sane defaults for limits
    if sponsor.MinPointsPerTxn is None:
        sponsor.MinPointsPerTxn = 1
    if sponsor.MaxPointsPerTxn is None or sponsor.MaxPointsPerTxn < sponsor.MinPointsPerTxn:
        sponsor.MaxPointsPerTxn = max(1000, sponsor.MinPointsPerTxn)
    db.session.commit()

    # === List drivers for THIS SPONSOR via DriverSponsor (environment points) ===
    env_rows = (
        db.session.query(Driver, DriverSponsor.PointsBalance.label("EnvPoints"))
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .order_by(Account.FirstName, Account.LastName)
        .all()
    )
    
    # Build drivers list with environment points
    drivers = []
    for driver, env_points in env_rows:
        drivers.append({
            "DriverID": driver.DriverID,
            "Account": driver.Account,
            "PointsBalance": env_points,  # Use environment-specific points
            "Status": driver.Status
        })

    # Provide optional lookup for templates that expect a separate map
    drivers_env = {driver.DriverID: env_points for driver, env_points in env_rows}

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_ratio":
            new_ratio = request.form.get("ratio")
            try:
                old_ratio = sponsor.PointToDollarRate
                new_ratio_value = round(float(new_ratio), 2)
                sponsor.PointToDollarRate = new_ratio_value
                
                # AUDIT: Log point conversion rate change
                ProfileAuditService.log_sponsor_change(
                    sponsor_id=sponsor.SponsorID,
                    account_id=sponsor.AccountID,
                    field_name="PointToDollarRate",
                    old_value=str(old_ratio),
                    new_value=str(new_ratio_value),
                    changed_by_account_id=current_user.AccountID,
                    change_reason="Point conversion rate updated via points settings page"
                )
                
                db.session.commit()
                flash("Point-to-dollar ratio updated successfully.", "success")
            except ValueError:
                flash("Invalid ratio value. Please enter a valid number.", "danger")

        elif action == "update_limits":
            try:
                min_pts = int(request.form.get("min_points") or 1)
                max_pts = int(request.form.get("max_points") or 1000)
                if min_pts < 1:
                    raise ValueError("Minimum must be at least 1.")
                if max_pts < min_pts:
                    raise ValueError("Maximum cannot be less than minimum.")

                # Capture old values for audit logging
                old_min_pts = sponsor.MinPointsPerTxn
                old_max_pts = sponsor.MaxPointsPerTxn

                company_name = sponsor.Company
                (
                    db.session.query(Sponsor)
                    .filter(Sponsor.Company == company_name)
                    .update(
                        {
                            Sponsor.MinPointsPerTxn: min_pts,
                            Sponsor.MaxPointsPerTxn: max_pts,
                        },
                        synchronize_session=False,
                    )
                )
                db.session.commit()

                sponsor.MinPointsPerTxn = min_pts
                sponsor.MaxPointsPerTxn = max_pts

                # AUDIT: Log per-transaction limits changes
                ProfileAuditService.log_sponsor_change(
                    sponsor_id=sponsor.SponsorID,
                    account_id=sponsor.AccountID,
                    field_name="MinPointsPerTxn",
                    old_value=str(old_min_pts),
                    new_value=str(min_pts),
                    changed_by_account_id=current_user.AccountID,
                    change_reason="Minimum per-transaction limit updated via points settings page"
                )
                
                ProfileAuditService.log_sponsor_change(
                    sponsor_id=sponsor.SponsorID,
                    account_id=sponsor.AccountID,
                    field_name="MaxPointsPerTxn",
                    old_value=str(old_max_pts),
                    new_value=str(max_pts),
                    changed_by_account_id=current_user.AccountID,
                    change_reason="Maximum per-transaction limit updated via points settings page"
                )

                flash("Per-transaction limits updated for your entire company.", "success")
            except ValueError as ve:
                flash(str(ve), "danger")
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating limits: {e}", "danger")

        # === modify_points updates the DriverSponsor (environment) balance ===
        elif action == "modify_points":
            driver_id = request.form.get("driver_id")
            points_raw = request.form.get("points")
            operation = request.form.get("operation")

            # SECURITY FIX: Validate and sanitize input data
            if not driver_id or not isinstance(driver_id, str) or len(driver_id) > 50:
                flash("Invalid driver selection.", "danger")
                return redirect(url_for("sponsor.points_settings"))

            # Reason fields (sanitize length)
            reason_choice = (request.form.get("reason_choice") or "").strip()[:200]
            reason_other  = (request.form.get("reason_other") or "").strip()[:500]
            if reason_choice == "__other__":
                reason = reason_other or None
            else:
                reason = reason_choice or (request.form.get("reason") or "").strip() or None

            if not points_raw:
                flash("Please enter a points amount.", "danger")
                return redirect(url_for("sponsor.points_settings"))

            if operation not in ["add", "deduct"]:
                flash("Invalid operation.", "danger")
                return redirect(url_for("sponsor.points_settings"))

            try:
                points = int(points_raw)

                # Enforce per-transaction limits (company-wide rule)
                if points < sponsor.MinPointsPerTxn or points > sponsor.MaxPointsPerTxn:
                    flash(
                        f"Points must be between {sponsor.MinPointsPerTxn} and {sponsor.MaxPointsPerTxn} for a single transaction.",
                        "danger"
                    )
                    return redirect(url_for("sponsor.points_settings"))

                # Ensure the selected driver is attached to THIS sponsor via DriverSponsor
                env = (
                    DriverSponsor.query
                    .filter_by(DriverID=driver_id, SponsorID=sponsor.SponsorID)
                    .first()
                )
                if not env:
                    flash("Driver is not attached to your company.", "danger")
                    return redirect(url_for("sponsor.points_settings"))

                # Load driver for messages/history (and name display)
                driver = (
                    Driver.query
                    .filter_by(DriverID=driver_id)
                    .options(joinedload(Driver.Account))
                    .first()
                )
                if not driver:
                    flash("Invalid driver selected.", "danger")
                    return redirect(url_for("sponsor.points_settings"))

                change = points if operation == "add" else -points

                # Apply to environment (per-sponsor) balance; keep non-negative
                if change >= 0:
                    env.PointsBalance = (env.PointsBalance or 0) + change
                    flash(f"Added {points} points to {driver.Account.FirstName}.", "success")
                else:
                    env.PointsBalance = max(0, (env.PointsBalance or 0) + change)
                    flash(f"Deducted {points} points from {driver.Account.FirstName}.", "warning")

                balance_after = env.PointsBalance

                # Check for low points alert (only if points were deducted)
                if change < 0:
                    try:
                        from app.models import NotificationPreferences
                        prefs = NotificationPreferences.query.filter_by(DriverID=driver.DriverID).first()
                        if prefs and prefs.LowPointsAlertEnabled and prefs.LowPointsThreshold is not None:
                            if balance_after < prefs.LowPointsThreshold:
                                from app.services.notification_service import NotificationService
                                NotificationService.notify_driver_low_points(
                                    driver_id=driver.DriverID,
                                    current_balance=balance_after,
                                    threshold=prefs.LowPointsThreshold
                                )
                    except Exception as e:
                        current_app.logger.error(f"Failed to check low points threshold: {e}")

                # Record audit row, still against (DriverID, SponsorID)
                actor_meta = derive_point_change_actor_metadata(current_user)

                pc = PointChange(
                    DriverID=driver.DriverID,
                    SponsorID=sponsor.SponsorID,
                    DeltaPoints=change,
                    TransactionID=None,
                    InitiatedByAccountID=current_user.AccountID,
                    BalanceAfter=balance_after,
                    Reason=reason,
                    ActorRoleCode=actor_meta["actor_role_code"],
                    ActorLabel=actor_meta["actor_label"],
                    ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
                    ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
                )
                db.session.add(pc)
                
                # Send notification to driver about point change
                try:
                    from app.services.notification_service import NotificationService
                    NotificationService.notify_driver_points_change(
                        driver_id=driver.DriverID,
                        delta_points=change,
                        reason=reason,
                        balance_after=balance_after,
                        sponsor_id=sponsor.SponsorID
                    )
                except Exception as e:
                    from flask import current_app
                    current_app.logger.error(f"Failed to send points change notification: {str(e)}")

                db.session.commit()

            except ValueError:
                flash("Points must be a whole number.", "danger")
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating points: {e}", "danger")

        return redirect(url_for("sponsor.points_settings"))

    return render_template(
        "sponsor_points_settings.html",
        sponsor=sponsor,
        drivers=drivers,
        drivers_env=drivers_env  # env-specific points
    )


# -----------------------------
# Quick history JSON (inline view)
# -----------------------------
@bp.route("/driver/<driver_id>/history.json")
@login_required
def driver_history_api(driver_id):
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return jsonify({"error": "unauthorized"}), 403

    limit = max(1, min(int(request.args.get("limit", 10)), 50))

    q = (
        PointChange.query
        .filter(PointChange.DriverID == driver_id,
                PointChange.SponsorID == sponsor.SponsorID)
        .order_by(PointChange.CreatedAt.desc())
        .limit(limit)
    )

    rows = [{
        "created_at": pc.CreatedAt.strftime("%Y-%m-%d %H:%M"),
        "delta": pc.DeltaPoints,
        "reason": pc.Reason or "",
        "balance_after": pc.BalanceAfter,
    } for pc in q.all()]

    return jsonify({"items": rows})


# -----------------------------
# Full history page (with date filters)
# -----------------------------
@bp.route("/driver/<driver_id>/history")
@login_required
def driver_history_page(driver_id):
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied", "danger")
        return redirect(url_for("home.dashboard"))

    page     = max(1, int(request.args.get("page", 1)))
    per_page = max(10, min(int(request.args.get("per_page", 25)), 100))

    start_str = (request.args.get("start") or "").strip()
    end_str   = (request.args.get("end") or "").strip()

    start_dt = None
    end_dt_exclusive = None
    try:
        if start_str:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        if end_str:
            end_dt_exclusive = datetime.strptime(end_str, "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        flash("Invalid date format. Use YYYY-MM-DD.", "warning")

    base_q = (
        PointChange.query
        .filter(PointChange.DriverID == driver_id,
                PointChange.SponsorID == sponsor.SponsorID)
    )

    if start_dt is not None:
        base_q = base_q.filter(PointChange.CreatedAt >= start_dt)
    if end_dt_exclusive is not None:
        base_q = base_q.filter(PointChange.CreatedAt < end_dt_exclusive)

    base_q = base_q.order_by(PointChange.CreatedAt.desc())

    total = base_q.count()
    rows  = base_q.offset((page-1)*per_page).limit(per_page).all()
    pages = max(1, ceil(total / per_page))

    driver = (
        Driver.query
        .filter_by(DriverID=driver_id)
        .options(joinedload(Driver.Account))
        .first()
    )
    if not driver:
        flash("Driver not found.", "warning")
        return redirect(url_for("sponsor.points_settings"))

    return render_template(
        "driver_points_history.html",
        sponsor=sponsor,
        driver=driver,
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
        pages=pages,
        start=start_str,
        end=end_str,
    )


# -----------------------------
# Multiple Driver Point Assignment (company-wide)
# -----------------------------
@bp.route("/multi-points", methods=["GET", "POST"], endpoint="multi_points")
@login_required
def multi_points():
    """
    Apply a point change to multiple drivers whose Sponsor.Company matches the
    logged-in sponsor's Company. Records each change against THIS sponsor and updates
    the per-environment DriverSponsor balance.
    """
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Only sponsors can modify points.", "danger")
        return redirect(url_for("home.dashboard"))

    # List ALL drivers under the same company via DriverSponsor relationship
    drivers = (
        Driver.query
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .join(Sponsor, DriverSponsor.SponsorID == Sponsor.SponsorID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .filter(Sponsor.Company == sponsor.Company,
                DriverSponsor.SponsorID == sponsor.SponsorID)
        .options(joinedload(Driver.Account))
        .order_by(Account.FirstName.asc(), Account.LastName.asc())
        .all()
    )

    if request.method == "POST":
        flash("POST request received for bulk points update", "info")
        
        selected_driver_ids = request.form.getlist("driver_ids")
        points_delta = request.form.get("points_delta", type=int)
        reason = (request.form.get("reason") or "").strip()

        from flask import current_app
        current_app.logger.info(f"Bulk points update - Selected drivers: {selected_driver_ids}")
        current_app.logger.info(f"Bulk points update - Points delta: {points_delta}")
        current_app.logger.info(f"Bulk points update - Reason: {reason}")
        current_app.logger.info(f"Bulk points update - Form data: {dict(request.form)}")

        if not selected_driver_ids:
            flash("Please select at least one driver.", "warning")
            return redirect(url_for("sponsor.multi_points"))
        if points_delta is None or points_delta == 0:
            flash("Points must be a non-zero integer.", "warning")
            return redirect(url_for("sponsor.multi_points"))
        if not reason:
            flash("Please provide a reason.", "warning")
            return redirect(url_for("sponsor.multi_points"))

        # Enforce company-level per-transaction limits (use absolute value)
        try:
            min_pts = sponsor.MinPointsPerTxn or 1
            max_pts = sponsor.MaxPointsPerTxn or 1000
            if abs(points_delta) < min_pts or abs(points_delta) > max_pts:
                flash(f"Each change must be between {min_pts} and {max_pts} points.", "danger")
                return redirect(url_for("sponsor.multi_points"))
        except Exception:
            pass

        # Re-confirm all chosen drivers belong to the same company and sponsor
        target_envs = (
            DriverSponsor.query
            .join(Driver, Driver.DriverID == DriverSponsor.DriverID)
            .join(Sponsor, Sponsor.SponsorID == DriverSponsor.SponsorID)
            .filter(DriverSponsor.DriverID.in_(selected_driver_ids),
                    Sponsor.Company == sponsor.Company,
                    DriverSponsor.SponsorID == sponsor.SponsorID)
            .all()
        )

        current_app.logger.info(f"Bulk points update - Found {len(target_envs)} target driver environments")
        current_app.logger.info(f"Bulk points update - Sponsor company: {sponsor.Company}")

        actor_meta = derive_point_change_actor_metadata(current_user)
        count = 0
        for env in target_envs:
            # Adjust environment balance
            old_balance = env.PointsBalance or 0
            env.PointsBalance = old_balance + points_delta

            # Load driver for notification + audit and account name
            driver = Driver.query.options(joinedload(Driver.Account)).filter_by(DriverID=env.DriverID).first()

            # Record PointChange
            change = PointChange(
                PointChangeID=str(uuid.uuid4()),
                DriverID=env.DriverID,
                SponsorID=sponsor.SponsorID,
                DeltaPoints=points_delta,
                BalanceAfter=env.PointsBalance,
                CreatedAt=datetime.utcnow(),
                Reason=reason,
                InitiatedByAccountID=current_user.AccountID,
                ActorRoleCode=actor_meta["actor_role_code"],
                ActorLabel=actor_meta["actor_label"],
                ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
                ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
            )
            db.session.add(change)
            
            # Send notification about point change (only once)
            try:
                from app.services.notification_service import NotificationService
                NotificationService.notify_driver_points_change(
                    driver_id=env.DriverID,
                    delta_points=points_delta,
                    reason=reason or f"Points {'added' if points_delta > 0 else 'deducted'} by sponsor",
                    balance_after=env.PointsBalance,
                    sponsor_id=sponsor.SponsorID
                )
            except Exception as e:
                current_app.logger.error(f"Failed to send point change notification: {e}")
            
            # Check for low points alert (only if points were deducted)
            if points_delta < 0:
                try:
                    from app.models import NotificationPreferences
                    prefs = NotificationPreferences.query.filter_by(DriverID=env.DriverID).first()
                    if prefs and prefs.LowPointsAlertEnabled and prefs.LowPointsThreshold is not None:
                        if env.PointsBalance < prefs.LowPointsThreshold:
                            from app.services.notification_service import NotificationService
                            NotificationService.notify_driver_low_points(
                                driver_id=env.DriverID,
                                current_balance=env.PointsBalance,
                                threshold=prefs.LowPointsThreshold
                            )
                except Exception as e:
                    current_app.logger.error(f"Failed to check low points threshold: {e}")
            
            count += 1

        try:
            db.session.commit()
            current_app.logger.info(f"Bulk points update - Successfully committed {count} changes")
            flash(f"Applied {points_delta:+} points to {count} driver(s).", "success")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Bulk points update - Commit failed: {str(e)}")
            flash(f"Error updating points: {str(e)}", "danger")
        
        return redirect(url_for("sponsor.points_settings"))

    return render_template("sponsor/multi_points.html", drivers=drivers)


# -------------------------------------------------------------------
# AUDIT LOG HUB (menu)
# -------------------------------------------------------------------
@bp.route("/audit-log", methods=["GET"], endpoint="audit_log")
@login_required
def audit_log():
    """Simple hub that links to individual audit logs."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    return render_template("sponsor_audit_log.html")


# -------------------------------------------------------------------
# Point Changes Audit Log
#   URL: /sponsor/audit-log/point-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/point-changes", methods=["GET"], endpoint="audit_point_changes")
@login_required
def audit_point_changes():
    """Lists point changes for drivers within the sponsor's organization."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))

    q = (request.args.get("q") or "").strip()
    change_type = (request.args.get("change_type") or "").strip()  # "", "positive", "negative"
    reason_filter = (request.args.get("reason") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    # Create aliases for joins
    InitiatorAccount = aliased(Account)  # who initiated the change
    DriverAccount = aliased(Account)     # driver's account info

    qry = (
        db.session.query(PointChange, DriverAccount, InitiatorAccount, Driver)
        .join(Driver, PointChange.DriverID == Driver.DriverID)
        .join(DriverAccount, Driver.AccountID == DriverAccount.AccountID)
        .outerjoin(InitiatorAccount, InitiatorAccount.AccountID == PointChange.InitiatedByAccountID)
        .filter(PointChange.SponsorID == sponsor.SponsorID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                DriverAccount.FirstName.ilike(like),
                DriverAccount.LastName.ilike(like),
                DriverAccount.Email.ilike(like),
                PointChange.Reason.ilike(like),
            )
        )

    if change_type == "positive":
        qry = qry.filter(PointChange.DeltaPoints > 0)
    elif change_type == "negative":
        qry = qry.filter(PointChange.DeltaPoints < 0)

    # Reason filtering
    if reason_filter:
        if reason_filter == "Other":
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
            qry = qry.filter(~PointChange.Reason.like("Order #ORD-% - Points Payment"))
        elif reason_filter == "Points Payment":
            qry = qry.filter(PointChange.Reason.like("Order #ORD-% - Points Payment"))
        else:
            qry = qry.filter(PointChange.Reason.ilike(f"%{reason_filter}%"))

    # Date range filtering
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(PointChange.CreatedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(PointChange.CreatedAt < date_to_obj)
        except ValueError:
            pass

    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(PointChange.CreatedAt.asc())
    else:
        qry = qry.order_by(PointChange.CreatedAt.desc())

    rows = qry.all()
    
    # Build reason list (normalize order-related reasons)
    reasons = (
        db.session.query(PointChange.Reason)
        .filter(PointChange.Reason.is_not(None),
                PointChange.SponsorID == sponsor.SponsorID)
        .distinct()
        .all()
    )
    reason_list = []
    for reason_tuple in reasons:
        reason = reason_tuple[0]
        if reason and reason.startswith("Order #ORD-") and reason.endswith("- Points Payment"):
            normalized_reason = "Points Payment"
        else:
            normalized_reason = reason
        if normalized_reason and normalized_reason.lower() != "speeding" and normalized_reason not in reason_list:
            reason_list.append(normalized_reason)
    
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
    
    return render_template(
        "sponsor_audit_point_changes.html",
        rows=rows, q=q, 
        change_type=change_type, reason_filter=reason_filter,
        date_from=date_from, date_to=date_to, sort_order=sort_order,
        reasons=reason_list,
        default_positive_reasons=default_positive_reasons, 
        default_negative_reasons=default_negative_reasons,
        sponsor=sponsor
    )


# -------------------------------------------------------------------
# Driver Applications Audit Log
#   URL: /sponsor/audit-log/applications
# -------------------------------------------------------------------
@bp.route("/audit-log/applications", methods=["GET"], endpoint="audit_applications")
@login_required
def audit_applications():
    """Lists driver applications for the sponsor's organization."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))

    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip().lower()  # "", pending, accepted, rejected, reviewed
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    Reviewer = aliased(Account)  # reviewer account (DecisionByAccountID)

    qry = (
        db.session.query(Application, Account, Reviewer)
        .join(Account, Account.AccountID == Application.AccountID)                   # applicant
        .outerjoin(Reviewer, Reviewer.AccountID == Application.DecisionByAccountID)  # reviewer (optional)
        .filter(Application.SponsorID == sponsor.SponsorID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                Account.FirstName.ilike(like),
                Account.LastName.ilike(like),
                Account.Email.ilike(like),
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

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(Application.SubmittedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(Application.SubmittedAt < date_to_obj)
        except ValueError:
            pass

    if sort_order == "asc":
        qry = qry.order_by(
            Application.SubmittedAt.is_(None),
            Application.SubmittedAt.asc(),
        )
    else:
        qry = qry.order_by(
            Application.SubmittedAt.is_(None),
            Application.SubmittedAt.desc(),
        )

    rows = qry.all()
    return render_template(
        "sponsor_audit_applications.html",
        rows=rows, q=q, status=status, 
        date_from=date_from, date_to=date_to,
        sort_order=sort_order, sponsor=sponsor
    )


# =========================
# SPONSOR NOTIFICATION SETTINGS
# =========================
@bp.route("/notification-settings", methods=["GET", "POST"], endpoint="notification_settings")
@login_required
def notification_settings():
    """Display and update sponsor notification preferences"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Sponsor account not found", "danger")
        return redirect(url_for("dashboard"))
    
    # Get or create notification preferences
    prefs = SponsorNotificationPreferences.get_or_create_for_sponsor(sponsor.SponsorID)
    
    if request.method == "POST":
        try:
            prefs.OrderConfirmations = request.form.get('order_confirmations') == 'on'
            prefs.NewApplications = request.form.get('new_applications') == 'on'
            # Large driver points change alerts (>=1000)
            prefs.DriverPointsChanges = request.form.get('driver_points_changes') == 'on'
            db.session.commit()
            flash("Notification preferences updated successfully!", "success")
            return redirect(url_for("sponsor.notification_settings"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating notification preferences: {str(e)}", "danger")
            return redirect(url_for("sponsor.notification_settings"))
    
    return render_template("sponsor/notification_settings.html", sponsor=sponsor, prefs=prefs)


@bp.route("/notification-settings/api/update", methods=["POST"])
@login_required
def update_notification_preference():
    """API endpoint to update individual notification preferences via AJAX"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return jsonify({"success": False, "error": "Sponsor not found"}), 403
    
    try:
        data = request.get_json()
        preference_name = data.get('preference')
        value = data.get('value', False)
        
        if not preference_name:
            return jsonify({"success": False, "error": "Preference name required"}), 400
        
        prefs = SponsorNotificationPreferences.get_or_create_for_sponsor(sponsor.SponsorID)
        
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
# Driver Profile Changes Audit Log
#   URL: /sponsor/audit-log/driver-profile-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/driver-profile-changes", methods=["GET"], endpoint="audit_driver_profile_changes")
@login_required
def audit_driver_profile_changes():
    """Lists driver profile changes for drivers within the sponsor's organization."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))

    q = (request.args.get("q") or "").strip()
    field_filter = (request.args.get("field") or "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()  # "desc" or "asc"

    from app.models import DriverProfileAudit

    DriverAccount = aliased(Account)      # driver's account info
    ChangedByAccount = aliased(Account)   # who made the change

    qry = (
        db.session.query(DriverProfileAudit, Driver, DriverAccount, ChangedByAccount)
        .join(Driver, DriverProfileAudit.DriverID == Driver.DriverID)
        .join(DriverAccount, DriverProfileAudit.AccountID == DriverAccount.AccountID)
        .outerjoin(ChangedByAccount, DriverProfileAudit.ChangedByAccountID == ChangedByAccount.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )

    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                DriverAccount.FirstName.ilike(like),
                DriverAccount.LastName.ilike(like),
                DriverAccount.Email.ilike(like),
                DriverProfileAudit.FieldName.ilike(like),
            )
        )

    if field_filter:
        qry = qry.filter(DriverProfileAudit.FieldName == field_filter)

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(DriverProfileAudit.ChangedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            date_to_obj = date_to_obj + timedelta(days=1)
            qry = qry.filter(DriverProfileAudit.ChangedAt < date_to_obj)
        except ValueError:
            pass

    qry = qry.order_by(DriverProfileAudit.ChangedAt.asc() if sort_order == "asc" else DriverProfileAudit.ChangedAt.desc())
    rows = qry.all()
    
    fields = (
        db.session.query(DriverProfileAudit.FieldName)
        .join(Driver, DriverProfileAudit.DriverID == Driver.DriverID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .distinct()
        .order_by(DriverProfileAudit.FieldName)
        .all()
    )
    field_list = [field[0] for field in fields]
    
    return render_template(
        "sponsor_audit_driver_profile_changes.html",
        rows=rows, q=q, field_filter=field_filter,
        date_from=date_from, date_to=date_to, 
        sort_order=sort_order, sponsor=sponsor, fields=field_list
    )


# ============================================================================
# SPONSOR ANALYTICS SYSTEM
# ============================================================================

# -------------------------------------------------------------------
# Sponsor Analytics Hub
#   URL: /sponsor/analytics
# -------------------------------------------------------------------
@bp.route("/analytics", methods=["GET"], endpoint="sponsor_analytics")
@login_required
def sponsor_analytics():
    """Sponsor analytics hub page with different report tools for their drivers."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    # Monthly points summary (use SponsorID from PointChange)
    current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_points = (
        db.session.query(PointChange)
        .filter(PointChange.SponsorID == sponsor.SponsorID,
                PointChange.CreatedAt >= current_month_start)
        .all()
    )
    monthly_total = sum(pc.DeltaPoints for pc in monthly_points if pc.DeltaPoints)
    
    # Driver counts via DriverSponsor
    driver_count = (
        db.session.query(DriverSponsor.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .distinct()
        .count()
    )
    active_driver_count = (
        db.session.query(DriverSponsor.DriverID)
        .join(Driver, Driver.DriverID == DriverSponsor.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID,
                Driver.Status == 'active')
        .distinct()
        .count()
    )
    
    return render_template(
        "sponsor_analytics.html",
        sponsor=sponsor, 
        monthly_total=monthly_total,
        driver_count=driver_count, 
        active_driver_count=active_driver_count
    )


# -------------------------------------------------------------------
# Sponsor Driver Performance Analytics
#   URL: /sponsor/analytics/driver-performance
# -------------------------------------------------------------------
@bp.route("/analytics/driver-performance", methods=["GET"], endpoint="sponsor_analytics_driver_performance")
@login_required
def sponsor_analytics_driver_performance():
    """Driver performance analytics for sponsor's drivers only."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    qry = (
        db.session.query(Driver, Account, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    
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
    
    return render_template(
        "sponsor_analytics_driver_performance.html",
        rows=rows, date_from=date_from, date_to=date_to, sponsor=sponsor
    )


# -------------------------------------------------------------------
# Sponsor Driver Performance Analytics CSV Export
#   URL: /sponsor/analytics/driver-performance/csv
# -------------------------------------------------------------------
@bp.route("/analytics/driver-performance/csv", methods=["GET"], endpoint="sponsor_analytics_driver_performance_csv")
@login_required
def sponsor_analytics_driver_performance_csv():
    """Generate a CSV version of the Driver Performance Analytics with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    qry = (
        db.session.query(Driver, Account, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    
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
    
    # Generate CSV
    output = BytesIO()
    header = "Driver Name|Email|Status|Points Change|Reason|Date\n"
    output.write(header.encode('utf-8'))
    
    for driver, account, point_change in rows:
        driver_name = f"{account.FirstName} {account.LastName}"
        email = account.Email or ''
        status = driver.Status or 'Unknown'
        points_change = f"{point_change.DeltaPoints}" if point_change and point_change.DeltaPoints is not None else "N/A"
        reason = point_change.Reason if point_change else 'N/A'
        date_str = point_change.CreatedAt.strftime('%Y-%m-%d %H:%M') if point_change and point_change.CreatedAt else 'N/A'
        
        row = f"{driver_name}|{email}|{status}|{points_change}|{reason}|{date_str}\n"
        output.write(row.encode('utf-8'))
    
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_performance_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response


# -------------------------------------------------------------------
# Sponsor Driver Performance Analytics PDF Export
#   URL: /sponsor/analytics/driver-performance/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/driver-performance/pdf", methods=["GET"], endpoint="sponsor_analytics_driver_performance_pdf")
@login_required
def sponsor_analytics_driver_performance_pdf():
    """Generate a PDF version of the Driver Performance Analytics with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    qry = (
        db.session.query(Driver, Account, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    
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
    
    elements.append(Paragraph("Driver Performance Analytics", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Company:</b> {sponsor.Company}", styles['Normal']))
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Records:</b> {len(rows)}", styles['Normal']))
    
    filter_info = "Filters: "
    filters = []
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
        small_style = ParagraphStyle(
            'TableContent',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
        )
        
        table_data = [[
            Paragraph('<b>Driver Name</b>', small_style),
            Paragraph('<b>Email</b>', small_style),
            Paragraph('<b>Status</b>', small_style),
            Paragraph('<b>Points Change</b>', small_style),
            Paragraph('<b>Reason</b>', small_style),
            Paragraph('<b>Date</b>', small_style)
        ]]
        
        for driver, account, point_change in rows:
            driver_name = f"{account.FirstName} {account.LastName}"
            email = account.Email or "N/A"
            status = driver.Status or "N/A"
            points_change = f"{point_change.DeltaPoints}" if point_change and point_change.DeltaPoints is not None else "N/A"
            reason = point_change.Reason if point_change else 'N/A'
            date_str = point_change.CreatedAt.strftime('%m/%d/%Y %H:%M') if point_change and point_change.CreatedAt else "N/A"
            
            driver_name_para = Paragraph(driver_name, small_style)
            email_para = Paragraph(email, small_style)
            reason_para = Paragraph(reason, small_style)
            
            table_data.append([driver_name_para, email_para, status, points_change, reason_para, date_str])
        
        # Adjusted column widths: 1.5 + 2.0 + 0.8 + 1.0 + 2.5 + 1.2 = 9.0" (leaving some margin)
        table = Table(table_data, colWidths=[1.5*inch, 2.0*inch, 0.8*inch, 1.0*inch, 2.5*inch, 1.2*inch])
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
        elements.append(Paragraph("No data found for the selected filters.", styles['Normal']))
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_performance_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    
    return response


# -------------------------------------------------------------------
# Sponsor Financial Analytics
#   URL: /sponsor/analytics/financial-analytics
# -------------------------------------------------------------------
@bp.route("/analytics/financial-analytics", methods=["GET"], endpoint="sponsor_analytics_financial")
@login_required
def sponsor_analytics_financial():
    """Financial analytics for sponsor's point transactions only."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    # Only include purchases and refunds (exclude manual adjustments and dispute resolutions)
    qry = (
        db.session.query(PointChange, Driver, Account)
        .join(Driver, Driver.DriverID == PointChange.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .filter(PointChange.SponsorID == sponsor.SponsorID)
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
    
    return render_template(
        "sponsor_analytics_financial.html",
        rows=rows, date_from=date_from, date_to=date_to, sponsor=sponsor
    )


# -------------------------------------------------------------------
# Sponsor Financial Analytics CSV Export
#   URL: /sponsor/analytics/financial-analytics/csv
# -------------------------------------------------------------------
@bp.route("/analytics/financial-analytics/csv", methods=["GET"], endpoint="sponsor_analytics_financial_csv")
@login_required
def sponsor_analytics_financial_csv():
    """Generate a CSV version of the Financial Analytics with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    # Only include purchases and refunds (exclude manual adjustments and dispute resolutions)
    qry = (
        db.session.query(PointChange, Driver, Account)
        .join(Driver, Driver.DriverID == PointChange.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .filter(PointChange.SponsorID == sponsor.SponsorID)
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
    
    # Generate CSV
    output = BytesIO()
    header = "Driver Name|Driver Email|Points Change|Dollar Value|Reason|Transaction Date\n"
    output.write(header.encode('utf-8'))
    
    for point_change, driver, account in rows:
        driver_name = f"{account.FirstName} {account.LastName}"
        driver_email = account.Email or ''
        points_change = point_change.DeltaPoints or 0
        dollar_value = float(points_change) * float(sponsor.PointToDollarRate)
        reason = point_change.Reason or 'N/A'
        date_str = point_change.CreatedAt.strftime('%Y-%m-%d %H:%M') if point_change.CreatedAt else 'N/A'
        
        row = f"{driver_name}|{driver_email}|{points_change}|{dollar_value:.2f}|{reason}|{date_str}\n"
        output.write(row.encode('utf-8'))
    
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=financial_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response


# -------------------------------------------------------------------
# Sponsor Financial Analytics PDF Export
#   URL: /sponsor/analytics/financial-analytics/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/financial-analytics/pdf", methods=["GET"], endpoint="sponsor_analytics_financial_pdf")
@login_required
def sponsor_analytics_financial_pdf():
    """Generate a PDF version of the Financial Analytics with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    
    # Only include purchases and refunds (exclude manual adjustments and dispute resolutions)
    qry = (
        db.session.query(PointChange, Driver, Account)
        .join(Driver, Driver.DriverID == PointChange.DriverID)
        .join(Account, Account.AccountID == Driver.AccountID)
        .filter(PointChange.SponsorID == sponsor.SponsorID)
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
    
    elements.append(Paragraph("Financial Analytics Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Company:</b> {sponsor.Company}", styles['Normal']))
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Records:</b> {len(rows)}", styles['Normal']))
    
    filter_info = "Filters: "
    filters = []
    if date_from:
        filters.append(f"From: {date_from}")
    if date_to:
        filters.append(f"To: {date_to}")
    
    if filters:
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph(f"<b>{filter_info}{'; '.join(filters)}</b>", styles['Normal']))
    else:
        elements.append(Paragraph("<b>Filters: None (All records)</b>", styles['Normal']))
    
    elements.append(Paragraph("<b>Note:</b> Only purchase and refund transactions are shown.", styles['Normal']))
    elements.append(Spacer(1, 0.2*inch))
    elements.append(Paragraph("Financial Transaction Data", heading_style))
    
    if rows:
        small_style = ParagraphStyle(
            'TableContent',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
        )
        
        table_data = [[
            Paragraph('<b>Driver Name</b>', small_style),
            Paragraph('<b>Driver Email</b>', small_style),
            Paragraph('<b>Points Change</b>', small_style),
            Paragraph('<b>Dollar Value</b>', small_style),
            Paragraph('<b>Reason</b>', small_style),
            Paragraph('<b>Transaction Date</b>', small_style)
        ]]
        
        for point_change, driver, account in rows:
            driver_name = f"{account.FirstName} {account.LastName}"
            driver_email = account.Email or "N/A"
            points_change = point_change.DeltaPoints or 0
            dollar_value = float(points_change) * float(sponsor.PointToDollarRate)
            reason = point_change.Reason or 'N/A'
            date_str = point_change.CreatedAt.strftime('%m/%d/%Y %H:%M') if point_change.CreatedAt else "N/A"
            
            driver_name_para = Paragraph(driver_name, small_style)
            email_para = Paragraph(driver_email, small_style)
            reason_para = Paragraph(reason, small_style)
            
            table_data.append([driver_name_para, email_para, str(points_change), f"${dollar_value:.2f}", reason_para, date_str])
        
        # Adjusted column widths: 1.5 + 2.0 + 1.0 + 1.0 + 2.5 + 1.0 = 10.0"
        table = Table(table_data, colWidths=[1.5*inch, 2.0*inch, 1.0*inch, 1.0*inch, 2.5*inch, 1.0*inch])
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
        elements.append(Paragraph("No data found for the selected filters.", styles['Normal']))
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=financial_analytics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    
    return response


# -------------------------------------------------------------------
# Sponsor Invoice Log
#   URL: /sponsor/analytics/invoices
# -------------------------------------------------------------------
@bp.route("/analytics/invoices", methods=["GET"], endpoint="sponsor_invoices")
@login_required
def sponsor_invoices():
    """Invoice log for sponsor's company only."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    # Get the sponsor's company name for filtering
    company_name = None
    if sponsor.SponsorCompanyID:
        sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=sponsor.SponsorCompanyID).first()
        if sponsor_company:
            company_name = sponsor_company.CompanyName
    else:
        # Fallback to Company field if SponsorCompanyID is not set
        company_name = sponsor.Company
    
    if not company_name:
        flash("Unable to determine your company. Please contact support.", "danger")
        return redirect(url_for("sponsor.sponsor_analytics_financial"))
    
    # Get date filters
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
    
    # Get invoices filtered by company (preset filter)
    try:
        invoice_log = InvoiceService.get_invoice_log(
            company_filter=company_name,
            start_month=start_month or None,
            end_month=end_month or None,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        invoice_log = []
    
    return render_template(
        "sponsor_invoices.html",
        invoice_log=invoice_log,
        company_name=company_name,
        start_month=start_month,
        end_month=end_month,
    )


# -------------------------------------------------------------------
# Sponsor Invoice Detail
#   URL: /sponsor/analytics/invoices/<invoice_id>
# -------------------------------------------------------------------
@bp.route("/analytics/invoices/<invoice_id>", methods=["GET"], endpoint="sponsor_invoice_detail")
@login_required
def sponsor_invoice_detail(invoice_id):
    """View a specific invoice detail for sponsor's company only."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    # Get the sponsor's company name for verification
    company_name = None
    if sponsor.SponsorCompanyID:
        sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=sponsor.SponsorCompanyID).first()
        if sponsor_company:
            company_name = sponsor_company.CompanyName
    else:
        company_name = sponsor.Company
    
    try:
        invoice_payload = InvoiceService.get_invoice_by_id(invoice_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    except Exception:
        current_app.logger.exception("Failed to load invoice %s", invoice_id)
        flash("Unable to load invoice.", "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    
    # Verify the invoice belongs to the sponsor's company
    invoice_company_name = invoice_payload.get("invoice", {}).get("company_name")
    if invoice_company_name and invoice_company_name != company_name:
        flash("Access denied: This invoice does not belong to your company.", "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    
    return render_template("sponsor_invoice_detail.html", invoice_payload=invoice_payload)


# -------------------------------------------------------------------
# Sponsor Invoice PDF Export
#   URL: /sponsor/analytics/invoices/<invoice_id>/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/invoices/<invoice_id>/pdf", methods=["GET"], endpoint="sponsor_invoice_pdf")
@login_required
def sponsor_invoice_pdf(invoice_id):
    """Export invoice as PDF for sponsor's company only."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    # Get the sponsor's company name for verification
    company_name = None
    if sponsor.SponsorCompanyID:
        sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=sponsor.SponsorCompanyID).first()
        if sponsor_company:
            company_name = sponsor_company.CompanyName
    else:
        company_name = sponsor.Company
    
    try:
        invoice_payload = InvoiceService.get_invoice_by_id(invoice_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    except Exception:
        current_app.logger.exception("Failed to build invoice PDF %s", invoice_id)
        flash("Unable to generate invoice PDF.", "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    
    # Verify the invoice belongs to the sponsor's company
    invoice_company_name = invoice_payload.get("invoice", {}).get("company_name")
    if invoice_company_name and invoice_company_name != company_name:
        flash("Access denied: This invoice does not belong to your company.", "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    
    invoice = invoice_payload["invoice"]
    sponsor_data = invoice_payload["sponsor"]
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

    elements.append(Paragraph(f"<b>Company:</b> {sponsor_data['company']}", meta_style))
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
    filename = f"invoice_{invoice['invoice_month']}_{sponsor_data['company'].replace(' ', '_')}.pdf"
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


# -------------------------------------------------------------------
# Sponsor Invoice CSV Export
#   URL: /sponsor/analytics/invoices/<invoice_id>/csv
# -------------------------------------------------------------------
@bp.route("/analytics/invoices/<invoice_id>/csv", methods=["GET"], endpoint="sponsor_invoice_csv")
@login_required
def sponsor_invoice_csv(invoice_id):
    """Export invoice as CSV for sponsor's company only."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    # Get the sponsor's company name for verification
    company_name = None
    if sponsor.SponsorCompanyID:
        sponsor_company = SponsorCompany.query.filter_by(SponsorCompanyID=sponsor.SponsorCompanyID).first()
        if sponsor_company:
            company_name = sponsor_company.CompanyName
    else:
        company_name = sponsor.Company
    
    try:
        invoice_payload = InvoiceService.get_invoice_by_id(invoice_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    except Exception:
        current_app.logger.exception("Failed to build invoice CSV %s", invoice_id)
        flash("Unable to generate invoice CSV.", "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    
    # Verify the invoice belongs to the sponsor's company
    invoice_company_name = invoice_payload.get("invoice", {}).get("company_name")
    if invoice_company_name and invoice_company_name != company_name:
        flash("Access denied: This invoice does not belong to your company.", "danger")
        return redirect(url_for("sponsor.sponsor_invoices"))
    
    invoice = invoice_payload["invoice"]
    sponsor_data = invoice_payload["sponsor"]
    orders = invoice_payload["orders"]

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(["Invoice Month", invoice["invoice_month"]])
    writer.writerow(["Company", sponsor_data["company"]])
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
    filename = f"invoice_{invoice['invoice_month']}_{sponsor_data['company'].replace(' ', '_')}.csv"
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response


# -------------------------------------------------------------------
# Sponsor Driver Reports
#   URL: /sponsor/analytics/driver-reports
# -------------------------------------------------------------------
@bp.route("/analytics/driver-reports", methods=["GET"], endpoint="sponsor_analytics_driver_reports")
@login_required
def sponsor_analytics_driver_reports():
    """Comprehensive driver reports with filtering options."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_status = request.args.get("driver_status", "").strip()
    driver_id = request.args.get("driver_id", "").strip()
    
    qry = (
        db.session.query(Driver, Account, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    
    if driver_status:
        qry = qry.filter(Driver.Status == driver_status)
    if driver_id:
        qry = qry.filter(Driver.DriverID == driver_id)
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
    
    all_drivers = (
        db.session.query(Driver, Account)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .order_by(Account.FirstName, Account.LastName)
        .all()
    )
    
    current_month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_points = (
        db.session.query(PointChange)
        .filter(PointChange.SponsorID == sponsor.SponsorID,
                PointChange.CreatedAt >= current_month_start)
        .all()
    )
    monthly_total = sum(pc.DeltaPoints for pc in monthly_points if pc.DeltaPoints)
    
    # Calculate driver engagement (total points per driver)
    driver_engagement = {}
    for driver, account in all_drivers:
        driver_points_qry = (
            db.session.query(PointChange)
            .filter(PointChange.DriverID == driver.DriverID,
                    PointChange.SponsorID == sponsor.SponsorID)
        )
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
                driver_points_qry = driver_points_qry.filter(PointChange.CreatedAt >= date_from_obj)
            except ValueError:
                pass
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
                driver_points_qry = driver_points_qry.filter(PointChange.CreatedAt <= date_to_obj)
            except ValueError:
                pass
        
        driver_points = driver_points_qry.all()
        total_points = sum(pc.DeltaPoints for pc in driver_points if pc.DeltaPoints)
        driver_engagement[driver.DriverID] = {
            'driver': driver,
            'account': account,
            'total_points': total_points,
            'transaction_count': len(driver_points)
        }
    
    return render_template(
        "sponsor_analytics_driver_reports.html", 
        rows=rows, date_from=date_from, date_to=date_to, 
        driver_status=driver_status, driver_id=driver_id,
        all_drivers=all_drivers, sponsor=sponsor,
        monthly_total=monthly_total, driver_engagement=driver_engagement
    )


# -------------------------------------------------------------------
# Sponsor Driver Reports CSV Export
#   URL: /sponsor/analytics/driver-reports/csv
# -------------------------------------------------------------------
@bp.route("/analytics/driver-reports/csv", methods=["GET"], endpoint="sponsor_analytics_driver_reports_csv")
@login_required
def sponsor_analytics_driver_reports_csv():
    """Generate a CSV version of the Driver Reports with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_status = request.args.get("driver_status", "").strip()
    driver_id = request.args.get("driver_id", "").strip()
    
    qry = (
        db.session.query(Driver, Account, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    
    if driver_status:
        qry = qry.filter(Driver.Status == driver_status)
    if driver_id:
        qry = qry.filter(Driver.DriverID == driver_id)
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
    
    # Generate CSV
    output = BytesIO()
    header = "Driver Name|Driver Email|Driver Status|Points Change|Reason|Changed By|Date\n"
    output.write(header.encode('utf-8'))
    
    for driver, account, point_change in rows:
        driver_name = f"{account.FirstName} {account.LastName}"
        driver_email = account.Email or ''
        driver_status = driver.Status or 'Unknown'
        points_change = f"{point_change.DeltaPoints}" if point_change and point_change.DeltaPoints is not None else "N/A"
        reason = point_change.Reason if point_change else 'N/A'
        changed_by = sponsor.Company
        date_str = point_change.CreatedAt.strftime('%Y-%m-%d %H:%M') if point_change and point_change.CreatedAt else 'N/A'
        
        row = f"{driver_name}|{driver_email}|{driver_status}|{points_change}|{reason}|{changed_by}|{date_str}\n"
        output.write(row.encode('utf-8'))
    
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_reports_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response


# -------------------------------------------------------------------
# Sponsor Driver Reports PDF Export
#   URL: /sponsor/analytics/driver-reports/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/driver-reports/pdf", methods=["GET"], endpoint="sponsor_analytics_driver_reports_pdf")
@login_required
def sponsor_analytics_driver_reports_pdf():
    """Generate a PDF version of the Driver Reports with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_status = request.args.get("driver_status", "").strip()
    driver_id = request.args.get("driver_id", "").strip()
    
    qry = (
        db.session.query(Driver, Account, PointChange)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .outerjoin(PointChange, PointChange.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
    )
    
    if driver_status:
        qry = qry.filter(Driver.Status == driver_status)
    if driver_id:
        qry = qry.filter(Driver.DriverID == driver_id)
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
    
    elements.append(Paragraph("Driver Reports", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Company:</b> {sponsor.Company}", styles['Normal']))
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Records:</b> {len(rows)}", styles['Normal']))
    
    filter_info = "Filters: "
    filters = []
    if driver_status:
        filters.append(f"Driver Status: {driver_status}")
    if driver_id:
        driver_obj = Driver.query.get(driver_id)
        if driver_obj:
            driver_account = Account.query.get(driver_obj.AccountID)
            if driver_account:
                filters.append(f"Driver: {driver_account.FirstName} {driver_account.LastName}")
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
    elements.append(Paragraph("Driver Point Changes", heading_style))
    
    if rows:
        small_style = ParagraphStyle(
            'TableContent',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
        )
        
        table_data = [[
            Paragraph('<b>Driver Name</b>', small_style),
            Paragraph('<b>Email</b>', small_style),
            Paragraph('<b>Status</b>', small_style),
            Paragraph('<b>Points Change</b>', small_style),
            Paragraph('<b>Reason</b>', small_style),
            Paragraph('<b>Changed By</b>', small_style),
            Paragraph('<b>Date</b>', small_style)
        ]]
        
        for driver, account, point_change in rows:
            driver_name = f"{account.FirstName} {account.LastName}"
            driver_email = account.Email or "N/A"
            driver_status = driver.Status or "N/A"
            points_change = f"{point_change.DeltaPoints}" if point_change and point_change.DeltaPoints is not None else "N/A"
            reason = point_change.Reason if point_change else 'N/A'
            changed_by = sponsor.Company
            date_str = point_change.CreatedAt.strftime('%m/%d/%Y %H:%M') if point_change and point_change.CreatedAt else "N/A"
            
            driver_name_para = Paragraph(driver_name, small_style)
            email_para = Paragraph(driver_email, small_style)
            reason_para = Paragraph(reason, small_style)
            
            table_data.append([driver_name_para, email_para, driver_status, points_change, reason_para, changed_by, date_str])
        
        # Adjusted column widths: 1.5 + 2.0 + 0.8 + 1.0 + 2.0 + 1.5 + 1.2 = 10.0"
        table = Table(table_data, colWidths=[1.5*inch, 2.0*inch, 0.8*inch, 1.0*inch, 2.0*inch, 1.5*inch, 1.2*inch])
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
        elements.append(Paragraph("No data found for the selected filters.", styles['Normal']))
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=driver_reports_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    
    return response


# -------------------------------------------------------------------
# Sponsor Sales By Report
#   URL: /sponsor/analytics/driver-reports/sales-by
# -------------------------------------------------------------------
@bp.route("/analytics/driver-reports/sales-by", methods=["GET"], endpoint="sponsor_sales_by")
@login_required
def sponsor_sales_by():
    """Sales By report for sponsor's company orders using driver-reports filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    # Get filter parameters (same as driver reports)
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_status = request.args.get("driver_status", "").strip()
    driver_id = request.args.get("driver_id", "").strip()
    status_filter = request.args.get("status_filter", "").strip()
    
    # Get sorting parameters
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")
    
    # Build query for sales data - filter by sponsor's company
    DriverAccount = aliased(Account)
    
    qry = (
        db.session.query(Orders, Driver, DriverAccount)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .filter(Orders.SponsorID == sponsor.SponsorID)
    )
    
    # Apply filtering (same as driver reports)
    if driver_status:
        qry = qry.filter(Driver.Status == driver_status)
    
    if driver_id:
        qry = qry.filter(Driver.DriverID == driver_id)
    
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
    total_points = sum(order.TotalPoints for order, _, _ in orders if order.TotalPoints)
    
    # Calculate total amount with fallback to point-to-dollar conversion
    total_amount = 0
    for order, _, _ in orders:
        if order.TotalAmount and order.TotalAmount > 0:
            total_amount += float(order.TotalAmount)
        else:
            # Fallback: calculate from points using sponsor's rate
            total_amount += float(order.TotalPoints or 0) * float(sponsor.PointToDollarRate)
    
    # Count by status
    status_counts = {}
    for order, _, _ in orders:
        status = order.Status or "Unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
    
    # Get unique order statuses for filter dropdown
    distinct_statuses = (
        db.session.query(Orders.Status)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .filter(Orders.SponsorID == sponsor.SponsorID)
        .distinct()
        .order_by(Orders.Status)
        .all()
    )
    status_list = [status_tuple[0] for status_tuple in distinct_statuses if status_tuple[0]]
    
    # Get all drivers for filter dropdown
    all_drivers = (
        db.session.query(Driver, Account)
        .join(Account, Account.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .order_by(Account.FirstName, Account.LastName)
        .all()
    )
    
    return render_template(
        "sponsor_sales_by.html",
        orders=orders,
        date_from=date_from,
        date_to=date_to,
        driver_status=driver_status,
        driver_id=driver_id,
        status_filter=status_filter,
        all_drivers=all_drivers,
        status_list=status_list,
        sort_by=sort_by,
        sort_order=sort_order,
        total_orders=total_orders,
        total_points=total_points,
        total_amount=total_amount,
        status_counts=status_counts,
        sponsor=sponsor
    )


# -------------------------------------------------------------------
# Sponsor Sales By Report CSV Export
#   URL: /sponsor/analytics/driver-reports/sales-by/csv
# -------------------------------------------------------------------
@bp.route("/analytics/driver-reports/sales-by/csv", methods=["GET"], endpoint="sponsor_sales_by_csv")
@login_required
def sponsor_sales_by_csv():
    """Generate a CSV version of the Sales By report with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    # Get filter parameters (same as sales by report)
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_status = request.args.get("driver_status", "").strip()
    driver_id = request.args.get("driver_id", "").strip()
    status_filter = request.args.get("status_filter", "").strip()
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")
    
    # Build query for sales data (same as sales by report)
    DriverAccount = aliased(Account)
    
    qry = (
        db.session.query(Orders, Driver, DriverAccount)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .filter(Orders.SponsorID == sponsor.SponsorID)
    )
    
    # Apply filtering
    if driver_status:
        qry = qry.filter(Driver.Status == driver_status)
    
    if driver_id:
        qry = qry.filter(Driver.DriverID == driver_id)
    
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
    
    # Generate CSV (using pipe delimiter like admin)
    output = BytesIO()
    
    # Write header
    header = "Order Date|Order Number|Driver|Total Points|Total Amount|Status|Driver Email\n"
    output.write(header.encode('utf-8'))
    
    # Write data rows
    for order, driver, driver_account in orders:
        date_str = order.CreatedAt.strftime('%Y-%m-%d %H:%M') if order.CreatedAt else 'N/A'
        order_num = order.OrderNumber or ''
        driver_name = f"{driver_account.FirstName} {driver_account.LastName}"
        points = order.TotalPoints or 0
        
        if order.TotalAmount and order.TotalAmount > 0:
            amount = float(order.TotalAmount)
        else:
            amount = float(points) * float(sponsor.PointToDollarRate)
        
        status = order.Status or 'Unknown'
        driver_email = driver_account.Email or ''
        
        row = f"{date_str}|{order_num}|{driver_name}|{points}|{amount:.2f}|{status}|{driver_email}\n"
        output.write(row.encode('utf-8'))
    
    # Create response
    output.seek(0)
    response = make_response(output.read())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=sales_by_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response


# -------------------------------------------------------------------
# Sponsor Sales By Report PDF Export
#   URL: /sponsor/analytics/driver-reports/sales-by/pdf
# -------------------------------------------------------------------
@bp.route("/analytics/driver-reports/sales-by/pdf", methods=["GET"], endpoint="sponsor_sales_by_pdf")
@login_required
def sponsor_sales_by_pdf():
    """Generate a PDF version of the Sales By report with current filters."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        return "Access denied: Sponsors only.", 403
    
    # Get filter parameters (same as sales by report)
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    driver_status = request.args.get("driver_status", "").strip()
    driver_id = request.args.get("driver_id", "").strip()
    status_filter = request.args.get("status_filter", "").strip()
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")
    
    # Build query for sales data (same as sales by report)
    DriverAccount = aliased(Account)
    
    qry = (
        db.session.query(Orders, Driver, DriverAccount)
        .join(Driver, Driver.DriverID == Orders.DriverID)
        .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
        .join(DriverSponsor, DriverSponsor.DriverID == Driver.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .filter(Orders.SponsorID == sponsor.SponsorID)
    )
    
    # Apply filtering
    if driver_status:
        qry = qry.filter(Driver.Status == driver_status)
    
    if driver_id:
        qry = qry.filter(Driver.DriverID == driver_id)
    
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
    total_points = sum(order.TotalPoints for order, _, _ in orders if order.TotalPoints)
    
    # Calculate total amount with fallback to point-to-dollar conversion
    total_amount = 0
    for order, _, _ in orders:
        if order.TotalAmount and order.TotalAmount > 0:
            total_amount += float(order.TotalAmount)
        else:
            # Fallback: calculate from points using sponsor's rate
            total_amount += float(order.TotalPoints or 0) * float(sponsor.PointToDollarRate)
    
    # Count by status
    status_counts = {}
    for order, _, _ in orders:
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
    elements.append(Paragraph("Sales By Report", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Report info
    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements.append(Paragraph(f"<b>Company:</b> {sponsor.Company}", styles['Normal']))
    elements.append(Paragraph(f"<b>Generated:</b> {report_date}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Orders:</b> {total_orders}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Points:</b> {total_points:,}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total Amount:</b> ${total_amount:,.2f}", styles['Normal']))
    
    # Add filter information
    filter_info = "Filters: "
    filters = []
    if driver_status:
        filters.append(f"Driver Status: {driver_status}")
    if driver_id:
        driver_obj = Driver.query.get(driver_id)
        if driver_obj:
            driver_account = Account.query.get(driver_obj.AccountID)
            if driver_account:
                filters.append(f"Driver: {driver_account.FirstName} {driver_account.LastName}")
    if status_filter:
        filters.append(f"Order Status: {status_filter}")
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
        # Table header - adapted for sponsor view (no company column)
        table_data = [['Date & Order #', 'Driver', 'Points & Amount', 'Status & Email']]
        
        # Add rows with stacked information
        for order, driver, driver_account in orders:
            # Stack date and order number vertically using Paragraph for line breaks
            date_str = order.CreatedAt.strftime('%m/%d/%Y') if order.CreatedAt else 'N/A'
            order_num = order.OrderNumber or 'N/A'
            date_order = Paragraph(f"{date_str}<br/>{order_num}", styles['Normal'])
            
            # Driver name
            driver_name = f"{driver_account.FirstName} {driver_account.LastName}"
            driver_para = Paragraph(driver_name, styles['Normal'])
            
            # Stack points and amount vertically
            points = f"{order.TotalPoints:,}"
            if order.TotalAmount and order.TotalAmount > 0:
                amount = f"${order.TotalAmount:,.2f}"
            else:
                amount = f"${order.TotalPoints * sponsor.PointToDollarRate:,.2f}"
            points_amount = Paragraph(f"{points}<br/>{amount}", styles['Normal'])
            
            # Stack status and email vertically
            status = order.Status or 'Unknown'
            email = driver_account.Email or 'N/A'
            status_email = Paragraph(f"{status}<br/>{email}", styles['Normal'])
            
            table_data.append([date_order, driver_para, points_amount, status_email])
        
        # Create table with balanced column widths
        # Adjusted to fit landscape letter (11" x 8.5") minus margins (1" total) = 10" usable width
        # Total: 2.2 + 2.5 + 2.2 + 3.1 = 10.0"
        table = Table(table_data, colWidths=[2.2*inch, 2.5*inch, 2.2*inch, 3.1*inch])
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
    response.headers['Content-Disposition'] = f'attachment; filename=sales_by_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
    
    return response


# -------------------------------------------------------------------
# Sponsor Point Settings Audit Log
#   URL: /sponsor/audit-log/point-settings-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/point-settings-changes", methods=["GET"], endpoint="sponsor_audit_point_settings_changes")
@login_required
def sponsor_audit_point_settings_changes():
    """Sponsor's own point settings changes audit log."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    field_filter = request.args.get("field_filter", "").strip()
    sort_order = request.args.get("sort", "desc").strip()
    
    SponsorAccount = aliased(Account)
    ChangedByAccount = aliased(Account)
    
    qry = (
        db.session.query(SponsorProfileAudit, Sponsor, SponsorAccount, ChangedByAccount)
        .join(Sponsor, Sponsor.SponsorID == SponsorProfileAudit.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == SponsorProfileAudit.AccountID)
        .outerjoin(ChangedByAccount, ChangedByAccount.AccountID == SponsorProfileAudit.ChangedByAccountID)
        .filter(SponsorProfileAudit.SponsorID == sponsor.SponsorID)
        .filter(SponsorProfileAudit.FieldName.in_([
            'PointToDollarRate', 'MinPointsPerTxn', 'MaxPointsPerTxn'
        ]))
    )
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(SponsorProfileAudit.ChangedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(SponsorProfileAudit.ChangedAt <= date_to_obj)
        except ValueError:
            pass
    
    if field_filter:
        qry = qry.filter(SponsorProfileAudit.FieldName == field_filter)
    
    if q:
        search_filter = or_(
            SponsorAccount.FirstName.ilike(f"%{q}%"),
            SponsorAccount.LastName.ilike(f"%{q}%"),
            SponsorAccount.Email.ilike(f"%{q}%"),
            SponsorProfileAudit.FieldName.ilike(f"%{q}%"),
            SponsorProfileAudit.OldValue.ilike(f"%{q}%"),
            SponsorProfileAudit.NewValue.ilike(f"%{q}%"),
            SponsorProfileAudit.ChangeReason.ilike(f"%{q}%")
        )
        qry = qry.filter(search_filter)
    
    qry = qry.order_by(SponsorProfileAudit.ChangedAt.asc() if sort_order == "asc" else SponsorProfileAudit.ChangedAt.desc())
    rows = qry.all()
    
    return render_template(
        "sponsor_audit_point_settings_changes.html",
        rows=rows, q=q, date_from=date_from, date_to=date_to,
        field_filter=field_filter, sponsor=sponsor, sort_order=sort_order
    )


# -------------------------------------------------------------------
# Sponsor Profile Changes Audit Log
#   URL: /sponsor/audit-log/profile-changes
# -------------------------------------------------------------------
@bp.route("/audit-log/profile-changes", methods=["GET"], endpoint="sponsor_audit_profile_changes")
@login_required
def sponsor_audit_profile_changes():
    """Sponsor's own profile changes audit log."""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("home.dashboard"))
    
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    field_filter = request.args.get("field_filter", "").strip()
    sort_order = request.args.get("sort", "desc").strip()
    
    SponsorAccount = aliased(Account)
    ChangedByAccount = aliased(Account)
    
    qry = (
        db.session.query(SponsorProfileAudit, Sponsor, SponsorAccount, ChangedByAccount)
        .join(Sponsor, Sponsor.SponsorID == SponsorProfileAudit.SponsorID)
        .join(SponsorAccount, SponsorAccount.AccountID == SponsorProfileAudit.AccountID)
        .outerjoin(ChangedByAccount, ChangedByAccount.AccountID == SponsorProfileAudit.ChangedByAccountID)
        .filter(SponsorProfileAudit.SponsorID == sponsor.SponsorID)
        .filter(~SponsorProfileAudit.FieldName.in_([
            'PointToDollarRate', 'MinPointsPerTxn', 'MaxPointsPerTxn'
        ]))
    )
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d")
            qry = qry.filter(SponsorProfileAudit.ChangedAt >= date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d")
            qry = qry.filter(SponsorProfileAudit.ChangedAt <= date_to_obj)
        except ValueError:
            pass
    
    if field_filter:
        qry = qry.filter(SponsorProfileAudit.FieldName == field_filter)
    
    if q:
        search_filter = or_(
            SponsorAccount.FirstName.ilike(f"%{q}%"),
            SponsorAccount.LastName.ilike(f"%{q}%"),
            SponsorAccount.Email.ilike(f"%{q}%"),
            SponsorProfileAudit.FieldName.ilike(f"%{q}%"),
            SponsorProfileAudit.OldValue.ilike(f"%{q}%"),
            SponsorProfileAudit.NewValue.ilike(f"%{q}%"),
            SponsorProfileAudit.ChangeReason.ilike(f"%{q}%")
        )
        qry = qry.filter(search_filter)
    
    qry = qry.order_by(SponsorProfileAudit.ChangedAt.asc() if sort_order == "asc" else SponsorProfileAudit.ChangedAt.desc())
    rows = qry.all()
    
    return render_template(
        "sponsor_audit_profile_changes.html",
        rows=rows, q=q, date_from=date_from, date_to=date_to,
        field_filter=field_filter, sponsor=sponsor, sort_order=sort_order
    )


# -------------------------------------------------------------------
# Helper functions for bulk import
# -------------------------------------------------------------------
def _get_account_type_code(code: str) -> str:
    """Get account type code"""
    valid_codes = ["DRIVER", "SPONSOR", "ADMIN"]
    if code not in valid_codes:
        raise RuntimeError(f"AccountType '{code}' is not valid. Valid codes: {valid_codes}")
    return code

def _get_account_type_id(code: str) -> str:
    """Resolve AccountTypeID from an AccountType code, creating it if missing"""
    code_norm = _get_account_type_code(code)
    at = AccountType.query.filter_by(AccountTypeCode=code_norm).first()
    if not at:
        at = AccountType(AccountTypeCode=code_norm, DisplayName=code_norm.title())
        db.session.add(at)
        db.session.flush()
    return at.AccountTypeID

def _hash_password(raw: str) -> str:
    """Hash a password"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


# -------------------------------------------------------------------
# Bulk Import Accounts (Sponsor-specific)
# -------------------------------------------------------------------
@bp.route("/bulk-import-accounts", methods=["GET", "POST"], endpoint="bulk_import_accounts")
@login_required
def bulk_import_accounts():
    """Sponsor-only route to bulk import driver and sponsor accounts for their company"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        action = request.form.get("action")
        if action == "bulk_import_accounts":
            csv_file = request.files.get("csv_file")
            
            if not csv_file or not csv_file.filename:
                flash("Please select a pipe-delimited .txt or .csv file to upload.", "danger")
                return redirect(url_for("sponsor.bulk_import_accounts"))
            
            allowed_extensions = ('.txt', '.csv')
            if not csv_file.filename.lower().endswith(allowed_extensions):
                flash("Please upload a pipe-delimited .txt or .csv file.", "danger")
                return redirect(url_for("sponsor.bulk_import_accounts"))
            
            # Get the sponsor's company information
            sponsor_company = sponsor.sponsor_company if sponsor.sponsor_company else None
            if not sponsor_company:
                flash("Error: Sponsor company not found. Please contact support.", "danger")
                return redirect(url_for("dashboard"))
            
            company_name = sponsor_company.CompanyName
            
            # Process pipe-delimited file
            try:
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
                        UploadedByRole="sponsor",
                        SponsorCompanyID=sponsor_company.SponsorCompanyID,
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
                    
                    # Validate row has 5 columns (type, company_ignored, first, last, email)
                    if len(row) != 5:
                        error_count += 1
                        error_msg = f"Invalid format (expected 5 columns, got {len(row)})"
                        errors.append(f"Row {row_num}: {error_msg}")
                        # Log to database
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
                    
                    user_type, _, first_name, last_name, email = [cell.strip() for cell in row]
                    user_type = user_type.upper()
                    
                    # Validate user type and convert to full name
                    if user_type == 'D':
                        account_type_code = 'DRIVER'
                    elif user_type == 'S':
                        account_type_code = 'SPONSOR'
                    else:
                        error_count += 1
                        error_msg = f"Invalid user type '{user_type}'. Only 'D' (Driver) and 'S' (Sponsor) are allowed."
                        errors.append(f"Row {row_num}: {error_msg}")
                        # Log to database
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
                    
                    # Validate required fields (ignore company column)
                    if not user_type or not first_name or not last_name or not email:
                        error_count += 1
                        error_msg = "Missing required fields"
                        errors.append(f"Row {row_num}: {error_msg}")
                        # Log to database
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
                        # Log to database
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
                        # Log to database
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
                        # Generate username from email
                        username = email.split('@')[0].lower()
                        counter = 1
                        original_username = username
                        while Account.query.filter_by(Username=username).first():
                            username = f"{original_username}{counter}"
                            counter += 1
                        
                        # Create Account
                        acc = Account(
                            AccountType=_get_account_type_code(account_type_code),
                            AccountTypeID=_get_account_type_id(account_type_code),
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
                            change_reason='sponsor_bulk_import',
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
                                SponsorCompanyID=sponsor_company.SponsorCompanyID,
                                Status='ACTIVE'
                            )
                            db.session.add(driver)
                            db.session.flush()  # Need DriverID for DriverSponsor
                            
                            # Create DriverSponsor relationship
                            driver_sponsor = DriverSponsor(
                                DriverID=driver.DriverID,
                                SponsorID=sponsor.SponsorID,
                                SponsorCompanyID=sponsor_company.SponsorCompanyID,
                                PointsBalance=0,
                                Status='ACTIVE'
                            )
                            db.session.add(driver_sponsor)
                        
                        elif user_type == 'S':  # Sponsor
                            # All sponsor users are added to this sponsor's company
                            sponsor_user = Sponsor(
                                AccountID=acc.AccountID,
                                Company=company_name,  # Sponsor's company
                                SponsorCompanyID=sponsor_company.SponsorCompanyID,
                                BillingEmail=email,
                                IsAdmin=False
                            )
                            db.session.add(sponsor_user)
                        
                        # Commit this user
                        db.session.commit()
                        success_count += 1
                        
                        # Send verification email
                        try:
                            account_type_label = "driver" if user_type == 'D' else "sponsor"
                            verify_url = url_for("auth.verify_email", token=token, _external=True)
                            msg = Message(
                                subject="Your Driver Rewards Account",
                                recipients=[acc.Email],
                                body=f"""Welcome to Driver Rewards!

Your {account_type_label} account has been created by {company_name}.

Your temporary credentials:
Email: {email}
Password: {default_password}

Please click the link below to verify your email and change your password:
{verify_url}

If you didn't expect this email, please contact support."""
                            )
                            from app.extensions import mail
                            mail.send(msg)
                        except Exception as e:
                            current_app.logger.error(f"Failed to send email to {email}: {str(e)}")
                    
                    except IntegrityError as e:
                        db.session.rollback()
                        error_count += 1
                        error_msg = f"Database error - {str(e)}"
                        errors.append(f"Row {row_num}: {error_msg}")
                        # Log to database
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
                        # Log to database
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
                    flash(f"Successfully imported {success_count} account(s)!", "success")
                if error_count > 0:
                    error_msg = f"Failed to import {error_count} account(s). "
                    if len(errors) <= 5:
                        error_msg += "Errors: " + "; ".join(errors)
                    else:
                        error_msg += f"First 5 errors: {'; '.join(errors[:5])}"
                    flash(error_msg, "warning")
                
                if success_count == 0 and error_count == 0:
                    flash("No valid rows found in CSV file.", "warning")
            
            except Exception as e:
                flash(f"Error reading CSV file: {str(e)}", "danger")
                current_app.logger.error(f"CSV import error: {str(e)}", exc_info=True)
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
    
    return render_template("sponsor/bulk_import_accounts.html", sponsor=sponsor, company_name=sponsor.sponsor_company.CompanyName if sponsor.sponsor_company else "Unknown Company")


# -------------------------------------------------------------------
# Bulk Import Audit Log (Sponsor-only - company filtered)
# -------------------------------------------------------------------
@bp.route("/bulk-import-audit-log", methods=["GET"], endpoint="bulk_import_audit_log")
@login_required
def bulk_import_audit_log():
    """View bulk import logs for sponsor's company only"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get the sponsor's company
    sponsor_company = sponsor.sponsor_company if sponsor.sponsor_company else None
    if not sponsor_company:
        flash("Error: Sponsor company not found.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get filter parameters
    q = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    sort_order = request.args.get("sort", "desc").strip()
    
    # Build query for bulk import logs - ONLY for this company
    qry = (
        db.session.query(BulkImportLog, Account)
        .join(Account, Account.AccountID == BulkImportLog.UploadedByAccountID)
        .filter(BulkImportLog.SponsorCompanyID == sponsor_company.SponsorCompanyID)
    )
    
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
                BulkImportLog.FileName.ilike(like)
            )
        )
    
    # Sorting
    if sort_order == "asc":
        qry = qry.order_by(BulkImportLog.ImportedAt.asc())
    else:
        qry = qry.order_by(BulkImportLog.ImportedAt.desc())
    
    logs = qry.all()
    
    return render_template(
        "sponsor_bulk_import_audit_log.html",
        logs=logs, q=q, date_from=date_from, date_to=date_to, 
        sort_order=sort_order, company_name=sponsor_company.CompanyName
    )


# -------------------------------------------------------------------
# Bulk Import Error Details (Sponsor-only)
# -------------------------------------------------------------------
@bp.route("/bulk-import-errors/<log_id>", methods=["GET"], endpoint="bulk_import_error_details")
@login_required
def bulk_import_error_details(log_id):
    """View detailed errors for a specific bulk import log"""
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Access denied: Sponsors only.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get the sponsor's company
    sponsor_company = sponsor.sponsor_company if sponsor.sponsor_company else None
    if not sponsor_company:
        flash("Error: Sponsor company not found.", "danger")
        return redirect(url_for("dashboard"))
    
    # Get the log - ensure it belongs to this company
    bulk_log = BulkImportLog.query.filter_by(
        BulkImportLogID=log_id,
        SponsorCompanyID=sponsor_company.SponsorCompanyID
    ).first()
    
    if not bulk_log:
        flash("Import log not found or access denied.", "danger")
        return redirect(url_for("sponsor.bulk_import_audit_log"))
    
    # Get errors for this log
    errors = BulkImportError.query.filter_by(BulkImportLogID=log_id).order_by(BulkImportError.RowNumber.asc()).all()
    
    return render_template(
        "sponsor_bulk_import_errors.html",
        bulk_log=bulk_log,
        errors=errors,
        company_name=sponsor_company.CompanyName
    )
