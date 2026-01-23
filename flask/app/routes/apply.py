# app/routes/apply.py
from __future__ import annotations
from datetime import datetime
import json

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Account, AccountType, Sponsor, SponsorCompany, Application, Driver, DriverSponsor
from app.utils.sponsor_selection import select_primary_sponsor_for_company

bp = Blueprint("apply", __name__)

def _is_driver(account_id: str) -> bool:
    acct = Account.query.filter_by(AccountID=account_id).first()
    if not acct:
        return False
    # Now we can directly check the AccountType column
    account_type = (acct.AccountType or "").upper()
    return account_type == "DRIVER"


@bp.route("/apply", methods=["GET"], endpoint="apply_form")
@login_required
def apply_form():
    """Render the driver application form (no single-app blocking)."""
    if not _is_driver(current_user.get_id()):
        flash("Only drivers can submit applications.", "danger")
        return redirect(url_for("dashboard"))

    sponsor_companies = (
        SponsorCompany.query.filter(SponsorCompany.sponsors.any())
        .order_by(SponsorCompany.CompanyName.asc())
        .all()
    )
    # (Optional) show the driver’s prior apps for context
    my_apps = (
        Application.query
        .filter_by(AccountID=current_user.get_id())
        .order_by(Application.SubmittedAt.desc())
        .all()
    )
    sponsor_lookup = {}
    if my_apps:
        sponsor_ids = {app.SponsorID for app in my_apps if app.SponsorID}
        if sponsor_ids:
            sponsors = Sponsor.query.filter(Sponsor.SponsorID.in_(sponsor_ids)).all()
            for sponsor in sponsors:
                sponsor_lookup[sponsor.SponsorID] = (
                    sponsor.sponsor_company.CompanyName
                    if sponsor.sponsor_company and sponsor.sponsor_company.CompanyName
                    else sponsor.Company
                )

    pending_apps = [
        {
            "application": app,
            "sponsor_name": sponsor_lookup.get(app.SponsorID, "Unknown sponsor"),
        }
        for app in my_apps
        if app.ReviewedAt is None
    ]
    return render_template(
        "driver/apply.html",
        sponsor_companies=sponsor_companies,
        my_apps=my_apps,
        pending_apps=pending_apps,
    )


@bp.route("/apply", methods=["POST"], endpoint="apply_submit")
@login_required
def apply_submit():
    """Accept a driver application, and ensure a DriverSponsor row is created/updated to PENDING."""
    if not _is_driver(current_user.get_id()):
        flash("Only drivers can submit applications.", "danger")
        return redirect(url_for("dashboard"))

    f = request.form

    # required
    sponsor_company_id = (f.get("SponsorCompanyID") or "").strip()
    if not sponsor_company_id:
        flash("Please choose the sponsor company you are applying to.", "danger")
        return redirect(url_for("apply.apply_form"))

    # If the driver already has a pending application to THIS sponsor, show its status
    sponsor = select_primary_sponsor_for_company(sponsor_company_id)
    if not sponsor or not sponsor.SponsorCompanyID:
        raise ValueError("Selected sponsor company is misconfigured. Please contact support.")

    existing_pending = (
        Application.query
        .filter_by(AccountID=current_user.get_id(), SponsorID=sponsor.SponsorID)
        .filter(Application.ReviewedAt.is_(None))
        .first()
    )
    if existing_pending:
        # Reuse the status page behavior the old route used
        return render_template("driver/apply_status.html", app=existing_pending)

    # core fields
    cdl_class    = (f.get("CDLClass") or "").strip().upper() or None
    exp_years    = int(f.get("ExperienceYears") or 0)
    exp_months   = int(f.get("ExperienceMonths") or 0)
    transmission = (f.get("Transmission") or "").strip().upper() or None
    pref_hours   = int(f.get("PreferredWeeklyHours") or 0)
    viols_3y     = int(f.get("ViolationsCount3Y") or 0)

    # JSON: accidents + extra notes/flags assembled by the form’s JS
    incidents_json_str = f.get("IncidentsJSON") or "{}"
    try:
        incidents = json.loads(incidents_json_str)
    except Exception:
        incidents = {}

    susp_5y     = (f.get("Suspensions5Y") == "1")
    susp_detail = (f.get("SuspensionsDetail") or "").strip() or None
    consent     = (f.get("ConsentedDataUse") == "1")
    agreed      = (f.get("AgreedTerms") == "1")
    esig        = (f.get("ESignature") or "").strip() or None
    esigned_at  = datetime.utcnow() if esig else None

    # 1) Create the Application row (same as before except no global single-app gate)
    app_row = Application(
        AccountID=current_user.get_id(),
        SponsorID=sponsor.SponsorID,
        CDLClass=cdl_class if cdl_class in {"A", "B", "C"} else None,
        ExperienceYears=exp_years,
        ExperienceMonths=exp_months,
        Transmission=transmission if transmission in {"AUTOMATIC", "MANUAL"} else None,
        PreferredWeeklyHours=pref_hours,
        ViolationsCount3Y=viols_3y,
        IncidentsJSON=incidents,
        Suspensions5Y=susp_5y,
        SuspensionsDetail=susp_detail,
        ConsentedDataUse=consent,
        AgreedTerms=agreed,
        ESignature=esig,
        ESignedAt=esigned_at,
        SubmittedAt=datetime.utcnow(),
    )
    db.session.add(app_row)
    db.session.flush()  # we don't need the key immediately, but safe for consistency

    # 2) Ensure ONE Driver exists per AccountID (no longer has SponsorID or PointsBalance).
    #    Reuse if present; otherwise create a single global Driver row for the account.
    account_id = current_user.get_id()
    drv = Driver.query.filter_by(AccountID=account_id).first()
    if not drv:
        drv = Driver(
            AccountID=account_id,
            Status="PENDING",   # keep out of ACTIVE driver flows until sponsor approves
        )
        db.session.add(drv)
        try:
            db.session.flush()  # need DriverID for DriverSponsor
        except IntegrityError:
            # If created concurrently in another txn, reload and reuse
            db.session.rollback()
            drv = Driver.query.filter_by(AccountID=account_id).first()
    # Track the driver's company affiliation
    if sponsor.SponsorCompanyID:
        drv.SponsorCompanyID = sponsor.SponsorCompanyID

    # 3) Ensure DriverSponsor join exists and reflects application lifecycle = PENDING
    env = DriverSponsor.query.filter_by(DriverID=drv.DriverID, SponsorID=sponsor.SponsorID).first()
    if not env:
        env = DriverSponsor(
            DriverID=drv.DriverID,
            SponsorID=sponsor.SponsorID,
            SponsorCompanyID=sponsor.SponsorCompanyID,
            PointsBalance=0,
            Status="PENDING",
        )
        db.session.add(env)
    else:
        # If it's previously REJECTED/WITHDRAWN and they re-apply, flip it back to PENDING
        if str(env.Status or "").upper() != "ACTIVE":
            env.Status = "PENDING"
        if not env.SponsorCompanyID:
            env.SponsorCompanyID = sponsor.SponsorCompanyID

    db.session.commit()

    # --- Notifications (from main) ---
    try:
        from app.services.notification_service import NotificationService

        # Notify the sponsor about the new application
        NotificationService.notify_sponsor_new_application(app_row.ApplicationID)

        # Send confirmation to the driver
        NotificationService.notify_driver_application_received(app_row.ApplicationID)

    except Exception as e:
        # Log error but don't fail the application submission
        from flask import current_app
        current_app.logger.error(f"Failed to send application notifications: {str(e)}")

    sponsor_company_name = sponsor.sponsor_company.CompanyName if sponsor.sponsor_company else "the selected sponsor"
    flash(f"Thank you for applying to {sponsor_company_name}!", "success")
    return redirect(url_for("apply.apply_form", _anchor="application-top"))
