"""
All SQLAlchemy models for the Good-Driving-Incentive-Program.

Place new models in the appropriate section below. Use the section headers
to find where each model belongs. All models must inherit from db.Model.
"""
import uuid
from datetime import datetime, date

from sqlalchemy import case
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import synonym

from . import db
from config import fernet
from flask_login import UserMixin

JSONT = db.JSON


def local_now():
    """Return current local time (not UTC)."""
    return datetime.now()


# =============================================================================
# LOOKUP TABLES
# Account types, enums, and other reference data.
# Add new lookup/reference models here.
# =============================================================================
class AccountType(db.Model):
    __tablename__ = "AccountType"

    AccountTypeID   = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountTypeCode = db.Column(db.String(50), nullable=False, unique=True)  # e.g., DRIVER, SPONSOR, ADMIN
    DisplayName     = db.Column(db.String(100))
    Description     = db.Column(db.String(255))
    CreatedAt       = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt       = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<AccountType {self.AccountTypeCode}>"


# =============================================================================
# CORE ENTITIES
# Account, Driver, Sponsor, Admin, SponsorCompany - the main user/org models.
# Add new core user or organization models here.
# =============================================================================

class Account(db.Model, UserMixin):
    __tablename__ = "Account"

    AccountID          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountTypeID      = db.Column(db.String(36), db.ForeignKey("AccountType.AccountTypeID"), nullable=False)

    Username           = db.Column(db.String(100), nullable=False)
    AccountType        = db.Column(db.String(50), nullable=False)  # e.g., DRIVER, SPONSOR, ADMIN
    Email              = db.Column(db.String(255), nullable=False, unique=True)
    Phone              = db.Column(db.String(255))  # encrypted string

    PasswordHash       = db.Column(db.String(255), nullable=False)

    FirstName          = db.Column(db.String(100))
    LastName           = db.Column(db.String(100))
    WholeName          = db.Column(db.String(300))
    ProfileImageURL    = db.Column(db.String(255))

    # A = Active, I = Inactive, P = Pending, R = Rejected
    Status             = db.Column(db.String(1), nullable=False, server_default="A")

    CreatedAt          = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    UpdatedByAccountID = db.Column(db.String(36))

    MFAEnabled         = db.Column(db.Boolean, default=False)
    MFASecretEnc       = db.Column(db.String(255))
    RecoveryCodes      = db.Column(MutableList.as_mutable(db.JSON), nullable=True)
    LockedUntil        = db.Column(db.DateTime, nullable=True)  # Account lockout expiration time

    # --- Decrypted accessors ---
    @property
    def phone_plain(self):
        if not self.Phone:
            return None
        try:
            return fernet.decrypt(self.Phone.encode()).decode()
        except Exception:
            return self.Phone

    @phone_plain.setter
    def phone_plain(self, value: str):
        self.Phone = fernet.encrypt(value.encode()).decode()

    # Flask-Login
    def get_id(self) -> str:
        return str(self.AccountID)

    @hybrid_property
    def is_active(self) -> bool:
        return (self.Status or "").upper() in {"A", "P"}  # allow Pending to log in

    @is_active.expression
    def is_active(cls):
        return case((cls.Status.in_(["A", "a", "P", "p"]), True), else_=False)
    
    # Helper methods for account type checking
    @property
    def is_driver(self) -> bool:
        return self.AccountType == "DRIVER"
    
    @property
    def is_sponsor(self) -> bool:
        return self.AccountType == "SPONSOR"
    
    @property
    def is_admin(self) -> bool:
        return self.AccountType == "ADMIN"


class Driver(db.Model):
    __tablename__ = "Driver"

    DriverID            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID           = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    SponsorCompanyID    = db.Column(db.String(36), db.ForeignKey("SponsorCompany.SponsorCompanyID"), nullable=True)
    # Removed PointsBalance - points are now environment-specific via DriverSponsor table

    Status              = db.Column(db.String(32), nullable=False, default='ACTIVE', server_default='ACTIVE')

    CreatedAt           = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    UpdatedByAccountID  = db.Column(db.String(36))

    ShippingStreet      = db.Column(db.String(255))
    ShippingCity        = db.Column(db.String(100))
    ShippingState       = db.Column(db.String(50))
    ShippingCountry     = db.Column(db.String(50))
    ShippingPostal      = db.Column(db.String(20))

    Age                 = db.Column(db.Integer)
    Gender              = db.Column(db.String(1))

    LicenseNumber          = db.Column(db.String(255))  # encrypted
    LicenseIssueDate       = db.Column(db.String(255))  # encrypted
    LicenseExpirationDate  = db.Column(db.String(255))  # encrypted

    # --- ORM relationships (capitalized name to match template: d.Account.FirstName) ---
    Account = db.relationship(
        "Account",
        primaryjoin="Account.AccountID==foreign(Driver.AccountID)",
        lazy="joined",
        backref=db.backref("Drivers", lazy="dynamic")
    )
    sponsor_company = db.relationship(
        "SponsorCompany",
        lazy="joined",
        backref=db.backref("drivers", lazy="dynamic")
    )

    # ✅ NEW: Explicit environments relationship (driver ↔ driver-sponsor bridge)
    Environments = db.relationship(
        "DriverSponsor",
        primaryjoin="Driver.DriverID==foreign(DriverSponsor.DriverID)",
        lazy="dynamic",
        back_populates="driver"
    )

    # --- Decrypted accessors ---
    @property
    def license_number_plain(self):
        if not self.LicenseNumber:
            return None
        try:
            return fernet.decrypt(self.LicenseNumber.encode()).decode()
        except Exception:
            return self.LicenseNumber

    @license_number_plain.setter
    def license_number_plain(self, value: str):
        self.LicenseNumber = fernet.encrypt(value.encode()).decode()

    @property
    def license_issue_date_plain(self):
        if not self.LicenseIssueDate:
            return None
        try:
            return fernet.decrypt(self.LicenseIssueDate.encode()).decode()
        except Exception:
            return self.LicenseIssueDate

    @license_issue_date_plain.setter
    def license_issue_date_plain(self, value: str):
        self.LicenseIssueDate = fernet.encrypt(value.encode()).decode()

    @property
    def license_expiration_date_plain(self):
        if not self.LicenseExpirationDate:
            return None
        try:
            return fernet.decrypt(self.LicenseExpirationDate.encode()).decode()
        except Exception:
            return self.LicenseExpirationDate

    @license_expiration_date_plain.setter
    def license_expiration_date_plain(self, value: str):
        self.LicenseExpirationDate = fernet.encrypt(value.encode()).decode()


class SponsorCompany(db.Model):
    __tablename__ = "SponsorCompany"

    SponsorCompanyID    = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    CompanyName         = db.Column(db.String(200), unique=True, nullable=False)
    
    # Company-wide settings
    PointToDollarRate   = db.Column(db.Numeric, nullable=False, default=0.0100)
    MinPointsPerTxn     = db.Column(db.Integer, nullable=False, default=1)
    MaxPointsPerTxn     = db.Column(db.Integer, nullable=False, default=1000)
    
    # Company billing information
    BillingEmail        = db.Column(db.String(255))
    BillingStreet       = db.Column(db.String(255))
    BillingCity         = db.Column(db.String(100))
    BillingState        = db.Column(db.String(50))
    BillingCountry      = db.Column(db.String(50))
    BillingPostal       = db.Column(db.String(20))
    
    CreatedAt           = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to Sponsor users
    sponsors = db.relationship("Sponsor", back_populates="sponsor_company", lazy=True)


class Sponsor(db.Model):
    __tablename__ = "Sponsor"

    SponsorID           = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID           = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    
    # Keep Company field for backward compatibility during transition
    # Will eventually be replaced by SponsorCompanyID
    Company             = db.Column(db.String(200), nullable=False)
    SponsorCompanyID    = db.Column(db.String(36), db.ForeignKey("SponsorCompany.SponsorCompanyID"), nullable=True)

    IsAdmin             = db.Column(db.Boolean, default=False)
    
    # Company-wide settings (keeping for backward compatibility)
    PointToDollarRate   = db.Column(db.Numeric, nullable=False, default=0.0100)
    MinPointsPerTxn     = db.Column(db.Integer, nullable=False, default=1)
    MaxPointsPerTxn     = db.Column(db.Integer, nullable=False, default=1000)
    
    BillingEmail        = db.Column(db.String(255))
    BillingStreet       = db.Column(db.String(255))
    BillingCity         = db.Column(db.String(100))
    BillingState        = db.Column(db.String(50))
    BillingCountry      = db.Column(db.String(50))
    BillingPostal       = db.Column(db.String(20))

    CreatedAt           = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    UpdatedByAccountID  = db.Column(db.String(36))

    CatalogVersion      = db.Column(db.Integer)
    Features            = db.Column(db.JSON)

    # Relationship to company
    sponsor_company = db.relationship("SponsorCompany", back_populates="sponsors")

    # ✅ Explicit environments relationship (sponsor ↔ driver-sponsor bridge)
    DriverEnvironments = db.relationship(
        "DriverSponsor",
        primaryjoin="Sponsor.SponsorID==foreign(DriverSponsor.SponsorID)",
        lazy="dynamic",
        back_populates="sponsor"
    )


class Admin(db.Model):
    __tablename__ = "Admin"

    AdminID            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID          = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    Role               = db.Column(db.String(100))
    AlertLoginActivity = db.Column(db.Boolean, nullable=False, default=False)

    CreatedAt          = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt          = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    UpdatedByAccountID = db.Column(db.String(36))


# =============================================================================
# STATIC CONTENT
# About page, CMS-like content, etc.
# Add new static/content models here.
# =============================================================================

class AboutPage(db.Model):
    __tablename__ = "AboutPage"

    AboutPageID       = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    TeamNumber        = db.Column(db.String(40), nullable=False)
    VersionNumber     = db.Column(db.String(20), nullable=False)
    ReleaseDate       = db.Column(db.Date, nullable=False)
    ProductName       = db.Column(db.String(150), nullable=False)
    ProductDescription= db.Column(db.Text, nullable=False)
    CreatedAt         = db.Column(db.DateTime)
    UpdatedAt         = db.Column(db.DateTime)


# =============================================================================
# APPLICATIONS & AUTH
# Driver applications, login attempts, email verification.
# Add new auth/application-flow models here.
# =============================================================================

class Application(db.Model):
    __tablename__ = "Application"

    ApplicationID        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    AccountID            = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    SponsorID            = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)

    CDLClass             = db.Column(db.Enum("A", "B", "C", name="cdl_class"))
    ExperienceYears      = db.Column(db.SmallInteger)
    ExperienceMonths     = db.Column(db.SmallInteger)
    Transmission         = db.Column(db.Enum("AUTOMATIC", "MANUAL", name="transmission"))
    PreferredWeeklyHours = db.Column(db.SmallInteger)
    ViolationsCount3Y    = db.Column(db.SmallInteger)

    IncidentsJSON        = db.Column(db.JSON)           # accidents and any extra notes
    Suspensions5Y        = db.Column(db.Boolean, default=False)
    SuspensionsDetail    = db.Column(db.String(1000))

    ConsentedDataUse     = db.Column(db.Boolean, nullable=False, default=False)
    AgreedTerms          = db.Column(db.Boolean, nullable=False, default=False)

    ESignature           = db.Column(db.String(200))
    ESignedAt            = db.Column(db.DateTime)

    SubmittedAt          = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    ReviewedAt           = db.Column(db.DateTime)
    DecisionByAccountID  = db.Column(db.String(36))
    DecisionReason       = db.Column(db.String(1000))

    CreatedAt            = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    UpdatedAt            = db.Column(
        db.DateTime, nullable=False,
        server_default=db.func.now(), onupdate=db.func.now()
    )
    Decision = db.Column(
        db.Enum('accepted', 'rejected', name='application_decision'),
        nullable=True
    )


class LoginAttempts(db.Model):
    __tablename__ = "LoginAttempts"

    LoginAttemptID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID      = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    WasSuccessful  = db.Column(db.Boolean, nullable=False)
    IPAddress      = db.Column(db.String(50))
    AttemptedAt    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class EmailVerification(db.Model):
    __tablename__ = "EmailVerifications"

    EmailVerificationID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID           = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False, unique=True)
    VerificationToken   = db.Column(db.String(64), nullable=False)
    SentAt              = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    SendCount           = db.Column(db.Integer, default=0, nullable=False)
    IsVerified          = db.Column(db.Boolean, default=False, nullable=False)
    VerifiedAt          = db.Column(db.DateTime)

    account = db.relationship("Account", backref=db.backref("email_verification", uselist=False))


# =============================================================================
# CART & ORDERS
# Shopping cart, cart items, orders, order line items.
# Add new cart/order models here.
# =============================================================================

class Cart(db.Model):
    __tablename__ = "Cart"

    CartID               = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID             = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    CreatedAt            = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    driver = db.relationship("Driver", backref=db.backref("Cart", lazy="dynamic"))
    items = db.relationship("CartItem", backref="cart", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def total_points(self):
        return sum(item.total_points for item in self.items)

    @property
    def item_count(self):
        return sum(item.Quantity for item in self.items)

class CartItem(db.Model):
    __tablename__ = "CartItem"

    CartItemID           = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    CartID               = db.Column(db.String(36), db.ForeignKey("Cart.CartID"), nullable=False)
    
    # Item details (stored for external catalog items)
    ExternalItemID       = db.Column(db.String(100), nullable=False)  # ID from external catalog (e.g., eBay)
    ItemTitle            = db.Column(db.String(500), nullable=False)
    ItemImageURL         = db.Column(db.String(1000))
    ItemURL              = db.Column(db.String(1000))
    
    # Pricing
    PointsPerUnit        = db.Column(db.Integer, nullable=False)
    Quantity             = db.Column(db.Integer, nullable=False, default=1)
    
    # Metadata
    CreatedAt            = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def total_points(self):
        return self.PointsPerUnit * self.Quantity


class Orders(db.Model):
    __tablename__ = "Orders"

    OrderID              = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID             = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    SponsorID            = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)
    OrderNumber          = db.Column(db.String(64), nullable=False, unique=True)
    TotalPoints          = db.Column(db.BigInteger, nullable=False)
    TotalAmount          = db.Column(db.Numeric(12, 2))
    Status               = db.Column(db.String(32), nullable=False)
    ProviderOrderID      = db.Column(db.String(36))
    CancelledAt          = db.Column(db.DateTime)
    CancelledByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))
    CreatedAt            = db.Column(db.DateTime, default=local_now)
    UpdatedAt            = db.Column(db.DateTime, default=local_now, onupdate=local_now)

    # Relationships
    driver = db.relationship("Driver", backref=db.backref("Orders", lazy="dynamic"))
    sponsor = db.relationship("Sponsor", backref=db.backref("Orders", lazy="dynamic"))
    cancelled_by = db.relationship("Account", foreign_keys=[CancelledByAccountID])
    line_items = db.relationship("OrderLineItem", backref="order", lazy="dynamic", cascade="all, delete-orphan")


class OrderLineItem(db.Model):
    __tablename__ = "OrderLineItem"

    OrderLineItemID      = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    OrderID              = db.Column(db.String(36), db.ForeignKey("Orders.OrderID"), nullable=False)
    ProductID            = db.Column(db.String(36), db.ForeignKey("Products.ProductID"), nullable=False)
    Title                = db.Column(db.String(300), nullable=False)
    UnitPoints           = db.Column(db.Integer, nullable=False)
    Quantity             = db.Column(db.Integer, nullable=False, default=1)
    LineTotalPoints      = db.Column(db.Integer, nullable=False)
    CreatedAt            = db.Column(db.DateTime, default=local_now)

    # Relationships
    product = db.relationship("Products", backref=db.backref("OrderLineItems", lazy="dynamic"))

    @property
    def total_points(self):
        return self.LineTotalPoints


# =============================================================================
# INVOICES & POINTS
# Sponsor invoices, point changes, point disputes.
# Add new invoice/points models here.
# =============================================================================

class SponsorInvoice(db.Model):
    __tablename__ = "SponsorInvoice"

    SponsorInvoiceID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorCompanyID = db.Column(db.String(36), db.ForeignKey("SponsorCompany.SponsorCompanyID"))
    SponsorID        = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)

    InvoiceMonth     = db.Column(db.String(7), nullable=False)  # Format: YYYY-MM
    PeriodStart      = db.Column(db.DateTime, nullable=False)
    PeriodEnd        = db.Column(db.DateTime, nullable=False)

    TotalOrders      = db.Column(db.Integer, nullable=False, default=0)
    TotalPoints      = db.Column(db.BigInteger, nullable=False, default=0)
    TotalAmount      = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    GeneratedAt      = db.Column(db.DateTime, nullable=False, default=local_now)
    GeneratedBy      = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    Notes            = db.Column(db.Text)
    Status           = db.Column(db.String(20), nullable=False, default="PENDING")

    sponsor = db.relationship("Sponsor", backref=db.backref("Invoices", lazy="dynamic"))
    sponsor_company = db.relationship("SponsorCompany", backref=db.backref("Invoices", lazy="dynamic"))
    generated_by_account = db.relationship("Account", foreign_keys=[GeneratedBy])
    orders = db.relationship(
        "SponsorInvoiceOrder",
        backref="invoice",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )


class SponsorInvoiceOrder(db.Model):
    __tablename__ = "SponsorInvoiceOrder"

    SponsorInvoiceOrderID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorInvoiceID      = db.Column(db.String(36), db.ForeignKey("SponsorInvoice.SponsorInvoiceID"), nullable=False)

    OrderID               = db.Column(db.String(36), db.ForeignKey("Orders.OrderID"), nullable=False)
    OrderNumber           = db.Column(db.String(64), nullable=False)
    OrderCreatedAt        = db.Column(db.DateTime, nullable=False)

    DriverID              = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"))
    DriverName            = db.Column(db.String(200))
    DriverEmail           = db.Column(db.String(255))

    TotalPoints           = db.Column(db.BigInteger, nullable=False, default=0)
    TotalAmount           = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    LineItemCount         = db.Column(db.Integer, nullable=False, default=0)

    order = db.relationship("Orders", backref=db.backref("SponsorInvoiceOrders", lazy="dynamic"))
    driver = db.relationship("Driver", backref=db.backref("SponsorInvoiceOrders", lazy="dynamic"))


# =============================================================================
# PRODUCTS
# Product catalog, external catalog items.
# Add new product/catalog models here.
# =============================================================================

class Products(db.Model):
    __tablename__ = "Products"

    ProductID            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ProviderID           = db.Column(db.String(36))
    ExternalItemID       = db.Column(db.String(100))  # ID from external catalog (e.g., eBay)
    Title                = db.Column(db.String(300), nullable=False)
    Description          = db.Column(db.Text)
    AvailabilityStatus   = db.Column(db.String(32), nullable=False, default='in_stock')
    PointsPrice          = db.Column(db.Integer, nullable=False)
    PriceAmount          = db.Column(db.Numeric(12, 2))
    Currency             = db.Column(db.String(8))
    StockQuantity        = db.Column(db.Integer)
    AgeRestricted        = db.Column(db.Boolean, nullable=False, default=False)
    LastSyncedAt         = db.Column(db.DateTime)
    CreatedAt            = db.Column(db.DateTime, default=datetime.utcnow)


class PointChange(db.Model):
    __tablename__ = "PointChanges"

    PointChangeID        = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID             = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    SponsorID            = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)

    DeltaPoints          = db.Column(db.Integer, nullable=False)
    TransactionID        = db.Column(db.String(36), nullable=True)
    InitiatedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    BalanceAfter         = db.Column(db.Integer, nullable=False)

    CreatedAt            = db.Column(db.DateTime, nullable=False, default=local_now)
    Reason               = db.Column(db.String(256), nullable=True)
    ActorRoleCode        = db.Column(db.String(32))
    ActorLabel           = db.Column(db.String(128))
    ImpersonatedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))
    ImpersonatedByRoleCode  = db.Column(db.String(32))

    # Relationships
    driver       = db.relationship("Driver",  backref=db.backref("PointChanges", lazy="dynamic"))
    sponsor      = db.relationship("Sponsor", backref=db.backref("PointChanges", lazy="dynamic"))
    initiated_by = db.relationship("Account", foreign_keys=[InitiatedByAccountID])
    impersonated_by = db.relationship("Account", foreign_keys=[ImpersonatedByAccountID])

    _ROLE_LABELS = {
        "DRIVER": "Driver",
        "SPONSOR": "Sponsor",
        "ADMIN": "Admin",
        "SYSTEM": "System",
        "UNKNOWN": "Unknown",
    }

    @staticmethod
    def _role_label_from_code(code: str | None) -> str:
        if not code:
            return PointChange._ROLE_LABELS["UNKNOWN"]
        upper = code.upper()
        return PointChange._ROLE_LABELS.get(upper, upper.title())

    @property
    def actor_role_label(self) -> str:
        if self.ActorRoleCode:
            return self._role_label_from_code(self.ActorRoleCode)
        if self.initiated_by and self.initiated_by.AccountType:
            return self._role_label_from_code(self.initiated_by.AccountType)
        return self._role_label_from_code("SYSTEM")

    @property
    def actor_display_label(self) -> str:
        if self.ActorLabel:
            return self.ActorLabel
        return self.actor_role_label

    @property
    def impersonation_label(self) -> str | None:
        if self.ImpersonatedByRoleCode:
            return self._role_label_from_code(self.ImpersonatedByRoleCode)
        return None

    @property
    def impersonation_hint(self) -> str | None:
        label = self.impersonation_label
        if not label:
            return None
        if self.impersonated_by:
            identity = (
                self.impersonated_by.WholeName
                or self.impersonated_by.Username
                or self.impersonated_by.Email
                or self.impersonated_by.AccountID
            )
            return f"Performed by {identity} ({label}) while impersonating."
        return f"Performed via {label} impersonation."


class PointChangeDispute(db.Model):
    """Track disputes submitted by drivers for point changes"""
    __tablename__ = "PointChangeDisputes"

    DisputeID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    PointChangeID = db.Column(db.String(36), db.ForeignKey("PointChanges.PointChangeID"), nullable=False)
    DriverID = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)
    
    Status = db.Column(db.String(20), nullable=False, default="pending")  # pending, approved, denied
    DriverReason = db.Column(db.Text, nullable=False)  # Driver's explanation for disputing
    SponsorNotes = db.Column(db.Text, nullable=True)  # Sponsor's notes when resolving
    
    SubmittedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    ResolvedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=True)
    ResolvedAt = db.Column(db.DateTime, nullable=True)
    
    CreatedAt = db.Column(db.DateTime, nullable=False, default=local_now)
    UpdatedAt = db.Column(db.DateTime, nullable=False, default=local_now, onupdate=local_now)
    
    # Relationships
    point_change = db.relationship("PointChange", backref=db.backref("disputes", lazy="select"))
    driver = db.relationship("Driver", backref=db.backref("point_disputes", lazy="dynamic"))
    sponsor = db.relationship("Sponsor", backref=db.backref("point_disputes", lazy="dynamic"))
    submitted_by = db.relationship("Account", foreign_keys=[SubmittedByAccountID])
    resolved_by = db.relationship("Account", foreign_keys=[ResolvedByAccountID])
    
    @property
    def is_pending(self) -> bool:
        return (self.Status or "").lower() == "pending"
    
    @property
    def is_approved(self) -> bool:
        return (self.Status or "").lower() == "approved"
    
    @property
    def is_denied(self) -> bool:
        return (self.Status or "").lower() == "denied"
    
    @property
    def is_resolved(self) -> bool:
        return not self.is_pending


# =============================================================================
# ACCOUNT SECURITY & MANAGEMENT
# Password history, account deactivation, driver-sponsor bridge.
# Add new account/security models here.
# =============================================================================

class PasswordHistory(db.Model):
    """Track password changes for security auditing and password reuse prevention"""
    __tablename__ = "PasswordHistory"

    PasswordHistoryID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    PasswordHash = db.Column(db.String(255), nullable=False)
    ChangedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    ChangedBy = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=True)
    ChangeReason = db.Column(db.Enum('self_change', 'admin_reset', 'password_reset', 'initial_setup', name='change_reason'), 
                            nullable=False, default='self_change')
    IPAddress = db.Column(db.String(45), nullable=True)  # IPv4 or IPv6
    UserAgent = db.Column(db.Text, nullable=True)

    # Relationships
    account = db.relationship("Account", foreign_keys=[AccountID], backref=db.backref("password_history", lazy="dynamic"))
    changed_by_account = db.relationship("Account", foreign_keys=[ChangedBy])

    def __repr__(self):
        return f"<PasswordHistory {self.PasswordHistoryID}: {self.AccountID} at {self.ChangedAt}>"
    

class DriverSponsor(db.Model):
    __tablename__ = "DriverSponsor"

    DriverSponsorID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID        = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    SponsorID       = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)
    SponsorCompanyID = db.Column(db.String(36), db.ForeignKey("SponsorCompany.SponsorCompanyID"), nullable=False)
    PointsBalance   = db.Column(db.Integer, nullable=False, default=0)
    Status          = db.Column(db.String(32), nullable=False, default="ACTIVE")

    CreatedAt       = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    UpdatedAt       = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (db.UniqueConstraint("DriverID", "SponsorID", name="uq_ds"),)

    # ✅ Switched to explicit, non-conflicting relationships
    driver  = db.relationship("Driver",  back_populates="Environments")
    sponsor = db.relationship("Sponsor", back_populates="DriverEnvironments")
    sponsor_company = db.relationship("SponsorCompany", lazy="joined")


class DriverRewardGoal(db.Model):
    __tablename__ = "DriverRewardGoal"

    DriverRewardGoalID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverSponsorID    = db.Column(db.String(36), db.ForeignKey("DriverSponsor.DriverSponsorID"), nullable=False, unique=True)
    TargetName         = db.Column(db.String(255))
    TargetPoints       = db.Column(db.Integer)
    CreatedAt          = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    UpdatedAt          = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    driver_sponsor = db.relationship(
        "DriverSponsor",
        backref=db.backref("reward_goal", uselist=False, cascade="all, delete"),
    )


class AccountDeactivationRequest(db.Model):
    __tablename__ = "AccountDeactivationRequest"

    RequestID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    ReasonCode = db.Column(db.String(50), nullable=False)
    ReasonDetails = db.Column(db.Text, nullable=True)
    Status = db.Column(db.String(20), nullable=False, default="pending")
    CreatedAt = db.Column(db.DateTime, nullable=False, default=local_now)
    UpdatedAt = db.Column(db.DateTime, nullable=False, default=local_now, onupdate=local_now)
    ProcessedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))
    ProcessedAt = db.Column(db.DateTime, nullable=True)
    DecisionNotes = db.Column(db.Text, nullable=True)

    account = db.relationship("Account", foreign_keys=[AccountID], backref=db.backref("deactivation_requests", lazy="dynamic"))
    processed_by = db.relationship("Account", foreign_keys=[ProcessedByAccountID])

    @property
    def reason_label(self) -> str:
        mapping = {
            "no_longer_needed": "No longer need the account",
            "switching": "Switching organizations",
            "privacy": "Privacy concerns",
            "other": "Other",
        }
        return mapping.get((self.ReasonCode or "").lower(), self.ReasonCode or "Unknown")

    @property
    def is_pending(self) -> bool:
        return (self.Status or "").lower() == "pending"

    @property
    def is_resolved(self) -> bool:
        return (self.Status or "").lower() in {"approved", "denied", "cancelled"}


# =============================================================================
# CHALLENGES & ACHIEVEMENTS
# Challenge templates, sponsor challenges, driver subscriptions, achievements.
# Add new challenge/achievement models here.
# =============================================================================

class ChallengeTemplate(db.Model):
    __tablename__ = "ChallengeTemplate"

    ChallengeTemplateID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    Code                = db.Column(db.String(64), nullable=False, unique=True)
    Title               = db.Column(db.String(200), nullable=False)
    Description         = db.Column(db.Text, nullable=True)
    DefaultRewardPoints = db.Column(db.Integer, nullable=True)
    IsActive            = db.Column(db.Boolean, nullable=False, default=True)
    CreatedAt           = db.Column(db.DateTime, nullable=False, default=local_now)

    sponsor_challenges = db.relationship(
        "SponsorChallenge",
        back_populates="template",
        lazy="dynamic"
    )

    def __repr__(self):
        return f"<ChallengeTemplate {self.Code}>"


class SponsorChallenge(db.Model):
    __tablename__ = "SponsorChallenge"

    SponsorChallengeID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID          = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)
    ChallengeTemplateID= db.Column(db.String(36), db.ForeignKey("ChallengeTemplate.ChallengeTemplateID"), nullable=True)

    Title              = db.Column(db.String(200), nullable=False)
    Description        = db.Column(db.Text, nullable=True)
    RewardPoints       = db.Column(db.Integer, nullable=False)
    IsOptional         = db.Column(db.Boolean, nullable=False, default=True)
    StartsAt           = db.Column(db.DateTime, nullable=True)
    ExpiresAt          = db.Column(db.DateTime, nullable=True)
    IsActive           = db.Column(db.Boolean, nullable=False, default=True)
    CreatedAt          = db.Column(db.DateTime, nullable=False, default=local_now)
    UpdatedAt          = db.Column(db.DateTime, nullable=False, default=local_now, onupdate=local_now)

    sponsor = db.relationship("Sponsor", backref=db.backref("challenges", lazy="dynamic"))
    template = db.relationship("ChallengeTemplate", back_populates="sponsor_challenges")
    subscriptions = db.relationship(
        "DriverChallengeSubscription",
        back_populates="challenge",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    @property
    def is_available(self) -> bool:
        if not self.IsActive:
            return False
        now = datetime.utcnow()
        if self.StartsAt and self.StartsAt > now:
            return False
        if self.ExpiresAt and self.ExpiresAt < now:
            return False
        return True


class DriverChallengeSubscription(db.Model):
    __tablename__ = "DriverChallengeSubscription"

    DriverChallengeSubscriptionID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID                      = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    SponsorChallengeID            = db.Column(db.String(36), db.ForeignKey("SponsorChallenge.SponsorChallengeID"), nullable=False)
    Status = db.Column(
        db.Enum("subscribed", "completed", "expired", "removed", name="driver_challenge_status"),
        nullable=False,
        default="subscribed"
    )
    SubscribedAt = db.Column(db.DateTime, nullable=False, default=local_now)
    UpdatedAt    = db.Column(db.DateTime, nullable=False, default=local_now, onupdate=local_now)

    __table_args__ = (
        db.UniqueConstraint("DriverID", "SponsorChallengeID", name="uq_driver_challenge_subscription"),
    )

    driver = db.relationship("Driver", backref=db.backref("challenge_subscriptions", lazy="dynamic"))
    challenge = db.relationship("SponsorChallenge", back_populates="subscriptions")


class Achievement(db.Model):
    __tablename__ = "Achievement"

    AchievementID   = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    Code            = db.Column(db.String(100), nullable=False, unique=True)
    Title           = db.Column(db.String(200), nullable=False)
    Description     = db.Column(db.Text, nullable=True)
    PointsThreshold = db.Column(db.Integer, nullable=True)
    IsPointsBased   = db.Column(db.Boolean, nullable=False, default=False)
    IsActive        = db.Column(db.Boolean, nullable=False, default=True)
    CreatedAt       = db.Column(db.DateTime, nullable=False, default=local_now)
    UpdatedAt       = db.Column(db.DateTime, nullable=False, default=local_now, onupdate=local_now)

    driver_achievements = db.relationship(
        "DriverAchievement",
        back_populates="achievement",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Achievement {self.Code}>"


class DriverAchievement(db.Model):
    __tablename__ = "DriverAchievement"

    DriverAchievementID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID            = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    AchievementID       = db.Column(db.String(36), db.ForeignKey("Achievement.AchievementID"), nullable=False)
    IsEarned            = db.Column(db.Boolean, nullable=False, default=False)
    EarnedAt            = db.Column(db.DateTime, nullable=True)
    CreatedAt           = db.Column(db.DateTime, nullable=False, default=local_now)
    UpdatedAt           = db.Column(db.DateTime, nullable=False, default=local_now, onupdate=local_now)

    __table_args__ = (
        db.UniqueConstraint("DriverID", "AchievementID", name="uq_driver_achievement"),
    )

    driver = db.relationship("Driver", backref=db.backref("driver_achievements", lazy="dynamic"))
    achievement = db.relationship("Achievement", back_populates="driver_achievements")


# =============================================================================
# PRODUCT VIEWS & ANALYTICS
# Driver product view history, analytics.
# Add new product-view/analytics models here.
# =============================================================================

class DriverProductView(db.Model):
    __tablename__ = "DriverProductView"

    DriverProductViewID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID            = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    ProductID           = db.Column(db.String(36), db.ForeignKey("Products.ProductID"), nullable=True)
    SponsorID           = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=True)
    Provider            = db.Column(db.String(50), nullable=True)
    ExternalItemID      = db.Column(db.String(150), nullable=True)
    ProductTitle        = db.Column(db.String(300), nullable=True)
    ImageURL            = db.Column(db.String(1000), nullable=True)
    PointsSnapshot      = db.Column(db.Integer, nullable=True)
    PriceSnapshot       = db.Column(db.Numeric(12, 2), nullable=True)
    Currency            = db.Column(db.String(8), nullable=True)
    ViewedAt            = db.Column(db.DateTime, nullable=False, default=local_now)
    CreatedAt           = db.Column(db.DateTime, nullable=False, default=local_now)
    UpdatedAt           = db.Column(db.DateTime, nullable=False, default=local_now, onupdate=local_now)

    __table_args__ = (
        db.Index("idx_driver_product_viewed", "DriverID", "ViewedAt"),
        db.Index("idx_driver_product_item", "DriverID", "ExternalItemID"),
    )

    driver = db.relationship("Driver", backref=db.backref("product_views", lazy="dynamic"))
    product = db.relationship("Products", backref=db.backref("driver_views", lazy="dynamic"))
    sponsor = db.relationship("Sponsor", backref=db.backref("driver_product_views", lazy="dynamic"))


# =============================================================================
# SESSIONS
# User session tracking for security and multi-device management.
# Add new session models here.
# =============================================================================

class UserSessions(db.Model):
    """Track active user sessions for security management and auto-logout"""
    __tablename__ = "UserSessions"

    SessionID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    SessionToken = db.Column(db.String(255), nullable=False, unique=True)
    DeviceName = db.Column(db.String(255), nullable=True)
    DeviceType = db.Column(db.String(50), nullable=True)  # 'desktop', 'mobile', 'tablet', 'unknown'
    BrowserName = db.Column(db.String(100), nullable=True)
    BrowserVersion = db.Column(db.String(50), nullable=True)
    OperatingSystem = db.Column(db.String(100), nullable=True)
    IPAddress = db.Column(db.String(45), nullable=False)
    UserAgent = db.Column(db.Text, nullable=True)
    CreatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    LastActivityAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    IsActive = db.Column(db.Boolean, nullable=False, default=True)
    ExpiresAt = db.Column(db.DateTime, nullable=False)

    # Relationships
    account = db.relationship("Account", backref=db.backref("sessions", lazy="dynamic"))

    def __repr__(self):
        return f"<UserSession {self.SessionID}: {self.AccountID} on {self.DeviceName or 'Unknown Device'}>"
    
    @property
    def is_expired(self):
        """Check if session has expired"""
        from datetime import datetime
        return datetime.utcnow() > self.ExpiresAt
    
    @property
    def is_inactive(self):
        """Check if session has been inactive for more than 30 minutes"""
        from datetime import datetime, timedelta
        return datetime.utcnow() - self.LastActivityAt > timedelta(minutes=30)


# =============================================================================
# NOTIFICATIONS
# In-app notifications, notification preferences (driver, sponsor, admin).
# Add new notification models here.
# =============================================================================

class DriverNotification(db.Model):
    """Individual notification records for drivers"""
    __tablename__ = "DriverNotification"

    NotificationID = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    DriverID = db.Column(
        db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False, index=True
    )
    Type = db.Column(db.String(50), nullable=False)
    Title = db.Column(db.String(255), nullable=False)
    Body = db.Column(db.Text, nullable=False)
    Metadata = db.Column(db.JSON, nullable=True)
    DeliveredVia = db.Column(db.String(50), nullable=True)  # email, in_app, push
    IsRead = db.Column(db.Boolean, nullable=False, default=False, index=True)
    CreatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    ReadAt = db.Column(db.DateTime, nullable=True)

    # Relationships
    driver = db.relationship(
        "Driver",
        backref=db.backref("notifications", lazy="dynamic"),
    )

    def mark_read(self):
        """Mark notification as read."""
        from datetime import datetime

        if not self.IsRead:
            self.IsRead = True
            self.ReadAt = datetime.utcnow()


class NotificationPreferences(db.Model):
    """Driver notification preferences for different notification types"""
    __tablename__ = "NotificationPreferences"

    NotificationPreferenceID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False, unique=True)
    
    # Notification type toggles
    PointChanges = db.Column(db.Boolean, nullable=False, default=True)
    OrderConfirmations = db.Column(db.Boolean, nullable=False, default=True)
    ApplicationUpdates = db.Column(db.Boolean, nullable=False, default=True)
    TicketUpdates = db.Column(db.Boolean, nullable=False, default=True)
    RefundWindowAlerts = db.Column(db.Boolean, nullable=False, default=True)
    AccountStatusChanges = db.Column(db.Boolean, nullable=False, default=True)
    SensitiveInfoResets = db.Column(db.Boolean, nullable=False, default=True)
    
    # Notification delivery preferences
    EmailEnabled = db.Column(db.Boolean, nullable=False, default=True)
    InAppEnabled = db.Column(db.Boolean, nullable=False, default=True)
    
    # Quiet Hours preferences (for non-critical notifications)
    # Non-critical: PointChanges, OrderConfirmations, ApplicationUpdates, TicketUpdates, RefundWindowAlerts
    # Critical (always sent): AccountStatusChanges, SensitiveInfoResets
    QuietHoursEnabled = db.Column(db.Boolean, nullable=False, default=False)
    QuietHoursStart = db.Column(db.Time, nullable=True)  # e.g., 22:00 (10 PM)
    QuietHoursEnd = db.Column(db.Time, nullable=True)   # e.g., 07:00 (7 AM)
    
    # Low Points Alert preferences
    LowPointsAlertEnabled = db.Column(db.Boolean, nullable=False, default=False)
    LowPointsThreshold = db.Column(db.Integer, nullable=True)  # Points threshold for low balance alert
    
    # Timestamps
    CreatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    # Relationships
    driver = db.relationship("Driver", backref=db.backref("notification_preferences", uselist=False))

    def __repr__(self):
        return f"<NotificationPreferences {self.NotificationPreferenceID}: Driver {self.DriverID}>"
    
    
    @classmethod
    def get_or_create_for_driver(cls, driver_id: str):
        """Get existing preferences or create default ones for a driver"""
        prefs = cls.query.filter_by(DriverID=driver_id).first()
        if not prefs:
            prefs = cls(DriverID=driver_id, LowPointsThreshold=100, AccountStatusChanges=True)
            db.session.add(prefs)
            db.session.commit()
        else:
            # Ensure AccountStatusChanges is always enabled (security requirement)
            if not prefs.AccountStatusChanges:
                prefs.AccountStatusChanges = True
            if prefs.LowPointsThreshold is None:
                prefs.LowPointsThreshold = 100
            db.session.commit()
        return prefs


class SponsorNotificationPreferences(db.Model):
    """Sponsor notification preferences for different notification types"""
    __tablename__ = "SponsorNotificationPreferences"

    NotificationPreferenceID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, unique=True)
    
    # Notification type toggles
    OrderConfirmations = db.Column(db.Boolean, nullable=False, default=True)
    NewApplications = db.Column(db.Boolean, nullable=False, default=True)
    DriverPointsChanges = db.Column(db.Boolean, nullable=False, default=False)
    SystemAlerts = db.Column(db.Boolean, nullable=False, default=True)
    TicketUpdates = db.Column(db.Boolean, nullable=False, default=True)
    
    # Notification delivery preferences
    EmailEnabled = db.Column(db.Boolean, nullable=False, default=True)
    InAppEnabled = db.Column(db.Boolean, nullable=False, default=True)
    
    # Timestamps
    CreatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    # Relationships
    sponsor = db.relationship("Sponsor", backref=db.backref("notification_preferences", uselist=False))

    def __repr__(self):
        return f"<SponsorNotificationPreferences {self.NotificationPreferenceID}: Sponsor {self.SponsorID}>"
    
    @classmethod
    def get_or_create_for_sponsor(cls, sponsor_id: str):
        """Get existing preferences or create default ones for a sponsor"""
        prefs = cls.query.filter_by(SponsorID=sponsor_id).first()
        if not prefs:
            prefs = cls(SponsorID=sponsor_id)
            db.session.add(prefs)
            db.session.commit()
        return prefs


class AdminNotificationPreferences(db.Model):
    """Admin notification preferences for different notification types"""
    __tablename__ = "AdminNotificationPreferences"

    NotificationPreferenceID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AdminID = db.Column(db.String(36), db.ForeignKey("Admin.AdminID"), nullable=False, unique=True)
    
    # Notification type toggles
    LoginSuspiciousActivity = db.Column(db.Boolean, nullable=False, default=True)
    SystemAlerts = db.Column(db.Boolean, nullable=False, default=True)
    SecurityIncidents = db.Column(db.Boolean, nullable=False, default=True)
    UserRegistration = db.Column(db.Boolean, nullable=False, default=False)
    
    # Notification delivery preferences
    EmailEnabled = db.Column(db.Boolean, nullable=False, default=True)
    InAppEnabled = db.Column(db.Boolean, nullable=False, default=True)
    
    # Timestamps
    CreatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())

    # Relationships
    admin = db.relationship("Admin", backref=db.backref("notification_preferences", uselist=False))

    def __repr__(self):
        return f"<AdminNotificationPreferences {self.NotificationPreferenceID}: Admin {self.AdminID}>"
    
    @classmethod
    def get_or_create_for_admin(cls, admin_id: str):
        """Get existing preferences or create default ones for an admin"""
        prefs = cls.query.filter_by(AdminID=admin_id).first()
        if not prefs:
            prefs = cls(AdminID=admin_id)
            db.session.add(prefs)
            db.session.commit()
        return prefs


# =============================================================================
# PROFILE AUDITS
# Audit logs for driver, sponsor, and admin profile changes.
# Add new profile-audit models here.
# =============================================================================

class DriverProfileAudit(db.Model):
    __tablename__ = "DriverProfileAudit"

    AuditID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False)
    AccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=True)
    FieldName = db.Column(db.String(100), nullable=False)
    OldValue = db.Column(db.Text, nullable=True)
    NewValue = db.Column(db.Text, nullable=True)
    ChangedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=True)
    ChangeReason = db.Column(db.String(500), nullable=True)
    ChangedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    Driver = db.relationship("Driver", backref="profile_audits")
    Account = db.relationship("Account", foreign_keys=[AccountID], backref="driver_profile_changes")
    Sponsor = db.relationship("Sponsor", backref="driver_profile_audits")
    ChangedBy = db.relationship("Account", foreign_keys=[ChangedByAccountID], backref="driver_profile_modifications")


class SponsorProfileAudit(db.Model):
    __tablename__ = "SponsorProfileAudit"

    AuditID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False)
    AccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    FieldName = db.Column(db.String(100), nullable=False)
    OldValue = db.Column(db.Text, nullable=True)
    NewValue = db.Column(db.Text, nullable=True)
    ChangedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=True)
    ChangeReason = db.Column(db.String(500), nullable=True)
    ChangedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    Sponsor = db.relationship("Sponsor", backref="profile_audits")
    Account = db.relationship("Account", foreign_keys=[AccountID], backref="sponsor_profile_changes")
    ChangedBy = db.relationship("Account", foreign_keys=[ChangedByAccountID], backref="sponsor_profile_modifications")


class AdminProfileAudit(db.Model):
    __tablename__ = "AdminProfileAudit"

    AuditID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    AdminID = db.Column(db.String(36), db.ForeignKey("Admin.AdminID"), nullable=False)
    AccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    FieldName = db.Column(db.String(100), nullable=False)
    OldValue = db.Column(db.Text, nullable=True)
    NewValue = db.Column(db.Text, nullable=True)
    ChangedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=True)
    ChangeReason = db.Column(db.String(500), nullable=True)
    ChangedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    Admin = db.relationship("Admin", backref="profile_audits")
    Account = db.relationship("Account", foreign_keys=[AccountID], backref="admin_profile_changes")
    ChangedBy = db.relationship("Account", foreign_keys=[ChangedByAccountID], backref="admin_profile_modifications")


# =============================================================================
# SUPPORT
# Support categories, tickets, messages.
# Add new support models here.
# =============================================================================

class SupportCategory(db.Model):
    __tablename__ = "SupportCategory"

    CategoryID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    Name = db.Column(db.String(100), nullable=False, unique=True)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SupportCategory {self.Name}>"


class SupportTicket(db.Model):
    __tablename__ = "SupportTicket"

    TicketID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    Source = db.Column(db.Enum("sponsor", "driver", name="ticket_source"), nullable=False)
    OwnerID = db.Column(db.String(36), nullable=False)  # SponsorID or DriverID
    Title = db.Column(db.String(200), nullable=False)
    Body = db.Column(db.Text, nullable=False)
    Status = db.Column(db.Enum("new", "open", "waiting", "resolved", "closed", name="ticket_status"), 
                      nullable=False, default="new")
    CategoryID = db.Column(db.String(36), db.ForeignKey("SupportCategory.CategoryID"), nullable=True)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)
    UpdatedAt = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ClosedAt = db.Column(db.DateTime, nullable=True)

    # Relationships
    category = db.relationship("SupportCategory", backref=db.backref("tickets", lazy="dynamic"))
    messages = db.relationship("SupportMessage", backref="ticket", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<SupportTicket {self.TicketID}: {self.Title}>"


class SupportMessage(db.Model):
    __tablename__ = "SupportMessage"

    MessageID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    TicketID = db.Column(db.String(36), db.ForeignKey("SupportTicket.TicketID"), nullable=False)
    AuthorRole = db.Column(db.Enum("admin", "sponsor", "driver", name="message_author_role"), nullable=False)
    AuthorID = db.Column(db.String(36), nullable=False)  # AdminID, SponsorID, or DriverID
    Body = db.Column(db.Text, nullable=False)
    CreatedAt = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SupportMessage {self.MessageID}: {self.AuthorRole}>"


# =============================================================================
# BULK IMPORT
# Bulk import logs and row-level errors.
# Add new bulk-import models here.
# =============================================================================

class BulkImportLog(db.Model):
    """Log bulk import operations and errors for auditing and debugging"""
    __tablename__ = "BulkImportLog"

    BulkImportLogID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Who performed the import
    UploadedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=False)
    UploadedByRole = db.Column(db.Enum("admin", "sponsor", name="uploader_role"), nullable=False)
    SponsorCompanyID = db.Column(db.String(36), db.ForeignKey("SponsorCompany.SponsorCompanyID"), nullable=True)
    
    # Import session details
    FileName = db.Column(db.String(255), nullable=False)
    TotalRows = db.Column(db.Integer, nullable=False, default=0)
    SuccessCount = db.Column(db.Integer, nullable=False, default=0)
    ErrorCount = db.Column(db.Integer, nullable=False, default=0)
    
    # Summary of import operation
    ImportSummary = db.Column(db.Text, nullable=True)  # JSON or text summary
    
    # Timestamps
    ImportedAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    uploaded_by = db.relationship("Account", foreign_keys=[UploadedByAccountID])
    sponsor_company = db.relationship("SponsorCompany", backref="bulk_import_logs")
    
    def __repr__(self):
        return f"<BulkImportLog {self.BulkImportLogID}: {self.FileName} by {self.UploadedByRole}>"


class BulkImportError(db.Model):
    """Individual row-level errors from bulk imports"""
    __tablename__ = "BulkImportError"

    BulkImportErrorID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Link to the import session
    BulkImportLogID = db.Column(db.String(36), db.ForeignKey("BulkImportLog.BulkImportLogID"), nullable=False)
    
    # Error details
    RowNumber = db.Column(db.Integer, nullable=False)
    CSVRowData = db.Column(db.Text, nullable=True)  # The actual row data that failed
    ErrorMessage = db.Column(db.Text, nullable=False)
    
    # Timestamps
    ErroredAt = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    bulk_import_log = db.relationship("BulkImportLog", backref="errors")
    
    def __repr__(self):
        return f"<BulkImportError {self.BulkImportErrorID}: Row {self.RowNumber}>"


# =============================================================================
# DRIVER FAVORITES & PRODUCT REPORTS
# Driver wishlists/favorites, product reports (inappropriate items).
# Add new driver-favorites or product-report models here.
# =============================================================================

class DriverFavorites(db.Model):
    __tablename__ = "DriverFavorites"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False, index=True)
    ExternalItemID = db.Column(db.String(255), nullable=False, index=True)  # eBay item ID
    ItemTitle = db.Column(db.String(500), nullable=True)
    ItemImageURL = db.Column(db.String(1000), nullable=True)
    ItemPoints = db.Column(db.Integer, nullable=True)
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    driver_id = synonym("DriverID")
    external_item_id = synonym("ExternalItemID")
    item_title = synonym("ItemTitle")
    item_image_url = synonym("ItemImageURL")
    item_points = synonym("ItemPoints")
    created_at = synonym("CreatedAt")
    updated_at = synonym("UpdatedAt")

    @property
    def id(self):
        return self.ID

    __table_args__ = (
        db.UniqueConstraint("DriverID", "ExternalItemID", name="unique_driver_favorite"),
    )


class ProductReports(db.Model):
    __tablename__ = "ProductReports"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    DriverID = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False, index=True)
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    ExternalItemID = db.Column(db.String(255), nullable=False, index=True)  # eBay item ID
    ItemTitle = db.Column(db.String(500), nullable=True)
    ItemImageURL = db.Column(db.String(1000), nullable=True)
    ItemURL = db.Column(db.String(1000), nullable=True)
    ReportReason = db.Column(db.String(50), nullable=False)
    ReportDescription = db.Column(db.Text, nullable=True)
    Status = db.Column(db.String(20), nullable=False, default="pending")
    ReviewedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=True)
    ReviewedAt = db.Column(db.DateTime, nullable=True)
    ReviewNotes = db.Column(db.Text, nullable=True)
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    driver_id = synonym("DriverID")
    sponsor_id = synonym("SponsorID")
    external_item_id = synonym("ExternalItemID")
    item_title = synonym("ItemTitle")
    item_image_url = synonym("ItemImageURL")
    item_url = synonym("ItemURL")
    report_reason = synonym("ReportReason")
    report_description = synonym("ReportDescription")
    status = synonym("Status")
    reviewed_by_account_id = synonym("ReviewedByAccountID")
    reviewed_at = synonym("ReviewedAt")
    review_notes = synonym("ReviewNotes")
    created_at = synonym("CreatedAt")
    updated_at = synonym("UpdatedAt")

    @property
    def id(self):
        return self.ID


# =============================================================================
# SPONSOR CATALOG
# Filter sets, pinned products, exclusions, cache, points policy, blacklist.
# Add new sponsor-catalog models here.
# =============================================================================

class SponsorCatalogFilterSet(db.Model):
    __tablename__ = "SponsorCatalogFilterSet"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    Name = db.Column(db.String(120), nullable=False)
    IsActive = db.Column(db.Boolean, nullable=False, default=True)
    Priority = db.Column(db.Integer, nullable=False, default=100)
    RulesJSON = db.Column(JSONT, nullable=False, default=dict)
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    sponsor_id = synonym("SponsorID")
    name = synonym("Name")
    is_active = synonym("IsActive")
    priority = synonym("Priority")
    rules_json = synonym("RulesJSON")
    created_at = synonym("CreatedAt")
    updated_at = synonym("UpdatedAt")

    @property
    def id(self):
        return self.ID


class SponsorPinnedProduct(db.Model):
    __tablename__ = "SponsorPinnedProduct"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID = db.Column(db.String(64), nullable=False, index=True)
    PinRank = db.Column(db.Integer)
    ItemTitle = db.Column(db.String(512))
    ItemImageURL = db.Column(db.String(1024))
    Note = db.Column(db.String(255))
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    PinnedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))

    __table_args__ = (
        db.UniqueConstraint("SponsorID", "ItemID", name="uq_sponsor_pinned_item"),
    )

    sponsor_id = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id = synonym("ItemID")
    pin_rank = synonym("PinRank")
    item_title = synonym("ItemTitle")
    item_image_url = synonym("ItemImageURL")
    note = synonym("Note")
    created_at = synonym("CreatedAt")
    updated_at = synonym("UpdatedAt")
    pinned_by_account_id = synonym("PinnedByAccountID")

    @property
    def id(self):
        return self.ID


class SponsorCatalogInclusion(db.Model):
    __tablename__ = "SponsorCatalogInclusion"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID = db.Column(db.String(64), nullable=False)
    IsPinned = db.Column(db.Boolean, nullable=False, default=False)
    PinRank = db.Column(db.Integer)
    Note = db.Column(db.String(255))
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())

    sponsor_id = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id = synonym("ItemID")
    is_pinned = synonym("IsPinned")
    pin_rank = synonym("PinRank")
    note = synonym("Note")
    created_at = synonym("CreatedAt")

    @property
    def id(self):
        return self.ID


class SponsorCatalogExclusion(db.Model):
    __tablename__ = "SponsorCatalogExclusion"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID = db.Column(db.String(64), nullable=False)
    Reason = db.Column(db.String(255))
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())

    sponsor_id = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id = synonym("ItemID")
    reason = synonym("Reason")
    created_at = synonym("CreatedAt")

    @property
    def id(self):
        return self.ID


class SponsorCatalogResultCache(db.Model):
    __tablename__ = "SponsorCatalogResultCache"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    FilterFingerprint = db.Column(db.String(64), nullable=False, index=True)
    Page = db.Column(db.Integer, nullable=False, default=1)
    Sort = db.Column(db.String(32), nullable=False, default="best_match")
    ResultsJSON = db.Column(JSONT, nullable=False, default=dict)
    ExpiresAt = db.Column(db.DateTime, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("SponsorID", "FilterFingerprint", "Page", "Sort", name="uq_sponsor_cache_key"),
    )

    sponsor_id = synonym("SponsorID")
    filter_fingerprint = synonym("FilterFingerprint")
    page = synonym("Page")
    sort = synonym("Sort")
    results_json = synonym("ResultsJSON")
    expires_at = synonym("ExpiresAt")

    @property
    def id(self):
        return self.ID


class SponsorAuditLog(db.Model):
    __tablename__ = "SponsorAuditLog"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    ActorUserID = db.Column(db.String(36))
    Action = db.Column(db.String(64), nullable=False)
    DetailsJSON = db.Column(JSONT)
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())

    sponsor_id = synonym("SponsorID")
    actor_user_id = synonym("ActorUserID")
    action = synonym("Action")
    details_json = synonym("DetailsJSON")
    created_at = synonym("CreatedAt")

    @property
    def id(self):
        return self.ID


class SponsorPointsPolicy(db.Model):
    __tablename__ = "SponsorPointsPolicy"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, unique=True, index=True)
    Strategy = db.Column(db.String(24), nullable=False, default="FLAT_RATE")
    ConfigJSON = db.Column(JSONT, nullable=False, default=dict)
    MinPoints = db.Column(db.Integer)
    MaxPoints = db.Column(db.Integer)
    Rounding = db.Column(db.String(24), nullable=False, default="NEAREST_10")
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    sponsor_id = synonym("SponsorID")
    strategy = synonym("Strategy")
    config_json = synonym("ConfigJSON")
    min_points = synonym("MinPoints")
    max_points = synonym("MaxPoints")
    rounding = synonym("Rounding")
    created_at = synonym("CreatedAt")
    updated_at = synonym("UpdatedAt")

    @property
    def id(self):
        return self.ID


class SponsorActiveFilterSelection(db.Model):
    __tablename__ = "SponsorActiveFilterSelection"

    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), primary_key=True)
    FilterSetID = db.Column(db.String(36), db.ForeignKey("SponsorCatalogFilterSet.ID"), nullable=True)
    SelectedAt = db.Column(db.DateTime, server_default=db.func.now())
    SelectedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))

    sponsor_id = synonym("SponsorID")
    filter_set_id = synonym("FilterSetID")
    selected_at = synonym("SelectedAt")
    selected_by_account_id = synonym("SelectedByAccountID")


class BlacklistedProduct(db.Model):
    __tablename__ = "BlacklistedProduct"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID = db.Column(db.String(64), nullable=False, index=True)
    Reason = db.Column(db.String(255))
    ItemTitle = db.Column(db.String(512))
    ItemImageURL = db.Column(db.String(1024))
    ItemURL = db.Column(db.String(1024))
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    BlacklistedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))
    SourceReportID = db.Column(db.String(36), db.ForeignKey("ProductReports.ID"))

    __table_args__ = (
        db.UniqueConstraint("SponsorID", "ItemID", name="uq_sponsor_blacklisted_item"),
    )

    sponsor_id = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id = synonym("ItemID")
    reason = synonym("Reason")
    item_title = synonym("ItemTitle")
    item_image_url = synonym("ItemImageURL")
    item_url = synonym("ItemURL")
    created_at = synonym("CreatedAt")
    blacklisted_by_account_id = synonym("BlacklistedByAccountID")
    source_report_id = synonym("SourceReportID")

    @property
    def id(self):
        return self.ID