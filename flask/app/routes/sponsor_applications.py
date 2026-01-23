# app/routes/sponsor_applications.py
from __future__ import annotations
from datetime import datetime
import json

from flask import Blueprint, render_template, request, redirect, url_for, abort, flash
from flask_login import login_required, current_user
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Account, Sponsor, Application, Driver, DriverSponsor

bp = Blueprint(
    "sponsor_apps",
    __name__,
    url_prefix="/sponsor/apps",
    template_folder="../templates",
)

def _require_sponsor() -> int:
    if not getattr(current_user, "is_authenticated", False):
        abort(401)
    acct_id = current_user.get_id()
    sponsor = Sponsor.query.filter_by(AccountID=acct_id).first()
    if not sponsor:
        abort(403)
    return sponsor.SponsorID

def _attach_accounts(apps: list[Application]) -> None:
    """Attach .account to each Application so templates can use a.account.FirstName, etc."""
    if not apps:
        return
    ids = {a.AccountID for a in apps if getattr(a, "AccountID", None)}
    if not ids:
        return
    acct_map = {a.AccountID: a for a in Account.query.filter(Account.AccountID.in_(ids)).all()}
    for app in apps:
        try:
            app.account = acct_map.get(app.AccountID)  # dynamic attribute for template access
        except Exception:
            pass


def _approve_application(app_obj: Application, reviewer_account_id: int, note: str | None):
    now = datetime.utcnow()
    app_obj.ReviewedAt = now
    app_obj.DecisionByAccountID = reviewer_account_id
    app_obj.DecisionReason = note
    app_obj.Decision = "accepted"

    sponsor = Sponsor.query.filter_by(SponsorID=app_obj.SponsorID).first()
    if not sponsor or not sponsor.SponsorCompanyID:
        raise ValueError("Sponsor record is misconfigured for application approval.")

    # ONE Driver per AccountID (no SponsorID/PointsBalance on Driver)
    drv = Driver.query.filter_by(AccountID=app_obj.AccountID).first()
    if not drv:
        drv = Driver(
            AccountID=app_obj.AccountID,
            Status="ACTIVE",
        )
        db.session.add(drv)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            drv = Driver.query.filter_by(AccountID=app_obj.AccountID).first()
    else:
        drv.Status = "ACTIVE"

    if sponsor.SponsorCompanyID:
        drv.SponsorCompanyID = sponsor.SponsorCompanyID

    # Ensure/upgrade per-sponsor join to ACTIVE
    env = DriverSponsor.query.filter_by(DriverID=drv.DriverID, SponsorID=app_obj.SponsorID).first()
    if not env:
        env = DriverSponsor(
            DriverID=drv.DriverID,
            SponsorID=app_obj.SponsorID,
            SponsorCompanyID=sponsor.SponsorCompanyID,
            PointsBalance=0,
            Status="ACTIVE",
        )
        db.session.add(env)
    else:
        env.Status = "ACTIVE"
        if not env.SponsorCompanyID:
            env.SponsorCompanyID = sponsor.SponsorCompanyID

    # Activate the account
    acct = Account.query.get(app_obj.AccountID)
    if acct:
        acct.Status = "a"

    # Notify driver about approval
    try:
        from app.services.notification_service import NotificationService
        NotificationService.notify_application_decision(app_obj.ApplicationID, "accepted", note)
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Failed to send approval notification: {str(e)}")


def _reject_application(app_obj: Application, reviewer_account_id: int, note: str | None):
    now = datetime.utcnow()
    app_obj.ReviewedAt = now
    app_obj.DecisionByAccountID = reviewer_account_id
    app_obj.DecisionReason = note
    app_obj.Decision = "rejected"

    sponsor = Sponsor.query.filter_by(SponsorID=app_obj.SponsorID).first()
    if not sponsor or not sponsor.SponsorCompanyID:
        raise ValueError("Sponsor record is misconfigured for application rejection.")

    acct = Account.query.get(app_obj.AccountID)
    if acct:
        acct.Status = "i"  # inactive (or 'p' if you prefer pending)

    # Reuse the single Driver by AccountID and mark env REJECTED
    drv = Driver.query.filter_by(AccountID=app_obj.AccountID).first()
    if drv:
        if sponsor.SponsorCompanyID and drv.SponsorCompanyID != sponsor.SponsorCompanyID:
            drv.SponsorCompanyID = sponsor.SponsorCompanyID
        env = DriverSponsor.query.filter_by(DriverID=drv.DriverID, SponsorID=app_obj.SponsorID).first()
        if not env:
            env = DriverSponsor(
                DriverID=drv.DriverID,
                SponsorID=app_obj.SponsorID,
                SponsorCompanyID=sponsor.SponsorCompanyID,
                PointsBalance=0,
                Status="REJECTED",
            )
            db.session.add(env)
        else:
            env.Status = "REJECTED"
            if not env.SponsorCompanyID:
                env.SponsorCompanyID = sponsor.SponsorCompanyID

    # Notify driver about rejection
    try:
        from app.services.notification_service import NotificationService
        NotificationService.notify_application_decision(app_obj.ApplicationID, "rejected", note)
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Failed to send rejection notification: {str(e)}")


@bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    sponsor_id = _require_sponsor()

    pending = (
        db.session.query(Application)
        .filter(and_(Application.SponsorID == sponsor_id, Application.ReviewedAt.is_(None)))
        .order_by(Application.SubmittedAt.desc())
        .all()
    )
    recent = (
        db.session.query(Application)
        .filter(and_(Application.SponsorID == sponsor_id, Application.ReviewedAt.is_not(None)))
        .order_by(Application.ReviewedAt.desc())
        .limit(50)
        .all()
    )

    # Attach related accounts so the template can use a.account.*
    _attach_accounts(pending)
    _attach_accounts(recent)

    return render_template("sponsor/apps/index.html", pending=pending, recent=recent)


# Detail page used by templates: url_for('sponsor_apps.show', app_id=...)
@bp.route("/<int:app_id>", methods=["GET"], endpoint="show")
@login_required
def show(app_id: int):
    sponsor_id = _require_sponsor()
    app_obj = (
        Application.query
        .filter(Application.ApplicationID == app_id, Application.SponsorID == sponsor_id)
        .first()
    )
    if not app_obj:
        abort(404)

    # Attach .account for this one object as well
    try:
        app_obj.account = Account.query.get(app_obj.AccountID)
    except Exception:
        pass

    # Always provide a JSON-serializable incidents payload for templates using |tojson
    incidents = app_obj.IncidentsJSON
    try:
        if isinstance(incidents, str):
            incidents = json.loads(incidents) if incidents.strip() else {}
        elif incidents is None:
            incidents = {}
    except Exception:
        incidents = {}

    # Pass BOTH names to satisfy templates that use `app` or `app_obj`
    return render_template(
        "sponsor/apps/show.html",
        app=app_obj,
        app_obj=app_obj,
        incidents=incidents,
    )


# Explicit endpoint so url_for('sponsor_apps.bulk') resolves
@bp.route("/bulk", methods=["POST"], endpoint="bulk")
@login_required
def bulk():
    """Bulk approve/reject selected applications for the current sponsor."""
    sponsor_id = _require_sponsor()

    action = (request.form.get("action") or "").strip().lower()  # "approve" | "reject"
    ids = request.form.getlist("app_id")                          # checkboxes named app_id
    note = request.form.get("note")                               # optional reviewer note

    if not ids:
        flash("No applications selected.", "info")
        return redirect(url_for("sponsor_apps.index"))

    try:
        id_list = [int(x) for x in ids]
    except ValueError:
        flash("Invalid application id(s).", "danger")
        return redirect(url_for("sponsor_apps.index"))

    apps = (
        Application.query
        .filter(Application.SponsorID == sponsor_id,
                Application.ApplicationID.in_(id_list))
        .all()
    )

    processed = 0
    reviewer_id = current_user.get_id()

    for app_obj in apps:
        if app_obj.ReviewedAt is not None:
            continue
        if action == "approve":
            _approve_application(app_obj, reviewer_id, note)
            processed += 1
        elif action == "reject":
            _reject_application(app_obj, reviewer_id, note)
            processed += 1

    db.session.commit()
    flash(f"Processed {processed} application(s).", "success")
    return redirect(url_for("sponsor_apps.index"))


# New single-app decision endpoint used by templates: url_for('sponsor_apps.decide', app_id=...)
@bp.route("/<int:app_id>/decide", methods=["POST"], endpoint="decide")
@login_required
def decide(app_id: int):
    """Approve or reject a single application from its detail page."""
    sponsor_id = _require_sponsor()

    action = (request.form.get("action") or "").strip().lower()  # "approve" | "reject"
    note = request.form.get("note")

    app_obj = (
        Application.query
        .filter(Application.ApplicationID == app_id, Application.SponsorID == sponsor_id)
        .first()
    )
    if not app_obj:
        abort(404)

    if app_obj.ReviewedAt is not None:
        flash("This application has already been reviewed.", "info")
        return redirect(url_for("sponsor_apps.show", app_id=app_id))

    reviewer_id = current_user.get_id()
    if action == "approve":
        _approve_application(app_obj, reviewer_id, note)
        msg = "Application approved."
    elif action == "reject":
        _reject_application(app_obj, reviewer_id, note)
        msg = "Application rejected."
    else:
        flash("Unknown action.", "danger")
        return redirect(url_for("sponsor_apps.show", app_id=app_id))

    db.session.commit()
    flash(msg, "success")
    return redirect(url_for("sponsor_apps.index"))
