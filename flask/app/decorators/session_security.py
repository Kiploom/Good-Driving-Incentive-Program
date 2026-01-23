"""
Session Security Decorators
Provides decorators for session management and auto-logout
"""

from functools import wraps
from flask import request, redirect, url_for, flash, session
from flask_login import current_user
from app.services.session_management_service import SessionManagementService


def require_active_session(f):
    """
    Decorator to ensure user has an active session and auto-logout after inactivity
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get session token from Flask session
        session_token = session.get('session_token')
        
        if not session_token:
            flash("Your session has expired. Please log in again.", "warning")
            return redirect(url_for('auth.login_page'))
        
        # Validate session and check for inactivity
        is_valid, user_session = SessionManagementService.validate_session(session_token)
        
        if not is_valid:
            flash("Your session has expired due to inactivity. Please log in again.", "warning")
            # Clear client-side token so UI unblocks
            session.pop('session_token', None)
            return redirect(url_for('auth.login_page'))
        
        # Update session activity
        SessionManagementService.update_session_activity(session_token)
        
        # Add session info to request context for use in views
        request.current_session = user_session
        
        return f(*args, **kwargs)
    
    return decorated_function


def update_session_activity(f):
    """
    Decorator to update session activity on each request
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Update session activity if session exists
        session_token = session.get('session_token')
        if session_token:
            SessionManagementService.update_session_activity(session_token)
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_role(allowed_roles):
    """
    Decorator to require specific user roles
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("You must be logged in to access this page.", "error")
                return redirect(url_for('auth.login_page'))
            
            # Map role names to AccountType values
            role_mapping = {
                'driver': 'DRIVER',
                'sponsor': 'SPONSOR', 
                'admin': 'ADMIN'
            }
            
            # Convert allowed_roles to AccountType values
            allowed_account_types = [role_mapping.get(role.lower(), role.upper()) for role in allowed_roles]
            
            if current_user.AccountType not in allowed_account_types:
                flash("You don't have permission to access this page.", "error")
                return redirect(url_for('auth.login_page'))
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator
