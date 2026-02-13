# app/routes/product_reports.py
from flask import Blueprint, render_template, request, jsonify, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc
from app.extensions import db
from app.models import Account, Driver, DriverSponsor, ProductReports, Sponsor

bp = Blueprint("product_reports", __name__, url_prefix="/product-reports")


def require_sponsor():
    """Require sponsor role and return sponsor ID."""
    if not current_user.is_authenticated:
        abort(401)
    
    # Check if user is a sponsor
    account = Account.query.get(current_user.AccountID)
    if not account:
        abort(401)
    
    # Look for sponsor record
    sponsor = Sponsor.query.filter_by(AccountID=account.AccountID).first()
    if not sponsor:
        abort(403, "Sponsor access required")
    
    return sponsor.SponsorID


@bp.get("/")
@login_required
def reports_list():
    """List all product reports for the sponsor's drivers."""
    sponsor_id = require_sponsor()
    
    # Get all drivers for this sponsor via the DriverSponsor bridge
    driver_ids = {
        rel.DriverID
        for rel in DriverSponsor.query.filter_by(SponsorID=sponsor_id).all()
    }
    
    # Get reports for these drivers
    reports = (
        ProductReports.query
        .filter(ProductReports.DriverID.in_(driver_ids))
        .order_by(desc(ProductReports.CreatedAt))
        .all()
    ) if driver_ids else []
    
    # Group reports by status for display
    pending_reports = [r for r in reports if r.Status == 'pending']
    reviewed_reports = [r for r in reports if r.Status in ['reviewed', 'resolved', 'dismissed']]
    
    return render_template(
        "product_reports/reports_list.html",
        pending_reports=pending_reports,
        reviewed_reports=reviewed_reports,
        total_reports=len(reports)
    )


@bp.get("/<string:report_id>")
@login_required
def report_detail(report_id: str):
    """View details of a specific report."""
    sponsor_id = require_sponsor()
    
    report = ProductReports.query.get_or_404(report_id)
    
    # Verify the report belongs to a driver of this sponsor
    driver = Driver.query.get(report.DriverID)
    if not driver:
        abort(404)

    driver_env = DriverSponsor.query.filter_by(
        DriverID=driver.DriverID,
        SponsorID=sponsor_id,
    ).first()
    if not driver_env:
        abort(404)
    
    # Get driver and reviewer account info
    driver_account = Account.query.get(driver.AccountID) if driver else None
    reviewer_account = Account.query.get(report.ReviewedByAccountID) if report.ReviewedByAccountID else None
    
    return render_template(
        "product_reports/report_detail.html",
        report=report,
        driver_account=driver_account,
        reviewer_account=reviewer_account
    )


@bp.post("/<string:report_id>/review")
@login_required
def review_report(report_id: str):
    """Review a product report (resolve, dismiss, etc.)."""
    sponsor_id = require_sponsor()
    
    report = ProductReports.query.get_or_404(report_id)
    
    # Verify the report belongs to a driver of this sponsor
    driver = Driver.query.get(report.DriverID)
    if not driver:
        abort(404)

    driver_env = DriverSponsor.query.filter_by(
        DriverID=driver.DriverID,
        SponsorID=sponsor_id,
    ).first()
    if not driver_env:
        abort(404)
    
    if report.Status != 'pending':
        return jsonify({"error": "Report already reviewed"}), 400
    
    action = request.json.get("action")
    notes = request.json.get("notes", "").strip()
    
    if action not in ["resolve", "dismiss"]:
        return jsonify({"error": "Invalid action"}), 400
    
    # Update report
    report.Status = "resolved" if action == "resolve" else "dismissed"
    report.ReviewedByAccountID = current_user.AccountID
    report.ReviewedAt = db.func.now()
    report.ReviewNotes = notes
    
    db.session.commit()
    
    flash(f"Report {action}d successfully", "success")
    return jsonify({"ok": True, "message": f"Report {action}d"})


@bp.get("/stats")
@login_required
def reports_stats():
    """Get statistics about product reports."""
    sponsor_id = require_sponsor()
    
    # Get all drivers for this sponsor via DriverSponsor
    driver_ids = {
        rel.DriverID
        for rel in DriverSponsor.query.filter_by(SponsorID=sponsor_id).all()
    }
    
    # Get report counts by status
    if not driver_ids:
        pending_count = resolved_count = dismissed_count = 0
    else:
        pending_count = ProductReports.query.filter(
            ProductReports.DriverID.in_(driver_ids),
            ProductReports.Status == 'pending'
        ).count()
        
        resolved_count = ProductReports.query.filter(
            ProductReports.DriverID.in_(driver_ids),
            ProductReports.Status == 'resolved'
        ).count()
        
        dismissed_count = ProductReports.query.filter(
            ProductReports.DriverID.in_(driver_ids),
            ProductReports.Status == 'dismissed'
        ).count()
    
    return jsonify({
        "pending": pending_count,
        "resolved": resolved_count,
        "dismissed": dismissed_count,
        "total": pending_count + resolved_count + dismissed_count
    })
