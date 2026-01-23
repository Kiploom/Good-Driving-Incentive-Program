from datetime import datetime

from flask import Blueprint, request, jsonify, session, current_app
from flask_login import login_user, current_user, login_required
from sqlalchemy.orm import joinedload

from app.extensions import db, bcrypt
from app.models import (
    Account,
    Driver,
    Cart,
    CartItem,
    DriverSponsor,
    Orders,
    OrderLineItem,
    Products,
    PointChange,
    Sponsor,
    SponsorCompany,
    NotificationPreferences,
)
from app.services.driver_notification_service import DriverNotificationService
from app.utils.point_change_actor import derive_point_change_actor_metadata
from app.services.session_management_service import SessionManagementService
import pyotp
from config import fernet
from werkzeug.security import check_password_hash

mobile_bp = Blueprint("mobile", __name__)

@mobile_bp.get("/api/mobile/test")
def mobile_test():
    """Test endpoint to verify mobile API connectivity"""
    return jsonify({
        "success": True,
        "message": "Mobile API is working",
        "timestamp": "2024-01-01T00:00:00Z"
    })

@mobile_bp.get("/api/mobile/debug/session")
@login_required
def mobile_debug_session():
    """Debug endpoint to inspect current session state"""
    from flask_login import current_user
    
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    env, sponsor_id, sponsor_company_id = _resolve_driver_environment(driver) if driver else (None, None, None)
    
    return jsonify({
        "success": True,
        "session": {
            "driver_sponsor_id": session.get('driver_sponsor_id'),
            "sponsor_id": session.get('sponsor_id'),
            "driver_id": session.get('driver_id'),
            "sponsor_company": session.get('sponsor_company'),
            "all_keys": list(session.keys()),
            "modified": session.modified,
            "permanent": session.permanent,
        },
        "resolved": {
            "driver_sponsor_id": str(env.DriverSponsorID) if env else None,
            "sponsor_id": sponsor_id,
            "sponsor_company_id": sponsor_company_id,
            "points_balance": env.PointsBalance if env else None,
        },
        "driver_id": driver.DriverID if driver else None,
        "account_id": current_user.AccountID,
    })

@mobile_bp.get("/api/mobile/catalog/test")
def mobile_catalog_test():
    """Test endpoint to verify catalog API connectivity without authentication"""
    return jsonify({
        "success": True,
        "message": "Catalog API is accessible",
        "test_data": {
            "items": [
                {
                    "id": "test1",
                    "title": "Test Product 1",
                    "points": 100,
                    "image": "https://via.placeholder.com/150",
                    "availability": "IN_STOCK",
                    "isFavorite": False,
                    "isPinned": False
                }
            ],
            "page": 1,
            "page_size": 1,
            "total": 1,
            "has_more": False
        }
    })

@mobile_bp.post("/api/mobile/login")
def mobile_login():
    """Mobile-specific login endpoint that returns JSON with user details"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No JSON data provided"}), 400
    
    email_or_username = (data.get("email") or "").strip()
    password = data.get("password") or ""
    
    if not email_or_username or not password:
        return jsonify({"success": False, "message": "Missing email/username or password"}), 400
    
    # Try to find account by email first, then by username
    if "@" in email_or_username:
        acct = Account.query.filter(Account.Email == email_or_username.lower()).first()
    else:
        acct = Account.query.filter(Account.Username == email_or_username).first()
    
    if not acct or not bcrypt.check_password_hash(acct.PasswordHash, password):
        return jsonify({"success": False, "message": "Incorrect email/username or password"}), 401
    
    # Check if this is a driver account
    driver = Driver.query.filter_by(AccountID=acct.AccountID).first()
    if not driver:
        return jsonify({"success": False, "message": "Only driver accounts can access the mobile app"}), 403
    
    # Check email verification
    from app.models import EmailVerification
    ev = EmailVerification.query.filter_by(AccountID=acct.AccountID).first()
    if ev and not ev.IsVerified:
        return jsonify({"success": False, "message": "Please verify your email before logging in"}), 403
    
    # Handle MFA if enabled - same logic as Flask web login
    if acct.MFAEnabled:
        session["pending_mfa_user"] = str(acct.AccountID)
        return jsonify({
            "success": False,
            "message": "MFA verification required",
            "mfa_required": True,
            "accountId": acct.AccountID
        }), 200  # Use 200 status but success:false to indicate MFA needed
    
    # Login successful (no MFA)
    login_user(acct, remember=True)
    session.permanent = True  # Make session permanent to match CSRF token lifetime (31 days)
    
    # Set role session
    session.pop("sponsor_id", None)
    session.pop("driver_id", None)
    session.pop("admin_id", None)
    session.pop("driver_sponsor_id", None)  # Clear any old environment selection
    session["driver_id"] = driver.DriverID
    
    # Set driver_sponsor_id to the most recently accepted sponsor environment
    from app.models import DriverSponsor
    env = (
        DriverSponsor.query
        .filter_by(DriverID=driver.DriverID, Status="ACTIVE")
        .order_by(DriverSponsor.UpdatedAt.desc(), DriverSponsor.CreatedAt.desc())
        .first()
    )
    if env:
        session["driver_sponsor_id"] = str(env.DriverSponsorID)
        session["sponsor_id"] = str(env.SponsorID)  # For legacy compatibility
        if env.sponsor:
            session["sponsor_company"] = env.sponsor.Company
    
    # Create session for tracking
    SessionManagementService.create_session(acct.AccountID, request)
    
    return jsonify({
        "success": True,
        "message": "Login successful",
        "accountId": acct.AccountID,
        "driverId": driver.DriverID,
        "username": acct.Username,
        "email": acct.Email
    })

@mobile_bp.post("/api/mobile/mfa/verify")
def mobile_mfa_verify():
    """Verify MFA code for mobile login - uses same logic as Flask web login"""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No JSON data provided"}), 400
    
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"success": False, "message": "MFA code is required"}), 400
    
    # Get pending MFA user from session (set during login)
    user_id = session.get("pending_mfa_user")
    if not user_id:
        return jsonify({"success": False, "message": "No pending MFA verification. Please log in again."}), 400
    
    acct = Account.query.get(user_id)
    if not acct:
        session.pop("pending_mfa_user", None)
        return jsonify({"success": False, "message": "Session expired. Please log in again."}), 400
    
    # Verify MFA code using same logic as Flask web login
    try:
        # Decrypt MFA secret and verify TOTP code
        secret = fernet.decrypt(acct.MFASecretEnc.encode()).decode()
        totp = pyotp.TOTP(secret)
        code_lower = code.lower()
        
        # Try TOTP verification first (valid_window=1 allows ±30 seconds)
        if totp.verify(code_lower, valid_window=1):
            verified = True
        else:
            # Try recovery codes if TOTP fails
            verified = False
            if acct.RecoveryCodes:
                for stored in list(acct.RecoveryCodes):
                    if check_password_hash(stored, code_lower):
                        verified = True
                        # Remove used recovery code (one-time use)
                        acct.RecoveryCodes.remove(stored)
                        db.session.commit()
                        break
            
            if not verified:
                return jsonify({"success": False, "message": "Invalid MFA or recovery code."}), 401
        
        # Successful verification - complete login (same as Flask web login)
        login_user(acct, remember=True)
        session.permanent = True  # Make session permanent to match CSRF token lifetime (31 days)
        session.pop("pending_mfa_user", None)
        
        # Set role session (same as mobile login)
        session.pop("sponsor_id", None)
        session.pop("driver_id", None)
        session.pop("admin_id", None)
        session.pop("driver_sponsor_id", None)
        
        driver = Driver.query.filter_by(AccountID=acct.AccountID).first()
        if driver:
            session["driver_id"] = driver.DriverID
            
            # Set driver_sponsor_id to the most recently accepted sponsor environment
            from app.models import DriverSponsor
            env = (
                DriverSponsor.query
                .filter_by(DriverID=driver.DriverID, Status="ACTIVE")
                .order_by(DriverSponsor.UpdatedAt.desc(), DriverSponsor.CreatedAt.desc())
                .first()
            )
            if env:
                session["driver_sponsor_id"] = str(env.DriverSponsorID)
                session["sponsor_id"] = str(env.SponsorID)
                if env.sponsor:
                    session["sponsor_company"] = env.sponsor.Company
        
        # Create session for tracking
        SessionManagementService.create_session(acct.AccountID, request)
        
        return jsonify({
            "success": True,
            "message": "MFA verification successful",
            "accountId": acct.AccountID,
            "driverId": driver.DriverID if driver else None,
            "username": acct.Username,
            "email": acct.Email
        })
        
    except Exception as e:
        current_app.logger.error(f"Error verifying MFA code: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error verifying MFA code: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/logout")
def mobile_logout():
    """Mobile logout endpoint"""
    from flask_login import logout_user
    logout_user()
    session.clear()
    return jsonify({"success": True, "message": "Logged out successfully"})

@mobile_bp.get("/api/mobile/mfa/status")
@login_required
def mobile_mfa_status():
    """Get current MFA status"""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    return jsonify({
        "success": True,
        "mfa_enabled": current_user.MFAEnabled
    })

@mobile_bp.post("/api/mobile/mfa/enable")
@login_required
def mobile_mfa_enable():
    """Start MFA enablement - generates secret and QR code"""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No JSON data provided"}), 400
    
    password = data.get("password") or ""
    if not bcrypt.check_password_hash(current_user.PasswordHash, password):
        return jsonify({"success": False, "message": "Incorrect password"}), 401
    
    secret = pyotp.random_base32()
    enc_secret = fernet.encrypt(secret.encode()).decode()
    current_user.MFASecretEnc = enc_secret
    db.session.commit()
    
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.Email,
        issuer_name="Driver Rewards"
    )
    
    return jsonify({
        "success": True,
        "qr_uri": uri,
        "secret": secret  # For manual entry
    })

@mobile_bp.post("/api/mobile/mfa/confirm")
@login_required
def mobile_mfa_confirm():
    """Confirm MFA setup with a verification code"""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No JSON data provided"}), 400
    
    code = (data.get("code") or "").strip().lower()
    if not code:
        return jsonify({"success": False, "message": "Code is required"}), 400
    
    if not current_user.MFASecretEnc:
        return jsonify({"success": False, "message": "MFA setup not started. Please enable MFA first."}), 400
    
    secret = fernet.decrypt(current_user.MFASecretEnc.encode()).decode()
    totp = pyotp.TOTP(secret)
    
    if not totp.verify(code, valid_window=1):
        return jsonify({"success": False, "message": "Invalid code. Try again."}), 401
    
    current_user.MFAEnabled = True
    
    # Generate 10 recovery codes
    import secrets
    from werkzeug.security import generate_password_hash
    raw_codes = [secrets.token_hex(4).lower() for _ in range(10)]
    current_user.RecoveryCodes = [generate_password_hash(c) for c in raw_codes]
    
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "MFA enabled successfully",
        "recovery_codes": raw_codes  # Show these once - user must save them
    })

@mobile_bp.post("/api/mobile/mfa/disable")
@login_required
def mobile_mfa_disable():
    """Disable MFA"""
    from flask_login import current_user
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No JSON data provided"}), 400
    
    password = data.get("password") or ""
    if not bcrypt.check_password_hash(current_user.PasswordHash, password):
        return jsonify({"success": False, "message": "Incorrect password"}), 401
    
    current_user.MFAEnabled = False
    current_user.MFASecretEnc = None
    current_user.RecoveryCodes = None
    
    db.session.commit()
    return jsonify({"success": True, "message": "MFA disabled successfully"})

@mobile_bp.get("/api/mobile/profile")
def mobile_profile():
    """Get driver profile information for mobile app"""
    from flask_login import current_user
    
    current_app.logger.info("=" * 80)
    current_app.logger.info("PROFILE REQUEST STARTED")
    current_app.logger.info(f"Request URL: {request.url}")
    current_app.logger.info(f"Request headers - Cookie: {request.headers.get('Cookie', 'N/A')[:200]}...")  # First 200 chars
    current_app.logger.info(f"Session ID: {session.get('_id', 'N/A')}")
    current_app.logger.info(f"Session - driver_sponsor_id: {session.get('driver_sponsor_id')}")
    current_app.logger.info(f"Session - sponsor_id: {session.get('sponsor_id')}")
    current_app.logger.info(f"Session - driver_id: {session.get('driver_id')}")
    current_app.logger.info(f"Session - sponsor_company: {session.get('sponsor_company')}")
    current_app.logger.info(f"Session permanent: {session.permanent}")
    current_app.logger.info(f"Session modified: {session.modified}")
    current_app.logger.info(f"All session keys: {list(session.keys())}")
    current_app.logger.info(f"Full session dict: {dict(session)}")
    
    if not current_user.is_authenticated:
        current_app.logger.error("User not authenticated")
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    # Get driver information
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        current_app.logger.error(f"Driver not found for AccountID: {current_user.AccountID}")
        return jsonify({"success": False, "message": "Driver not found"}), 404
    
    current_app.logger.info(f"Driver ID: {driver.DriverID}")
    
    # Get sponsor environment context and points balance
    env, sponsor_id, sponsor_company_id = _resolve_driver_environment(driver)
    current_app.logger.info(f"Resolved environment - DriverSponsorID: {env.DriverSponsorID if env else None}")
    current_app.logger.info(f"Resolved sponsor_id: {sponsor_id}")
    current_app.logger.info(f"Resolved sponsor_company_id: {sponsor_company_id}")
    points_balance = env.PointsBalance or 0 if env else 0
    current_app.logger.info(f"Points balance: {points_balance}")

    sponsor_name = None
    if sponsor_id:
        sponsor = Sponsor.query.get(sponsor_id)
        if sponsor:
            sponsor_name = sponsor.Company
            current_app.logger.info(f"Found sponsor name from Sponsor table: {sponsor_name}")
    if not sponsor_name and sponsor_company_id:
        sponsor_company = SponsorCompany.query.get(sponsor_company_id)
        if sponsor_company:
            sponsor_name = sponsor_company.CompanyName
            current_app.logger.info(f"Found sponsor name from SponsorCompany table: {sponsor_name}")
    
    current_app.logger.info(f"Final sponsor_name for profile: {sponsor_name}")
    current_app.logger.info("PROFILE REQUEST COMPLETED")
    current_app.logger.info("=" * 80)
    
    # Format shipping address
    shipping_address = None
    if driver.ShippingStreet:
        address_parts = [driver.ShippingStreet]
        if driver.ShippingCity:
            address_parts.append(driver.ShippingCity)
        if driver.ShippingState:
            address_parts.append(driver.ShippingState)
        if driver.ShippingPostal:
            address_parts.append(driver.ShippingPostal)
        if driver.ShippingCountry:
            address_parts.append(driver.ShippingCountry)
        shipping_address = ", ".join(address_parts)
    
    # Build profile image URL - use S3 service to get presigned URL or local URL
    from app.services.s3_service import get_avatar_url
    profile_image_url = get_avatar_url(current_user.ProfileImageURL)
    if not profile_image_url:
        # Fallback to default avatar
        from flask import url_for
        profile_image_url = url_for('static', filename='img/default_avatar.svg')
    
    return jsonify({
        "success": True,
        "profile": {
            "accountId": current_user.AccountID,
            "driverId": driver.DriverID,
            "email": current_user.Email,
            "username": current_user.Username,
            "firstName": current_user.FirstName,
            "lastName": current_user.LastName,
            "wholeName": current_user.WholeName,
            "pointsBalance": points_balance,
            "memberSince": current_user.CreatedAt.isoformat() if current_user.CreatedAt else None,
            "shippingAddress": shipping_address,
            "licenseNumber": driver.license_number_plain,
            "licenseIssueDate": driver.license_issue_date_plain,
            "licenseExpirationDate": driver.license_expiration_date_plain,
            "sponsorCompany": sponsor_name,
            "status": driver.Status,
            "age": driver.Age,
            "gender": driver.Gender,
            "profileImageURL": profile_image_url
        }
    })

@mobile_bp.put("/api/mobile/profile")
def mobile_update_profile():
    """Update driver profile information"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400
    
    try:
        driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
        if not driver:
            return jsonify({"success": False, "message": "Driver not found"}), 404
        
        # Update account information
        if "firstName" in data:
            current_user.FirstName = data["firstName"]
        if "lastName" in data:
            current_user.LastName = data["lastName"]
        if "wholeName" in data:
            current_user.WholeName = data["wholeName"]
        
        # Update driver shipping information
        if "shippingAddress" in data:
            # Parse shipping address (simple implementation)
            address_parts = data["shippingAddress"].split(",")
            if len(address_parts) >= 1:
                driver.ShippingStreet = address_parts[0].strip()
            if len(address_parts) >= 2:
                driver.ShippingCity = address_parts[1].strip()
            if len(address_parts) >= 3:
                driver.ShippingState = address_parts[2].strip()
            if len(address_parts) >= 4:
                driver.ShippingPostal = address_parts[3].strip()
            if len(address_parts) >= 5:
                driver.ShippingCountry = address_parts[4].strip()
        
        # Update license information
        if "licenseNumber" in data:
            driver.license_number_plain = data["licenseNumber"]
        if "licenseIssueDate" in data:
            driver.license_issue_date_plain = data["licenseIssueDate"]
        if "licenseExpirationDate" in data:
            driver.license_expiration_date_plain = data["licenseExpirationDate"]
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "Profile updated successfully"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error updating profile: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/profile/upload-picture")
@login_required
def mobile_upload_profile_picture():
    """Upload profile picture for mobile app"""
    from flask_login import current_user
    from app.services.s3_service import upload_avatar, delete_avatar, generate_presigned_url
    
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    try:
        if 'profile_image' not in request.files:
            return jsonify({"success": False, "message": "No file provided"}), 400
        
        file = request.files['profile_image']
        if not file or not file.filename:
            return jsonify({"success": False, "message": "No file selected"}), 400
        
        # Get old S3 key before updating (if it exists and is an S3 key)
        old_profile_image_url = current_user.ProfileImageURL
        old_s3_key = None
        if old_profile_image_url and not old_profile_image_url.startswith('uploads/'):
            # This is likely an S3 key (not a local path)
            old_s3_key = old_profile_image_url
        
        # Upload to S3
        try:
            s3_key = upload_avatar(file, current_user.AccountID)
        except ValueError as e:
            return jsonify({"success": False, "message": str(e)}), 400
        except Exception as e:
            current_app.logger.error(f"Error uploading to S3: {e}", exc_info=True)
            return jsonify({"success": False, "message": f"Failed to upload profile picture: {str(e)}"}), 500
        
        # Delete old avatar from S3 if it exists
        if old_s3_key:
            try:
                delete_avatar(old_s3_key)
            except Exception as e:
                # Log but don't fail - old avatar cleanup is not critical
                current_app.logger.warning(f"Failed to delete old avatar from S3: {e}")
        
        # Update account with new S3 key
        current_user.ProfileImageURL = s3_key
        db.session.commit()
        
        # Generate presigned URL for response
        presigned_url = generate_presigned_url(s3_key)
        if not presigned_url:
            current_app.logger.error(f"Failed to generate presigned URL for {s3_key}")
            return jsonify({"success": False, "message": "Failed to generate image URL"}), 500
        
        return jsonify({
            "success": True,
            "message": "Profile picture updated successfully",
            "profileImageURL": presigned_url
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error uploading profile picture: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Failed to upload profile picture: {str(e)}"}), 500

@mobile_bp.put("/api/mobile/change-password")
def mobile_change_password():
    """Change user password"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No data provided"}), 400
    
    current_password = data.get("currentPassword")
    new_password = data.get("newPassword")
    
    if not current_password or not new_password:
        return jsonify({"success": False, "message": "Current password and new password are required"}), 400
    
    # Verify current password
    if not bcrypt.check_password_hash(current_user.PasswordHash, current_password):
        return jsonify({"success": False, "message": "Current password is incorrect"}), 400
    
    # Validate new password
    if len(new_password) < 8:
        return jsonify({"success": False, "message": "New password must be at least 8 characters long"}), 400
    
    try:
        # Hash new password
        current_user.PasswordHash = bcrypt.generate_password_hash(new_password).decode('utf-8')
        
        # Log password change
        from app.models import PasswordHistory
        password_history = PasswordHistory(
            AccountID=current_user.AccountID,
            PasswordHash=current_user.PasswordHash,
            ChangedBy=current_user.AccountID,
            ChangeReason='self_change',
            IPAddress=request.remote_addr,
            UserAgent=request.headers.get('User-Agent')
        )
        db.session.add(password_history)
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "Password changed successfully"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error changing password: {str(e)}"}), 500

@mobile_bp.get("/api/mobile/catalog")
def mobile_catalog():
    """Get catalog data for mobile app with all filtering and sorting options"""
    from flask_login import current_user
    
    current_app.logger.info("=" * 80)
    current_app.logger.info("CATALOG REQUEST STARTED")
    current_app.logger.info(f"Request URL: {request.url}")
    current_app.logger.info(f"Request headers - Cookie: {request.headers.get('Cookie', 'N/A')[:200]}...")  # First 200 chars
    current_app.logger.info(f"Session ID: {session.get('_id', 'N/A')}")
    current_app.logger.info(f"Session - driver_sponsor_id: {session.get('driver_sponsor_id')}")
    current_app.logger.info(f"Session - sponsor_id: {session.get('sponsor_id')}")
    current_app.logger.info(f"Session - driver_id: {session.get('driver_id')}")
    current_app.logger.info(f"Session - sponsor_company: {session.get('sponsor_company')}")
    current_app.logger.info(f"Session permanent: {session.permanent}")
    current_app.logger.info(f"Session modified: {session.modified}")
    current_app.logger.info(f"All session keys: {list(session.keys())}")
    current_app.logger.info(f"Full session dict: {dict(session)}")
    
    if not current_user.is_authenticated:
        current_app.logger.error("User not authenticated")
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    # Get driver information
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        current_app.logger.error(f"Driver not found for AccountID: {current_user.AccountID}")
        return jsonify({"success": False, "message": "Driver not found"}), 404
    
    current_app.logger.info(f"Driver ID: {driver.DriverID}")
    
    env, sponsor_id, _ = _resolve_driver_environment(driver)
    current_app.logger.info(f"Resolved environment - DriverSponsorID: {env.DriverSponsorID if env else None}")
    current_app.logger.info(f"Resolved sponsor_id: {sponsor_id}")
    
    if not sponsor_id:
        current_app.logger.error("No sponsor assignment found")
        return jsonify({"success": False, "message": "No sponsor assignment found"}), 403
    
    current_app.logger.info(f"Using sponsor_id for catalog: {sponsor_id}")
    
    try:
        # Import required modules
        from app.driver_points_catalog.services.driver_query_service import (
            compose_effective_rules_for_driver,
            sponsor_enabled_driver_points,
            sponsor_enabled_filters_first,
        )
        from app.driver_points_catalog.services.points_service import price_to_points
        from app.sponsor_catalog.providers.ebay_provider import EbayProvider
        from app.models_sponsor_catalog import SponsorPinnedProduct, BlacklistedProduct
        
        # Check if sponsor has enabled driver points and filters
        if not sponsor_enabled_driver_points(sponsor_id) or not sponsor_enabled_filters_first(sponsor_id):
            return jsonify({"success": False, "message": "Catalog not available for this sponsor"}), 404
        
        # Get request parameters
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(100, int(request.args.get("page_size", 48))))
        sort = (request.args.get("sort") or "best_match").strip()
        q = (request.args.get("q") or "").strip() or None
        cats = request.args.getlist("cat[]") or request.args.getlist("cat") or None
        if cats:
            cats = [c for c in cats if str(c).strip()]
        
        def _parse_num(s):
            try:
                return float(s.strip()) if s and s.strip() else None
            except Exception:
                return None

        min_pts_raw = request.args.get("min_points")
        max_pts_raw = request.args.get("max_points")
        
        current_app.logger.info(f"===== MOBILE CATALOG REQUEST STARTING =====")
        current_app.logger.info(f"Raw query parameters - min_points: '{min_pts_raw}', max_points: '{max_pts_raw}'")
        current_app.logger.info(f"All query parameters: {dict(request.args)}")
        
        min_pts = _parse_num(min_pts_raw)
        max_pts = _parse_num(max_pts_raw)
        fav_only = request.args.get("favorites_only", "").strip().lower() == "true"
        
        current_app.logger.info(f"Parsed values - min_pts: {min_pts}, max_pts: {max_pts}, fav_only: {fav_only}")
        
        # Compose search rules
        rules = compose_effective_rules_for_driver(sponsor_id, driver_q=q, driver_cats=cats)
        provider = EbayProvider()
        
        # Get blacklisted products
        bl_ids = {str(b.ItemID) for b in BlacklistedProduct.query.filter_by(SponsorID=sponsor_id).all()}
        
        # Get pinned products
        pinned_only = rules.get("special_mode") == "pinned_only"
        current_app.logger.info(f"Fetching pinned products for sponsor_id: {sponsor_id}")
        pinned = _fetch_pinned_products(sponsor_id, provider)
        current_app.logger.info(f"Found {len(pinned)} pinned products")
        
        valid_pinned = []
        for it in pinned:
            if str(it.get("id")) in bl_ids:
                continue
            price = it.get("price")
            it["points"] = price_to_points(sponsor_id, float(price)) if price else None
            it.pop("price", None)
            it.pop("currency", None)
            valid_pinned.append(it)
        pinned_ids = {str(it.get("id")) for it in valid_pinned}
        
        # Get regular catalog items
        if pinned_only:
            combined = valid_pinned
        else:
            res = provider.search_extended(
                rules, page=page, page_size=page_size,
                sort=sort, strict_total=True)
            items = res.get("items", []) or []
            valid = []
            for it in items:
                iid = str(it.get("id"))
                if iid in bl_ids:
                    continue
                # Only exclude pinned items from regular search results if they're already in pinned list
                if iid in pinned_ids and (not q or not q.strip()):
                    continue
                price = it.get("price")
                it["points"] = price_to_points(sponsor_id, float(price)) if price else None
                it.pop("price", None)
                it.pop("currency", None)
                if iid in pinned_ids:
                    it["is_pinned"] = True
                    for p in valid_pinned:
                        if str(p.get("id")) == iid:
                            it["pin_rank"] = p.get("pin_rank")
                            break
                valid.append(it)
            # Only show pinned items when not searching
            if q and q.strip():
                # When searching, ONLY show search results (no pinned items)
                combined = valid
            else:
                # When browsing, show pinned first, then regular results
                combined = valid_pinned + valid
        
        # Apply point range filtering
        if min_pts is not None or max_pts is not None:
            filtered_items = []
            current_app.logger.info(f"===== APPLYING POINT RANGE FILTER =====")
            current_app.logger.info(f"Filter criteria: min_pts={min_pts}, max_pts={max_pts}")
            current_app.logger.info(f"Total items before filter: {len(combined)}")
            
            # Show sample of item points
            sample_items = []
            for item in combined[:10]:
                points = item.get("points")
                sample_items.append({
                    "id": item.get("id", "unknown"),
                    "title": item.get("title", "unknown")[:50],
                    "points": points
                })
            current_app.logger.info(f"Sample of items before filtering: {sample_items}")
            
            for item in combined:
                points = item.get("points")
                # Skip items without points when filtering by point range
                if points is None:
                    continue
                # Convert points to float for comparison
                try:
                    points_float = float(points)
                except (TypeError, ValueError):
                    current_app.logger.warning(f"Item {item.get('id', 'unknown')} has invalid points value: {points}")
                    continue
                    
                # Check min points filter
                if min_pts is not None:
                    if points_float < min_pts:
                        current_app.logger.debug(f"Skipping item {item.get('id', 'unknown')} ({item.get('title', 'unknown')[:30]}): points {points_float} < min {min_pts}")
                        continue
                # Check max points filter
                if max_pts is not None:
                    if points_float > max_pts:
                        current_app.logger.debug(f"Skipping item {item.get('id', 'unknown')} ({item.get('title', 'unknown')[:30]}): points {points_float} > max {max_pts}")
                        continue
                filtered_items.append(item)
            
            current_app.logger.info(f"===== FILTERING COMPLETE =====")
            current_app.logger.info(f"Items after filter: {len(filtered_items)}")
            
            # Show sample of items after filtering
            filtered_sample = []
            for item in filtered_items[:10]:
                points = item.get("points")
                filtered_sample.append({
                    "id": item.get("id", "unknown"),
                    "title": item.get("title", "unknown")[:50],
                    "points": points
                })
            current_app.logger.info(f"Sample of items after filtering: {filtered_sample}")
            
            combined = filtered_items
        
        # Apply client-side sorting for points-based sorting
        if sort == "points_asc":
            combined.sort(key=lambda x: x.get("points", 0) or 0)
        elif sort == "points_desc":
            combined.sort(key=lambda x: x.get("points", 0) or 0, reverse=True)
        
        # Add low stock flags and favorites data
        _inject_low_stock_flags(combined)
        _inject_favorites_data(combined, driver.DriverID)
        
        # Apply favorites filter if requested
        if fav_only:
            # If favorites_only is true and no search query, fetch ALL favorites from database
            if not q:
                from app.models_favorites import DriverFavorites
                # Get all favorite item IDs for this driver
                favorites = DriverFavorites.query.filter_by(
                    DriverID=driver.DriverID
                ).all()
                
                if favorites:
                    favorite_item_ids = [fav.ExternalItemID for fav in favorites]
                    # Fetch product details for all favorite items from eBay
                    favorite_items = []
                    for item_id in favorite_item_ids:
                        try:
                            item_data = provider.get_item_details(item_id)
                            if item_data:
                                # Convert to points
                                price = item_data.get("price")
                                if price:
                                    try:
                                        points = price_to_points(sponsor_id, float(price))
                                        item_data["points"] = points
                                    except Exception:
                                        item_data["points"] = None
                                else:
                                    item_data["points"] = None
                                item_data.pop("price", None)
                                item_data.pop("currency", None)
                                
                                # Filter out blacklisted items
                                if str(item_data.get("id", "")) not in bl_ids:
                                    favorite_items.append(item_data)
                        except Exception as e:
                            current_app.logger.warning(f"Could not fetch favorite item {item_id}: {e}")
                            continue
                    
                    # Mark all as favorites
                    for item in favorite_items:
                        item["is_favorite"] = True
                    
                    # Add low stock flags
                    _inject_low_stock_flags(favorite_items)
                    
                    # Sort favorites (most recent first by default, or by requested sort)
                    if sort == "best_match":
                        # Keep original order (most recently added)
                        pass
                    elif sort == "points_asc":
                        favorite_items.sort(key=lambda x: (x.get("points") or float('inf'), x.get("title", "")))
                    elif sort == "points_desc":
                        favorite_items.sort(key=lambda x: (-(x.get("points") or -1), x.get("title", "")))
                    elif sort == "title_asc":
                        favorite_items.sort(key=lambda x: (x.get("title", "") or ""))
                    elif sort == "title_desc":
                        favorite_items.sort(key=lambda x: (x.get("title", "") or ""), reverse=True)
                    
                    # Apply pagination
                    total_items = len(favorite_items)
                    start_idx = (page - 1) * page_size
                    end_idx = start_idx + page_size
                    paginated_items = favorite_items[start_idx:end_idx]
                    
                    return jsonify({
                        "success": True,
                        "items": paginated_items,
                        "page": page,
                        "page_size": page_size,
                        "total": total_items,
                        "has_more": end_idx < total_items
                    })
                else:
                    # No favorites found
                    return jsonify({
                        "success": True,
                        "items": [],
                        "page": page,
                        "page_size": page_size,
                        "total": 0,
                        "has_more": False
                    })
            else:
                # Search query exists - filter the search results for favorites
                combined = [item for item in combined if item.get("is_favorite", False)]
        
        # For search results, use eBay's pagination info
        if q and q.strip():
            # When searching, apply client-side pagination to filtered results
            total_items = len(combined)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_items = combined[start_idx:end_idx]
            has_more = end_idx < total_items
            
            current_app.logger.info(f"Search results pagination - page {page}, showing {len(paginated_items)} items out of {total_items} total")
            
            return jsonify({
                "success": True,
                "items": paginated_items,
                "page": page,
                "page_size": page_size,
                "total": total_items,
                "has_more": has_more
            })
        else:
            # For browsing (with pinned items), use client-side pagination
            total_items = len(combined)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            paginated_items = combined[start_idx:end_idx]
            
            return jsonify({
                "success": True,
                "items": paginated_items,
                "page": page,
                "page_size": page_size,
                "total": total_items,
                "has_more": end_idx < total_items
            })
        
    except Exception as e:
        current_app.logger.error(f"Error loading mobile catalog: {e}")
        return jsonify({"success": False, "message": f"Failed to load catalog: {str(e)}"}), 500

def _fetch_pinned_products(sponsor_id: str, provider):
    """Fetch sponsor-pinned products"""
    from app.models_sponsor_catalog import SponsorPinnedProduct
    
    pinned = SponsorPinnedProduct.query.filter_by(SponsorID=sponsor_id).order_by(SponsorPinnedProduct.PinRank).all()
    items = []
    
    for pin in pinned:
        try:
            item_data = provider.get_item_details(pin.ItemID)
            if item_data:
                item_data["pin_rank"] = pin.PinRank
                item_data["is_pinned"] = True
                items.append(item_data)
        except Exception as e:
            current_app.logger.warning(f"Failed to fetch pinned item {pin.ItemID}: {e}")
    
    return items

def _inject_low_stock_flags(items):
    """Add low stock availability flags to items"""
    for item in items:
        availability = item.get("availability_threshold", "")
        if "OUT_OF_STOCK" in str(availability).upper():
            item["availability"] = "OUT_OF_STOCK"
        elif "LIMITED" in str(availability).upper() or "LOW" in str(availability).upper():
            item["availability"] = "LIMITED"
        else:
            item["availability"] = "IN_STOCK"

def _inject_favorites_data(items, driver_id: str):
    """Add favorites data to items"""
    from app.models_favorites import DriverFavorites
    
    if not driver_id:
        return
    
    # Get all item IDs
    item_ids = [str(item.get("id")) for item in items if item.get("id")]
    if not item_ids:
        return
    
    # Query favorites in batch
    favorites = DriverFavorites.query.filter(
        DriverFavorites.DriverID == driver_id,
        DriverFavorites.ExternalItemID.in_(item_ids)
    ).all()
    
    favorite_ids = {fav.ExternalItemID for fav in favorites}
    
    # Mark items as favorites
    for item in items:
        item["is_favorite"] = str(item.get("id")) in favorite_ids

@mobile_bp.get("/api/mobile/catalog/categories")
@login_required
def mobile_catalog_categories():
    """Get available categories from sponsor's selected filter set for mobile app."""
    try:
        from app.driver_points_catalog.services.driver_query_service import (
            _fetch_selected_set_for_sponsor,
            _load_json_maybe
        )
        from app.sponsor_catalog.services.category_service import resolve as resolve_categories
        from app.sponsor_catalog.policies import ADULT_CATEGORY_IDS
        
        driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
        if not driver:
            return jsonify({"success": False, "message": "Driver not found"}), 404
        
        env, sponsor_id, _ = _resolve_driver_environment(driver)
        if not sponsor_id:
            return jsonify({"success": False, "message": "No sponsor assignment found"}), 403
        
        # Get selected filter set
        sets = _fetch_selected_set_for_sponsor(sponsor_id)
        
        current_app.logger.debug(f"Mobile categories request for sponsor {sponsor_id}: found {len(sets)} filter set(s)")
        
        if not sets:
            current_app.logger.warning(f"No filter sets found for sponsor {sponsor_id}")
            return jsonify({"categories": []})
        
        # Helper function to get attribute
        def _get_attr(obj, *names):
            for n in names:
                if hasattr(obj, n):
                    return getattr(obj, n)
            return None
        
        # Extract categories from filter set
        category_ids = set()
        for fs in sets:
            filter_set_id = _get_attr(fs, "ID", "id")
            rules_raw = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config")
            rules = _load_json_maybe(rules_raw) if rules_raw else {}
            
            cats = ((rules.get("categories") or {}).get("include") or [])
            current_app.logger.debug(f"Found {len(cats)} categories in filter set {filter_set_id}")
            
            if cats:
                resolved = set(resolve_categories(cats))
                if not category_ids:
                    category_ids = resolved
                else:
                    category_ids = category_ids & resolved
        
        if not category_ids:
            return jsonify({"categories": []})
        
        # Load category ID to name mapping
        import os
        import json
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ebay_categories_tree.json")
        
        category_map = {}
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    tree_data = json.load(f)
                
                def extract_categories(node, cat_map):
                    cat = node.get("category", {})
                    cat_id = cat.get("categoryId")
                    cat_name = cat.get("categoryName", "")
                    if cat_id and cat_id != "0":
                        cat_map[str(cat_id)] = cat_name
                    
                    for child in node.get("childCategoryTreeNodes", []):
                        extract_categories(child, cat_map)
                
                root = tree_data.get("rootCategoryNode", {})
                extract_categories(root, category_map)
            except Exception as e:
                current_app.logger.warning(f"Error loading category names: {e}")
        
        # Check if exclude_explicit is enabled
        exclude_explicit = False
        for fs in sets:
            rules_raw = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config")
            rules = _load_json_maybe(rules_raw) if rules_raw else {}
            if rules.get("safety", {}).get("exclude_explicit"):
                exclude_explicit = True
                break
        
        # Filter out adult categories if exclude_explicit is enabled
        if exclude_explicit:
            original_count = len(category_ids)
            adult_cats_found = category_ids & ADULT_CATEGORY_IDS
            category_ids = category_ids - ADULT_CATEGORY_IDS
            current_app.logger.info(
                f"[ADULT_FILTER] Mobile categories - exclude_explicit=True: "
                f"Filtered out {len(adult_cats_found)} adult categories "
                f"({original_count} -> {len(category_ids)})"
            )
        
        # Extract parent category IDs (simplified version)
        def _extract_parent_category_ids(allowed_category_ids):
            """Extract parent category IDs for categories that have allowed children."""
            import os
            import json
            
            json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ebay_categories_tree.json")
            parent_map = {}
            
            if not os.path.exists(json_path):
                return parent_map
            
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    tree_data = json.load(f)
                
                def traverse_tree(node, parent_id=None, parent_name=None):
                    cat = node.get("category", {})
                    cat_id = cat.get("categoryId", "")
                    cat_name = cat.get("categoryName", "")
                    children = node.get("childCategoryTreeNodes", [])
                    
                    if cat_id and cat_id != "0":
                        has_allowed_child = False
                        for child in children:
                            child_cat = child.get("category", {})
                            child_id = child_cat.get("categoryId", "")
                            if str(child_id) in allowed_category_ids:
                                has_allowed_child = True
                                break
                            if child.get("childCategoryTreeNodes"):
                                if _has_allowed_descendant(child, allowed_category_ids):
                                    has_allowed_child = True
                                    break
                        
                        if has_allowed_child and str(cat_id) not in allowed_category_ids:
                            parent_map[cat_name] = str(cat_id)
                        
                        for child in children:
                            traverse_tree(child, cat_id, cat_name)
                
                def _has_allowed_descendant(node, allowed_ids):
                    cat = node.get("category", {})
                    cat_id = cat.get("categoryId", "")
                    if str(cat_id) in allowed_ids:
                        return True
                    for child in node.get("childCategoryTreeNodes", []):
                        if _has_allowed_descendant(child, allowed_ids):
                            return True
                    return False
                
                root = tree_data.get("rootCategoryNode", {})
                traverse_tree(root)
            except Exception as e:
                current_app.logger.warning(f"Error extracting parent category IDs: {e}")
            
            return parent_map
        
        parent_category_map = _extract_parent_category_ids(category_ids)
        
        # Add parent categories to the allowed set
        skipped_parents = []
        for parent_name, parent_id in parent_category_map.items():
            if exclude_explicit and str(parent_id) in ADULT_CATEGORY_IDS:
                skipped_parents.append(f"{parent_name} ({parent_id})")
                continue
            category_ids.add(parent_id)
            if str(parent_id) not in category_map:
                category_map[str(parent_id)] = parent_name
        
        # Build category list with hierarchy
        # Use the same category tree processing as the sponsor catalog
        from app.sponsor_catalog.routes import _process_category_tree
        import os
        import json
        json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ebay_categories_tree.json")
        
        filtered_tree = {}
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    tree_data = json.load(f)
                
                # Process the tree using the same function as sponsor catalog
                full_tree = _process_category_tree(tree_data.get("rootCategoryNode", {}), exclude_explicit=exclude_explicit)
                
                # Filter the tree to only include paths to allowed categories
                def filter_tree_for_allowed(node_data, allowed_ids, result=None):
                    """Recursively filter category tree to only show paths to allowed categories."""
                    if result is None:
                        result = {}
                    
                    if isinstance(node_data, dict):
                        for category_name, subcategories in node_data.items():
                            if isinstance(subcategories, dict):
                                # Check if all values are strings (leaf categories)
                                values = list(subcategories.values())
                                if values and all(isinstance(v, str) for v in values):
                                    # Leaf categories - filter to only allowed ones
                                    filtered = {k: v for k, v in subcategories.items() if k in allowed_ids}
                                    if filtered:
                                        result[category_name] = filtered
                                else:
                                    # Nested structure - recurse
                                    nested_result = filter_tree_for_allowed(subcategories, allowed_ids, {})
                                    if nested_result:
                                        result[category_name] = nested_result
                    
                    return result
                
                # Filter the full tree to only show allowed categories
                filtered_tree = filter_tree_for_allowed(full_tree, category_ids)
            except Exception as e:
                current_app.logger.warning(f"Error loading category tree: {e}")
                filtered_tree = {}
        
        # Also build flat list for backward compatibility
        categories = []
        for cat_id in sorted(category_ids, key=lambda x: category_map.get(str(x), str(x))):
            if exclude_explicit and str(cat_id) in ADULT_CATEGORY_IDS:
                continue
            is_parent = str(cat_id) in parent_category_map.values()
            categories.append({
                "id": str(cat_id),
                "name": category_map.get(str(cat_id), f"Category {cat_id}"),
                "is_parent": is_parent
            })
        
        return jsonify({
            "categories": categories,  # Flat list for backward compatibility
            "category_tree": filtered_tree,  # Hierarchical tree structure
            "parent_categories": {name: id for name, id in parent_category_map.items()}
        })
    except Exception as e:
        current_app.logger.error(f"Error loading mobile categories: {e}", exc_info=True)
        return jsonify({"error": "Failed to load categories.", "categories": []}), 500

@mobile_bp.post("/api/mobile/favorites")
def mobile_add_favorite():
    """Add item to favorites"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    # Get driver information
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        return jsonify({"success": False, "message": "Driver not found"}), 404
    
    data = request.get_json()
    if not data or not data.get("item_id"):
        return jsonify({"success": False, "message": "Item ID is required"}), 400
    
    try:
        from app.models_favorites import DriverFavorites
        
        item_id = data["item_id"]
        
        # Check if already favorited
        existing = DriverFavorites.query.filter_by(
            DriverID=driver.DriverID,
            ExternalItemID=item_id
        ).first()
        
        if existing:
            return jsonify({"success": True, "message": "Already in favorites"})
        
        # Add to favorites
        favorite = DriverFavorites(
            DriverID=driver.DriverID,
            ExternalItemID=item_id
        )
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({"success": True, "message": "Added to favorites"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error adding to favorites: {str(e)}"}), 500

@mobile_bp.delete("/api/mobile/favorites/<item_id>")
def mobile_remove_favorite(item_id: str):
    """Remove item from favorites"""
    from flask_login import current_user
    
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    # Get driver information
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        return jsonify({"success": False, "message": "Driver not found"}), 404
    
    try:
        from app.models_favorites import DriverFavorites
        
        # Find and remove favorite
        favorite = DriverFavorites.query.filter_by(
            DriverID=driver.DriverID,
            ExternalItemID=item_id
        ).first()
        
        if not favorite:
            return jsonify({"success": False, "message": "Not in favorites"}), 404
        
        db.session.delete(favorite)
        db.session.commit()
        
        return jsonify({"success": True, "message": "Removed from favorites"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error removing from favorites: {str(e)}"}), 500

@mobile_bp.get("/api/mobile/product/<path:item_id>")
def mobile_product_detail(item_id: str):
    """Get detailed product information for mobile app"""
    from flask_login import current_user
    from urllib.parse import unquote
    
    if not current_user.is_authenticated:
        return jsonify({"success": False, "message": "Not authenticated"}), 401
    
    # Get driver information
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        return jsonify({"success": False, "message": "Driver not found"}), 404
    
    env, sponsor_id, _ = _resolve_driver_environment(driver)
    if not sponsor_id:
        return jsonify({"success": False, "message": "No sponsor assignment found"}), 403
    
    # Decode URL-encoded item ID (handles pipe characters and special chars)
    item_id = unquote(item_id)
    driver_id = driver.DriverID
    
    try:
        from app.sponsor_catalog.providers.ebay_provider import EbayProvider
        from app.driver_points_catalog.services.points_service import price_to_points
        from app.models_favorites import DriverFavorites
        
        provider = EbayProvider()
        
        # Fetch full item details from eBay
        current_app.logger.info(f"Mobile: Driver viewing product details for item_id: {item_id}")
        item_data = provider.get_item_details(item_id)
        
        if not item_data:
            current_app.logger.error(f"Product not found: {item_id}")
            return jsonify({"success": False, "message": "Product not found"}), 404
        
        current_app.logger.info(f"Product data retrieved: {item_data.get('title', 'No title')}")
        
        # Convert price to points for drivers
        price = item_data.get("price")
        if price:
            try:
                points = price_to_points(sponsor_id, float(price))
                item_data["points"] = points
                item_data["display_points"] = f"{points} pts"
            except (ValueError, TypeError):
                current_app.logger.warning(f"Could not convert price to points: {price}")
                item_data["points"] = None
                item_data["display_points"] = "N/A"
        else:
            item_data["points"] = None
            item_data["display_points"] = "N/A"
        
        # Clean up description - remove shipping, payment, return policy info
        description = item_data.get("description", "")
        if description:
            import re
            remove_patterns = [
                r'(?i)(shipping|shipment).*?(?=\n\n|\Z)',
                r'(?i)(payment|pay).*?(?=\n\n|\Z)',
                r'(?i)(return|refund).*?(?=\n\n|\Z)',
                r'(?i)(warranty|guarantee).*?(?=\n\n|\Z)',
                r'(?i)(seller|store) (policy|policies|information).*?(?=\n\n|\Z)',
                r'(?i)(terms and conditions|t&c|tos).*?(?=\n\n|\Z)',
            ]
            for pattern in remove_patterns:
                description = re.sub(pattern, '', description, flags=re.DOTALL | re.MULTILINE)
            description = re.sub(r'\n{3,}', '\n\n', description).strip()
            item_data["description"] = description
        
        # Ensure all required fields have defaults
        item_data.setdefault("image", "")
        item_data.setdefault("additional_images", [])
        item_data.setdefault("subtitle", "")
        item_data.setdefault("description", "")
        item_data.setdefault("condition", "")
        item_data.setdefault("brand", "")
        item_data.setdefault("seller", {})
        item_data.setdefault("item_specifics", {})
        item_data.setdefault("variants", {})
        item_data.setdefault("url", "")
        item_data.setdefault("variation_details", [])
        
        # Check if this product is favorited
        if driver_id:
            favorite = DriverFavorites.query.filter_by(
                DriverID=driver_id,
                ExternalItemID=item_id
            ).first()
            item_data["is_favorite"] = favorite is not None
        else:
            item_data["is_favorite"] = False
        
        # Apply low stock flags using same logic as driver catalog
        def _inject_low_stock_flags(items: list[dict]) -> None:
            """Inject availability flags based on eBay API data."""
            threshold = int(current_app.config.get("LOW_STOCK_THRESHOLD", 10))
            for it in items:
                est = it.get("estimated_quantity")
                th = it.get("availability_threshold")
                it.update({"stock_qty": None, "low_stock": False, "no_stock": False, "available": False})
                if est is not None:
                    try:
                        qty = int(est)
                        it["stock_qty"] = qty
                        if qty == 0:
                            it["no_stock"] = True
                        elif 0 < qty < threshold:
                            it["low_stock"] = True
                        elif qty >= 10:
                            it["available"] = True
                    except Exception:
                        pass
                elif th:
                    th_str = str(th).upper()
                    if "OUT_OF_STOCK" in th_str:
                        it["no_stock"] = True
                    elif "LIMITED" in th_str or "LOW" in th_str:
                        it["low_stock"] = True
                    else:
                        it["available"] = True
                else:
                    it["available"] = True
        
        _inject_low_stock_flags([item_data])
        
        # Also apply to variation_details if they exist
        if item_data.get("variation_details"):
            for variation in item_data["variation_details"]:
                _inject_low_stock_flags([variation])
        
        # Fetch related items using first 3 words from title
        related_items = []
        try:
            title_words = item_data.get("title", "").split()[:3]  # First 3 words
            search_query = " ".join(title_words) if title_words else None
            
            current_app.logger.info(f"Fetching related items with query: {search_query}")
            
            # Simple search with just the keywords, no complex filter rules
            if search_query:
                rules = {
                    "keywords": {"must": [search_query]},
                    "safety": {"exclude_explicit": True}
                }
            else:
                rules = {"safety": {"exclude_explicit": True}}
            
            related_res = provider.search(rules, page=1, page_size=10, sort="best_match")
            related_items = related_res.get("items", [])
            
            current_app.logger.info(f"Found {len(related_items)} related items before filtering")
            
            # Filter out current item and convert prices to points
            related_items = [
                it for it in related_items
                if str(it.get("id")) != str(item_id)
            ][:5]
            
            for item in related_items:
                price = item.get("price")
                if price:
                    try:
                        item["points"] = price_to_points(sponsor_id, float(price))
                    except (ValueError, TypeError):
                        item["points"] = None
                else:
                    item["points"] = None
                item.pop("price", None)
                item.pop("currency", None)
            
            current_app.logger.info(f"Showing {len(related_items)} related items after filtering")
            
            # Apply low stock flags to related items
            _inject_low_stock_flags(related_items)
            
        except Exception as e:
            current_app.logger.error(f"Error fetching related items: {e}", exc_info=True)
        
        # Return JSON response
        return jsonify({
            "success": True,
            "product": item_data,
            "related_items": related_items
        })
        
    except Exception as e:
        current_app.logger.error(f"Error loading product detail: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading product details: {str(e)}"}), 500

# ========== Notification API Endpoints ==========

def _get_driver_for_mobile():
    """Get driver for mobile API - ensures user is authenticated driver."""
    if not current_user.is_authenticated:
        return None, jsonify({"success": False, "message": "Not authenticated"}), 401
    
    driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
    if not driver:
        return None, jsonify({"success": False, "message": "Driver not found"}), 404
    
    return driver, None, None


def _parse_iso8601(value: str):
    """Parse ISO-8601 date/time strings (with optional Z)."""
    if not value:
        return None
    try:
        cleaned = value.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


@mobile_bp.get("/api/mobile/notifications")
@login_required
def mobile_list_notifications():
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code

    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = int(
            request.args.get(
                "pageSize", DriverNotificationService.DEFAULT_PAGE_SIZE
            )
        )
    except ValueError:
        return jsonify({"success": False, "message": "Invalid pagination values"}), 400

    page_size = max(1, min(page_size, DriverNotificationService.MAX_PAGE_SIZE))
    unread_only = str(request.args.get("unreadOnly", "")).lower() in ("1", "true", "yes")
    since_param = request.args.get("since")
    since_dt = None
    if since_param:
        since_dt = _parse_iso8601(since_param)
        if not since_dt:
            return jsonify({"success": False, "message": "Invalid since parameter"}), 400

    notifications, total = DriverNotificationService.fetch_notifications(
        driver.DriverID,
        page=page,
        page_size=page_size,
        unread_only=unread_only,
        since=since_dt,
    )
    items = [
        DriverNotificationService.serialize_notification(notification)
        for notification in notifications
    ]
    has_more = page * page_size < total
    return jsonify(
        {
            "success": True,
            "notifications": items,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "hasMore": has_more,
            },
        }
    )


@mobile_bp.post("/api/mobile/notifications/mark-read")
@login_required
def mobile_mark_notifications_read():
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code

    data = request.get_json() or {}
    mark_all = bool(data.get("markAll"))
    notification_ids = data.get("notificationIds") or []

    if not mark_all:
        if not isinstance(notification_ids, list) or not notification_ids:
            return jsonify(
                {
                    "success": False,
                    "message": "Provide notificationIds array or set markAll=true",
                }
            ), 400
    else:
        notification_ids = None

    updated = DriverNotificationService.mark_notifications_read(
        driver.DriverID, notification_ids
    )
    return jsonify({"success": True, "updated": updated})


@mobile_bp.get("/api/mobile/notifications/preferences")
@login_required
def mobile_get_notification_preferences():
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code

    prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
    return jsonify(
        {
            "success": True,
            "preferences": DriverNotificationService.serialize_preferences(prefs),
        }
    )


@mobile_bp.put("/api/mobile/notifications/preferences")
@login_required
def mobile_update_notification_preferences():
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code

    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Invalid JSON payload"}), 400

    prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
    updated_prefs = DriverNotificationService.update_preferences_from_payload(prefs, data)
    return jsonify(
        {
            "success": True,
            "preferences": DriverNotificationService.serialize_preferences(updated_prefs),
        }
    )


@mobile_bp.post("/api/mobile/notifications/test-low-points")
@login_required
def mobile_test_low_points_notification():
    if not (current_app.debug or current_app.config.get("TESTING")):
        return jsonify({"success": False, "message": "Endpoint disabled"}), 403

    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code

    data = request.get_json() or {}
    prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
    balance = int(data.get("balance", prefs.LowPointsThreshold or 50))
    threshold = int(data.get("threshold", prefs.LowPointsThreshold or 100))

    from app.services.notification_service import NotificationService

    NotificationService.notify_driver_low_points(driver.DriverID, balance, threshold)
    return jsonify(
        {
            "success": True,
            "message": "Low points notification enqueued",
            "payload": {"balance": balance, "threshold": threshold},
        }
    )


@mobile_bp.get("/api/mobile/driver-sponsors")
@login_required
def mobile_list_driver_sponsors():
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code

    # Use _resolve_driver_environment to get the current environment
    # This ensures we get the correct active sponsor, even if session is stale
    current_env, _, _ = _resolve_driver_environment(driver)
    current_env_id = str(current_env.DriverSponsorID) if current_env else None
    
    # Only return ACTIVE environments (accepted sponsors)
    envs = (
        DriverSponsor.query.options(
            joinedload(DriverSponsor.sponsor),
            joinedload(DriverSponsor.sponsor_company),
        )
        .filter_by(DriverID=driver.DriverID, Status="ACTIVE")
        .order_by(DriverSponsor.CreatedAt.asc())
        .all()
    )
    serialized = [
        _serialize_driver_sponsor_environment(env, current_env_id) for env in envs
    ]
    return jsonify(
        {
            "success": True,
            "currentDriverSponsorId": current_env_id,
            "sponsors": serialized,
            "hasMultiple": len(serialized) > 1,
        }
    )


# ========== Cart API Endpoints ==========

def _resolve_driver_environment(driver: Driver):
    """Resolve the driver's current sponsor environment and company context.

    Returns a tuple of (environment, sponsor_id, sponsor_company_id).
    
    Always uses the most recently accepted sponsor environment (by UpdatedAt/CreatedAt).
    """
    current_app.logger.info("_resolve_driver_environment called")
    current_app.logger.info(f"Driver ID: {driver.DriverID}")
    
    # Always find the most recently accepted active sponsor environment
    env = (
        DriverSponsor.query
        .filter_by(DriverID=driver.DriverID, Status="ACTIVE")
        .order_by(DriverSponsor.UpdatedAt.desc(), DriverSponsor.CreatedAt.desc())
        .first()
    )
    
    # If no active environment, try any environment as last resort
    if not env:
        current_app.logger.info("No active environment found, trying last resort query...")
        env = (
            DriverSponsor.query
            .filter_by(DriverID=driver.DriverID)
            .order_by(DriverSponsor.UpdatedAt.desc(), DriverSponsor.CreatedAt.desc())
            .first()
        )
    
    if env:
        # Update session with the found environment
        session['driver_sponsor_id'] = str(env.DriverSponsorID)
        session['sponsor_id'] = str(env.SponsorID)
        if env.sponsor:
            session['sponsor_company'] = env.sponsor.Company
        session.modified = True
        current_app.logger.info(
            f"Using most recently accepted environment {env.DriverSponsorID} for driver {driver.DriverID}"
        )
    else:
        current_app.logger.warning(f"No sponsor environment found for driver {driver.DriverID}")

    sponsor_id = env.SponsorID if env else None
    sponsor_company_id = env.SponsorCompanyID if env and env.SponsorCompanyID else driver.SponsorCompanyID
    
    current_app.logger.info(f"_resolve_driver_environment result: env={env.DriverSponsorID if env else None}, sponsor_id={sponsor_id}, sponsor_company_id={sponsor_company_id}")
    
    return env, sponsor_id, sponsor_company_id


def _serialize_driver_sponsor_environment(env: DriverSponsor, current_env_id: str | None):
    sponsor = getattr(env, "sponsor", None)
    sponsor_company = getattr(env, "sponsor_company", None)
    status_value = (env.Status or "").upper()
    return {
        "driverSponsorId": env.DriverSponsorID,
        "driverId": env.DriverID,
        "sponsorId": env.SponsorID,
        "sponsorCompanyId": env.SponsorCompanyID,
        "sponsorName": sponsor.Company if sponsor else None,
        "sponsorCompanyName": sponsor_company.CompanyName if sponsor_company else None,
        "status": status_value,
        "pointsBalance": int(env.PointsBalance or 0),
        "joinedAt": env.CreatedAt.isoformat() if env.CreatedAt else None,
        "updatedAt": env.UpdatedAt.isoformat() if env.UpdatedAt else None,
        "isActive": status_value == "ACTIVE",
        "isCurrent": current_env_id == env.DriverSponsorID,
    }

def _get_or_create_cart_mobile(driver_id: str):
    """Get existing cart or create a new one for the driver."""
    cart = Cart.query.filter_by(DriverID=driver_id).first()
    if not cart:
        cart = Cart(DriverID=driver_id)
        db.session.add(cart)
        db.session.commit()
    return cart

def _get_driver_points_balance_mobile():
    """Get the current driver's points balance from their selected environment."""
    try:
        driver_sponsor_id = session.get('driver_sponsor_id')
        if driver_sponsor_id:
            env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
            if env:
                return env.PointsBalance or 0
    except Exception:
        pass
    return 0

@mobile_bp.get("/api/mobile/cart")
@login_required
def mobile_get_cart():
    """Get current cart contents for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        cart = _get_or_create_cart_mobile(driver.DriverID)
        cart_items = CartItem.query.filter_by(CartID=cart.CartID).all()
        
        items_data = []
        for item in cart_items:
            items_data.append({
                "cart_item_id": item.CartItemID,
                "external_item_id": item.ExternalItemID,
                "item_title": item.ItemTitle,
                "item_image_url": item.ItemImageURL or "",
                "item_url": item.ItemURL or "",
                "points_per_unit": item.PointsPerUnit,
                "quantity": item.Quantity,
                "line_total_points": item.PointsPerUnit * item.Quantity
            })
        
        driver_points = _get_driver_points_balance_mobile()
        
        return jsonify({
            "success": True,
            "cart": {
                "cart_id": cart.CartID,
                "total_points": cart.total_points,
                "item_count": cart.item_count,
                "driver_points": driver_points,
                "items": items_data
            }
        })
    except Exception as e:
        current_app.logger.error(f"Error getting cart: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading cart: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/cart/add")
@login_required
def mobile_add_to_cart():
    """Add item to cart for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data provided"}), 400
        
        external_item_id = data.get("external_item_id")
        item_title = data.get("item_title", "")
        item_image_url = data.get("item_image_url", "")
        item_url = data.get("item_url", "")
        points_per_unit = int(data.get("points_per_unit", 0))
        quantity = int(data.get("quantity", 1))
        
        # Validate inputs
        if not external_item_id or not isinstance(external_item_id, str):
            return jsonify({"success": False, "message": "Invalid item ID"}), 400
        
        # Normalize external_item_id: strip whitespace and ensure consistent format
        external_item_id = external_item_id.strip()
        # Truncate to 100 chars but preserve the structure (base::variation)
        if len(external_item_id) > 100:
            # If it contains ::, try to preserve the variation part
            if '::' in external_item_id:
                base_part = external_item_id.split('::', 1)[0]
                variation_part = external_item_id.split('::', 1)[1]
                # Keep base part and as much of variation as possible
                max_base = min(50, len(base_part))
                max_var = min(100 - max_base - 2, len(variation_part))  # -2 for ::
                external_item_id = base_part[:max_base] + '::' + variation_part[:max_var]
            else:
                external_item_id = external_item_id[:100]
        
        item_title = item_title.strip()[:500] if item_title else ""
        item_image_url = item_image_url.strip()[:1000] if item_image_url else ""
        item_url = item_url.strip()[:1000] if item_url else ""
        
        if points_per_unit <= 0 or quantity <= 0 or quantity > 100:
            return jsonify({"success": False, "message": "Invalid item data"}), 400
        
        cart = _get_or_create_cart_mobile(driver.DriverID)
        
        # Check if item already exists in cart (exact match on normalized external_item_id)
        # This ensures items with same base ID and same variations are treated as duplicates
        existing_item = CartItem.query.filter_by(
            CartID=cart.CartID,
            ExternalItemID=external_item_id
        ).first()
        
        if existing_item:
            existing_item.Quantity += quantity
            existing_item.UpdatedAt = db.func.now()
        else:
            cart_item = CartItem(
                CartID=cart.CartID,
                ExternalItemID=external_item_id,
                ItemTitle=item_title,
                ItemImageURL=item_image_url,
                ItemURL=item_url,
                PointsPerUnit=points_per_unit,
                Quantity=quantity
            )
            db.session.add(cart_item)
        
        db.session.commit()
        
        # Refresh cart to get updated totals
        cart = Cart.query.filter_by(CartID=cart.CartID).first()
        
        return jsonify({
            "success": True,
            "message": "Item added to cart",
            "cart_total": cart.total_points,
            "item_count": cart.item_count
        })
    except (ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Invalid data: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding to cart: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error adding to cart: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/cart/update")
@login_required
def mobile_update_cart_item():
    """Update cart item quantity for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data provided"}), 400
        
        cart_item_id = data.get("cart_item_id")
        quantity = int(data.get("quantity", 1))
        
        if not cart_item_id or quantity < 0:
            return jsonify({"success": False, "message": "Invalid data"}), 400
        
        cart_item = CartItem.query.filter_by(CartItemID=cart_item_id).first()
        if not cart_item:
            return jsonify({"success": False, "message": "Item not found"}), 404
        
        # Verify the item belongs to the current driver's cart
        cart = Cart.query.filter_by(CartID=cart_item.CartID, DriverID=driver.DriverID).first()
        if not cart:
            return jsonify({"success": False, "message": "Unauthorized"}), 403
        
        if quantity == 0:
            db.session.delete(cart_item)
        else:
            cart_item.Quantity = quantity
            cart_item.UpdatedAt = db.func.now()
        
        db.session.commit()
        
        # Refresh cart to get updated totals
        cart = Cart.query.filter_by(CartID=cart.CartID).first()
        
        return jsonify({
            "success": True,
            "message": "Cart updated",
            "cart_total": cart.total_points,
            "item_count": cart.item_count
        })
    except (ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Invalid data: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating cart item: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error updating cart: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/cart/remove")
@login_required
def mobile_remove_from_cart():
    """Remove item from cart for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data provided"}), 400
        
        cart_item_id = data.get("cart_item_id")
        if not cart_item_id:
            return jsonify({"success": False, "message": "Item ID required"}), 400
        
        cart_item = CartItem.query.filter_by(CartItemID=cart_item_id).first()
        if not cart_item:
            return jsonify({"success": False, "message": "Item not found"}), 404
        
        # Verify the item belongs to the current driver's cart
        cart = Cart.query.filter_by(CartID=cart_item.CartID, DriverID=driver.DriverID).first()
        if not cart:
            return jsonify({"success": False, "message": "Unauthorized"}), 403
        
        db.session.delete(cart_item)
        db.session.commit()
        
        # Refresh cart to get updated totals
        cart = Cart.query.filter_by(CartID=cart.CartID).first()
        
        return jsonify({
            "success": True,
            "message": "Item removed from cart",
            "cart_total": cart.total_points,
            "item_count": cart.item_count
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error removing from cart: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error removing from cart: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/cart/clear")
@login_required
def mobile_clear_cart():
    """Clear all items from cart for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        cart = _get_or_create_cart_mobile(driver.DriverID)
        
        # Delete all cart items
        CartItem.query.filter_by(CartID=cart.CartID).delete()
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Cart cleared",
            "cart_total": 0,
            "item_count": 0
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing cart: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error clearing cart: {str(e)}"}), 500

@mobile_bp.get("/api/mobile/cart/summary")
@login_required
def mobile_cart_summary():
    """Get cart summary for mobile app (for badge counts)"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        cart = _get_or_create_cart_mobile(driver.DriverID)
        driver_points = _get_driver_points_balance_mobile()
        
        return jsonify({
            "success": True,
            "cart_total": cart.total_points,
            "item_count": cart.item_count,
            "driver_points": driver_points
        })
    except Exception as e:
        current_app.logger.error(f"Error getting cart summary: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading cart summary: {str(e)}"}), 500

# ========== Checkout API Endpoints ==========

@mobile_bp.post("/api/mobile/checkout/process")
@login_required
def mobile_process_checkout():
    """Process checkout and create order for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Get the driver's cart
        cart = Cart.query.filter_by(DriverID=driver.DriverID).first()
        if not cart or cart.items.count() == 0:
            return jsonify({"success": False, "message": "Cart is empty"}), 400
        
        # Get form data
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data provided"}), 400
        
        # Validate required fields
        required_fields = [
            'first_name', 'last_name', 'email', 
            'shipping_street', 'shipping_city', 'shipping_state', 
            'shipping_postal', 'shipping_country'
        ]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "message": f"Missing required field: {field}"}), 400
        
        # Get shipping cost
        shipping_cost_points = int(data.get('shipping_cost_points', 0))
        
        # Calculate total points (items + shipping)
        total_points = cart.total_points + shipping_cost_points
        
        # Get environment-specific points
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "message": "No environment selected"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "message": "Invalid environment"}), 400
        
        # Check if driver has enough points (environment-specific)
        current_balance = env.PointsBalance or 0
        if current_balance < total_points:
            return jsonify({"success": False, "message": "Insufficient points"}), 400
        
        # Generate order number
        import time
        order_number = f"ORD-{int(time.time())}-{driver.DriverID[:8]}"
        
        # Get sponsor to calculate dollar amount
        sponsor = Sponsor.query.get(env.SponsorID)
        if not sponsor:
            return jsonify({"success": False, "message": "Invalid sponsor"}), 400
        
        # Calculate total dollar amount based on sponsor's point-to-dollar rate
        total_amount = float(total_points) * float(sponsor.PointToDollarRate)
        
        # Create the order with 'pending' status (will be fulfilled after 5 minutes)
        order = Orders(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,
            OrderNumber=order_number,
            TotalPoints=total_points,
            TotalAmount=total_amount,
            Status='pending'
        )
        db.session.add(order)
        db.session.flush()  # Get the order ID
        
        # Update driver's shipping information if provided
        if data.get('shipping_street'):
            driver.ShippingStreet = data.get('shipping_street')
            driver.ShippingCity = data.get('shipping_city')
            driver.ShippingState = data.get('shipping_state')
            driver.ShippingPostal = data.get('shipping_postal')
            driver.ShippingCountry = data.get('shipping_country')
        
        # Create order line items from cart items
        for cart_item in cart.items:
            # For external catalog items, we'll create a temporary product entry
            product = Products.query.filter_by(ExternalItemID=cart_item.ExternalItemID).first()
            if not product:
                product = Products(
                    Title=cart_item.ItemTitle,
                    PointsPrice=cart_item.PointsPerUnit,
                    ExternalItemID=cart_item.ExternalItemID,
                )
                db.session.add(product)
                db.session.flush()
            
            line_total_points = cart_item.PointsPerUnit * cart_item.Quantity
            
            order_line_item = OrderLineItem(
                OrderID=order.OrderID,
                ProductID=product.ProductID,
                Title=cart_item.ItemTitle,
                UnitPoints=cart_item.PointsPerUnit,
                Quantity=cart_item.Quantity,
                LineTotalPoints=line_total_points
            )
            db.session.add(order_line_item)
        
        # Add shipping cost as a line item if there's a shipping cost
        if shipping_cost_points > 0:
            shipping_product = Products.query.filter_by(Title="Shipping Cost").first()
            if not shipping_product:
                shipping_product = Products(
                    Title="Shipping Cost",
                    PointsPrice=shipping_cost_points,
                    ExternalItemID="SHIPPING",
                )
                db.session.add(shipping_product)
                db.session.flush()
            
            shipping_line_item = OrderLineItem(
                OrderID=order.OrderID,
                ProductID=shipping_product.ProductID,
                Title="Shipping Cost",
                UnitPoints=shipping_cost_points,
                Quantity=1,
                LineTotalPoints=shipping_cost_points
            )
            db.session.add(shipping_line_item)
        
        # Deduct points from environment-specific balance
        env.PointsBalance = (env.PointsBalance or 0) - total_points
        
        # Ensure the environment is tracked by the session
        db.session.merge(env)
        
        actor_meta = derive_point_change_actor_metadata(current_user)

        # Record the point change
        point_change = PointChange(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,
            DeltaPoints=-total_points,
            TransactionID=order.OrderID,
            InitiatedByAccountID=driver.AccountID,
            BalanceAfter=env.PointsBalance,
            Reason=f"Order #{order.OrderNumber} - Points Payment",
            ActorRoleCode=actor_meta["actor_role_code"],
            ActorLabel=actor_meta["actor_label"],
            ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
            ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
        )
        db.session.add(point_change)
        
        # Send notifications
        try:
            from app.services.notification_service import NotificationService
            
            NotificationService.notify_driver_points_change(
                driver_id=driver.DriverID,
                delta_points=-total_points,
                reason=f"Order #{order.OrderNumber} - Points Payment",
                balance_after=env.PointsBalance,
            transaction_id=order.OrderNumber,
            sponsor_id=env.SponsorID if env else None
            )
            
            NotificationService.notify_driver_order_confirmation(order_id=order.OrderID)
            NotificationService.notify_sponsor_new_order(order_id=order.OrderID)
            
        except Exception as e:
            current_app.logger.error(f"Failed to send checkout notifications: {str(e)}")
        
        # Clear the cart
        CartItem.query.filter_by(CartID=cart.CartID).delete()
        
        # Commit all changes
        db.session.commit()
        
        # Schedule order fulfillment after 5 minutes
        # Use threading Timer but capture current_app context
        from threading import Timer
        order_id_for_fulfillment = order.OrderID
        order_number_for_log = order.OrderNumber
        
        def fulfill_order():
            # Create new app context for background thread
            from app import create_app
            app = create_app()
            with app.app_context():
                try:
                    from app import db
                    order_to_fulfill = Orders.query.filter_by(OrderID=order_id_for_fulfillment).first()
                    if order_to_fulfill and order_to_fulfill.Status == 'pending':
                        order_to_fulfill.Status = 'completed'
                        db.session.commit()
                        app.logger.info(f"Order {order_number_for_log} automatically fulfilled after 5 minutes")
                except Exception as e:
                    app.logger.error(f"Error fulfilling order: {e}", exc_info=True)
                    try:
                        db.session.rollback()
                    except:
                        pass
        
        timer = Timer(300.0, fulfill_order)  # 5 minutes = 300 seconds
        timer.daemon = True  # Allow program to exit even if timer is running
        timer.start()
        
        return jsonify({
            "success": True,
            "message": "Order placed successfully",
            "order_id": order.OrderID,
            "order_number": order.OrderNumber
        })
        
    except (ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Invalid data: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing checkout: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error processing checkout: {str(e)}"}), 500

# ========== Orders API Endpoints ==========

@mobile_bp.get("/api/mobile/orders")
@login_required
def mobile_get_orders():
    """Get order history for mobile app with pagination"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Get pagination parameters
        page = max(1, int(request.args.get("page", 1)))
        page_size = max(1, min(100, int(request.args.get("page_size", 20))))
        
        # Get orders with pagination
        orders_query = Orders.query.filter_by(DriverID=driver.DriverID).order_by(Orders.CreatedAt.desc())
        total = orders_query.count()
        
        orders = orders_query.offset((page - 1) * page_size).limit(page_size).all()
        
        # Get line items for all orders
        order_ids = [order.OrderID for order in orders]
        line_items = {}
        if order_ids:
            items = OrderLineItem.query.filter(OrderLineItem.OrderID.in_(order_ids)).all()
            for item in items:
                if item.OrderID not in line_items:
                    line_items[item.OrderID] = []
                line_items[item.OrderID].append(item)
        
        # Format orders for display
        formatted_orders = []
        for order in orders:
            # Calculate refund eligibility (30-minute window)
            from datetime import datetime, timedelta
            now = datetime.now()
            order_time = order.CreatedAt
            if order_time.tzinfo is not None:
                order_time = order_time.replace(tzinfo=None)
            
            time_since_order = now - order_time
            refund_window = timedelta(minutes=30)
            
            can_refund = (
                order.Status == 'completed' and 
                time_since_order <= refund_window
            )
            
            refund_time_remaining = 0
            if can_refund:
                remaining_time = refund_window - time_since_order
                refund_time_remaining = int(remaining_time.total_seconds() / 60)
            
            order_data = {
                'order_id': order.OrderID,
                'order_number': order.OrderNumber,
                'total_points': order.TotalPoints,
                'status': order.Status,
                'created_at': order.CreatedAt.isoformat() if order.CreatedAt else None,
                'can_refund': can_refund,
                'refund_time_remaining': refund_time_remaining,
                'order_items': []
            }
            
            # Add line items
            order_line_items = line_items.get(order.OrderID, [])
            for line_item in order_line_items:
                item_data = {
                    'title': line_item.Title,
                    'unit_points': line_item.UnitPoints,
                    'quantity': line_item.Quantity,
                    'line_total_points': line_item.LineTotalPoints,
                    'created_at': line_item.CreatedAt.isoformat() if line_item.CreatedAt else None
                }
                order_data['order_items'].append(item_data)
            
            formatted_orders.append(order_data)
        
        has_more = (page * page_size) < total
        
        return jsonify({
            "success": True,
            "orders": formatted_orders,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_more": has_more
        })
    except Exception as e:
        current_app.logger.error(f"Error getting orders: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading orders: {str(e)}"}), 500

@mobile_bp.get("/api/mobile/orders/<order_id>")
@login_required
def mobile_get_order_detail(order_id):
    """Get order details for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Validate order_id
        if not order_id or len(order_id) > 50:
            return jsonify({"success": False, "message": "Invalid order ID"}), 400
        
        # Get the order
        order = Orders.query.filter_by(OrderID=order_id, DriverID=driver.DriverID).first()
        if not order:
            return jsonify({"success": False, "message": "Order not found"}), 404
        
        # Get line items
        order_items = OrderLineItem.query.filter_by(OrderID=order.OrderID).all()
        
        # Calculate refund eligibility
        from datetime import datetime, timedelta
        now = datetime.now()
        order_time = order.CreatedAt
        if order_time.tzinfo is not None:
            order_time = order_time.replace(tzinfo=None)
        
        time_since_order = now - order_time
        refund_window = timedelta(minutes=30)
        
        can_refund = (
            order.Status == 'completed' and 
            time_since_order <= refund_window
        )
        
        refund_time_remaining = 0
        if can_refund:
            remaining_time = refund_window - time_since_order
            refund_time_remaining = int(remaining_time.total_seconds() / 60)
        
        items_data = []
        for line_item in order_items:
            # Get product to extract external_item_id and variation info
            product = Products.query.filter_by(ProductID=line_item.ProductID).first()
            external_item_id = product.ExternalItemID if product else None
            
            item_data = {
                'title': line_item.Title,
                'unit_points': line_item.UnitPoints,
                'quantity': line_item.Quantity,
                'line_total_points': line_item.LineTotalPoints,
                'created_at': line_item.CreatedAt.isoformat() if line_item.CreatedAt else None,
                'external_item_id': external_item_id
            }
            
            # Extract variation info from external_item_id if present
            if external_item_id and '::' in external_item_id:
                variation_part = external_item_id.split('::', 1)[1]
                item_data['variation_info'] = variation_part
            
            items_data.append(item_data)
        
        order_data = {
            'order_id': order.OrderID,
            'order_number': order.OrderNumber,
            'total_points': order.TotalPoints,
            'total_amount': float(order.TotalAmount) if order.TotalAmount else None,
            'status': order.Status,
            'created_at': order.CreatedAt.isoformat() if order.CreatedAt else None,
            'updated_at': order.UpdatedAt.isoformat() if order.UpdatedAt else None,
            'can_refund': can_refund,
            'refund_time_remaining': refund_time_remaining,
            'order_items': items_data
        }
        
        return jsonify({
            "success": True,
            "order": order_data
        })
    except Exception as e:
        current_app.logger.error(f"Error getting order detail: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading order details: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/orders/<order_id>/cancel")
@login_required
def mobile_cancel_order(order_id):
    """Cancel a pending order for mobile app"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Validate order_id
        if not order_id or len(order_id) > 50:
            return jsonify({"success": False, "message": "Invalid order ID"}), 400
        
        # Get the order
        order = Orders.query.filter_by(OrderID=order_id, DriverID=driver.DriverID).first()
        if not order:
            return jsonify({"success": False, "message": "Order not found"}), 404
        
        # Check if order can be cancelled (must be pending)
        if order.Status != 'pending':
            return jsonify({"success": False, "message": "Only pending orders can be cancelled"}), 400
        
        # Get environment to refund points
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "message": "No environment selected"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "message": "Invalid environment"}), 400
        
        # Refund points
        env.PointsBalance = (env.PointsBalance or 0) + order.TotalPoints
        
        # Ensure the environment is tracked by the session
        db.session.merge(env)
        
        actor_meta = derive_point_change_actor_metadata(current_user)

        # Record the point change
        point_change = PointChange(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,
            DeltaPoints=order.TotalPoints,
            TransactionID=order.OrderID,
            InitiatedByAccountID=driver.AccountID,
            BalanceAfter=env.PointsBalance,
            Reason=f"Order #{order.OrderNumber} - Cancellation Refund",
            ActorRoleCode=actor_meta["actor_role_code"],
            ActorLabel=actor_meta["actor_label"],
            ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
            ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
        )
        db.session.add(point_change)
        
        # Mark order as cancelled
        order.Status = 'cancelled'
        order.CancelledAt = db.func.now()
        order.CancelledByAccountID = driver.AccountID
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Order cancelled successfully",
            "points_refunded": order.TotalPoints,
            "balance_after": env.PointsBalance
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error cancelling order: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error cancelling order: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/orders/<order_id>/refund")
@login_required
def mobile_refund_order(order_id):
    """Refund an order for mobile app (within 30-minute window)"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Validate order_id
        if not order_id or len(order_id) > 50:
            return jsonify({"success": False, "message": "Invalid order ID"}), 400
        
        # Get the order
        order = Orders.query.filter_by(OrderID=order_id, DriverID=driver.DriverID).first()
        if not order:
            return jsonify({"success": False, "message": "Order not found"}), 404
        
        # Check if order can be refunded
        from datetime import datetime, timedelta
        now = datetime.now()
        order_time = order.CreatedAt
        if order_time.tzinfo is not None:
            order_time = order_time.replace(tzinfo=None)
        
        time_since_order = now - order_time
        refund_window = timedelta(minutes=30)
        
        if order.Status != 'completed':
            return jsonify({"success": False, "message": "Only completed orders can be refunded"}), 400
        
        if time_since_order > refund_window:
            return jsonify({"success": False, "message": "Refund window has expired (30 minutes)"}), 400
        
        # Get environment-specific points balance
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "message": "No environment selected"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "message": "Invalid environment"}), 400
        
        # Process refund - add points back
        env.PointsBalance = (env.PointsBalance or 0) + order.TotalPoints
        
        # Ensure the environment is tracked by the session
        db.session.merge(env)
        
        # Update order status
        order.Status = 'refunded'
        
        actor_meta = derive_point_change_actor_metadata(current_user)

        # Record the point change
        point_change = PointChange(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,
            DeltaPoints=order.TotalPoints,
            TransactionID=order.OrderID,
            InitiatedByAccountID=driver.AccountID,
            BalanceAfter=env.PointsBalance,
            Reason=f"Refund for Order #{order.OrderNumber}",
            ActorRoleCode=actor_meta["actor_role_code"],
            ActorLabel=actor_meta["actor_label"],
            ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
            ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
        )
        db.session.add(point_change)
        
        # Send notification
        try:
            from app.services.notification_service import NotificationService
            NotificationService.notify_driver_points_change(
                driver_id=driver.DriverID,
                delta_points=order.TotalPoints,
                reason=f"Refund for Order #{order.OrderNumber}",
                balance_after=env.PointsBalance,
                transaction_id=order.OrderNumber,
                sponsor_id=env.SponsorID
            )
        except Exception as e:
            current_app.logger.error(f"Failed to send refund notification: {str(e)}")
        
        # Commit changes
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Order refunded successfully",
            "points_refunded": order.TotalPoints,
            "balance_after": env.PointsBalance
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error refunding order: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error refunding order: {str(e)}"}), 500

@mobile_bp.post("/api/mobile/orders/<order_id>/reorder")
@login_required
def mobile_reorder_checkout(order_id):
    """Re-order an existing order without touching the cart"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Validate order_id
        if not order_id or len(order_id) > 50:
            return jsonify({"success": False, "message": "Invalid order ID"}), 400
        
        # Get the original order
        original_order = Orders.query.filter_by(OrderID=order_id, DriverID=driver.DriverID).first()
        if not original_order:
            return jsonify({"success": False, "message": "Order not found"}), 404
        
        # Get form data
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No JSON data provided"}), 400
        
        # Validate required fields
        required_fields = [
            'first_name', 'last_name', 'email', 
            'shipping_street', 'shipping_city', 'shipping_state', 
            'shipping_postal', 'shipping_country'
        ]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "message": f"Missing required field: {field}"}), 400
        
        # Get shipping cost
        shipping_cost_points = int(data.get('shipping_cost_points', 0))
        
        # Get environment-specific points
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "message": "No environment selected"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "message": "Invalid environment"}), 400
        
        # Get original order items
        original_line_items = OrderLineItem.query.filter_by(OrderID=original_order.OrderID).all()
        if not original_line_items:
            return jsonify({"success": False, "message": "Original order has no items"}), 400
        
        # Calculate total points from original order items + shipping
        items_total_points = sum(item.LineTotalPoints for item in original_line_items)
        total_points = items_total_points + shipping_cost_points
        
        # Check if driver has enough points
        current_balance = env.PointsBalance or 0
        if current_balance < total_points:
            return jsonify({"success": False, "message": "Insufficient points"}), 400
        
        # Generate new order number
        import time
        order_number = f"ORD-{int(time.time())}-{driver.DriverID[:8]}"
        
        # Get sponsor to calculate dollar amount
        sponsor = Sponsor.query.get(env.SponsorID)
        if not sponsor:
            return jsonify({"success": False, "message": "Invalid sponsor"}), 400
        
        # Calculate total dollar amount based on sponsor's point-to-dollar rate
        total_amount = float(total_points) * float(sponsor.PointToDollarRate)
        
        # Create the new order with 'pending' status (will be fulfilled after 30 seconds)
        new_order = Orders(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,
            OrderNumber=order_number,
            TotalPoints=total_points,
            TotalAmount=total_amount,
            Status='pending'
        )
        db.session.add(new_order)
        db.session.flush()  # Get the order ID
        
        # Update driver's shipping information if provided
        if data.get('shipping_street'):
            driver.ShippingStreet = data.get('shipping_street')
            driver.ShippingCity = data.get('shipping_city')
            driver.ShippingState = data.get('shipping_state')
            driver.ShippingPostal = data.get('shipping_postal')
            driver.ShippingCountry = data.get('shipping_country')
        
        # Create order line items from original order items
        for original_line_item in original_line_items:
            # Create new order line item with same data as original
            new_line_item = OrderLineItem(
                OrderID=new_order.OrderID,
                ProductID=original_line_item.ProductID,
                Title=original_line_item.Title,
                UnitPoints=original_line_item.UnitPoints,
                Quantity=original_line_item.Quantity,
                LineTotalPoints=original_line_item.LineTotalPoints
            )
            db.session.add(new_line_item)
        
        # Add shipping cost as a line item if there's a shipping cost
        if shipping_cost_points > 0:
            shipping_product = Products.query.filter_by(Title="Shipping Cost").first()
            if not shipping_product:
                shipping_product = Products(
                    Title="Shipping Cost",
                    PointsPrice=shipping_cost_points,
                    ExternalItemID="SHIPPING",
                )
                db.session.add(shipping_product)
                db.session.flush()
            
            shipping_line_item = OrderLineItem(
                OrderID=new_order.OrderID,
                ProductID=shipping_product.ProductID,
                Title="Shipping Cost",
                UnitPoints=shipping_cost_points,
                Quantity=1,
                LineTotalPoints=shipping_cost_points
            )
            db.session.add(shipping_line_item)
        
        # Deduct points from environment-specific balance
        env.PointsBalance = (env.PointsBalance or 0) - total_points
        
        # Ensure the environment is tracked by the session
        db.session.merge(env)
        
        actor_meta = derive_point_change_actor_metadata(current_user)

        # Record the point change
        point_change = PointChange(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,
            DeltaPoints=-total_points,
            TransactionID=new_order.OrderID,
            InitiatedByAccountID=driver.AccountID,
            BalanceAfter=env.PointsBalance,
            Reason=f"Re-order #{new_order.OrderNumber} - Points Payment",
            ActorRoleCode=actor_meta["actor_role_code"],
            ActorLabel=actor_meta["actor_label"],
            ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
            ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
        )
        db.session.add(point_change)
        
        # Send notifications
        try:
            from app.services.notification_service import NotificationService
            
            NotificationService.notify_driver_points_change(
                driver_id=driver.DriverID,
                delta_points=-total_points,
                reason=f"Re-order #{new_order.OrderNumber} - Points Payment",
                balance_after=env.PointsBalance,
            transaction_id=new_order.OrderNumber,
            sponsor_id=env.SponsorID
            )
            
            NotificationService.notify_driver_order_confirmation(order_id=new_order.OrderID)
            NotificationService.notify_sponsor_new_order(order_id=new_order.OrderID)
            
        except Exception as e:
            current_app.logger.error(f"Failed to send re-order notifications: {str(e)}")
        
        # Commit all changes (NOTE: We do NOT touch the Cart table at all)
        db.session.commit()
        
        # Schedule order fulfillment after 30 seconds
        from threading import Timer
        order_id_for_fulfillment = new_order.OrderID
        order_number_for_log = new_order.OrderNumber
        
        def fulfill_order():
            # Create new app context for background thread
            from app import create_app
            app = create_app()
            with app.app_context():
                try:
                    from app import db
                    order_to_fulfill = Orders.query.filter_by(OrderID=order_id_for_fulfillment).first()
                    if order_to_fulfill and order_to_fulfill.Status == 'pending':
                        order_to_fulfill.Status = 'completed'
                        db.session.commit()
                        app.logger.info(f"Re-order {order_number_for_log} automatically fulfilled after 30 seconds")
                except Exception as e:
                    app.logger.error(f"Error fulfilling re-order: {e}", exc_info=True)
                    try:
                        db.session.rollback()
                    except:
                        pass
        
        timer = Timer(300.0, fulfill_order)  # 5 minutes = 300 seconds
        timer.daemon = True
        timer.start()
        
        return jsonify({
            "success": True,
            "message": "Re-order placed successfully",
            "order_id": new_order.OrderID,
            "order_number": new_order.OrderNumber
        })
        
    except (ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Invalid data: {str(e)}"}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing re-order checkout: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error processing re-order checkout: {str(e)}"}), 500

# ========== Points Details API Endpoints ==========

@mobile_bp.get("/api/mobile/points/history")
@login_required
def mobile_get_points_history():
    """Get points transaction history for the current driver"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Get active environment (sponsor-specific)
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "message": "No active sponsor environment"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "message": "Invalid sponsor environment"}), 400
        
        sponsor_id = env.SponsorID
        
        # Get query parameters
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")
        limit = max(1, min(int(request.args.get("limit", 50)), 500))
        sort = request.args.get("sort", "desc").lower()
        
        # Build query
        query = PointChange.query.filter_by(
            DriverID=driver.DriverID,
            SponsorID=sponsor_id
        )
        
        # Apply date filters
        if start_date_str:
            try:
                from datetime import datetime
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
                query = query.filter(PointChange.CreatedAt >= start_date)
            except ValueError:
                return jsonify({"success": False, "message": "Invalid start_date format. Use YYYY-MM-DD"}), 400
        
        if end_date_str:
            try:
                from datetime import datetime, timedelta
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d") + timedelta(days=1)
                query = query.filter(PointChange.CreatedAt < end_date)
            except ValueError:
                return jsonify({"success": False, "message": "Invalid end_date format. Use YYYY-MM-DD"}), 400
        
        # Get total count before pagination
        total_count = query.count()
        
        # Apply sorting
        if sort == "asc":
            query = query.order_by(PointChange.CreatedAt.asc())
        else:
            query = query.order_by(PointChange.CreatedAt.desc())
        
        # Apply limit
        point_changes = query.limit(limit).all()
        
        # Build response
        transactions = []
        for pc in point_changes:
            transactions.append({
                "point_change_id": pc.PointChangeID,
                "delta_points": pc.DeltaPoints,
                "balance_after": pc.BalanceAfter,
                "reason": pc.Reason or "",
                "created_at": pc.CreatedAt.isoformat() if pc.CreatedAt else None,
                "transaction_id": pc.TransactionID
            })
        
        return jsonify({
            "success": True,
            "transactions": transactions,
            "total_count": total_count
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting points history: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading points history: {str(e)}"}), 500

@mobile_bp.get("/api/mobile/points/details")
@login_required
def mobile_get_points_details():
    """Get comprehensive points details for the current driver"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Get active environment (sponsor-specific)
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "message": "No active sponsor environment"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "message": "Invalid sponsor environment"}), 400
        
        sponsor_id = env.SponsorID
        sponsor = Sponsor.query.get(sponsor_id)
        
        # Get current balance
        current_balance = env.PointsBalance or 0
        
        # Get conversion rate (dollar value per point)
        # Sponsor.PointToDollarRate is dollars per point (e.g., 0.01 = $0.01 per point)
        conversion_rate = float(sponsor.PointToDollarRate) if sponsor and sponsor.PointToDollarRate else 0.01
        dollar_value = current_balance * conversion_rate
        
        # Get member since date from account
        member_since = driver.Account.CreatedAt.isoformat() if driver.Account and driver.Account.CreatedAt else None
        
        # Calculate total earned and spent
        all_changes = PointChange.query.filter_by(
            DriverID=driver.DriverID,
            SponsorID=sponsor_id
        ).all()
        
        total_earned = sum(pc.DeltaPoints for pc in all_changes if pc.DeltaPoints > 0)
        total_spent = abs(sum(pc.DeltaPoints for pc in all_changes if pc.DeltaPoints < 0))
        
        return jsonify({
            "success": True,
            "current_balance": current_balance,
            "conversion_rate": conversion_rate,
            "dollar_value": round(dollar_value, 2),
            "sponsor_company": sponsor.Company if sponsor else None,
            "member_since": member_since,
            "total_earned": total_earned,
            "total_spent": total_spent
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting points details: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading points details: {str(e)}"}), 500

@mobile_bp.get("/api/mobile/points/graph")
@login_required
def mobile_get_points_graph():
    """Get aggregated points data for graph visualization"""
    driver, error_response, error_code = _get_driver_for_mobile()
    if error_response:
        return error_response, error_code
    
    try:
        # Get active environment (sponsor-specific)
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "message": "No active sponsor environment"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "message": "Invalid sponsor environment"}), 400
        
        sponsor_id = env.SponsorID
        
        # Get query parameters
        period = request.args.get("period", "30d")
        granularity = request.args.get("granularity", "day")
        
        # Calculate date range based on period
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        
        if period == "7d":
            start_date = now - timedelta(days=7)
        elif period == "30d":
            start_date = now - timedelta(days=30)
        elif period == "90d":
            start_date = now - timedelta(days=90)
        elif period == "1y":
            start_date = now - timedelta(days=365)
        else:  # "all"
            start_date = None
        
        # Get all point changes in range
        query = PointChange.query.filter_by(
            DriverID=driver.DriverID,
            SponsorID=sponsor_id
        )
        
        if start_date:
            query = query.filter(PointChange.CreatedAt >= start_date)
        
        query = query.order_by(PointChange.CreatedAt.asc())
        point_changes = query.all()
        
        # Aggregate data based on granularity
        data_points = []
        
        if not point_changes:
            # Return current balance as single point
            current_balance = env.PointsBalance or 0
            data_points.append({
                "date": now.date().isoformat(),
                "balance": current_balance,
                "delta": 0
            })
        else:
            # Group by time period
            from collections import defaultdict
            from datetime import date
            
            grouped = defaultdict(lambda: {"delta": 0, "latest_balance": 0, "latest_date": None})
            
            for pc in point_changes:
                pc_date = pc.CreatedAt.date() if pc.CreatedAt else date.today()
                
                # Determine grouping key based on granularity
                if granularity == "week":
                    # Get week start (Monday)
                    days_since_monday = pc_date.weekday()
                    week_start = pc_date - timedelta(days=days_since_monday)
                    key = week_start
                elif granularity == "month":
                    key = date(pc_date.year, pc_date.month, 1)
                else:  # "day"
                    key = pc_date
                
                grouped[key]["delta"] += pc.DeltaPoints
                if grouped[key]["latest_date"] is None or pc.CreatedAt > grouped[key]["latest_date"]:
                    grouped[key]["latest_balance"] = pc.BalanceAfter
                    grouped[key]["latest_date"] = pc.CreatedAt
            
            # Convert to sorted list
            sorted_keys = sorted(grouped.keys())
            
            # Calculate cumulative balance (starting from earliest point)
            # We need to get the balance before the first transaction
            running_balance = 0
            if sorted_keys:
                first_key = sorted_keys[0]
                first_change = next((pc for pc in point_changes if (pc.CreatedAt.date() if pc.CreatedAt else date.today()) == first_key), None)
                if first_change:
                    running_balance = first_change.BalanceAfter - first_change.DeltaPoints
            
            for key in sorted_keys:
                group = grouped[key]
                running_balance += group["delta"]
                data_points.append({
                    "date": key.isoformat(),
                    "balance": running_balance,
                    "delta": group["delta"]
                })
        
        return jsonify({
            "success": True,
            "data_points": data_points
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting points graph data: {e}", exc_info=True)
        return jsonify({"success": False, "message": f"Error loading graph data: {str(e)}"}), 500