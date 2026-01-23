from flask import Blueprint, render_template, session, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from app.models import db, Driver, DriverSponsor, Sponsor, Account

bp = Blueprint("leaderboard", __name__)


@bp.route("/leaderboard", methods=["GET"], endpoint="view")
@login_required
def view():
    role = None
    if session.get("admin_id"):
        role = "admin"
    elif session.get("driver_id"):
        role = "driver"
    elif session.get("sponsor_id"):
        role = "sponsor"

    sponsor_filter = None
    page_title = "Driver Leaderboard"
    scope_message = None
    action_url = None

    def _as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    if role == "sponsor":
        sponsor_record = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
        if sponsor_record:
            sponsor_filter = sponsor_record.SponsorID
            page_title = f"{sponsor_record.Company} Driver Leaderboard"
            scope_message = f"Showing drivers for {sponsor_record.Company}"
    elif role == "driver":
        sponsor_record = None
        driver_sponsor_id = session.get("driver_sponsor_id")
        driver_id = session.get("driver_id")

        if driver_sponsor_id and driver_id:
            env_row = (
                db.session.query(DriverSponsor, Sponsor)
                .join(Sponsor, Sponsor.SponsorID == DriverSponsor.SponsorID)
                .filter(
                    DriverSponsor.DriverSponsorID == driver_sponsor_id,
                    DriverSponsor.DriverID == driver_id,
                )
                .first()
            )
            if env_row:
                sponsor_record = env_row[1]

        if sponsor_record is None:
            sponsor_id = _as_int(session.get("sponsor_id"))
            if sponsor_id:
                sponsor_record = Sponsor.query.filter_by(SponsorID=sponsor_id).first()

        if sponsor_record:
            sponsor_filter = sponsor_record.SponsorID
            page_title = f"{sponsor_record.Company} Leaderboard"
            scope_message = f"Showing drivers for {sponsor_record.Company}"
        else:
            page_title = "Sponsor Leaderboard"
            scope_message = "Select a sponsor environment to view its leaderboard."
            action_url = url_for("driver.select_environment_page")
    elif role == "admin":
        page_title = "Global Driver Leaderboard"

    if role == "driver" and sponsor_filter is None:
        return render_template(
            "leaderboard.html",
            leaderboard=[],
            page_title=page_title,
            scope_message=scope_message,
            role=role,
            action_url=action_url,
        )

    # Sum points across environments (optionally scoped to a sponsor)
    totals_query = db.session.query(
        DriverSponsor.DriverID.label("driver_id"),
        func.coalesce(func.sum(DriverSponsor.PointsBalance), 0).label("total_points")
    )

    if sponsor_filter is not None:
        totals_query = totals_query.filter(DriverSponsor.SponsorID == sponsor_filter)

    totals_subq = totals_query.group_by(DriverSponsor.DriverID).subquery()

    env_query = db.session.query(
        DriverSponsor.DriverID.label("driver_id"),
        DriverSponsor.SponsorID.label("sponsor_id"),
        func.row_number().over(
            partition_by=DriverSponsor.DriverID,
            order_by=DriverSponsor.PointsBalance.desc()
        ).label("rn")
    )

    if sponsor_filter is not None:
        env_query = env_query.filter(DriverSponsor.SponsorID == sponsor_filter)

    top_env_subq = env_query.subquery()

    rows = (
        db.session.query(
            totals_subq.c.total_points,
            Driver.DriverID,
            Account.Username,
            Account.ProfileImageURL,
            Sponsor.Company.label("SponsorCompany"),
        )
        .join(Driver, Driver.DriverID == totals_subq.c.driver_id)
        .join(Account, Account.AccountID == Driver.AccountID)
        .outerjoin(top_env_subq, (top_env_subq.c.driver_id == Driver.DriverID) & (top_env_subq.c.rn == 1))
        .outerjoin(Sponsor, Sponsor.SponsorID == top_env_subq.c.sponsor_id)
        .order_by(totals_subq.c.total_points.desc())
        .limit(100)
        .all()
    )

    # Convert to plain dicts for template
    leaderboard = []
    rank = 1
    for total_points, driver_id, username, avatar, sponsor_company in rows:
        leaderboard.append({
            "rank": rank,
            "username": username or f"Driver {driver_id[:6]}",
            "profile": avatar,
            "sponsor": sponsor_company or "—",
            "points": int(total_points or 0),
        })
        rank += 1

    return render_template(
        "leaderboard.html",
        leaderboard=leaderboard,
        page_title=page_title,
        scope_message=scope_message,
        role=role,
        action_url=action_url,
    )


