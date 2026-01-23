"""
Session Management Routes
Handles session viewing and revocation for drivers
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_required, current_user
from app.extensions import db
from app.models import UserSessions
from app.services.session_management_service import SessionManagementService
from app.decorators.session_security import require_active_session, update_session_activity
from datetime import datetime

bp = Blueprint("sessions", __name__, url_prefix="/sessions")


@bp.route("/")
@login_required
@require_active_session
@update_session_activity
def view_sessions():
    """Display active sessions for the current user"""
    # Get all active sessions for the current user
    active_sessions = SessionManagementService.get_active_sessions(current_user.AccountID)
    
    # Format session data for display
    sessions_data = []
    for user_session in active_sessions:
        sessions_data.append({
            'session_id': user_session.SessionID,
            'device_name': user_session.DeviceName or 'Unknown Device',
            'device_type': user_session.DeviceType or 'unknown',
            'browser_name': user_session.BrowserName or 'Unknown Browser',
            'browser_version': user_session.BrowserVersion or '',
            'operating_system': user_session.OperatingSystem or 'Unknown OS',
            'ip_address': user_session.IPAddress,
            'created_at': user_session.CreatedAt,
            'last_activity': user_session.LastActivityAt,
            'is_current': user_session.SessionToken == session.get('session_token'),
            'time_since_activity': _format_time_since(user_session.LastActivityAt)
        })
    
    return render_template("sessions/view_sessions.html", sessions=sessions_data)


@bp.route("/revoke/<session_id>", methods=["POST"])
@login_required
@require_active_session
@update_session_activity
def revoke_session(session_id):
    """Revoke a specific session"""
    # Find the session
    user_session = UserSessions.query.filter_by(
        SessionID=session_id,
        AccountID=current_user.AccountID,
        IsActive=True
    ).first()
    
    if not user_session:
        if request.is_json:
            return jsonify({"success": False, "message": "Session not found or already revoked."}), 404
        flash("Session not found or already revoked.", "danger")
        return redirect(url_for("sessions.view_sessions"))
    
    # Revoke the session
    user_session.IsActive = False
    db.session.commit()
    
    # If this is the current session, log out the user
    if user_session.SessionToken == session.get('session_token'):
        from flask_login import logout_user
        logout_user()
        if request.is_json:
            return jsonify({"success": True, "logged_out": True})
        flash("Your session has been revoked. You have been logged out.", "warning")
        return redirect(url_for('auth.login_page'))
    
    if request.is_json:
        return jsonify({"success": True})
    flash(f"Session on {user_session.DeviceName or 'Unknown Device'} has been revoked.", "success")
    return redirect(url_for("sessions.view_sessions"))


@bp.route("/revoke-all", methods=["POST"])
@login_required
@require_active_session
@update_session_activity
def revoke_all_sessions():
    """Revoke all sessions except the current one"""
    current_session_token = session.get('session_token')
    
    # Get all active sessions except current one
    sessions_to_revoke = UserSessions.query.filter(
        UserSessions.AccountID == current_user.AccountID,
        UserSessions.IsActive == True,
        UserSessions.SessionToken != current_session_token
    ).all()
    
    count = 0
    for user_session in sessions_to_revoke:
        user_session.IsActive = False
        count += 1
    
    db.session.commit()
    
    if request.is_json:
        return jsonify({"success": True, "revoked": count})
    if count > 0:
        flash(f"Successfully revoked {count} other session(s).", "success")
    else:
        flash("No other sessions to revoke.", "info")
    
    return redirect(url_for("sessions.view_sessions"))


@bp.route("/api/sessions")
@login_required
@require_active_session
@update_session_activity
def api_sessions():
    """API endpoint to get session data as JSON"""
    active_sessions = SessionManagementService.get_active_sessions(current_user.AccountID)
    
    sessions_data = []
    for user_session in active_sessions:
        sessions_data.append({
            'session_id': user_session.SessionID,
            'device_name': user_session.DeviceName or 'Unknown Device',
            'device_type': user_session.DeviceType or 'unknown',
            'browser_name': user_session.BrowserName or 'Unknown Browser',
            'browser_version': user_session.BrowserVersion or '',
            'operating_system': user_session.OperatingSystem or 'Unknown OS',
            'ip_address': user_session.IPAddress,
            'created_at': user_session.CreatedAt.isoformat(),
            'last_activity': user_session.LastActivityAt.isoformat(),
            'is_current': user_session.SessionToken == session.get('session_token'),
            'time_since_activity': _format_time_since(user_session.LastActivityAt)
        })
    
    return jsonify({
        'success': True,
        'sessions': sessions_data
    })


@bp.route("/api/validate-me", methods=["GET"])
@login_required
def api_validate_me():
    """Heartbeat endpoint: validates current session, updates last activity when valid"""
    token = session.get('session_token')
    if not token:
        return jsonify({'valid': False})
    is_valid, _ = SessionManagementService.validate_session(token)
    if not is_valid:
        # Ensure server-side sees this session as inactive
        SessionManagementService.revoke_session(token)
        return jsonify({'valid': False})
    # Touch activity so timestamps stay fresh
    SessionManagementService.update_session_activity(token)
    return jsonify({'valid': True})


def _format_time_since(last_activity):
    """Format time since last activity in a human-readable way"""
    # Normalize last_activity to naive UTC if it has tzinfo
    try:
        last_dt = last_activity
        if hasattr(last_dt, 'tzinfo') and last_dt.tzinfo is not None:
            last_dt = last_dt.replace(tzinfo=None)
    except Exception:
        last_dt = last_activity
    now = datetime.utcnow()
    diff = now - last_dt
    
    if diff.total_seconds() < 0:
        return "Just now"
    if diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"
