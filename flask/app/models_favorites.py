# app/models_favorites.py
from uuid import uuid4
from .extensions import db
from sqlalchemy.orm import synonym

# Portable JSON type
JSONT = db.JSON


# ------------------------------------------------------------
# DriverFavorites
# ------------------------------------------------------------
class DriverFavorites(db.Model):
    __tablename__ = "DriverFavorites"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    DriverID = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False, index=True)
    ExternalItemID = db.Column(db.String(255), nullable=False, index=True)  # eBay item ID
    ItemTitle = db.Column(db.String(500), nullable=True)  # Cache item title for display
    ItemImageURL = db.Column(db.String(1000), nullable=True)  # Cache item image URL
    ItemPoints = db.Column(db.Integer, nullable=True)  # Cache item points for display
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # snake_case synonyms (what the rest of the app uses)
    driver_id = synonym("DriverID")
    external_item_id = synonym("ExternalItemID")
    item_title = synonym("ItemTitle")
    item_image_url = synonym("ItemImageURL")
    item_points = synonym("ItemPoints")
    created_at = synonym("CreatedAt")
    updated_at = synonym("UpdatedAt")

    # convenience for templates that expect .id
    @property
    def id(self): return self.ID

    # Unique constraint on driver + item combination
    __table_args__ = (
        db.UniqueConstraint('DriverID', 'ExternalItemID', name='unique_driver_favorite'),
    )


# ------------------------------------------------------------
# ProductReports (for reporting inappropriate items)
# ------------------------------------------------------------
class ProductReports(db.Model):
    __tablename__ = "ProductReports"

    ID = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    DriverID = db.Column(db.String(36), db.ForeignKey("Driver.DriverID"), nullable=False, index=True)
    SponsorID = db.Column(db.String(36), db.ForeignKey("Sponsor.SponsorID"), nullable=False, index=True)  # Added to associate reports with sponsors
    ExternalItemID = db.Column(db.String(255), nullable=False, index=True)  # eBay item ID
    ItemTitle = db.Column(db.String(500), nullable=True)  # Cache item title for display
    ItemImageURL = db.Column(db.String(1000), nullable=True)  # Cache item image URL
    ItemURL = db.Column(db.String(1000), nullable=True)  # eBay product page URL
    ReportReason = db.Column(db.String(50), nullable=False)  # e.g., 'inappropriate', 'broken_link', 'wrong_category'
    ReportDescription = db.Column(db.Text, nullable=True)  # Optional detailed description
    Status = db.Column(db.String(20), nullable=False, default='pending')  # pending, approved, denied, restored
    ReviewedByAccountID = db.Column(db.String(36), db.ForeignKey("Account.AccountID"), nullable=True)
    ReviewedAt = db.Column(db.DateTime, nullable=True)
    ReviewNotes = db.Column(db.Text, nullable=True)  # Admin notes about the review
    CreatedAt = db.Column(db.DateTime, server_default=db.func.now())
    UpdatedAt = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # snake_case synonyms
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

    # convenience for templates that expect .id
    @property
    def id(self): return self.ID
