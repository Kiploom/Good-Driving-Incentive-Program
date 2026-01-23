"""
Password Security Service
Handles password history tracking and password reuse prevention
"""

import bcrypt
import re
from datetime import datetime
from typing import List, Optional, Tuple
from flask import request
from app.extensions import db
from app.models import PasswordHistory, Account


class PasswordSecurityService:
    """Service for managing password security and history"""
    
    PASSWORD_HISTORY_LIMIT = 5  # Keep last 5 passwords
    
    @staticmethod
    def log_password_change(
        account_id: str,
        new_password_hash: str,
        change_reason: str = 'self_change',
        changed_by: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> PasswordHistory:
        """
        Log a password change in the password history
        
        Args:
            account_id: ID of the account whose password was changed
            new_password_hash: The new hashed password
            change_reason: Reason for the change (self_change, admin_reset, password_reset, initial_setup)
            changed_by: ID of the account that made the change (None if self-changed)
            ip_address: IP address of the request
            user_agent: User agent string from the request
            
        Returns:
            PasswordHistory: The created password history record
        """
        # Get request info if not provided
        if ip_address is None:
            ip_address = request.remote_addr if request else None
        if user_agent is None:
            user_agent = request.headers.get('User-Agent') if request else None
            
        # Create password history record
        password_history = PasswordHistory(
            AccountID=account_id,
            PasswordHash=new_password_hash,
            ChangedBy=changed_by,
            ChangeReason=change_reason,
            IPAddress=ip_address,
            UserAgent=user_agent,
            ChangedAt=datetime.utcnow()
        )
        
        db.session.add(password_history)
        db.session.commit()
        
        return password_history
    
    
    @staticmethod
    def check_password_reuse(
        account_id: str,
        new_password: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if the new password has been used recently (in the last 5 passwords)
        
        Args:
            account_id: ID of the account
            new_password: The new plaintext password to check
            
        Returns:
            Tuple[bool, Optional[str]]: (is_reused, error_message)
            - is_reused: True if password was recently used, False otherwise
            - error_message: Error message if password is reused, None otherwise
        """
        # Get recent password history for this account
        recent_passwords = (
            PasswordHistory.query
            .filter_by(AccountID=account_id)
            .order_by(PasswordHistory.ChangedAt.desc())
            .limit(PasswordSecurityService.PASSWORD_HISTORY_LIMIT)
            .all()
        )
        
        # Check if the new password matches any of the recent passwords
        for password_record in recent_passwords:
            if bcrypt.checkpw(new_password.encode('utf-8'), password_record.PasswordHash.encode('utf-8')):
                return True, f"Password cannot be reused. You must choose a different password than your last {PasswordSecurityService.PASSWORD_HISTORY_LIMIT} passwords."
        
        return False, None
    
    @staticmethod
    def get_password_history(account_id: str, limit: int = 10) -> List[PasswordHistory]:
        """
        Get password change history for an account
        
        Args:
            account_id: ID of the account
            limit: Maximum number of records to return
            
        Returns:
            List[PasswordHistory]: List of password history records
        """
        return (
            PasswordHistory.query
            .filter_by(AccountID=account_id)
            .order_by(PasswordHistory.ChangedAt.desc())
            .limit(limit)
            .all()
        )
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt
        
        Args:
            password: Plaintext password
            
        Returns:
            str: Hashed password
        """
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash
        
        Args:
            password: Plaintext password
            password_hash: Hashed password
            
        Returns:
            bool: True if password matches, False otherwise
        """
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    @staticmethod
    def is_password_strong(password: str) -> Tuple[bool, Optional[str]]:
        """
        Check if password meets complexity requirements
        
        Args:
            password: Plaintext password to check
            
        Returns:
            Tuple[bool, Optional[str]]: (is_strong, error_message)
            - is_strong: True if password meets requirements, False otherwise
            - error_message: Error message if password is weak, None otherwise
        """
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        if not re.search(r"[A-Z]", password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r"[a-z]", password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r"[0-9]", password):
            return False, "Password must contain at least one number"
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            return False, "Password must contain at least one special character"
        return True, None


def log_password_change_for_account(
    account_id: str,
    new_password: str,
    change_reason: str = 'self_change',
    changed_by: Optional[str] = None
) -> PasswordHistory:
    """
    Convenience function to hash and log a password change
    
    Args:
        account_id: ID of the account whose password was changed
        new_password: The new plaintext password
        change_reason: Reason for the change
        changed_by: ID of the account that made the change
        
    Returns:
        PasswordHistory: The created password history record
    """
    hashed_password = PasswordSecurityService.hash_password(new_password)
    return PasswordSecurityService.log_password_change(
        account_id=account_id,
        new_password_hash=hashed_password,
        change_reason=change_reason,
        changed_by=changed_by
    )
