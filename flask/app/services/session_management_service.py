"""
Session Management Service
Handles user session tracking, auto-logout, and session security
"""

import secrets
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict
from flask import request, session
from app.extensions import db
from app.models import UserSessions, Account


class SessionManagementService:
    """Service for managing user sessions and security"""
    
    SESSION_TIMEOUT_MINUTES = 30
    SESSION_EXPIRY_HOURS = 24  # Sessions expire after 24 hours
    
    @staticmethod
    def create_session(account_id: str, request_obj=None) -> UserSessions:
        """
        Create a new user session
        
        Args:
            account_id: ID of the account
            request_obj: Flask request object (optional, uses current request if not provided)
            
        Returns:
            UserSessions: The created session
        """
        if request_obj is None:
            request_obj = request
            
        # Generate secure session token
        session_token = secrets.token_urlsafe(32)
        
        # Parse user agent for device information
        user_agent = request_obj.headers.get('User-Agent', '')
        device_info = SessionManagementService._parse_user_agent(user_agent)
        
        # Calculate expiry time (UTC)
        now_utc = datetime.utcnow()
        expires_at = now_utc + timedelta(hours=SessionManagementService.SESSION_EXPIRY_HOURS)
        
        # Create session record
        user_session = UserSessions(
            AccountID=account_id,
            SessionToken=session_token,
            DeviceName=device_info.get('device_name', 'Unknown Device'),
            DeviceType=device_info.get('device_type', 'unknown'),
            BrowserName=device_info.get('browser_name', 'Unknown Browser'),
            BrowserVersion=device_info.get('browser_version', ''),
            OperatingSystem=device_info.get('os_name', 'Unknown OS'),
            IPAddress=request_obj.remote_addr,
            UserAgent=user_agent,
            CreatedAt=now_utc,
            LastActivityAt=now_utc,
            ExpiresAt=expires_at
        )
        
        db.session.add(user_session)
        db.session.commit()
        
        # Store session token in Flask session
        session['session_token'] = session_token
        
        return user_session
    
    @staticmethod
    def update_session_activity(session_token: str) -> bool:
        """
        Update the last activity time for a session
        
        Args:
            session_token: The session token to update
            
        Returns:
            bool: True if session was updated, False if not found
        """
        user_session = UserSessions.query.filter_by(
            SessionToken=session_token,
            IsActive=True
        ).first()
        
        if user_session and not user_session.is_expired:
            # Update last activity using UTC
            user_session.LastActivityAt = datetime.utcnow()
            db.session.commit()
            return True
        
        return False
    
    @staticmethod
    def validate_session(session_token: str) -> Tuple[bool, Optional[UserSessions]]:
        """
        Validate a session token and check for inactivity
        
        Args:
            session_token: The session token to validate
            
        Returns:
            Tuple[bool, Optional[UserSessions]]: (is_valid, session_object)
        """
        user_session = UserSessions.query.filter_by(
            SessionToken=session_token,
            IsActive=True
        ).first()
        
        if not user_session:
            return False, None
            
        # Check if session is expired
        if user_session.is_expired:
            SessionManagementService.revoke_session(session_token)
            return False, None
            
        # Check for inactivity (30 minutes)
        if user_session.is_inactive:
            SessionManagementService.revoke_session(session_token)
            return False, None
            
        return True, user_session
    
    @staticmethod
    def revoke_session(session_token: str) -> bool:
        """
        Revoke a specific session
        
        Args:
            session_token: The session token to revoke
            
        Returns:
            bool: True if session was revoked, False if not found
        """
        user_session = UserSessions.query.filter_by(SessionToken=session_token).first()
        
        if user_session:
            user_session.IsActive = False
            db.session.commit()
            return True
            
        return False
    
    @staticmethod
    def revoke_all_sessions(account_id: str) -> int:
        """
        Revoke all sessions for a specific account
        
        Args:
            account_id: The account ID
            
        Returns:
            int: Number of sessions revoked
        """
        sessions = UserSessions.query.filter_by(
            AccountID=account_id,
            IsActive=True
        ).all()
        
        count = 0
        for user_session in sessions:
            user_session.IsActive = False
            count += 1
            
        db.session.commit()
        return count
    
    @staticmethod
    def get_active_sessions(account_id: str) -> List[UserSessions]:
        """
        Get all active sessions for an account
        
        Args:
            account_id: The account ID
            
        Returns:
            List[UserSessions]: List of active sessions
        """
        return UserSessions.query.filter_by(
            AccountID=account_id,
            IsActive=True
        ).order_by(UserSessions.LastActivityAt.desc()).all()
    
    @staticmethod
    def cleanup_expired_sessions() -> int:
        """
        Clean up expired and inactive sessions
        
        Returns:
            int: Number of sessions cleaned up
        """
        # Find expired sessions
        expired_sessions = UserSessions.query.filter(
            UserSessions.ExpiresAt < datetime.utcnow(),
            UserSessions.IsActive == True
        ).all()
        
        # Find inactive sessions (30+ minutes)
        inactive_cutoff = datetime.utcnow() - timedelta(minutes=SessionManagementService.SESSION_TIMEOUT_MINUTES)
        inactive_sessions = UserSessions.query.filter(
            UserSessions.LastActivityAt < inactive_cutoff,
            UserSessions.IsActive == True
        ).all()
        
        # Deactivate all found sessions
        all_sessions = set(expired_sessions + inactive_sessions)
        count = 0
        
        for user_session in all_sessions:
            user_session.IsActive = False
            count += 1
            
        db.session.commit()
        return count
    
    @staticmethod
    def _parse_user_agent(user_agent: str) -> Dict[str, str]:
        """
        Parse user agent string to extract device and browser information
        
        Args:
            user_agent: The user agent string
            
        Returns:
            Dict[str, str]: Parsed device information
        """
        if not user_agent:
            return {
                'device_name': 'Unknown Device',
                'device_type': 'unknown',
                'browser_name': 'Unknown Browser',
                'browser_version': '',
                'os_name': 'Unknown OS'
            }
        
        # Detect device type
        device_type = 'desktop'
        device_name = 'Desktop Computer'
        
        if re.search(r'(Mobile|Android|iPhone|iPad|iPod)', user_agent, re.IGNORECASE):
            device_type = 'mobile'
            device_name = 'Mobile Device'
        elif re.search(r'(Tablet|iPad)', user_agent, re.IGNORECASE):
            device_type = 'tablet'
            device_name = 'Tablet Device'
        
        # Detect browser
        browser_name = 'Unknown Browser'
        browser_version = ''
        
        if 'Chrome' in user_agent and 'Edge' not in user_agent:
            browser_name = 'Chrome'
            match = re.search(r'Chrome/(\d+\.\d+)', user_agent)
            if match:
                browser_version = match.group(1)
        elif 'Firefox' in user_agent:
            browser_name = 'Firefox'
            match = re.search(r'Firefox/(\d+\.\d+)', user_agent)
            if match:
                browser_version = match.group(1)
        elif 'Safari' in user_agent and 'Chrome' not in user_agent:
            browser_name = 'Safari'
            match = re.search(r'Version/(\d+\.\d+)', user_agent)
            if match:
                browser_version = match.group(1)
        elif 'Edge' in user_agent:
            browser_name = 'Edge'
            match = re.search(r'Edge/(\d+\.\d+)', user_agent)
            if match:
                browser_version = match.group(1)
        
        # Detect operating system
        os_name = 'Unknown OS'
        
        if 'Windows' in user_agent:
            os_name = 'Windows'
        elif 'Mac' in user_agent:
            os_name = 'macOS'
        elif 'Linux' in user_agent:
            os_name = 'Linux'
        elif 'Android' in user_agent:
            os_name = 'Android'
        elif 'iOS' in user_agent or 'iPhone' in user_agent or 'iPad' in user_agent:
            os_name = 'iOS'
        
        return {
            'device_name': device_name,
            'device_type': device_type,
            'browser_name': browser_name,
            'browser_version': browser_version,
            'os_name': os_name
        }
    
    @staticmethod
    def get_current_session() -> Optional[UserSessions]:
        """
        Get the current session from Flask session
        
        Returns:
            Optional[UserSessions]: Current session or None
        """
        session_token = session.get('session_token')
        if not session_token:
            return None
            
        is_valid, user_session = SessionManagementService.validate_session(session_token)
        if is_valid:
            return user_session
        else:
            # Clear invalid session token
            session.pop('session_token', None)
            return None
