# app/models_sponsor_catalog.py
from uuid import uuid4
from .extensions import db
from sqlalchemy.orm import synonym

# Portable JSON type
JSONT = db.JSON


# ------------------------------------------------------------
# SponsorCatalogFilterSet
# ------------------------------------------------------------
class SponsorCatalogFilterSet(db.Model):
    __tablename__ = "SponsorCatalogFilterSet"

    ID         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID  = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)

    # DB columns (PascalCase)
    Name       = db.Column(db.String(120), nullable=False)
    IsActive   = db.Column(db.Boolean,      nullable=False, default=True)
    Priority   = db.Column(db.Integer,      nullable=False, default=100)
    RulesJSON  = db.Column(JSONT,           nullable=False, default=dict)
    CreatedAt  = db.Column(db.DateTime,     server_default=db.func.now())
    UpdatedAt  = db.Column(db.DateTime,     server_default=db.func.now(), onupdate=db.func.now())

    # snake_case synonyms (what the rest of the app uses)
    sponsor_id = synonym("SponsorID")
    name       = synonym("Name")
    is_active  = synonym("IsActive")
    priority   = synonym("Priority")
    rules_json = synonym("RulesJSON")
    created_at = synonym("CreatedAt")
    updated_at = synonym("UpdatedAt")

    # convenience for templates that expect .id
    @property
    def id(self): return self.ID


# ------------------------------------------------------------
# SponsorPinnedProduct - Sponsor-curated featured products
# ------------------------------------------------------------
class SponsorPinnedProduct(db.Model):
    __tablename__ = "SponsorPinnedProduct"

    ID         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID  = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)

    # DB columns (PascalCase) - stores enough info to re-fetch from eBay API
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID      = db.Column(db.String(64),  nullable=False, index=True)  # eBay item ID
    PinRank     = db.Column(db.Integer)  # display order (lower = higher priority)
    
    # Cached display info (refreshed from API on pinned products page)
    ItemTitle   = db.Column(db.String(512))  # cached for display
    ItemImageURL = db.Column(db.String(1024))  # cached thumbnail
    
    Note        = db.Column(db.String(255))  # sponsor's internal note
    CreatedAt   = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt   = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    PinnedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))  # who pinned it

    # Unique constraint: one sponsor can't pin the same item twice
    __table_args__ = (
        db.UniqueConstraint("SponsorID", "ItemID", name="uq_sponsor_pinned_item"),
    )

    # snake_case synonyms
    sponsor_id  = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id     = synonym("ItemID")
    pin_rank    = synonym("PinRank")
    item_title  = synonym("ItemTitle")
    item_image_url = synonym("ItemImageURL")
    note        = synonym("Note")
    created_at  = synonym("CreatedAt")
    updated_at  = synonym("UpdatedAt")
    pinned_by_account_id = synonym("PinnedByAccountID")

    @property
    def id(self): return self.ID


# ------------------------------------------------------------
# SponsorCatalogInclusion (legacy - kept for backward compatibility)
# ------------------------------------------------------------
class SponsorCatalogInclusion(db.Model):
    __tablename__ = "SponsorCatalogInclusion"

    ID         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID  = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)

    # DB columns (PascalCase)
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID      = db.Column(db.String(64),  nullable=False)
    IsPinned    = db.Column(db.Boolean,      nullable=False, default=False)
    PinRank     = db.Column(db.Integer)  # nullable for non-pinned rows
    Note        = db.Column(db.String(255))
    CreatedAt   = db.Column(db.DateTime, server_default=db.func.now())

    # snake_case synonyms
    sponsor_id  = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id     = synonym("ItemID")
    is_pinned   = synonym("IsPinned")
    pin_rank    = synonym("PinRank")
    note        = synonym("Note")
    created_at  = synonym("CreatedAt")

    @property
    def id(self): return self.ID


# ------------------------------------------------------------
# SponsorCatalogExclusion (blocked items)
# ------------------------------------------------------------
class SponsorCatalogExclusion(db.Model):
    __tablename__ = "SponsorCatalogExclusion"

    ID         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID  = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)

    # DB columns (PascalCase)
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID      = db.Column(db.String(64),  nullable=False)
    Reason      = db.Column(db.String(255))
    CreatedAt   = db.Column(db.DateTime, server_default=db.func.now())

    # snake_case synonyms
    sponsor_id  = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id     = synonym("ItemID")
    reason      = synonym("Reason")
    created_at  = synonym("CreatedAt")

    @property
    def id(self): return self.ID


# ------------------------------------------------------------
# SponsorCatalogResultCache
# ------------------------------------------------------------
class SponsorCatalogResultCache(db.Model):
    __tablename__ = "SponsorCatalogResultCache"

    ID        = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)

    # DB columns (PascalCase)
    FilterFingerprint = db.Column(db.String(64), nullable=False, index=True)
    Page              = db.Column(db.Integer,    nullable=False, default=1)
    Sort              = db.Column(db.String(32), nullable=False, default="best_match")
    ResultsJSON       = db.Column(JSONT,         nullable=False, default=dict)
    ExpiresAt         = db.Column(db.DateTime,   nullable=False)

    __table_args__ = (
        db.UniqueConstraint("SponsorID", "FilterFingerprint", "Page", "Sort", name="uq_sponsor_cache_key"),
    )

    # snake_case synonyms
    sponsor_id         = synonym("SponsorID")
    filter_fingerprint = synonym("FilterFingerprint")
    page               = synonym("Page")
    sort               = synonym("Sort")
    results_json       = synonym("ResultsJSON")
    expires_at         = synonym("ExpiresAt")

    @property
    def id(self): return self.ID


# ------------------------------------------------------------
# SponsorAuditLog
# ------------------------------------------------------------
class SponsorAuditLog(db.Model):
    __tablename__ = "SponsorAuditLog"

    ID          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID   = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)
    ActorUserID = db.Column(db.String(36))
    Action      = db.Column(db.String(64), nullable=False)
    DetailsJSON = db.Column(JSONT)
    CreatedAt   = db.Column(db.DateTime, server_default=db.func.now())

    # snake_case synonyms
    sponsor_id    = synonym("SponsorID")
    actor_user_id = synonym("ActorUserID")
    action        = synonym("Action")
    details_json  = synonym("DetailsJSON")
    created_at    = synonym("CreatedAt")

    @property
    def id(self): return self.ID


# ------------------------------------------------------------
# SponsorPointsPolicy
# ------------------------------------------------------------
class SponsorPointsPolicy(db.Model):
    __tablename__ = "SponsorPointsPolicy"

    ID        = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, unique=True, index=True)

    # DB columns (PascalCase)
    Strategy   = db.Column(db.String(24), nullable=False, default="FLAT_RATE")
    ConfigJSON = db.Column(JSONT,         nullable=False, default=dict)
    MinPoints  = db.Column(db.Integer)
    MaxPoints  = db.Column(db.Integer)
    Rounding   = db.Column(db.String(24), nullable=False, default="NEAREST_10")
    CreatedAt  = db.Column(db.DateTime,   server_default=db.func.now())
    UpdatedAt  = db.Column(db.DateTime,   server_default=db.func.now(), onupdate=db.func.now())

    # snake_case synonyms
    sponsor_id  = synonym("SponsorID")
    strategy    = synonym("Strategy")
    config_json = synonym("ConfigJSON")
    min_points  = synonym("MinPoints")
    max_points  = synonym("MaxPoints")
    rounding    = synonym("Rounding")
    created_at  = synonym("CreatedAt")
    updated_at  = synonym("UpdatedAt")

    @property
    def id(self): return self.ID


# ------------------------------------------------------------
# SponsorActiveFilterSelection
# ------------------------------------------------------------
class SponsorActiveFilterSelection(db.Model):
    __tablename__ = "SponsorActiveFilterSelection"

    SponsorID           = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), primary_key=True)
    FilterSetID         = db.Column(db.String(36), db.ForeignKey("SponsorCatalogFilterSet.ID"), nullable=True)
    SelectedAt          = db.Column(db.DateTime, server_default=db.func.now())
    SelectedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))

    # snake_case aliases
    sponsor_id          = synonym("SponsorID")
    filter_set_id       = synonym("FilterSetID")
    selected_at         = synonym("SelectedAt")
    selected_by_account_id = synonym("SelectedByAccountID")


# ------------------------------------------------------------
# BlacklistedProduct - Products excluded from ALL sponsor searches
# ------------------------------------------------------------
class BlacklistedProduct(db.Model):
    __tablename__ = "BlacklistedProduct"

    ID         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    SponsorID  = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)

    # DB columns (PascalCase)
    Marketplace = db.Column(db.String(32), nullable=False, default="ebay")
    ItemID      = db.Column(db.String(64),  nullable=False, index=True)  # eBay item ID
    Reason      = db.Column(db.String(255))
    
    # Cached display info
    ItemTitle    = db.Column(db.String(512))
    ItemImageURL = db.Column(db.String(1024))
    ItemURL      = db.Column(db.String(1024))  # eBay product page URL
    
    CreatedAt   = db.Column(db.DateTime, server_default=db.func.now())
    BlacklistedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"))
    SourceReportID = db.Column(db.String(36), db.ForeignKey("ProductReports.ID"))  # Reference to original report if blacklisted via report

    # Unique constraint: one sponsor can't blacklist the same item twice
    __table_args__ = (
        db.UniqueConstraint("SponsorID", "ItemID", name="uq_sponsor_blacklisted_item"),
    )

    # snake_case synonyms
    sponsor_id  = synonym("SponsorID")
    marketplace = synonym("Marketplace")
    item_id     = synonym("ItemID")
    reason      = synonym("Reason")
    item_title  = synonym("ItemTitle")
    item_image_url = synonym("ItemImageURL")
    item_url    = synonym("ItemURL")
    created_at  = synonym("CreatedAt")
    blacklisted_by_account_id = synonym("BlacklistedByAccountID")
    source_report_id = synonym("SourceReportID")

    @property
    def id(self): return self.ID