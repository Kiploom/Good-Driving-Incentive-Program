from datetime import datetime
import uuid

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user, login_required

from app.decorators.session_security import require_role
from app.models import (
    Account,
    AccountDeactivationRequest,
    Driver,
    DriverSponsor,
    Sponsor,
    db,
)

bp = Blueprint("account_deactivation", __name__, url_prefix="/deactivation")

REASON_CHOICES = [
    ("no_longer_needed", "I no longer need the account"),
    ("switching", "I'm switching organizations"),
    ("privacy", "I have privacy or security concerns"),
    ("other", "Other"),
]
REASON_MAP = dict(REASON_CHOICES)

STATUS_LABELS = {
    "pending": "Pending",
    "approved": "Approved",
    "denied": "Denied",
    "cancelled": "Cancelled",
}


def _get_current_account() -> Account | None:
    return Account.query.get(current_user.AccountID)


def _format_request_payload(req: AccountDeactivationRequest, include_account: bool = False) -> dict:
    data = {
        "request": req,
        "reason": REASON_MAP.get((req.ReasonCode or "").lower(), req.ReasonCode or "Unknown"),
        "status_label": STATUS_LABELS.get((req.Status or "").lower(), req.Status or "Unknown"),
    }
    if include_account and req.account:
        acct = req.account
        display_name = acct.WholeName or acct.Username or acct.Email or acct.AccountID
        data.update(
            {
                "account": acct,
                "account_display": display_name,
                "account_email": acct.Email,
                "account_role": acct.AccountType,
            }
        )
    return data


@bp.route("/account", methods=["GET", "POST"])
@login_required
def request_page():
    account = _get_current_account()
    if not account:
        flash("Account not found.", "error")
        return redirect(url_for("dashboard"))

    existing_requests = (
        AccountDeactivationRequest.query.filter_by(AccountID=account.AccountID)
        .order_by(AccountDeactivationRequest.CreatedAt.desc())
        .all()
    )

    if request.method == "POST":
        action = request.form.get("action", "").lower()
        if action == "submit":
            if (account.Status or "").upper() == "I":
                flash("Your account is already inactive.", "info")
                return redirect(url_for("account_deactivation.request_page"))

            pending = next((req for req in existing_requests if req.is_pending), None)
            if pending:
                flash("You already have a pending deactivation request.", "warning")
                return redirect(url_for("account_deactivation.request_page"))

            reason_code = (request.form.get("reason_code") or "").strip()
            if not reason_code:
                flash("Please choose a reason for deactivation.", "error")
                return redirect(url_for("account_deactivation.request_page"))

            reason_details = (request.form.get("reason_details") or "").strip()
            new_request = AccountDeactivationRequest(
                RequestID=str(uuid.uuid4()),
                AccountID=account.AccountID,
                ReasonCode=reason_code,
                ReasonDetails=reason_details,
                Status="pending",
                CreatedAt=datetime.utcnow(),
                UpdatedAt=datetime.utcnow(),
            )
            db.session.add(new_request)
            db.session.commit()
            flash("Your deactivation request has been submitted.", "success")
            return redirect(url_for("account_deactivation.request_page"))

        if action == "cancel":
            pending = next((req for req in existing_requests if req.is_pending), None)
            if not pending:
                flash("There is no pending request to cancel.", "warning")
                return redirect(url_for("account_deactivation.request_page"))

            pending.Status = "cancelled"
            pending.ProcessedByAccountID = current_user.AccountID
            pending.ProcessedAt = datetime.utcnow()
            pending.UpdatedAt = datetime.utcnow()
            db.session.commit()
            flash("Your pending request has been cancelled.", "success")
            return redirect(url_for("account_deactivation.request_page"))

    payload_requests = [_format_request_payload(req) for req in existing_requests]
    return render_template(
        "account_deactivation.html",
        account=account,
        reason_choices=REASON_CHOICES,
        requests=payload_requests,
    )


@bp.route("/admin", methods=["GET"])
@login_required
@require_role(["admin"])
def admin_list():
    status_filter = (request.args.get("status") or "").strip().lower()
    query = AccountDeactivationRequest.query.order_by(AccountDeactivationRequest.CreatedAt.desc())
    if status_filter:
        query = query.filter(AccountDeactivationRequest.Status == status_filter)

    requests = [_format_request_payload(req, include_account=True) for req in query.all()]
    return render_template(
        "admin_deactivation_requests.html",
        requests=requests,
        status_filter=status_filter,
        status_labels=STATUS_LABELS,
    )


@bp.route("/admin/<request_id>/decision", methods=["POST"])
@login_required
@require_role(["admin"])
def admin_decide(request_id: str):
    decision = request.form.get("decision", "").lower()
    notes = (request.form.get("decision_notes") or "").strip()

    req = AccountDeactivationRequest.query.get(request_id)
    if not req:
        flash("Request not found.", "error")
        return redirect(url_for("account_deactivation.admin_list"))
    if not req.is_pending:
        flash("This request has already been processed.", "warning")
        return redirect(url_for("account_deactivation.admin_list"))

    account = req.account
    if not account:
        flash("Associated account could not be found.", "error")
        return redirect(url_for("account_deactivation.admin_list"))

    if decision not in {"approve", "deny"}:
        flash("Invalid decision.", "error")
        return redirect(url_for("account_deactivation.admin_list"))

    if req.AccountID == current_user.AccountID:
        flash("You cannot process your own deactivation request.", "error")
        return redirect(url_for("account_deactivation.admin_list"))

    if decision == "approve":
        account.Status = "I"
        account.UpdatedAt = datetime.utcnow()
        req.Status = "approved"
    else:
        req.Status = "denied"

    req.DecisionNotes = notes
    req.ProcessedByAccountID = current_user.AccountID
    req.ProcessedAt = datetime.utcnow()
    req.UpdatedAt = datetime.utcnow()

    db.session.commit()
    flash("Request processed successfully.", "success")
    return redirect(url_for("account_deactivation.admin_list"))


@bp.route("/sponsor", methods=["GET"])
@login_required
@require_role(["sponsor"])
def sponsor_list():
    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Sponsor profile not found.", "error")
        return redirect(url_for("dashboard"))

    driver_subquery = (
        db.session.query(Driver.DriverID)
        .join(DriverSponsor, Driver.DriverID == DriverSponsor.DriverID)
        .filter(DriverSponsor.SponsorID == sponsor.SponsorID)
        .subquery()
    )

    requests = (
        AccountDeactivationRequest.query
        .join(Account, AccountDeactivationRequest.AccountID == Account.AccountID)
        .join(Driver, Driver.AccountID == Account.AccountID)
        .filter(Driver.DriverID.in_(driver_subquery))
        .order_by(AccountDeactivationRequest.CreatedAt.desc())
        .all()
    )

    payloads = [_format_request_payload(req, include_account=True) for req in requests]
    return render_template(
        "sponsor_deactivation_requests.html",
        requests=payloads,
        status_labels=STATUS_LABELS,
    )


@bp.route("/sponsor/<request_id>/decision", methods=["POST"])
@login_required
@require_role(["sponsor"])
def sponsor_decide(request_id: str):
    decision = request.form.get("decision", "").lower()
    notes = (request.form.get("decision_notes") or "").strip()

    sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
    if not sponsor:
        flash("Sponsor profile not found.", "error")
        return redirect(url_for("account_deactivation.sponsor_list"))

    req = AccountDeactivationRequest.query.get(request_id)
    if not req:
        flash("Request not found.", "error")
        return redirect(url_for("account_deactivation.sponsor_list"))
    if not req.is_pending:
        flash("This request has already been processed.", "warning")
        return redirect(url_for("account_deactivation.sponsor_list"))

    account = req.account
    if not account:
        flash("Associated account not found.", "error")
        return redirect(url_for("account_deactivation.sponsor_list"))

    driver = Driver.query.filter_by(AccountID=account.AccountID).first()
    if not driver:
        flash("This request does not belong to a driver account.", "error")
        return redirect(url_for("account_deactivation.sponsor_list"))

    # Ensure driver belongs to sponsor
    allowed = DriverSponsor.query.filter_by(DriverID=driver.DriverID, SponsorID=sponsor.SponsorID).first()
    if not allowed:
        flash("You may only process requests for your own drivers.", "error")
        return redirect(url_for("account_deactivation.sponsor_list"))

    if decision not in {"approve", "deny"}:
        flash("Invalid decision.", "error")
        return redirect(url_for("account_deactivation.sponsor_list"))

    if req.AccountID == current_user.AccountID:
        flash("You cannot process your own deactivation request.", "error")
        return redirect(url_for("account_deactivation.sponsor_list"))

    if decision == "approve":
        account.Status = "I"
        account.UpdatedAt = datetime.utcnow()
        req.Status = "approved"
    else:
        req.Status = "denied"

    req.DecisionNotes = notes
    req.ProcessedByAccountID = current_user.AccountID
    req.ProcessedAt = datetime.utcnow()
    req.UpdatedAt = datetime.utcnow()

    db.session.commit()
    flash("Request processed successfully.", "success")
    return redirect(url_for("account_deactivation.sponsor_list"))
