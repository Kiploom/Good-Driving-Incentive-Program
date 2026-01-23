from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy.exc import IntegrityError
from .. import db
from ..models import AccountType, Account, Driver, Sponsor, SponsorCompany, Admin, EmailVerification
import bcrypt, re
from config import fernet
from flask_mail import Message
from zoneinfo import ZoneInfo
import uuid
from datetime import datetime
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, IntegerField, TextAreaField, BooleanField
from wtforms.validators import DataRequired, Length, Regexp, NumberRange, Optional
from wtforms.validators import Email as EmailValidator
from ..services.password_security_service import PasswordSecurityService

bp = Blueprint("users", __name__)

# ---------------------------
# Form validation classes
# ---------------------------
class DriverRegistrationForm(FlaskForm):
    """Secure form validation for driver registration"""
    Username = StringField('Username', validators=[
        DataRequired(), 
        Length(min=3, max=50),
        Regexp(r'^[a-zA-Z0-9_-]+$', message='Username can only contain letters, numbers, underscores, and hyphens')
    ])
    Email = StringField('Email', validators=[DataRequired(), EmailValidator()])
    Password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, max=128),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).*$', 
               message='Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character')
    ])
    FirstName = StringField('First Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='First name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    LastName = StringField('Last Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='Last name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    Phone = StringField('Phone', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^[\d\s\-\+\(\)]+$', message='Phone number contains invalid characters')
    ])
    LicenseNumber = StringField('License Number', validators=[
        Optional(),
        Length(max=50),
        Regexp(r'^[a-zA-Z0-9\s\-]+$', message='License number contains invalid characters')
    ])
    LicenseIssueDate = StringField('License Issue Date', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^\d{4}-\d{2}-\d{2}$', message='Date must be in YYYY-MM-DD format')
    ])
    LicenseExpirationDate = StringField('License Expiration Date', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^\d{4}-\d{2}-\d{2}$', message='Date must be in YYYY-MM-DD format')
    ])
    SponsorID = SelectField('Sponsor', coerce=str, validators=[Optional()])

class SponsorRegistrationForm(FlaskForm):
    """Secure form validation for sponsor registration"""
    Username = StringField('Username', validators=[
        DataRequired(), 
        Length(min=3, max=50),
        Regexp(r'^[a-zA-Z0-9_-]+$', message='Username can only contain letters, numbers, underscores, and hyphens')
    ])
    Email = StringField('Email', validators=[DataRequired(), EmailValidator()])
    Password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, max=128),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).*$', 
               message='Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character')
    ])
    FirstName = StringField('First Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='First name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    LastName = StringField('Last Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='Last name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    Phone = StringField('Phone', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^[\d\s\-\+\(\)]+$', message='Phone number contains invalid characters')
    ])
    Company = StringField('Company', validators=[
        DataRequired(),
        Length(min=1, max=200),
        Regexp(r'^[a-zA-Z0-9\s\.,\-\'&]+$', message='Company name contains invalid characters')
    ])
    BillingEmail = StringField('Billing Email', validators=[Optional(), EmailValidator()])

class AdminRegistrationForm(FlaskForm):
    """Secure form validation for admin registration"""
    Username = StringField('Username', validators=[
        DataRequired(), 
        Length(min=3, max=50),
        Regexp(r'^[a-zA-Z0-9_-]+$', message='Username can only contain letters, numbers, underscores, and hyphens')
    ])
    Email = StringField('Email', validators=[DataRequired(), EmailValidator()])
    Password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, max=128),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?":{}|<>]).*$', 
               message='Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character')
    ])
    FirstName = StringField('First Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='First name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    LastName = StringField('Last Name', validators=[
        DataRequired(), 
        Length(min=1, max=100),
        Regexp(r'^[a-zA-Z\s\'-]+$', message='Last name can only contain letters, spaces, hyphens, and apostrophes')
    ])
    Phone = StringField('Phone', validators=[
        Optional(),
        Length(max=20),
        Regexp(r'^[\d\s\-\+\(\)]+$', message='Phone number contains invalid characters')
    ])
    Role = StringField('Role', validators=[
        Optional(),
        Length(max=100),
        Regexp(r'^[a-zA-Z0-9\s\-\_]+$', message='Role contains invalid characters')
    ])

# ---------------------------
# Password complexity checker
# ---------------------------
def _is_password_strong(pw: str) -> bool:
    if len(pw) < 8:
        return False
    if not re.search(r"[A-Z]", pw):
        return False
    if not re.search(r"[a-z]", pw):
        return False
    if not re.search(r"[0-9]", pw):
        return False
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", pw):
        return False
    return True

# --- helpers ---
def _get_account_type_code(code: str) -> str:
    # Since we now store AccountType directly, we just return the code
    # This function is kept for backward compatibility but now just validates and returns the code
    valid_codes = ["DRIVER", "SPONSOR", "ADMIN"]
    if code not in valid_codes:
        raise RuntimeError(f"AccountType '{code}' is not valid. Valid codes: {valid_codes}")
    return code

def _hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

# Resolve AccountTypeID from an AccountType code, creating it if missing
def _get_account_type_id(code: str) -> str:
    code_norm = _get_account_type_code(code)
    at = AccountType.query.filter_by(AccountTypeCode=code_norm).first()
    if not at:
        at = AccountType(AccountTypeCode=code_norm, DisplayName=code_norm.title())
        db.session.add(at)
        db.session.flush()
    return at.AccountTypeID

# -----------------------------------
# DRIVER SIGNUP
# -----------------------------------
@bp.route("/driver", methods=["GET", "POST"])
def driver():
    form = DriverRegistrationForm()
    sponsors = Sponsor.query.all()
    form.SponsorID.choices = [(s.SponsorID, s.Company) for s in sponsors]
    if form.validate_on_submit():
        try:
            phone_raw = form.Phone.data
            phone_enc = fernet.encrypt(phone_raw.encode()).decode() if phone_raw else None

            acc = Account(
                AccountType=_get_account_type_code("DRIVER"),
                AccountTypeID=_get_account_type_id("DRIVER"),
                Username=form.Username.data.strip(),
                Email=form.Email.data.lower().strip(),
                Phone=phone_enc,
                PasswordHash=_hash_password(form.Password.data),
                FirstName=form.FirstName.data.strip(),
                LastName=form.LastName.data.strip(),
                WholeName=f"{form.FirstName.data.strip()} {form.LastName.data.strip()}".strip(),
                Status='A',
            )
            db.session.add(acc)
            db.session.flush()

            # Do NOT create Driver at signup since DB requires SponsorID non-null
            # Driver will be created later during the application flow when a Sponsor is selected

            # SECURITY: Log initial password creation
            PasswordSecurityService.log_password_change(
                account_id=acc.AccountID,
                new_password_hash=acc.PasswordHash,
                change_reason='initial_setup',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            token = str(uuid.uuid4())
            ev = EmailVerification(AccountID=acc.AccountID, VerificationToken=token, SentAt=datetime.utcnow())
            db.session.add(ev)
            db.session.commit()

            verify_url = url_for("auth.verify_email", token=token, _external=True)
            msg = Message(
                subject="Verify Your Email",
                recipients=[acc.Email],
                body=f"Welcome to Driver Rewards!\n\nClick to verify your email:\n{verify_url}\n\nIf you didn't sign up, ignore this message."
            )
            from ..extensions import mail
            mail.send(msg)

            return redirect(url_for("users.verify_notice", email=acc.Email))

        except IntegrityError as e:
            db.session.rollback()
            flash(f"Could not create driver: {e.orig}", "error")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
    elif request.method == "POST":
        # Form did not validate; surface errors
        for field, errs in form.errors.items():
            for err in errs:
                flash(f"{field}: {err}", "error")

    return render_template("driver.html", form=form, sponsors=sponsors)

# -----------------------------------
# SPONSOR SIGNUP
# -----------------------------------
@bp.route("/sponsor", methods=["GET", "POST"])
def sponsor():
    if request.method == "POST":
        password = request.form["Password"]
        # SECURITY: Check password complexity using centralized service
        is_strong, complexity_error = PasswordSecurityService.is_password_strong(password)
        if not is_strong:
            return render_template("sponsor.html", error=f"Password complexity error: {complexity_error}")
        try:
            phone_raw = request.form.get("Phone")
            phone_enc = fernet.encrypt(phone_raw.encode()).decode() if phone_raw else None

            acc = Account(
                AccountType=_get_account_type_code("SPONSOR"),
                AccountTypeID=_get_account_type_id("SPONSOR"),
                Username=request.form["Username"],
                Email=request.form["Email"],
                Phone=phone_enc,
                PasswordHash=_hash_password(password),
                FirstName=request.form.get("FirstName"),
                LastName=request.form.get("LastName"),
                WholeName=f"{request.form.get('FirstName','')} {request.form.get('LastName','')}".strip(),
                Status='A',
            )
            db.session.add(acc)
            db.session.flush()

            # Create or find SponsorCompany
            company_name = request.form.get("Company") or "Unnamed Sponsor"
            sponsor_company = SponsorCompany.query.filter_by(CompanyName=company_name).first()
            if not sponsor_company:
                sponsor_company = SponsorCompany(CompanyName=company_name)
                db.session.add(sponsor_company)
                db.session.flush()
            
            sp = Sponsor(
                AccountID=acc.AccountID,
                Company=company_name,
                SponsorCompanyID=sponsor_company.SponsorCompanyID,
                BillingEmail=request.form.get("BillingEmail") or request.form.get("Email"),
                IsAdmin=False,
            )
            db.session.add(sp)

            # SECURITY: Log initial password creation
            PasswordSecurityService.log_password_change(
                account_id=acc.AccountID,
                new_password_hash=acc.PasswordHash,
                change_reason='initial_setup',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            token = str(uuid.uuid4())
            ev = EmailVerification(AccountID=acc.AccountID, VerificationToken=token, SentAt=datetime.utcnow())
            db.session.add(ev)
            db.session.commit()

            verify_url = url_for("auth.verify_email", token=token, _external=True)
            msg = Message(
                subject="Verify Your Email",
                recipients=[acc.Email],
                body=f"Welcome to Driver Rewards!\n\nClick to verify your email:\n{verify_url}\n\nIf you didn’t sign up, ignore this message."
            )
            from ..extensions import mail
            mail.send(msg)

            return redirect(url_for("users.verify_notice", email=acc.Email))

        except IntegrityError as e:
            db.session.rollback()
            return render_template("sponsor.html", error=f"Could not create sponsor: {e.orig}")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
    return render_template("sponsor.html")

# -----------------------------------
# ADMIN SIGNUP
# -----------------------------------
@bp.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        password = request.form["Password"]
        # SECURITY: Check password complexity using centralized service
        is_strong, complexity_error = PasswordSecurityService.is_password_strong(password)
        if not is_strong:
            return render_template("admin.html", error=f"Password complexity error: {complexity_error}")
        try:
            phone_raw = request.form.get("Phone")
            phone_enc = fernet.encrypt(phone_raw.encode()).decode() if phone_raw else None

            acc = Account(
                AccountType=_get_account_type_code("ADMIN"),
                AccountTypeID=_get_account_type_id("ADMIN"),
                Username=request.form["Username"],
                Email=request.form["Email"],
                Phone=phone_enc,
                PasswordHash=_hash_password(password),
                FirstName=request.form.get("FirstName"),
                LastName=request.form.get("LastName"),
                WholeName=f"{request.form.get('FirstName','')} {request.form.get('LastName','')}".strip(),
                Status='A',
            )
            db.session.add(acc)
            db.session.flush()

            ad = Admin(AccountID=acc.AccountID, Role=request.form.get("Role") or "Admin")
            db.session.add(ad)

            # SECURITY: Log initial password creation
            PasswordSecurityService.log_password_change(
                account_id=acc.AccountID,
                new_password_hash=acc.PasswordHash,
                change_reason='initial_setup',
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

            token = str(uuid.uuid4())
            ev = EmailVerification(AccountID=acc.AccountID, VerificationToken=token, SentAt=datetime.utcnow())
            db.session.add(ev)
            db.session.commit()

            verify_url = url_for("auth.verify_email", token=token, _external=True)
            msg = Message(
                subject="Verify Your Email",
                recipients=[acc.Email],
                body=f"Welcome to Driver Rewards!\n\nClick to verify your email:\n{verify_url}\n\nIf you didn’t sign up, ignore this message."
            )
            from ..extensions import mail
            mail.send(msg)

            return redirect(url_for("users.verify_notice", email=acc.Email))

        except IntegrityError as e:
            db.session.rollback()
            return render_template("admin.html", error=f"Could not create admin: {e.orig}")
        except Exception as e:
            db.session.rollback()
            flash(str(e), "error")
    return render_template("admin.html")

# -----------------------------------
# Verification Notice Page
# -----------------------------------
@bp.get("/verify-notice")
def verify_notice():
    email = request.args.get("email")
    return render_template("verify_notice.html", email=email)

@bp.get("/success")
def success():
    return render_template("success.html")