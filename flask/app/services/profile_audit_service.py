"""
Profile Audit Service

This service handles tracking and logging profile changes for drivers, sponsors, and admins.
"""
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from flask import current_app
from app.models import (
    db,
    DriverProfileAudit,
    SponsorProfileAudit,
    AdminProfileAudit,
    Driver,
    Sponsor,
    Admin,
    Account,
    DriverSponsor,
)


class ProfileAuditService:
    """Service for tracking profile changes and creating audit logs."""
    
    @staticmethod
    def log_driver_change(
        driver_id: str,
        account_id: str,
        sponsor_id: Optional[str],
        field_name: str,
        old_value: Optional[str],
        new_value: Optional[str],
        changed_by_account_id: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> None:
        """Log a change to a driver's profile."""
        try:
            audit = DriverProfileAudit(
                DriverID=driver_id,
                AccountID=account_id,
                SponsorID=sponsor_id,
                FieldName=field_name,
                OldValue=old_value,
                NewValue=new_value,
                ChangedByAccountID=changed_by_account_id,
                ChangeReason=change_reason,
                ChangedAt=datetime.utcnow()
            )
            db.session.add(audit)
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to log driver profile change: {e}")
            db.session.rollback()
    
    @staticmethod
    def _resolve_primary_sponsor_id(driver: Optional[Driver]) -> Optional[str]:
        """Best-effort lookup of the sponsor responsible for a driver's environment."""
        if not driver:
            return None

        try:
            active_env = (
                DriverSponsor.query
                .filter_by(DriverID=driver.DriverID, Status="ACTIVE")
                .order_by(DriverSponsor.UpdatedAt.desc(), DriverSponsor.CreatedAt.desc())
                .first()
            )
            if active_env:
                return active_env.SponsorID

            fallback_env = (
                DriverSponsor.query
                .filter_by(DriverID=driver.DriverID)
                .order_by(DriverSponsor.UpdatedAt.desc(), DriverSponsor.CreatedAt.desc())
                .first()
            )
            if fallback_env:
                return fallback_env.SponsorID
        except Exception as exc:
            current_app.logger.debug(
                "Unable to resolve primary sponsor for driver %s: %s",
                getattr(driver, "DriverID", "UNKNOWN"),
                exc,
            )
        return None

    @staticmethod
    def log_sponsor_change(
        sponsor_id: str,
        account_id: str,
        field_name: str,
        old_value: Optional[str],
        new_value: Optional[str],
        changed_by_account_id: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> None:
        """Log a change to a sponsor's profile."""
        try:
            audit = SponsorProfileAudit(
                SponsorID=sponsor_id,
                AccountID=account_id,
                FieldName=field_name,
                OldValue=old_value,
                NewValue=new_value,
                ChangedByAccountID=changed_by_account_id,
                ChangeReason=change_reason,
                ChangedAt=datetime.utcnow()
            )
            db.session.add(audit)
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to log sponsor profile change: {e}")
            db.session.rollback()
    
    @staticmethod
    def log_admin_change(
        admin_id: str,
        account_id: str,
        field_name: str,
        old_value: Optional[str],
        new_value: Optional[str],
        changed_by_account_id: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> None:
        """Log a change to an admin's profile."""
        try:
            audit = AdminProfileAudit(
                AdminID=admin_id,
                AccountID=account_id,
                FieldName=field_name,
                OldValue=old_value,
                NewValue=new_value,
                ChangedByAccountID=changed_by_account_id,
                ChangeReason=change_reason,
                ChangedAt=datetime.utcnow()
            )
            db.session.add(audit)
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Failed to log admin profile change: {e}")
            db.session.rollback()
    
    @staticmethod
    def audit_driver_profile_changes(
        driver: Driver,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        changed_by_account_id: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> None:
        """Compare old and new driver data and log any changes."""
        fields_to_track = [
            'ShippingStreet', 'ShippingCity', 'ShippingState', 'ShippingCountry', 'ShippingPostal',
            'Age', 'Gender', 'Status', 'PointsBalance'
        ]

        sponsor_id = ProfileAuditService._resolve_primary_sponsor_id(driver)
        
        for field in fields_to_track:
            old_val = old_data.get(field)
            new_val = new_data.get(field)
            
            # Convert to string for comparison
            old_str = str(old_val) if old_val is not None else None
            new_str = str(new_val) if new_val is not None else None
            
            if old_str != new_str:
                ProfileAuditService.log_driver_change(
                    driver_id=driver.DriverID,
                    account_id=driver.AccountID,
                    sponsor_id=sponsor_id,
                    field_name=field,
                    old_value=old_str,
                    new_value=new_str,
                    changed_by_account_id=changed_by_account_id,
                    change_reason=change_reason
                )
    
    @staticmethod
    def audit_sponsor_profile_changes(
        sponsor: Sponsor,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        changed_by_account_id: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> None:
        """Compare old and new sponsor data and log any changes."""
        fields_to_track = [
            'Company', 'PointToDollarRate', 'MinPointsPerTxn', 'MaxPointsPerTxn',
            'BillingEmail', 'BillingStreet', 'BillingCity', 'BillingState', 
            'BillingCountry', 'BillingPostal', 'IsAdmin', 'Features'
        ]
        
        for field in fields_to_track:
            old_val = old_data.get(field)
            new_val = new_data.get(field)
            
            # Convert to string for comparison
            old_str = str(old_val) if old_val is not None else None
            new_str = str(new_val) if new_val is not None else None
            
            if old_str != new_str:
                ProfileAuditService.log_sponsor_change(
                    sponsor_id=sponsor.SponsorID,
                    account_id=sponsor.AccountID,
                    field_name=field,
                    old_value=old_str,
                    new_value=new_str,
                    changed_by_account_id=changed_by_account_id,
                    change_reason=change_reason
                )
    
    @staticmethod
    def audit_admin_profile_changes(
        admin: Admin,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        changed_by_account_id: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> None:
        """Compare old and new admin data and log any changes."""
        fields_to_track = [
            'Role'
        ]
        
        for field in fields_to_track:
            old_val = old_data.get(field)
            new_val = new_data.get(field)
            
            # Convert to string for comparison
            old_str = str(old_val) if old_val is not None else None
            new_str = str(new_val) if new_val is not None else None
            
            if old_str != new_str:
                ProfileAuditService.log_admin_change(
                    admin_id=admin.AdminID,
                    account_id=admin.AccountID,
                    field_name=field,
                    old_value=old_str,
                    new_value=new_str,
                    changed_by_account_id=changed_by_account_id,
                    change_reason=change_reason
                )
    
    @staticmethod
    def audit_account_changes(
        account: Account,
        old_data: Dict[str, Any],
        new_data: Dict[str, Any],
        changed_by_account_id: Optional[str] = None,
        change_reason: Optional[str] = None
    ) -> None:
        """Compare old and new account data and log any changes."""
        fields_to_track = [
            'FirstName', 'LastName', 'Email', 'Phone', 'Status', 'MFAEnabled'
        ]
        
        # Get the associated profile (Driver, Sponsor, or Admin)
        if account.is_driver:
            driver = Driver.query.filter_by(AccountID=account.AccountID).first()
            if driver:
                sponsor_id = ProfileAuditService._resolve_primary_sponsor_id(driver)
                for field in fields_to_track:
                    old_val = old_data.get(field)
                    new_val = new_data.get(field)
                    
                    old_str = str(old_val) if old_val is not None else None
                    new_str = str(new_val) if new_val is not None else None
                    
                    if old_str != new_str:
                        ProfileAuditService.log_driver_change(
                            driver_id=driver.DriverID,
                            account_id=account.AccountID,
                            sponsor_id=sponsor_id,
                            field_name=f"Account.{field}",
                            old_value=old_str,
                            new_value=new_str,
                            changed_by_account_id=changed_by_account_id,
                            change_reason=change_reason
                        )
        
        elif account.is_sponsor:
            sponsor = Sponsor.query.filter_by(AccountID=account.AccountID).first()
            if sponsor:
                for field in fields_to_track:
                    old_val = old_data.get(field)
                    new_val = new_data.get(field)
                    
                    old_str = str(old_val) if old_val is not None else None
                    new_str = str(new_val) if new_val is not None else None
                    
                    if old_str != new_str:
                        ProfileAuditService.log_sponsor_change(
                            sponsor_id=sponsor.SponsorID,
                            account_id=account.AccountID,
                            field_name=f"Account.{field}",
                            old_value=old_str,
                            new_value=new_str,
                            changed_by_account_id=changed_by_account_id,
                            change_reason=change_reason
                        )
        
        elif account.is_admin:
            admin = Admin.query.filter_by(AccountID=account.AccountID).first()
            if admin:
                for field in fields_to_track:
                    old_val = old_data.get(field)
                    new_val = new_data.get(field)
                    
                    old_str = str(old_val) if old_val is not None else None
                    new_str = str(new_val) if new_val is not None else None
                    
                    if old_str != new_str:
                        ProfileAuditService.log_admin_change(
                            admin_id=admin.AdminID,
                            account_id=account.AccountID,
                            field_name=f"Account.{field}",
                            old_value=old_str,
                            new_value=new_str,
                            changed_by_account_id=changed_by_account_id,
                            change_reason=change_reason
                        )

