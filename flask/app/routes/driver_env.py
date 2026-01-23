# app/routes/driver_env.py
from __future__ import annotations
from flask import Blueprint, jsonify, session, request, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.models import Driver, DriverSponsor, Sponsor

bp = Blueprint("driver_env", __name__, url_prefix="/driver-env")


def _require_authenticated_account_id() -> str:
    """Return the logged-in AccountID (string per Flask-Login), or 401."""
    if not getattr(current_user, "is_authenticated", False):
        abort(401)
    return current_user.get_id()


def _resolve_driver_id() -> str | None:
    """
    Get the current driver's DriverID.
    Prefer the session (set at login or on env switch), then fall back to finding
    a Driver via AccountID (assuming one driver per account).

    NOTE: IDs in this app are UUID strings (CHAR/VARCHAR), so do NOT cast to int.
    """
    # Best: session
    driver_id = session.get("driver_id")
    if driver_id:
        return str(driver_id)

    # Fallback: lookup by AccountID
    acct_id = _require_authenticated_account_id()
    drv = Driver.query.filter(Driver.AccountID == acct_id).first()
    return str(drv.DriverID) if drv else None


@bp.get("/list", endpoint="list")
@login_required
def list_envs():
    """
    List all DriverSponsor environments available to the current driver.

    Optional query param:
      - only=active   -> return only ACTIVE environments
    """
    driver_id = _resolve_driver_id()
    if not driver_id:
        abort(404, description="No driver profile found for the current account.")

    only = (request.args.get("only") or "").strip().lower()
    active_only = (only == "active")

    q = (
        DriverSponsor.query
        .options(joinedload(DriverSponsor.sponsor))  # e.sponsor relation
        .filter(DriverSponsor.DriverID == driver_id)
        .order_by(DriverSponsor.DriverSponsorID.asc())
    )
    envs = q.all()

    selected_env_id = session.get("driver_sponsor_id")
    out = []
    for e in envs:
        status = (e.Status or "PENDING").strip().upper()
        if active_only and status != "ACTIVE":
            continue
        out.append({
            "driverSponsorId": e.DriverSponsorID,  # UUID string
            "driverId": e.DriverID,                # UUID string
            "sponsorId": e.SponsorID,              # UUID string
            "sponsorName": (e.sponsor.Company if getattr(e, "sponsor", None) else f"Sponsor {e.SponsorID}"),
            "points": int(e.PointsBalance or 0),
            "status": status,
            "isSelected": (selected_env_id == e.DriverSponsorID),
        })
    return jsonify(out)


@bp.post("/switch", endpoint="switch")
@login_required
def switch_env():
    """
    Switch current environment by DriverSponsorID.
    Accepts JSON, form-encoded, or querystring:
      - driverSponsorId (camelCase)
      - driver_sponsor_id (snake_case)
    Validates that the env belongs to the logged-in driver AND is ACTIVE.
    """
    driver_id = _resolve_driver_id()
    if not driver_id:
        abort(404, description="No driver profile found for the current account.")

    data = request.get_json(silent=True) or {}
    raw_env_id = (
        data.get("driverSponsorId")
        or request.form.get("driverSponsorId")
        or request.form.get("driver_sponsor_id")
        or request.args.get("driverSponsorId")
        or request.args.get("driver_sponsor_id")
    )
    if not raw_env_id:
        abort(400, description="driverSponsorId is required")

    # IDs are UUID strings; keep as string (no int cast)
    env_id = str(raw_env_id).strip()

    # Must belong to the current driver
    env = (
        DriverSponsor.query
        .options(joinedload(DriverSponsor.sponsor))
        .filter(
            DriverSponsor.DriverSponsorID == env_id,  # UUID string compare
            DriverSponsor.DriverID == driver_id       # UUID string compare
        )
        .first()
    )
    if not env:
        abort(404, description="Environment not found for this driver.")

    # Only allow switching into ACTIVE environments
    status = (env.Status or "").strip().upper()
    if status != "ACTIVE":
        abort(403, description="Environment is not ACTIVE.")

    # Commit to session (preserve UUID string types)
    session["driver_sponsor_id"] = str(env.DriverSponsorID)
    session["driver_id"] = str(env.DriverID)
    session["sponsor_id"] = str(env.SponsorID)  # convenience for UI pieces that need sponsor_id
    # NEW: store company name so the navbar can display it for drivers
    session["sponsor_company"] = env.sponsor.Company if getattr(env, "sponsor", None) else None
    session["driver_env_selection_pending"] = False

    # Handle different request types
    if request.is_json or request.content_type == 'application/json':
        return jsonify({
            "ok": True,
            "driverSponsorId": env.DriverSponsorID,
            "sponsorId": env.SponsorID,
            "sponsorName": env.sponsor.Company if getattr(env, "sponsor", None) else f"Sponsor {env.SponsorID}",
            "status": status,
        })
    else:
        # Form submission - redirect back to dashboard
        from flask import redirect, url_for
        return redirect(url_for("dashboard"))


@bp.get("/current-points", endpoint="current_points")
@login_required
def current_points():
    env_id = session.get("driver_sponsor_id")
    if not env_id:
        return jsonify({"points": 0})

    env = DriverSponsor.query.filter_by(DriverSponsorID=env_id).first()
    return jsonify({"points": int(env.PointsBalance) if env and env.PointsBalance is not None else 0})
