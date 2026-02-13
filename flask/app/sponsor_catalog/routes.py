from __future__ import annotations

import json, csv, io, os, string

from flask import Blueprint, render_template, request, jsonify, abort, session, Response, url_for, current_app
from flask_login import login_required, current_user
from sqlalchemy import case, asc, desc
from datetime import datetime

from io import BytesIO
# PDF bits (ReportLab) - Optional import
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors, HexColor
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

from ..models import (
    BlacklistedProduct,
    ProductReports,
    Sponsor,
    SponsorActiveFilterSelection,
    SponsorCatalogExclusion,
    SponsorCatalogFilterSet,
    SponsorCatalogInclusion,
    SponsorPinnedProduct,
)
from .services.preview_service import preview as build_preview
from .services.audit_service import log
from ..extensions import db

bp = Blueprint(
    "sponsor_catalog",
    __name__,
    template_folder="templates",
    static_folder="static",
)


def _current_sponsor_id() -> str:
    """
    Resolve the sponsor_id for the logged-in user.
    Adjust this if your user/session stores it differently.
    """
    # Common attributes we’ve seen in your codebase:
    for attr in ("SponsorID", "sponsor_id"):
        if hasattr(current_user, attr) and getattr(current_user, attr):
            return str(getattr(current_user, attr))

    # If you store it under current_user.account or session, adapt here:
    # from flask import session
    # if session.get("sponsor_id"): return session["sponsor_id"]

    raise RuntimeError("Could not determine sponsor_id for current user")


def require_sponsor() -> str:
    """Return SponsorID for the logged-in user or abort with 403."""
    if not current_user.is_authenticated:
        abort(401)

    # 1) prefer what we stashed at login
    sponsor_id = session.get("sponsor_id")

    # 2) if absent, resolve by AccountID -> Sponsor
    if not sponsor_id and getattr(current_user, "AccountID", None):
        s = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
        if s:
            sponsor_id = s.SponsorID
            session["sponsor_id"] = sponsor_id  # cache for later

    if not sponsor_id:
        abort(403)  # logged in but not a sponsor

    return sponsor_id


@bp.get("/")
@login_required
def index():
    _ = require_sponsor()
    return render_template("sponsor_catalog/index.html")


@bp.get("/filter-sets/export.csv")
@login_required
def export_filter_sets_csv():
    sponsor_id = require_sponsor()

    all_rows = (
        SponsorCatalogFilterSet.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(SponsorCatalogFilterSet.priority.asc(), SponsorCatalogFilterSet.UpdatedAt.desc())
        .all()
    )
    
    # Filter out dummy filter sets (they should only appear in the dropdown, not in exports)
    rows = [r for r in all_rows if str(getattr(r, "ID", getattr(r, "id", ""))) not in ["__no_filter__", "__recommended_only__"]]

    # Category ID to name mapping
    CATEGORY_MAP = {
        # Electronics
        "9355": "Cell Phones & Smartphones",
        "58058": "Computers, Tablets & Networking", 
        "625": "Cameras & Photo",
        "293": "TV, Video & Home Audio",
        "1249": "Video Games & Consoles",
        "175673": "Smart Home & Surveillance",
        "15052": "Portable Audio & Headphones",
        "3270": "Car Electronics",
        "178893": "Wearable Technology",
        "183067": "Virtual Reality",
        
        # Fashion
        "15724": "Women's Clothing",
        "1059": "Men's Clothing", 
        "3034": "Women's Shoes",
        "93427": "Men's Shoes",
        "281": "Jewelry & Watches",
        "169291": "Women's Handbags & Bags",
        "4250": "Women's Accessories",
        "4251": "Men's Accessories",
        "147": "Kids & Baby Clothing",
        "79720": "Sunglasses & Eyewear",
        
        # Home & Garden
        "3197": "Furniture",
        "10033": "Home Decor",
        "20625": "Kitchen, Dining & Bar",
        "20444": "Bedding",
        "20452": "Bath",
        "159912": "Garden & Outdoor Living",
        "631": "Tools & Workshop Equipment",
        "20594": "Home Improvement",
        "20706": "Lamps, Lighting & Ceiling Fans",
        "20571": "Rugs & Carpets",
        "20626": "Storage & Organization",
        
        # Sports & Outdoors
        "15273": "Exercise & Fitness",
        "7294": "Cycling",
        "16034": "Camping & Hiking",
        "1492": "Fishing",
        "7301": "Hunting",
        "64482": "Team Sports",
        "1497": "Water Sports",
        "16058": "Winter Sports",
        "1513": "Golf",
        "15277": "Yoga & Pilates",
        "15272": "Running & Jogging",
        
        # Toys & Hobbies
        "246": "Action Figures",
        "18991": "Building Toys",
        "237": "Dolls & Bears",
        "233": "Games",
        "19107": "Model Trains & Railroads",
        "2562": "Radio Control & RC",
        "19149": "Slot Cars",
        "160636": "Arts & Crafts",
        "2617": "Preschool Toys & Pretend Play",
        "1247": "Puzzles",
        "19026": "Educational Toys",
        
        # Automotive
        "6030": "Car & Truck Parts",
        "10063": "Motorcycle Parts",
        "34998": "Automotive Tools & Supplies",
        "156955": "GPS & Security Devices",
        "10058": "Car Care & Detailing",
        "66471": "Tires & Wheels",
        "33615": "Performance & Racing Parts",
        "6028": "Exterior Parts & Accessories",
        "6029": "Interior Parts & Accessories",
        
        # Health & Beauty
        "31411": "Fragrances",
        "31786": "Makeup",
        "11854": "Skin Care",
        "6197": "Health Care",
        "180959": "Vitamins & Dietary Supplements",
        "11338": "Oral Care",
        "11855": "Shaving & Hair Removal",
        "182": "Medical Devices & Equipment",
        
        # Pet Supplies
        "20737": "Dog Supplies",
        "20738": "Cat Supplies",
        "20754": "Fish & Aquarium",
        "20748": "Bird Supplies",
        "3756": "Small Animal Supplies",
        "157692": "Reptile & Amphibian Supplies",
        "3226": "Horse Care & Supplies",
        "46262": "Pet Feeding & Watering",
        "114835": "Pet Grooming Supplies",
        "20746": "Pet Toys"
    }

    def format_categories(category_ids):
        """Convert category IDs to readable names"""
        if not category_ids:
            return ""
        names = []
        for cat_id in category_ids:
            name = CATEGORY_MAP.get(str(cat_id), f"Category {cat_id}")
            names.append(name)
        return "; ".join(names)

    def format_conditions(conditions):
        """Format product conditions"""
        if not conditions:
            return ""
        return "; ".join(conditions)

    def format_keywords(keywords_dict):
        """Format keywords for CSV"""
        if not keywords_dict:
            return ""
        parts = []
        if keywords_dict.get("must"):
            parts.append(f"Must: {', '.join(keywords_dict['must'])}")
        if keywords_dict.get("exclude"):
            parts.append(f"Exclude: {', '.join(keywords_dict['exclude'])}")
        return " | ".join(parts)

    # Build CSV in-memory with comprehensive columns
    sio = io.StringIO()
    writer = csv.writer(sio)
    
    # Header row with all filter fields
    writer.writerow([
        "ID", "Name", "IsActive", "UpdatedAt",
        "FilterMode", "Categories", "PriceMin", "PriceMax", 
        "ProductConditions", "FreeShippingOnly", "MaxHandlingDays",
        "MinFeedbackScore", "MinPositivePercent", "BuyItNowOnly",
        "KeywordsMustInclude", "KeywordsMustExclude", "ExcludeAdultContent"
    ])

    for r in rows:
        # Basic fields
        updated = getattr(r, "updated_at", None) or getattr(r, "UpdatedAt", None)
        updated_str = ""
        try:
            if updated is not None:
                updated_str = updated.isoformat(sep=" ", timespec="seconds")
        except Exception:
            updated_str = str(updated or "")

        rules = getattr(r, "rules_json", None) or getattr(r, "RulesJSON", {}) or {}
        
        # Extract filter mode (support both old and new names for backward compatibility)
        filter_mode = "Normal Filter"
        if rules.get("special_mode") == "recommended_only" or rules.get("filter_mode") == "pinned_only" or rules.get("special_mode") == "pinned_only":
            filter_mode = "Recommended Products Only"
        
        # Extract categories
        categories = ""
        if rules.get("categories", {}).get("include"):
            categories = format_categories(rules["categories"]["include"])
        
        # Extract price range
        price_min = ""
        price_max = ""
        if rules.get("price"):
            price_min = rules["price"].get("min", "")
            price_max = rules["price"].get("max", "")
        
        # Extract product conditions
        conditions = ""
        if rules.get("conditions"):
            conditions = format_conditions(rules["conditions"])
        
        # Extract shipping settings
        free_shipping_only = ""
        max_handling_days = ""
        if rules.get("shipping"):
            free_shipping_only = rules["shipping"].get("free_shipping_only", "")
            max_handling_days = rules["shipping"].get("max_handling_days", "")
        
        # Extract seller requirements
        min_feedback_score = ""
        min_positive_percent = ""
        if rules.get("seller"):
            min_feedback_score = rules["seller"].get("min_feedback_score", "")
            min_positive_percent = rules["seller"].get("min_positive_percent", "")
        
        # Extract listing type
        buy_it_now_only = ""
        if rules.get("listing_type", {}).get("buy_it_now_only"):
            buy_it_now_only = "Yes"
        
        # Extract keywords
        keywords_must_include = ""
        keywords_must_exclude = ""
        if rules.get("keywords"):
            keywords_must_include = ", ".join(rules["keywords"].get("must", []))
            keywords_must_exclude = ", ".join(rules["keywords"].get("exclude", []))
        
        # Extract safety settings
        exclude_adult_content = ""
        if rules.get("safety", {}).get("exclude_explicit"):
            exclude_adult_content = "Yes"

        writer.writerow([
            getattr(r, "ID", getattr(r, "id", "")),
            getattr(r, "Name", getattr(r, "name", "")),
            getattr(r, "IsActive", getattr(r, "is_active", False)),
            updated_str,
            filter_mode,
            categories,
            price_min,
            price_max,
            conditions,
            free_shipping_only,
            max_handling_days,
            min_feedback_score,
            min_positive_percent,
            buy_it_now_only,
            keywords_must_include,
            keywords_must_exclude,
            exclude_adult_content
        ])

    resp = Response(sio.getvalue(), mimetype="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="filter-sets_{sponsor_id}.csv"'

    # optional audit trail
    try:
        log(sponsor_id, "FILTER_EXPORT", current_user.get_id(), {"count": len(rows)})
    except Exception:
        pass

    return resp


@bp.get("/filter-sets/export.pdf")
@login_required
def export_filter_sets_pdf():
    if not REPORTLAB_AVAILABLE:
        from flask import abort
        abort(501, "PDF export not available - reportlab not installed")
    
    sponsor_id = require_sponsor()

    # Pull filter sets
    all_rows = (
        SponsorCatalogFilterSet.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(SponsorCatalogFilterSet.priority.asc(), SponsorCatalogFilterSet.UpdatedAt.desc())
        .all()
    )
    
    # Filter out dummy filter sets (they should only appear in the dropdown, not in exports)
    rows = [r for r in all_rows if str(getattr(r, "ID", getattr(r, "id", ""))) not in ["__no_filter__", "__recommended_only__"]]

    # Try to get a sponsor name (fallback gracefully)
    sponsor_name = f"Sponsor {sponsor_id}"
    try:
        from ..models import Sponsor
        s = Sponsor.query.get(sponsor_id)
        if s:
            # Prefer the Company column on Sponsor
            sponsor_name = (
                getattr(s, "Company", None)           # PascalCase DB column
                or getattr(s, "company", None)        # if you also expose a pythonic alias
                or getattr(s, "Name", None)           # fallback
                or getattr(s, "name", None)           # fallback
                or f"Sponsor {sponsor_id}"            # ultimate fallback
            )
    except Exception:
        pass

    # Build a beautiful, professional PDF
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"{sponsor_name} – Filter Sets Report"
    )

    # Define custom styles with colors and typography
    styles = getSampleStyleSheet()
    
    # Header styles
    title_style = ParagraphStyle(
        name="Title",
        parent=styles["Title"],
        fontSize=24,
        textColor=colors.HexColor("#2c3e50"),
        alignment=TA_CENTER,
        spaceAfter=20,
        fontName="Helvetica-Bold"
    )
    
    subtitle_style = ParagraphStyle(
        name="Subtitle",
        parent=styles["Heading2"],
        fontSize=16,
        textColor=colors.HexColor("#7f8c8d"),
        alignment=TA_CENTER,
        spaceAfter=30,
        fontName="Helvetica"
    )
    
    # Section headers
    section_style = ParagraphStyle(
        name="Section",
        parent=styles["Heading2"],
        fontSize=14,
        textColor=colors.HexColor("#34495e"),
        spaceBefore=20,
        spaceAfter=10,
        fontName="Helvetica-Bold",
        leftIndent=0
    )
    
    # Summary box style
    summary_style = ParagraphStyle(
        name="Summary",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#2c3e50"),
        alignment=TA_CENTER,
        spaceBefore=10,
        spaceAfter=10,
        fontName="Helvetica"
    )
    
    # Filter set name style
    filter_name_style = ParagraphStyle(
        name="FilterName",
        parent=styles["Normal"],
        fontSize=12,
        textColor=colors.HexColor("#2c3e50"),
        fontName="Helvetica-Bold",
        spaceAfter=5
    )
    
    # Filter details style
    filter_detail_style = ParagraphStyle(
        name="FilterDetail",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#34495e"),
        fontName="Helvetica",
        leftIndent=15,
        spaceAfter=3
    )
    
    # Status styles
    active_style = ParagraphStyle(
        name="Active",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#27ae60"),
        fontName="Helvetica-Bold"
    )
    
    inactive_style = ParagraphStyle(
        name="Inactive",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#e74c3c"),
        fontName="Helvetica-Bold"
    )

    story = []
    
    # Header section
    story.append(Paragraph("📊 SPONSOR CATALOG FILTER SETS", title_style))
    story.append(Paragraph(f"Report for {sponsor_name}", subtitle_style))
    
    # Add generation timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    story.append(Paragraph(f"Generated on {timestamp}", summary_style))
    story.append(Spacer(1, 0.2 * inch))

    if not rows:
        story.append(Paragraph("No filter sets found for this sponsor.", summary_style))
        doc.build(story)
        pdf = buf.getvalue()
        buf.close()
        resp = Response(pdf, mimetype="application/pdf")
        resp.headers["Content-Disposition"] = f'attachment; filename="filter-sets_{sponsor_id}.pdf"'
        return resp

    # Summary statistics
    active_count = sum(1 for r in rows if getattr(r, "IsActive", getattr(r, "is_active", False)))
    inactive_count = len(rows) - active_count
    avg_priority = sum(getattr(r, "Priority", getattr(r, "priority", 100)) for r in rows) / len(rows) if rows else 0
    
    # Summary box
    summary_text = f"""
    <para align="center">
    <b>📈 SUMMARY STATISTICS</b><br/>
    Total Filter Sets: <b>{len(rows)}</b> | 
    Active: <font color="#27ae60"><b>{active_count}</b></font> | 
    Inactive: <font color="#e74c3c"><b>{inactive_count}</b></font> | 
    Average Priority: <b>{avg_priority:.1f}</b>
    </para>
    """
    story.append(Paragraph(summary_text, summary_style))
    story.append(Spacer(1, 0.3 * inch))

    # Category ID to name mapping (same as CSV)
    CATEGORY_MAP = {
        # Electronics
        "9355": "Cell Phones & Smartphones",
        "58058": "Computers, Tablets & Networking", 
        "625": "Cameras & Photo",
        "293": "TV, Video & Home Audio",
        "1249": "Video Games & Consoles",
        "175673": "Smart Home & Surveillance",
        "15052": "Portable Audio & Headphones",
        "3270": "Car Electronics",
        "178893": "Wearable Technology",
        "183067": "Virtual Reality",
        
        # Fashion
        "15724": "Women's Clothing",
        "1059": "Men's Clothing", 
        "3034": "Women's Shoes",
        "93427": "Men's Shoes",
        "281": "Jewelry & Watches",
        "169291": "Women's Handbags & Bags",
        "4250": "Women's Accessories",
        "4251": "Men's Accessories",
        "147": "Kids & Baby Clothing",
        "79720": "Sunglasses & Eyewear",
        
        # Home & Garden
        "3197": "Furniture",
        "10033": "Home Decor",
        "20625": "Kitchen, Dining & Bar",
        "20444": "Bedding",
        "20452": "Bath",
        "159912": "Garden & Outdoor Living",
        "631": "Tools & Workshop Equipment",
        "20594": "Home Improvement",
        "20706": "Lamps, Lighting & Ceiling Fans",
        "20571": "Rugs & Carpets",
        "20626": "Storage & Organization",
        
        # Sports & Outdoors
        "15273": "Exercise & Fitness",
        "7294": "Cycling",
        "16034": "Camping & Hiking",
        "1492": "Fishing",
        "7301": "Hunting",
        "64482": "Team Sports",
        "1497": "Water Sports",
        "16058": "Winter Sports",
        "1513": "Golf",
        "15277": "Yoga & Pilates",
        "15272": "Running & Jogging",
        
        # Toys & Hobbies
        "246": "Action Figures",
        "18991": "Building Toys",
        "237": "Dolls & Bears",
        "233": "Games",
        "19107": "Model Trains & Railroads",
        "2562": "Radio Control & RC",
        "19149": "Slot Cars",
        "160636": "Arts & Crafts",
        "2617": "Preschool Toys & Pretend Play",
        "1247": "Puzzles",
        "19026": "Educational Toys",
        
        # Automotive
        "6030": "Car & Truck Parts",
        "10063": "Motorcycle Parts",
        "34998": "Automotive Tools & Supplies",
        "156955": "GPS & Security Devices",
        "10058": "Car Care & Detailing",
        "66471": "Tires & Wheels",
        "33615": "Performance & Racing Parts",
        "6028": "Exterior Parts & Accessories",
        "6029": "Interior Parts & Accessories",
        
        # Health & Beauty
        "31411": "Fragrances",
        "31786": "Makeup",
        "11854": "Skin Care",
        "6197": "Health Care",
        "180959": "Vitamins & Dietary Supplements",
        "11338": "Oral Care",
        "11855": "Shaving & Hair Removal",
        "182": "Medical Devices & Equipment",
        
        # Pet Supplies
        "20737": "Dog Supplies",
        "20738": "Cat Supplies",
        "20754": "Fish & Aquarium",
        "20748": "Bird Supplies",
        "3756": "Small Animal Supplies",
        "157692": "Reptile & Amphibian Supplies",
        "3226": "Horse Care & Supplies",
        "46262": "Pet Feeding & Watering",
        "114835": "Pet Grooming Supplies",
        "20746": "Pet Toys"
    }

    # Helper function to format rules in human-readable way
    def format_filter_rules(rules):
        if not rules:
            return "No specific filters applied"
        
        descriptions = []
        
        # Filter Mode
        filter_mode = rules.get("filter_mode", "normal")
        # Support both old "pinned_only" and new "recommended_only" for backward compatibility
        if filter_mode == "pinned_only" or rules.get("special_mode") == "recommended_only" or rules.get("special_mode") == "pinned_only":
            descriptions.append("⭐ <b>Filter Mode:</b> Recommended Products Only")
        else:
            descriptions.append("🔍 <b>Filter Mode:</b> Normal Filter")
        
        # Categories
        if rules.get("categories", {}).get("include"):
            cat_ids = rules["categories"]["include"]
            cat_names = []
            for cat_id in cat_ids:
                name = CATEGORY_MAP.get(str(cat_id), f"Category {cat_id}")
                cat_names.append(name)
            descriptions.append(f"📂 <b>Categories:</b> {', '.join(cat_names)}")
        
        # Price range
        if rules.get("price"):
            price = rules["price"]
            if price.get("min") and price.get("max"):
                descriptions.append(f"💰 <b>Price Range:</b> ${price['min']:.2f} - ${price['max']:.2f}")
            elif price.get("min"):
                descriptions.append(f"💰 <b>Minimum Price:</b> ${price['min']:.2f}")
            elif price.get("max"):
                descriptions.append(f"💰 <b>Maximum Price:</b> ${price['max']:.2f}")
        
        # Product Conditions
        if rules.get("conditions"):
            conditions = rules["conditions"]
            descriptions.append(f"🏷️ <b>Product Conditions:</b> {', '.join(conditions)}")
        
        # Shipping
        if rules.get("shipping"):
            ship = rules["shipping"]
            ship_items = []
            if ship.get("free_shipping_only"):
                ship_items.append("Free shipping only")
            if ship.get("max_handling_days"):
                ship_items.append(f"Max {ship['max_handling_days']} handling days")
            if ship_items:
                descriptions.append(f"🚚 <b>Shipping:</b> {', '.join(ship_items)}")
        
        # Seller Requirements
        if rules.get("seller"):
            seller = rules["seller"]
            seller_items = []
            if seller.get("min_feedback_score"):
                seller_items.append(f"Min {seller['min_feedback_score']} feedback score")
            if seller.get("min_positive_percent"):
                seller_items.append(f"Min {seller['min_positive_percent']}% positive")
            if seller_items:
                descriptions.append(f"👤 <b>Seller Requirements:</b> {', '.join(seller_items)}")
        
        # Listing Type
        if rules.get("listing_type", {}).get("buy_it_now_only"):
            descriptions.append("🛒 <b>Listing Type:</b> Buy It Now Only")
        
        # Keywords
        if rules.get("keywords"):
            kw = rules["keywords"]
            if kw.get("must"):
                descriptions.append(f"🔍 <b>Must Include:</b> {', '.join(kw['must'])}")
            if kw.get("exclude"):
                descriptions.append(f"🚫 <b>Must Exclude:</b> {', '.join(kw['exclude'])}")
        
        # Safety filters
        if rules.get("safety", {}).get("exclude_explicit"):
            descriptions.append("🛡️ <b>Safety:</b> Exclude adult/explicit content")
        
        return "<br/>".join(descriptions) if descriptions else "Basic filtering applied"

    # Helper function to format updated date
    def _fmt_updated(r):
        updated = getattr(r, "updated_at", None) or getattr(r, "UpdatedAt", None)
        try:
            if updated:
                return updated.strftime("%b %d, %Y")
            return "Never"
        except Exception:
            return "Unknown"

    # Individual filter sets
    story.append(Paragraph("📋 FILTER SET DETAILS", section_style))
    
    for i, r in enumerate(rows):
        # Filter set header
        name = getattr(r, "Name", getattr(r, "name", "")) or f"Filter Set {i+1}"
        priority = getattr(r, "Priority", getattr(r, "priority", 100))
        is_active = getattr(r, "IsActive", getattr(r, "is_active", False))
        updated = _fmt_updated(r)
        rules = getattr(r, "rules_json", None) or getattr(r, "RulesJSON", {}) or {}
        
        # Status badge
        status_text = "🟢 ACTIVE" if is_active else "🔴 INACTIVE"
        status_color = "#27ae60" if is_active else "#e74c3c"
        
        # Filter set header
        header_text = f"""
        <para>
        <b>{name}</b><br/>
        <font color="{status_color}">{status_text}</font> | 
        Priority: <b>{priority}</b> | 
        Updated: <b>{updated}</b>
        </para>
        """
        story.append(Paragraph(header_text, filter_name_style))
        
        # Filter rules description
        rules_desc = format_filter_rules(rules)
        story.append(Paragraph(rules_desc, filter_detail_style))
        
        # Add spacing between filter sets
        story.append(Spacer(1, 0.15 * inch))
        
        # Add page break if we're getting close to the end
        if i > 0 and i % 3 == 0:
            story.append(Spacer(1, 0.1 * inch))

    # Footer with branding
    story.append(Spacer(1, 0.3 * inch))
    footer_text = f"""
    <para align="center">
    <font color="#7f8c8d" size="9">
    📊 Generated by Sponsor Catalog System<br/>
    {sponsor_name} • {timestamp}
    </font>
    </para>
    """
    story.append(Paragraph(footer_text, summary_style))

    # Build and return
    doc.build(story)
    pdf = buf.getvalue()
    buf.close()

    resp = Response(pdf, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="filter-sets-report_{sponsor_id}.pdf"'
    try:
        log(sponsor_id, "FILTER_EXPORT_PDF", current_user.get_id(), {"count": len(rows)})
    except Exception:
        pass
    return resp


@bp.get("/filter-sets")  # endpoint name = 'filter_sets'
@login_required
def filter_sets():
    sponsor_id = require_sponsor()

    # Fetch model rows
    model_rows = (
        SponsorCatalogFilterSet.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(SponsorCatalogFilterSet.UpdatedAt.desc())
        .all()
    )

    # Make them JSON-serializable for the template's |tojson fallback
    def row_to_view(m):
        _id = str(getattr(m, "ID", getattr(m, "id", "")))
        _name = getattr(m, "Name", getattr(m, "name", "")) or _id
        _dt = getattr(m, "UpdatedAt", getattr(m, "updated_at", None))
        if isinstance(_dt, datetime):
            _updated = _dt.isoformat(timespec="seconds")
        else:
            _updated = str(_dt) if _dt is not None else ""
        return {"id": _id, "name": _name, "updated_at": _updated}

    # Filter out dummy filter sets (they should only appear in the dropdown, not the table)
    rows = [row_to_view(m) for m in model_rows if str(getattr(m, "ID", getattr(m, "id", ""))) not in ["__no_filter__", "__recommended_only__"]]

    sel = SponsorActiveFilterSelection.query.get(sponsor_id)
    selected_filter_set_id = getattr(sel, "FilterSetID", None)

    return render_template(
        "sponsor_catalog/filter_sets.html",
        rows=rows,
        selected_filter_set_id=selected_filter_set_id,
    )

# -----------------------------------
# JSON: list all sets + mark selection
# -----------------------------------
@bp.get("/filter-sets.json")
@login_required
def filter_sets_json():
    sponsor_id = require_sponsor()
    sel = SponsorActiveFilterSelection.query.get(sponsor_id)
    selected_id = getattr(sel, "FilterSetID", None)

    current_app.logger.info(f"[FILTER SET JSON] ========== filter_sets_json() CALLED ==========")
    current_app.logger.info(f"[FILTER SET JSON] Sponsor ID: {sponsor_id}")
    current_app.logger.info(f"[FILTER SET JSON] Selected filter set ID: {selected_id}")

    rows = (
        SponsorCatalogFilterSet.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(SponsorCatalogFilterSet.UpdatedAt.desc())
        .all()
    )
    
    current_app.logger.info(f"[FILTER SET JSON] Query returned {len(rows)} filter set rows")

    result = []
    seen_ids = set()
    duplicate_ids = []
    
    # Add special "No Filter Set" option (allows all categories)
    result.append({
        "id": "__no_filter__",
        "name": "No Filter Set",
        "selected": str(selected_id) == "__no_filter__" if selected_id else False,
    })
    current_app.logger.info(f"[FILTER SET JSON] Added special option: No Filter Set")
    
    # Add special "Recommended Products Only" option
    result.append({
        "id": "__recommended_only__",
        "name": "Recommended Products Only",
        "selected": str(selected_id) == "__recommended_only__" if selected_id else False,
    })
    current_app.logger.info(f"[FILTER SET JSON] Added special option: Recommended Products Only")
    
    for r in rows:
        filter_set_id = str(getattr(r, "ID", getattr(r, "id", "")))
        
        # Skip dummy filter sets (they're already added as special options above)
        if filter_set_id in ["__no_filter__", "__recommended_only__"]:
            current_app.logger.debug(f"[FILTER SET JSON] Skipping dummy filter set: {filter_set_id}")
            continue
        filter_set_id = str(getattr(r, "ID", getattr(r, "id", "")))
        filter_set_name = getattr(r, "Name", getattr(r, "name", "")) or str(getattr(r, "ID", getattr(r, "id", "")))
        
        current_app.logger.info(f"[FILTER SET JSON] Processing filter set: ID={filter_set_id}, Name={filter_set_name}")
        
        if filter_set_id in seen_ids:
            duplicate_ids.append({"id": filter_set_id, "name": filter_set_name})
            current_app.logger.warning(f"[FILTER SET JSON] DUPLICATE DETECTED IN QUERY RESULT: ID={filter_set_id}, Name={filter_set_name}")
        else:
            seen_ids.add(filter_set_id)
            result.append({
                "id": filter_set_id,
                "name": filter_set_name,
                "selected": filter_set_id == str(selected_id),
            })
            current_app.logger.info(f"[FILTER SET JSON] Added filter set to result: ID={filter_set_id}, Name={filter_set_name}")
    
    if duplicate_ids:
        current_app.logger.error(f"[FILTER SET JSON] ========== DUPLICATES FOUND IN DATABASE QUERY ==========")
        current_app.logger.error(f"[FILTER SET JSON] Duplicate filter sets: {duplicate_ids}")
        current_app.logger.error(f"[FILTER SET JSON] Total unique IDs in result: {len(result)}")
        current_app.logger.error(f"[FILTER SET JSON] Duplicate count: {len(duplicate_ids)}")
        current_app.logger.error(f"[FILTER SET JSON] ======================================================")
    
    current_app.logger.info(f"[FILTER SET JSON] Returning {len(result)} filter sets")
    current_app.logger.info(f"[FILTER SET JSON] Result IDs: {[r['id'] for r in result]}")
    current_app.logger.info(f"[FILTER SET JSON] ========== filter_sets_json() COMPLETE ==========")

    return jsonify(result)

# ----------------------------------
# JSON: current selection for sponsor
# ----------------------------------
@bp.get("/active-set.json")
@login_required
def active_set_json():
    sponsor_id = require_sponsor()
    sel = SponsorActiveFilterSelection.query.get(sponsor_id)
    return jsonify({"selected_filter_set_id": getattr(sel, "FilterSetID", None)})

# ------------------------------
# Action: set active filter set
# ------------------------------
@bp.post("/active-set")
@login_required
def set_active_filter_set():
    try:
        # Check authentication manually to return JSON errors instead of HTML
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        
        # Get sponsor_id manually to avoid abort() which returns HTML
        sponsor_id = session.get("sponsor_id")
        if not sponsor_id and getattr(current_user, "AccountID", None):
            s = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
            if s:
                sponsor_id = s.SponsorID
                session["sponsor_id"] = sponsor_id
        
        if not sponsor_id:
            return jsonify({"ok": False, "error": "Sponsor account required"}), 403
        
        fs_id = (request.form.get("filter_set_id") or "").strip()
        if not fs_id:
            current_app.logger.warning(f"[FILTER_SET] set_active_filter_set - No filter_set_id provided for sponsor {sponsor_id}")
            return jsonify({"ok": False, "error": "filter_set_id required"}), 400

        current_app.logger.info(f"[FILTER_SET] set_active_filter_set - Sponsor {sponsor_id} attempting to set active filter set to {fs_id}")

        # Handle special filter set IDs
        if fs_id == "__no_filter__":
            # For no_filter, we need to create or find a dummy filter set
            # Check if a system-wide no_filter filter set exists for this sponsor
            dummy_fs = SponsorCatalogFilterSet.query.filter_by(
                ID="__no_filter__",
                SponsorID=sponsor_id
            ).first()
            if not dummy_fs:
                # Create dummy filter set for this sponsor (empty rules = no filtering)
                dummy_fs = SponsorCatalogFilterSet(
                    ID="__no_filter__",
                    SponsorID=sponsor_id,
                    Name="No Filter Set",
                    IsActive=True,
                    Priority=0,
                    RulesJSON={}  # Empty rules = allow all categories
                )
                db.session.add(dummy_fs)
                current_app.logger.info(f"[FILTER_SET] Created dummy __no_filter__ filter set for sponsor {sponsor_id}")
            
            sel = SponsorActiveFilterSelection.query.get(sponsor_id)
            old_filter_set_id = getattr(sel, "FilterSetID", None) if sel else None
            
            if not sel:
                sel = SponsorActiveFilterSelection(SponsorID=sponsor_id)
                db.session.add(sel)
                current_app.logger.info(f"[FILTER_SET] set_active_filter_set - Creating new SponsorActiveFilterSelection for sponsor {sponsor_id}")

            sel.FilterSetID = "__no_filter__"
            sel.SelectedByAccountID = current_user.get_id() if hasattr(current_user, "get_id") else None
            
            current_app.logger.info(f"[FILTER_SET] set_active_filter_set - Setting FilterSetID to __no_filter__ (was {old_filter_set_id})")
            
            db.session.commit()
            
            current_app.logger.info(f"[FILTER_SET] ✓ Successfully set active filter set to __no_filter__ for sponsor {sponsor_id}")
            
            # Log the active filter set change
            try:
                log(
                    sponsor_id, 
                    "ACTIVE_FILTER_SET_CHANGE", 
                    current_user.get_id(), 
                    {
                        "old_filter_set_id": old_filter_set_id,
                        "new_filter_set_id": "__no_filter__",
                        "filter_set_name": "No Filter Set"
                    }
                )
            except Exception:
                pass

            return jsonify({"ok": True})
        
        if fs_id == "__recommended_only__":
            # For recommended_only, we need to create or find a dummy filter set
            # Check if a system-wide recommended_only filter set exists
            dummy_fs = SponsorCatalogFilterSet.query.filter_by(ID="__recommended_only__").first()
            if not dummy_fs:
                # Create a system-wide dummy filter set (not tied to any specific sponsor)
                # We'll use a special sponsor ID or make it sponsor-agnostic
                # Actually, let's create one per sponsor to avoid FK issues
                dummy_fs = SponsorCatalogFilterSet.query.filter_by(
                    ID="__recommended_only__",
                    SponsorID=sponsor_id
                ).first()
                if not dummy_fs:
                    # Create dummy filter set for this sponsor
                    dummy_fs = SponsorCatalogFilterSet(
                        ID="__recommended_only__",
                        SponsorID=sponsor_id,
                        Name="Recommended Products Only",
                        IsActive=True,
                        Priority=0,
                        RulesJSON={"special_mode": "recommended_only"}
                    )
                    db.session.add(dummy_fs)
                    current_app.logger.info(f"[FILTER_SET] Created dummy recommended_only filter set for sponsor {sponsor_id}")
            
            sel = SponsorActiveFilterSelection.query.get(sponsor_id)
            old_filter_set_id = getattr(sel, "FilterSetID", None) if sel else None
            
            if not sel:
                sel = SponsorActiveFilterSelection(SponsorID=sponsor_id)
                db.session.add(sel)
                current_app.logger.info(f"[FILTER_SET] set_active_filter_set - Creating new SponsorActiveFilterSelection for sponsor {sponsor_id}")

            sel.FilterSetID = "__recommended_only__"
            sel.SelectedByAccountID = current_user.get_id() if hasattr(current_user, "get_id") else None
            
            current_app.logger.info(f"[FILTER_SET] set_active_filter_set - Setting FilterSetID to __recommended_only__ (was {old_filter_set_id})")
            
            db.session.commit()
            
            current_app.logger.info(f"[FILTER_SET] ✓ Successfully set active filter set to __recommended_only__ for sponsor {sponsor_id}")
            
            # Log the active filter set change
            try:
                log(
                    sponsor_id, 
                    "ACTIVE_FILTER_SET_CHANGE", 
                    current_user.get_id(), 
                    {
                        "old_filter_set_id": old_filter_set_id,
                        "new_filter_set_id": "__recommended_only__",
                        "filter_set_name": "Recommended Products Only"
                    }
                )
            except Exception:
                pass

            return jsonify({"ok": True})

        # Existing code for regular filter sets
        fs = SponsorCatalogFilterSet.query.filter_by(ID=fs_id, SponsorID=sponsor_id).first()
        if not fs:
            current_app.logger.warning(f"[FILTER_SET] set_active_filter_set - Filter set {fs_id} not found for sponsor {sponsor_id}")
            return jsonify({"ok": False, "error": "filter set not found"}), 404

        sel = SponsorActiveFilterSelection.query.get(sponsor_id)
        old_filter_set_id = getattr(sel, "FilterSetID", None) if sel else None
        
        if not sel:
            sel = SponsorActiveFilterSelection(SponsorID=sponsor_id)
            db.session.add(sel)
            current_app.logger.info(f"[FILTER_SET] set_active_filter_set - Creating new SponsorActiveFilterSelection for sponsor {sponsor_id}")

        sel.FilterSetID = fs_id
        sel.SelectedByAccountID = current_user.get_id() if hasattr(current_user, "get_id") else None
        
        current_app.logger.info(f"[FILTER_SET] set_active_filter_set - Setting FilterSetID to {fs_id} (was {old_filter_set_id})")
        
        db.session.commit()
        
        current_app.logger.info(f"[FILTER_SET] ✓ Successfully set active filter set {fs_id} for sponsor {sponsor_id}")

        # Log the active filter set change
        try:
            log(
                sponsor_id, 
                "ACTIVE_FILTER_SET_CHANGE", 
                current_user.get_id(), 
                {
                    "old_filter_set_id": old_filter_set_id,
                    "new_filter_set_id": fs_id,
                    "filter_set_name": getattr(fs, "Name", None)
                }
            )
        except Exception:
            pass

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Unexpected error: {str(e)}"}), 500


@bp.post("/filter-sets")
@login_required
def create_filter_set():
    """Create a new filter set."""
    try:
        # Check authentication manually to return JSON errors instead of HTML
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        
        # Get sponsor_id manually to avoid abort() which returns HTML
        sponsor_id = session.get("sponsor_id")
        if not sponsor_id and getattr(current_user, "AccountID", None):
            s = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
            if s:
                sponsor_id = s.SponsorID
                session["sponsor_id"] = sponsor_id
        
        if not sponsor_id:
            return jsonify({"ok": False, "error": "Sponsor account required"}), 403
        
        name = (request.form.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "name required"}), 400
        
        rules_json_str = request.form.get("rules_json", "{}")
        try:
            rules_json = json.loads(rules_json_str)
        except json.JSONDecodeError:
            return jsonify({"ok": False, "error": "invalid rules_json"}), 400
        
        # Prevent creating filter sets with recommended_only mode
        if rules_json.get("special_mode") == "recommended_only" or rules_json.get("special_mode") == "pinned_only":
            return jsonify({"ok": False, "error": "Cannot create filter sets with 'Recommended Products Only' mode. Use the 'Recommended Products Only' option in the active filter set selection instead."}), 400
        
        try:
            priority = int(request.form.get("priority", 100))
        except (ValueError, TypeError):
            priority = 100
        
        is_active_str = request.form.get("is_active", "true")
        is_active = str(is_active_str).lower() == "true"
        
        # Create new filter set
        try:
            fs = SponsorCatalogFilterSet(
                SponsorID=sponsor_id,
                Name=name,
                Priority=priority,
                IsActive=is_active,
                RulesJSON=rules_json
            )
            db.session.add(fs)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"ok": False, "error": f"Error creating filter set: {str(e)}"}), 500
        
        # Log creation (non-critical, don't fail if this errors)
        try:
            log(
                sponsor_id, 
                "FILTER_CREATE", 
                current_user.get_id(), 
                {
                    "id": fs.ID,
                    "name": name,
                    "priority": priority,
                    "is_active": is_active
                }
            )
        except Exception:
            pass
        
        return jsonify({"ok": True, "id": fs.ID})
        
    except Exception as e:
        # Catch any unexpected errors and return JSON
        return jsonify({"ok": False, "error": f"Unexpected error: {str(e)}"}), 500


@bp.get("/filter-sets/<string:fsid>")
@login_required
def get_filter_set(fsid: str):
    """Get a single filter set by ID (for editing)"""
    try:
        # Check authentication manually to return JSON errors instead of HTML
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        
        # Get sponsor_id manually to avoid abort() which returns HTML
        sponsor_id = session.get("sponsor_id")
        if not sponsor_id and getattr(current_user, "AccountID", None):
            s = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
            if s:
                sponsor_id = s.SponsorID
                session["sponsor_id"] = sponsor_id
        
        if not sponsor_id:
            return jsonify({"ok": False, "error": "Sponsor account required"}), 403
        
        # Prevent editing dummy filter sets
        if fsid in ["__no_filter__", "__recommended_only__"]:
            return jsonify({"ok": False, "error": "Cannot edit special filter sets. These are managed automatically."}), 400
        
        fs = SponsorCatalogFilterSet.query.filter_by(ID=fsid, SponsorID=sponsor_id).first()
        if not fs:
            return jsonify({"ok": False, "error": "Filter set not found"}), 404
        
        return jsonify({
            "id": fs.ID,
            "name": fs.name,
            "rules_json": fs.rules_json or {},
            "priority": fs.priority,
            "is_active": fs.is_active,
            "created_at": fs.created_at.isoformat() if fs.created_at else None,
            "updated_at": fs.updated_at.isoformat() if fs.updated_at else None
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"Unexpected error: {str(e)}"}), 500


@bp.post("/filter-sets/<string:fsid>")
@login_required
def update_filter_set(fsid: str):
    try:
        # Check authentication manually to return JSON errors instead of HTML
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        
        # Get sponsor_id manually to avoid abort() which returns HTML
        sponsor_id = session.get("sponsor_id")
        if not sponsor_id and getattr(current_user, "AccountID", None):
            s = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
            if s:
                sponsor_id = s.SponsorID
                session["sponsor_id"] = sponsor_id
        
        if not sponsor_id:
            return jsonify({"ok": False, "error": "Sponsor account required"}), 403
        
        fs = SponsorCatalogFilterSet.query.filter_by(ID=fsid, SponsorID=sponsor_id).first()
        if not fs:
            return jsonify({"ok": False, "error": "filter set not found"}), 404

        changes = {}
        if "name" in request.form:
            old_name = fs.name
            fs.name = request.form.get("name", fs.name).strip() or fs.name
            if old_name != fs.name:
                changes["name"] = {"old": old_name, "new": fs.name}
        if "priority" in request.form:
            old_priority = fs.priority
            fs.priority = int(request.form.get("priority") or fs.priority)
            if old_priority != fs.priority:
                changes["priority"] = {"old": old_priority, "new": fs.priority}
        if "is_active" in request.form:
            old_is_active = fs.is_active
            fs.is_active = (request.form.get("is_active") or "true").lower() == "true"
            if old_is_active != fs.is_active:
                changes["is_active"] = {"old": old_is_active, "new": fs.is_active}
        if "rules_json" in request.form:
            try:
                new_rules_json = json.loads(request.form.get("rules_json") or "{}")
                
                # Prevent updating filter sets to recommended_only mode
                if new_rules_json.get("special_mode") == "recommended_only" or new_rules_json.get("special_mode") == "pinned_only":
                    return jsonify({"ok": False, "error": "Cannot set filter sets to 'Recommended Products Only' mode. Use the 'Recommended Products Only' option in the active filter set selection instead."}), 400
                
                fs.rules_json = new_rules_json
                changes["rules_json"] = "updated"
            except json.JSONDecodeError:
                return jsonify({"ok": False, "error": "invalid rules_json"}), 400

        db.session.commit()
        
        try:
            log(
                sponsor_id, 
                "FILTER_UPDATE", 
                current_user.get_id(), 
                {
                    "id": fs.ID,
                    "name": fs.name,
                    "changes": changes
                }
            )
        except Exception:
            pass
        
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Unexpected error: {str(e)}"}), 500


@bp.get("/filter-sets/<string:fsid>/edit")
@login_required
def edit_filter_set_page(fsid: string):
    sponsor_id = require_sponsor()
    fs = (
        SponsorCatalogFilterSet.query
        .filter_by(ID=fsid, SponsorID=sponsor_id)
        .first_or_404()
    )
    return render_template("sponsor_catalog/edit_filter_set.html", row=fs)


@bp.post("/filter-sets/<string:fsid>/delete")
@login_required
def delete_filter_set(fsid: str):
    try:
        # Check authentication manually to return JSON errors instead of HTML
        if not current_user.is_authenticated:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        
        # Get sponsor_id manually to avoid abort() which returns HTML
        sponsor_id = session.get("sponsor_id")
        if not sponsor_id and getattr(current_user, "AccountID", None):
            s = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
            if s:
                sponsor_id = s.SponsorID
                session["sponsor_id"] = sponsor_id
        
        if not sponsor_id:
            return jsonify({"ok": False, "error": "Sponsor account required"}), 403
        
        fs = SponsorCatalogFilterSet.query.filter_by(ID=fsid, SponsorID=sponsor_id).first()
        if not fs:
            return jsonify({"ok": False, "error": "filter set not found"}), 404
        
        filter_name = getattr(fs, "Name", None)
        db.session.delete(fs)
        db.session.commit()
        
        try:
            log(
                sponsor_id, 
                "FILTER_DELETE", 
                current_user.get_id(), 
                {
                    "id": fsid,
                    "name": filter_name
                }
            )
        except Exception:
            pass
        
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Unexpected error: {str(e)}"}), 500


@bp.get("/filter-sets/audit-history")
@login_required
def filter_sets_audit_history():
    """Display audit history for filter set changes."""
    sponsor_id = require_sponsor()
    
    # Get all audit logs related to filter sets
    filter_actions = [
        'FILTER_CREATE',
        'FILTER_UPDATE', 
        'FILTER_DELETE',
        'ACTIVE_FILTER_SET_CHANGE',
        'FILTER_EXPORT',
        'FILTER_EXPORT_PDF'
    ]
    
    from ..models import Account, SponsorAuditLog
    
    # Query audit logs with actor information
    audit_logs = (
        db.session.query(SponsorAuditLog, Account)
        .outerjoin(Account, SponsorAuditLog.ActorUserID == Account.AccountID)
        .filter(
            SponsorAuditLog.SponsorID == sponsor_id,
            SponsorAuditLog.Action.in_(filter_actions)
        )
        .order_by(SponsorAuditLog.CreatedAt.desc())
        .limit(500)  # Limit to most recent 500 entries
        .all()
    )
    
    # Format the logs for the template
    formatted_logs = []
    for log_entry, account in audit_logs:
        actor_name = "System"
        actor_email = ""
        
        if account:
            actor_name = (
                getattr(account, "WholeName", None) or
                f"{getattr(account, 'FirstName', '')} {getattr(account, 'LastName', '')}".strip() or
                getattr(account, "Username", "Unknown User")
            )
            actor_email = getattr(account, "Email", "")
        
        # Format the action description
        action = getattr(log_entry, "Action", "")
        details = getattr(log_entry, "DetailsJSON", {}) or {}
        
        action_desc = action.replace("_", " ").title()
        detail_info = ""
        
        if action == "FILTER_CREATE":
            detail_info = f"Created filter set: {details.get('name', 'Unnamed')}"
        elif action == "FILTER_UPDATE":
            filter_name = details.get('name', details.get('id', 'Unknown'))
            changes = details.get('changes', {})
            if changes:
                change_desc = ", ".join([f"{k}: {v}" for k, v in changes.items()])
                detail_info = f"Updated '{filter_name}' - Changes: {change_desc}"
            else:
                detail_info = f"Updated filter set: {filter_name}"
        elif action == "FILTER_DELETE":
            detail_info = f"Deleted filter set: {details.get('name', details.get('id', 'Unknown'))}"
        elif action == "ACTIVE_FILTER_SET_CHANGE":
            old_id = details.get('old_filter_set_id', 'None')
            new_name = details.get('filter_set_name', details.get('new_filter_set_id', 'Unknown'))
            detail_info = f"Changed active filter set to: {new_name}"
        elif action in ["FILTER_EXPORT", "FILTER_EXPORT_PDF"]:
            count = details.get('count', 0)
            detail_info = f"Exported {count} filter set(s)"
        else:
            detail_info = str(details)
        
        formatted_logs.append({
            "id": getattr(log_entry, "ID", ""),
            "action": action,
            "action_display": action_desc,
            "detail_info": detail_info,
            "actor_name": actor_name,
            "actor_email": actor_email,
            "created_at": getattr(log_entry, "CreatedAt", None),
            "details_json": details
        })
    
    return render_template(
        "sponsor_catalog/filter_sets_audit_history.html",
        audit_logs=formatted_logs
    )


@bp.get("/overrides")
@login_required
def overrides_page():
    # Redirect to pinned products page
    return render_template("sponsor_catalog/pinned_products.html")


@bp.get("/recommended-products")
@login_required
def recommended_products_page():
    """Display all recommended products with real-time eBay API data."""
    # Alias for backward compatibility - redirect old route
    return pinned_products_page()

@bp.get("/pinned-products")
@login_required
def pinned_products_page():
    """Display all pinned products with real-time eBay API data. (Legacy route - use recommended-products)"""
    sponsor_id = require_sponsor()
    
    # Get all pinned products for this sponsor
    # Use case() for NULLS LAST compatibility with MySQL
    pins = (
        SponsorPinnedProduct.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(
            case((SponsorPinnedProduct.PinRank.is_(None), 1), else_=0),
            SponsorPinnedProduct.PinRank.asc(),
            SponsorPinnedProduct.CreatedAt.desc()
        )
        .all()
    )
    
    current_app.logger.info(f"[PINNED PRODUCTS] Found {len(pins)} pinned products in database for sponsor {sponsor_id}")
    
    # Fetch current data from eBay API for each pinned product
    from .providers.ebay_provider import EbayProvider
    provider = EbayProvider()
    
    pinned_items = []
    for pin in pins:
        item_id = getattr(pin, "ItemID", None)
        if not item_id:
            current_app.logger.warning(f"[PINNED PRODUCTS] Pin {pin.ID} has no ItemID, skipping")
            continue
        
        current_app.logger.info(f"[PINNED PRODUCTS] Fetching eBay data for item {item_id}")
        try:
            # Fetch item details from eBay
            item_data = provider.get_item(item_id)
            if item_data:
                # Add pin-specific metadata
                item_data["pin_id"] = getattr(pin, "ID", "")
                item_data["pin_rank"] = getattr(pin, "PinRank", None)
                item_data["note"] = getattr(pin, "Note", "")
                item_data["pinned_at"] = getattr(pin, "CreatedAt", None)
                pinned_items.append(item_data)
                current_app.logger.info(f"[PINNED PRODUCTS] Successfully fetched eBay data for item {item_id}")
            else:
                # get_item() returned None/False - item might not exist on eBay anymore
                current_app.logger.warning(f"[PINNED PRODUCTS] eBay API returned no data for item {item_id}, using cached data")
                # Add cached data as fallback
                pinned_items.append({
                    "id": item_id,
                    "title": getattr(pin, "ItemTitle", "") or f"Item {item_id}",
                    "image": getattr(pin, "ItemImageURL", ""),
                    "pin_id": getattr(pin, "ID", ""),
                    "pin_rank": getattr(pin, "PinRank", None),
                    "note": getattr(pin, "Note", ""),
                    "pinned_at": getattr(pin, "CreatedAt", None),
                    "error": "Could not fetch current data from eBay"
                })
        except Exception as e:
            current_app.logger.warning(f"[PINNED PRODUCTS] Exception fetching eBay data for item {item_id}: {e}", exc_info=True)
            # Add cached data as fallback
            pinned_items.append({
                "id": item_id,
                "title": getattr(pin, "ItemTitle", "") or f"Item {item_id}",
                "image": getattr(pin, "ItemImageURL", ""),
                "pin_id": getattr(pin, "ID", ""),
                "pin_rank": getattr(pin, "PinRank", None),
                "note": getattr(pin, "Note", ""),
                "pinned_at": getattr(pin, "CreatedAt", None),
                "error": f"Error fetching data: {str(e)}"
            })
    
    current_app.logger.info(f"[PINNED PRODUCTS] Returning {len(pinned_items)} items to template (expected {len(pins)})")
    if len(pinned_items) != len(pins):
        current_app.logger.warning(f"[PINNED PRODUCTS] Mismatch! Database has {len(pins)} pins but only {len(pinned_items)} items will be displayed")
    
    return render_template(
        "sponsor_catalog/recommended_products.html",
        pinned_items=pinned_items
    )


@bp.post("/pin-product")
@login_required
def pin_product():
    """Pin a product to feature in driver catalogs."""
    sponsor_id = require_sponsor()
    
    item_id = (request.form.get("item_id") or "").strip()
    if not item_id:
        abort(400, "item_id required")
    
    # Get optional metadata
    item_title = (request.form.get("title") or "").strip()
    item_image = (request.form.get("image") or "").strip()
    note = (request.form.get("note") or "").strip()
    
    # Check if already pinned
    existing = SponsorPinnedProduct.query.filter_by(
        SponsorID=sponsor_id,
        ItemID=item_id
    ).first()
    
    if existing:
        return jsonify({"ok": False, "message": "Product already pinned"}), 400
    
    # Get current max rank to add at end
    max_rank_row = (
        db.session.query(db.func.max(SponsorPinnedProduct.PinRank))
        .filter_by(SponsorID=sponsor_id)
        .scalar()
    )
    next_rank = (max_rank_row or 0) + 1
    
    # Create pinned product
    pin = SponsorPinnedProduct(
        SponsorID=sponsor_id,
        Marketplace="ebay",
        ItemID=item_id,
        ItemTitle=item_title,
        ItemImageURL=item_image,
        PinRank=next_rank,
        Note=note,
        PinnedByAccountID=current_user.get_id() if hasattr(current_user, "get_id") else None
    )
    
    try:
        current_app.logger.info(f"[PIN DEBUG] Adding pin to session: item_id={item_id}, sponsor_id={sponsor_id}")
        db.session.add(pin)
        
        # Flush to get the ID before commit
        db.session.flush()
        pin_id = pin.ID
        current_app.logger.info(f"[PIN DEBUG] Pin ID generated: {pin_id}")
        
        current_app.logger.info(f"[PIN DEBUG] Committing to database...")
        db.session.commit()
        current_app.logger.info(f"[PIN DEBUG] Commit successful! Pin ID: {pin_id}")
        
        # Verify it was actually saved
        verify_pin = SponsorPinnedProduct.query.filter_by(ID=pin_id).first()
        if verify_pin:
            current_app.logger.info(f"[PIN DEBUG] Verification: Pin found in database with ItemID={verify_pin.ItemID}")
        else:
            current_app.logger.error(f"[PIN DEBUG] Verification FAILED: Pin {pin_id} not found in database after commit!")
        
        # Log the action (don't let audit log failures prevent success response)
        try:
            log(
                sponsor_id,
                "PRODUCT_PINNED",
                current_user.get_id(),
                {
                    "item_id": item_id,
                    "title": item_title,
                    "rank": next_rank
                }
            )
        except Exception as log_error:
            # Log the audit failure but don't fail the request
            current_app.logger.error(f"Failed to log pin action: {log_error}", exc_info=True)
        
        response_data = {"ok": True, "message": "Product pinned successfully", "pin_id": pin_id}
        current_app.logger.info(f"[PIN DEBUG] Returning response: {response_data}")
        return jsonify(response_data)
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[PIN DEBUG] Error pinning product {item_id}: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"[PIN DEBUG] Traceback: {traceback.format_exc()}")
        return jsonify({"ok": False, "message": f"Failed to pin product: {str(e)}"}), 500


@bp.get("/pinned-product/<string:item_id>")
@login_required
def get_pinned_product(item_id: str):
    """Get a pinned product by item_id for verification."""
    try:
        sponsor_id = require_sponsor()
        
        pin = SponsorPinnedProduct.query.filter_by(
            SponsorID=sponsor_id,
            ItemID=item_id
        ).first()
        
        if not pin:
            return jsonify({"ok": False, "message": "Product not found in pinned products"}), 404
        
        return jsonify({
            "ok": True,
            "pin": {
                "id": pin.ID,
                "item_id": pin.ItemID,
                "sponsor_id": pin.SponsorID,
                "marketplace": pin.Marketplace,
                "title": pin.ItemTitle,
                "image": pin.ItemImageURL,
                "pin_rank": pin.PinRank,
                "note": pin.Note,
                "created_at": pin.CreatedAt.isoformat() if pin.CreatedAt else None,
                "updated_at": pin.UpdatedAt.isoformat() if pin.UpdatedAt else None,
                "pinned_by_account_id": pin.PinnedByAccountID
            }
        })
    except Exception as e:
        current_app.logger.error(f"Error getting pinned product {item_id}: {e}", exc_info=True)
        return jsonify({"ok": False, "message": "Error retrieving pinned product"}), 500


@bp.post("/unpin-product/<string:pin_id>")
@login_required
def unpin_product(pin_id: str):
    """Unpin a product and renumber remaining pins."""
    sponsor_id = require_sponsor()
    
    current_app.logger.info(f"[UNPIN] Starting unpin operation for pin {pin_id}, sponsor {sponsor_id}")
    
    try:
        pin = SponsorPinnedProduct.query.filter_by(
            ID=pin_id,
            SponsorID=sponsor_id
        ).first()
        
        if not pin:
            current_app.logger.warning(f"[UNPIN] Pin {pin_id} not found for sponsor {sponsor_id}")
            return jsonify({"ok": False, "message": "Pin not found"}), 404
        
        item_id = getattr(pin, "ItemID", None)
        item_title = getattr(pin, "ItemTitle", "")
        deleted_rank = getattr(pin, "PinRank", None)
        
        current_app.logger.info(f"[UNPIN] Found pin: item_id={item_id}, rank={deleted_rank}")
        
        # Delete the pin
        db.session.delete(pin)
        db.session.flush()  # Flush to ensure deletion is processed before renumbering
        current_app.logger.info(f"[UNPIN] Pin deleted from session, flushing...")
        
        # Renumber remaining pins to be sequential starting from 1
        remaining_pins = (
            SponsorPinnedProduct.query
            .filter_by(SponsorID=sponsor_id)
            .order_by(
                case((SponsorPinnedProduct.PinRank.is_(None), 1), else_=0),
                SponsorPinnedProduct.PinRank.asc(),
                SponsorPinnedProduct.CreatedAt.desc()
            )
            .all()
        )
        
        current_app.logger.info(f"[UNPIN] Found {len(remaining_pins)} remaining pins to renumber")
        
        # Renumber sequentially
        renumbered_count = 0
        for index, remaining_pin in enumerate(remaining_pins, start=1):
            old_rank = remaining_pin.PinRank
            if old_rank != index:
                remaining_pin.PinRank = index
                renumbered_count += 1
                current_app.logger.info(f"[UNPIN] Renumbered pin {remaining_pin.ID} from rank {old_rank} to {index}")
            else:
                current_app.logger.debug(f"[UNPIN] Pin {remaining_pin.ID} already has correct rank {index}")
        
        current_app.logger.info(f"[UNPIN] Committing changes: deleted 1 pin, renumbered {renumbered_count} pins")
        db.session.commit()
        
        current_app.logger.info(f"[UNPIN] Successfully deleted pin {pin_id} (was rank {deleted_rank}), renumbered {len(remaining_pins)} remaining pins")
        
        # Log the action (don't let audit log failures prevent success response)
        try:
            log(
                sponsor_id,
                "PRODUCT_UNPINNED",
                current_user.get_id(),
                {
                    "item_id": item_id,
                    "title": item_title,
                    "deleted_rank": deleted_rank,
                    "remaining_count": len(remaining_pins)
                }
            )
        except Exception as log_error:
            current_app.logger.error(f"[UNPIN] Failed to log unpin action: {log_error}", exc_info=True)
        
        return jsonify({"ok": True, "message": "Product unpinned successfully"})
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[UNPIN] Error unpinning product {pin_id}: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"[UNPIN] Traceback: {traceback.format_exc()}")
        return jsonify({"ok": False, "message": f"Failed to unpin product: {str(e)}"}), 500


@bp.post("/pin-product/<string:pin_id>/update-rank")
@login_required
def update_pin_rank(pin_id: str):
    """Update the display order of a pinned product."""
    sponsor_id = require_sponsor()
    
    pin = SponsorPinnedProduct.query.filter_by(
        ID=pin_id,
        SponsorID=sponsor_id
    ).first_or_404()
    
    new_rank = request.form.get("rank")
    if new_rank is not None:
        try:
            pin.PinRank = int(new_rank)
            db.session.commit()
            return jsonify({"ok": True, "message": "Rank updated"})
        except ValueError:
            abort(400, "Invalid rank")
    
    abort(400, "rank required")


@bp.get("/preview")
@login_required
def preview_page():
    """Live Preview page with a filter-set selector."""
    sponsor_id = require_sponsor()  # robust resolver

    # Use PascalCase column names to match your model/DB mapping
    rows = (
        SponsorCatalogFilterSet.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(
            desc(SponsorCatalogFilterSet.IsActive),
            asc(SponsorCatalogFilterSet.Priority),
            desc(SponsorCatalogFilterSet.UpdatedAt),
        )
        .all()
    )

    filter_set_options = [
        {
            "id": str(getattr(r, "ID", getattr(r, "id", ""))),
            "name": getattr(r, "Name", getattr(r, "name", "")) or f"Set {getattr(r, 'ID', getattr(r, 'id', ''))}",
            "active": bool(getattr(r, "IsActive", getattr(r, "is_active", False))),
            "priority": getattr(r, "Priority", getattr(r, "priority", 100)),
        }
        for r in rows
    ]

    return render_template(
        "sponsor_catalog/preview.html",
        filter_set_options=filter_set_options,
        default_sort="best_match",
    )


@bp.get("/preview/data")
@login_required
def preview_data():
    """
    Data endpoint for the preview grid.
    Accepts page, page_size, sort, q, filter_set_id, min_price, max_price, category_id, fast.
    
    Query params:
        fast: If '1', uses fast mode (strict_total=False) for faster TTFB.
              Skips expensive total count and relies on has_more only.
        min_price: Minimum price filter (overrides filter set price min if provided)
        max_price: Maximum price filter (overrides filter set price max if provided)
        category_id: Category ID to filter by (overrides filter set categories if provided)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    sponsor_id = require_sponsor()
    
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 24))
    sort = (request.args.get("sort") or "best_match").strip()
    keyword_overlay = (request.args.get("q") or "").strip() or None
    filter_set_id = (request.args.get("filter_set_id") or "").strip()
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")
    category_id = request.args.get("category_id")
    
    logger.info(f"[PREVIEW DATA] Request received: sponsor_id={sponsor_id}, page={page}, page_size={page_size}, "
                f"sort={sort}, filter_set_id={filter_set_id}, category_id={category_id}, "
                f"min_price={min_price}, max_price={max_price}, keyword_overlay={keyword_overlay}")
    
    # Fast mode: skip expensive total count
    fast_mode = request.args.get("fast", "").strip() == "1"
    strict_total = not fast_mode

    rules_overlay = None
    no_filter = False
    
    # IMPORTANT: If category_id is provided, we should NOT use recommended_only mode
    # Category browsing should show products from that category, not recommended products
    if category_id:
        logger.info(f"[PREVIEW DATA] Category filter provided ({category_id}), ignoring recommended_only mode")
        # When browsing by category, treat as no_filter but with category overlay
        no_filter = True
        rules_overlay = {"categories": {"include": [category_id]}}
    elif not filter_set_id or filter_set_id == "__no_filter__":
        # Empty filter_set_id or explicit __no_filter__ means show all products (with pinned items at top)
        logger.info(f"[PREVIEW DATA] No filter mode enabled (filter_set_id='{filter_set_id}')")
        no_filter = True
    elif filter_set_id == "__recommended_only__":
        # Special mode: show only recommended (pinned) products
        logger.info(f"[PREVIEW DATA] Recommended_only mode enabled")
        no_filter = True  # Set no_filter so it doesn't merge with active rules
        rules_overlay = {"special_mode": "recommended_only"}
    elif filter_set_id:
        logger.info(f"[PREVIEW DATA] Loading filter set: {filter_set_id}")
        fs = (
            SponsorCatalogFilterSet.query
            .filter_by(ID=filter_set_id, SponsorID=sponsor_id)
            .first()
        )
        if fs:
            # model exposes Pascal + snake; prefer Pascal to match schema
            rules_overlay = getattr(fs, "RulesJSON", None) or getattr(fs, "rules_json", None)
            logger.info(f"[PREVIEW DATA] Filter set loaded, rules_overlay keys: {list(rules_overlay.keys()) if rules_overlay else 'None'}")
        else:
            logger.warning(f"[PREVIEW DATA] Filter set {filter_set_id} not found for sponsor {sponsor_id}")
    
    # PRICE FILTER DEBUGGING: Log received price parameters
    logger.info(f"[PRICE FILTER] Received price parameters: min_price={min_price} (type: {type(min_price)}), max_price={max_price} (type: {type(max_price)}), category_id={category_id}")
    
    # Apply price filters if provided (override filter set prices)
    # Only apply if we're not in category-only mode (category mode already has rules_overlay set)
    if (min_price or max_price) and not category_id:
        logger.info(f"[PRICE FILTER] Applying price filters (no category_id): min_price={min_price}, max_price={max_price}")
        if rules_overlay is None:
            rules_overlay = {}
        if "price" not in rules_overlay:
            rules_overlay["price"] = {}
        if min_price:
            try:
                price_min = float(min_price)
                rules_overlay["price"]["min"] = price_min
                logger.info(f"[PRICE FILTER] Set price min to {price_min}")
            except (ValueError, TypeError) as e:
                logger.warning(f"[PRICE FILTER] Failed to convert min_price to float: {min_price}, error: {e}")
        if max_price:
            try:
                price_max = float(max_price)
                rules_overlay["price"]["max"] = price_max
                logger.info(f"[PRICE FILTER] Set price max to {price_max}")
            except (ValueError, TypeError) as e:
                logger.warning(f"[PRICE FILTER] Failed to convert max_price to float: {max_price}, error: {e}")
    elif (min_price or max_price) and category_id:
        # Add price filter to existing category overlay
        logger.info(f"[PRICE FILTER] Applying price filters (with category_id): min_price={min_price}, max_price={max_price}, category_id={category_id}")
        if "price" not in rules_overlay:
            rules_overlay["price"] = {}
        if min_price:
            try:
                price_min = float(min_price)
                rules_overlay["price"]["min"] = price_min
                logger.info(f"[PRICE FILTER] Set price min to {price_min} (with category)")
            except (ValueError, TypeError) as e:
                logger.warning(f"[PRICE FILTER] Failed to convert min_price to float: {min_price}, error: {e}")
        if max_price:
            try:
                price_max = float(max_price)
                rules_overlay["price"]["max"] = price_max
                logger.info(f"[PRICE FILTER] Set price max to {price_max} (with category)")
            except (ValueError, TypeError) as e:
                logger.warning(f"[PRICE FILTER] Failed to convert max_price to float: {max_price}, error: {e}")
    
    # PRICE FILTER DEBUGGING: Log final rules_overlay
    if rules_overlay and "price" in rules_overlay:
        logger.info(f"[PRICE FILTER] Final rules_overlay price settings: {rules_overlay.get('price')}")
    else:
        logger.info(f"[PRICE FILTER] No price filters in rules_overlay (rules_overlay keys: {list(rules_overlay.keys()) if rules_overlay else 'None'})")
    
    # Check for recommended products mode (when filter set has recommended_only or user requests it)
    # If the current filter set doesn't have recommended_only mode but user wants recommended,
    # we can create a temporary rules overlay with recommended_only mode
    recommended_mode = request.args.get("recommended_mode", "").strip() == "1"
    if recommended_mode:
        # Check if current rules_overlay already has recommended_only mode
        has_recommended_mode = False
        if rules_overlay:
            has_recommended_mode = (
                rules_overlay.get("special_mode") == "recommended_only" or
                rules_overlay.get("filter_mode") == "pinned_only" or
                rules_overlay.get("special_mode") == "pinned_only"
            )
        
        if not has_recommended_mode:
            # Create or modify rules_overlay to include recommended_only mode
            if rules_overlay:
                rules_overlay = dict(rules_overlay)  # Make a copy
            else:
                rules_overlay = {}
            rules_overlay["special_mode"] = "recommended_only"

    logger.info(f"[PREVIEW DATA] Calling build_preview with: no_filter={no_filter}, rules_overlay={rules_overlay}")
    try:
        data, _cache_meta = build_preview(
            sponsor_id=sponsor_id,
            page=page,
            page_size=page_size,
            sort=sort,
            keyword_overlay=keyword_overlay,
            rules_overlay=rules_overlay,
            no_filter=no_filter,
            strict_total=strict_total,
        )
        
        logger.info(f"[PREVIEW DATA] build_preview returned: items_count={len(data.get('items', []))}, "
                    f"total={data.get('total')}, page={data.get('page')}, has_more={data.get('has_more')}")
        
        return jsonify(data)
    except Exception as e:
        logger.error(f"[PREVIEW DATA] Error in build_preview: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "items": [], "total": 0, "page": page, "page_size": page_size, "has_more": False}), 500


# ================================================================
# PRODUCT REPORTS & BLACKLIST MANAGEMENT
# ================================================================

@bp.get("/product-reports")
@login_required
def product_reports_page():
    """Page to view and manage reported products."""
    sponsor_id = require_sponsor()
    
    # Get all reports for this sponsor
    reports = (
        ProductReports.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(ProductReports.CreatedAt.desc())
        .all()
    )
    
    # Get driver names for reports (join with Account table for names)
    from ..models import Driver, Account
    driver_ids = list(set(r.DriverID for r in reports))
    
    # Build a dictionary of driver info with account details
    drivers = {}
    if driver_ids:
        drivers_with_accounts = (
            db.session.query(Driver, Account)
            .join(Account, Driver.AccountID == Account.AccountID)
            .filter(Driver.DriverID.in_(driver_ids))
            .all()
        )
        drivers = {d.DriverID: a for d, a in drivers_with_accounts}
    
    return render_template(
        "sponsor_catalog/product_reports.html",
        reports=reports,
        drivers=drivers
    )


@bp.post("/product-reports/<string:report_id>/approve")
@login_required
def approve_report(report_id: str):
    """Approve a report and add the product to blacklist."""
    sponsor_id = require_sponsor()
    account_id = session.get("account_id")
    
    report = ProductReports.query.filter_by(
        ID=report_id,
        SponsorID=sponsor_id
    ).first_or_404()
    
    if report.Status != "pending":
        return jsonify({"ok": False, "message": "Report already processed"})
    
    # Check if already blacklisted
    existing = BlacklistedProduct.query.filter_by(
        SponsorID=sponsor_id,
        ItemID=report.ExternalItemID
    ).first()
    
    if not existing:
        # Add to blacklist
        blacklisted = BlacklistedProduct(
            SponsorID=sponsor_id,
            ItemID=report.ExternalItemID,
            ItemTitle=report.ItemTitle,
            ItemImageURL=report.ItemImageURL,
            ItemURL=report.ItemURL,
            Reason=f"Reported: {report.ReportReason}",
            BlacklistedByAccountID=account_id,
            SourceReportID=report_id
        )
        db.session.add(blacklisted)
    
    # Mark report as approved
    report.Status = "approved"
    report.ReviewedByAccountID = account_id
    report.ReviewedAt = datetime.utcnow()
    
    # If the product is currently pinned/recommended, unpin it
    pinned_product = SponsorPinnedProduct.query.filter_by(
        SponsorID=sponsor_id,
        ItemID=report.ExternalItemID
    ).first()
    
    if pinned_product:
        current_app.logger.info(f"[APPROVE REPORT] Unpinning product {report.ExternalItemID} that was blacklisted via report {report_id}")
        pin_id = pinned_product.ID
        deleted_rank = pinned_product.PinRank
        
        # Delete the pin
        db.session.delete(pinned_product)
        db.session.flush()
        
        # Renumber remaining pins to be sequential starting from 1
        remaining_pins = (
            SponsorPinnedProduct.query
            .filter_by(SponsorID=sponsor_id)
            .order_by(
                case((SponsorPinnedProduct.PinRank.is_(None), 1), else_=0),
                SponsorPinnedProduct.PinRank.asc(),
                SponsorPinnedProduct.CreatedAt.desc()
            )
            .all()
        )
        
        # Renumber sequentially
        for index, remaining_pin in enumerate(remaining_pins, start=1):
            old_rank = remaining_pin.PinRank
            if old_rank != index:
                remaining_pin.PinRank = index
        
        # Log the unpin action
        try:
            log(
                sponsor_id=sponsor_id,
                action="PRODUCT_UNPINNED",
                actor_user_id=account_id,
                details={
                    "item_id": report.ExternalItemID,
                    "title": report.ItemTitle,
                    "deleted_rank": deleted_rank,
                    "remaining_count": len(remaining_pins),
                    "reason": f"Auto-unpinned when blacklisted via report {report_id}"
                }
            )
        except Exception as log_error:
            current_app.logger.error(f"[APPROVE REPORT] Failed to log unpin action: {log_error}", exc_info=True)
    
    db.session.commit()
    
    # Invalidate blacklist cache so the change takes effect immediately
    try:
        from app.utils.cache import get_cache
        cache = get_cache()
        cache_key = f"blacklist:sponsor:{sponsor_id}"
        cache.delete(cache_key)
        current_app.logger.info(f"[BLACKLIST] Invalidated cache for sponsor {sponsor_id} after blacklisting item {report.ExternalItemID}")
    except Exception as e:
        current_app.logger.warning(f"[BLACKLIST] Failed to invalidate cache: {e}")
    
    # Invalidate catalog cache if product was unpinned (so it disappears from recommended products)
    if pinned_product:
        try:
            from app.sponsor_catalog.services.cache_service import purge_cache_for_sponsor
            deleted_count = purge_cache_for_sponsor(sponsor_id)
            current_app.logger.info(f"[APPROVE REPORT] Invalidated {deleted_count} catalog cache entries for sponsor {sponsor_id} after unpinning blacklisted item {report.ExternalItemID}")
        except Exception as e:
            current_app.logger.warning(f"[APPROVE REPORT] Failed to invalidate catalog cache: {e}")
    
    # Log the action
    log(
        sponsor_id=sponsor_id,
        action="product_blacklisted",
        actor_user_id=account_id,
        details={
            "item_id": report.ExternalItemID,
            "item_title": report.ItemTitle,
            "reason": f"Approved report {report_id}",
            "report_reason": report.ReportReason
        }
    )
    
    return jsonify({"ok": True, "message": "Product blacklisted successfully"})


@bp.post("/product-reports/<string:report_id>/deny")
@login_required
def deny_report(report_id: str):
    """Deny a report without blacklisting."""
    sponsor_id = require_sponsor()
    account_id = session.get("account_id")
    
    report = ProductReports.query.filter_by(
        ID=report_id,
        SponsorID=sponsor_id
    ).first_or_404()
    
    if report.Status != "pending":
        return jsonify({"ok": False, "message": "Report already processed"})
    
    # Mark report as denied
    report.Status = "denied"
    report.ReviewedByAccountID = account_id
    report.ReviewedAt = datetime.utcnow()
    
    db.session.commit()
    
    return jsonify({"ok": True, "message": "Report denied"})


@bp.get("/blacklisted-products")
@login_required
def blacklisted_products_page():
    """Page to view and manage blacklisted products."""
    sponsor_id = require_sponsor()
    
    # Get all blacklisted products for this sponsor
    blacklisted = (
        BlacklistedProduct.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(BlacklistedProduct.CreatedAt.desc())
        .all()
    )
    
    return render_template(
        "sponsor_catalog/blacklisted_products.html",
        blacklisted_products=blacklisted
    )


@bp.delete("/blacklisted-products/<string:blacklist_id>")
@login_required
def unblacklist_product(blacklist_id: str):
    """Remove a product from the blacklist."""
    sponsor_id = require_sponsor()
    account_id = session.get("account_id")
    
    blacklisted = BlacklistedProduct.query.filter_by(
        ID=blacklist_id,
        SponsorID=sponsor_id
    ).first_or_404()
    
    item_id = blacklisted.ItemID
    item_title = blacklisted.ItemTitle
    
    # Update any approved reports for this item to "restored" status
    reports = ProductReports.query.filter_by(
        SponsorID=sponsor_id,
        ExternalItemID=item_id,
        Status="approved"
    ).all()
    
    for report in reports:
        report.Status = "restored"
        report.ReviewNotes = "Item was removed from blacklist"
    
    db.session.delete(blacklisted)
    db.session.commit()
    
    # Log the action
    log(
        sponsor_id=sponsor_id,
        action="product_unblacklisted",
        actor_user_id=account_id,
        details={
            "item_id": item_id,
            "item_title": item_title
        }
    )
    
    return jsonify({"ok": True, "message": "Product removed from blacklist"})


@bp.get("/product/<path:item_id>")
@login_required
def product_detail(item_id: str):
    """Display detailed product page with variants and related items for sponsors."""
    from urllib.parse import unquote
    
    # Decode URL-encoded item ID (handles pipe characters and special chars)
    item_id = unquote(item_id)
    
    sponsor_id = require_sponsor()
    
    try:
        from .providers.ebay_provider import EbayProvider
        provider = EbayProvider()
        
        # Fetch full item details from eBay
        current_app.logger.info(f"Sponsor viewing product details for item_id: {item_id}")
        item_data = provider.get_item_details(item_id)
        
        if not item_data:
            current_app.logger.error(f"Product not found: {item_id}")
            abort(404, "Product not found")
        
        current_app.logger.info(f"Product data retrieved: {item_data.get('title', 'No title')}")
        
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
        
        # Keep price as-is for sponsors (they see actual prices, not points)
        price = item_data.get("price")
        if price:
            try:
                item_data["display_price"] = f"${float(price):.2f}"
            except (ValueError, TypeError):
                current_app.logger.warning(f"Could not convert price to float: {price}")
                item_data["display_price"] = "N/A"
        else:
            item_data["display_price"] = "N/A"
        
        # Sponsors don't have favorites
        item_data["is_favorite"] = False
        
        # Check if this product is already pinned
        pinned_product = SponsorPinnedProduct.query.filter_by(
            SponsorID=sponsor_id,
            ItemID=item_id
        ).first()
        item_data["is_pinned"] = pinned_product is not None
        item_data["pin_id"] = pinned_product.ID if pinned_product else None
        
        # Apply low stock flags to the main item
        from .services.preview_service import _inject_low_stock_flags
        _inject_low_stock_flags([item_data])
        
        # Fetch related items using first 3 words from title
        related_items = []
        try:
            # Get some keywords from the title for better related items
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
            
            # Filter out current item
            related_items = [
                it for it in related_items 
                if str(it.get("id")) != str(item_id)
            ][:5]
            
            current_app.logger.info(f"Showing {len(related_items)} related items after filtering")
            
            # Apply low stock flags to related items
            _inject_low_stock_flags(related_items)
            
        except Exception as e:
            current_app.logger.error(f"Error fetching related items: {e}", exc_info=True)
        
        return render_template(
            "sponsor_catalog/product_detail.html",
            product=item_data,
            related_items=related_items,
            is_sponsor=True
        )
        
    except Exception as e:
        current_app.logger.error(f"Error loading product detail: {e}")
        abort(500, "Error loading product details")


@bp.get("/categories")
@login_required
def get_categories():
    """Get eBay category tree for the category browser."""
    import os
    import json
    
    # Check if exclude_explicit is requested (from query param or filter set being edited)
    exclude_explicit = request.args.get('exclude_explicit', '').lower() == 'true'
    
    # If editing a filter set, check its exclude_explicit setting
    filter_set_id = request.args.get('filter_set_id')
    if filter_set_id and not exclude_explicit:
        try:
            fs = SponsorCatalogFilterSet.query.filter_by(ID=filter_set_id).first()
            if fs:
                rules = fs.RulesJSON if hasattr(fs, 'RulesJSON') else fs.rules_json if hasattr(fs, 'rules_json') else {}
                if isinstance(rules, str):
                    import json
                    rules = json.loads(rules)
                exclude_explicit = rules.get("safety", {}).get("exclude_explicit", False)
                current_app.logger.info(
                    f"[ADULT_FILTER] Sponsor categories - Filter set {filter_set_id} "
                    f"exclude_explicit={exclude_explicit}"
                )
        except Exception as e:
            current_app.logger.warning(f"[ADULT_FILTER] Sponsor categories - Error checking filter set: {e}")
    
    current_app.logger.info(
        f"[ADULT_FILTER] Sponsor categories - Loading categories with exclude_explicit={exclude_explicit}"
    )
    
    # Try to load from the JSON file
    json_path = __import__("app.utils.ebay_categories_path", fromlist=["get_ebay_categories_path"]).get_ebay_categories_path()
    
    if not os.path.exists(json_path):
        # Fallback: return a simplified structure from test catalog
        fallback = _get_fallback_categories()
        if exclude_explicit:
            fallback = _filter_adult_categories_from_tree(fallback)
        return jsonify({
            "error": "Category tree file not found, using fallback",
            "categories": fallback
        })
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            tree_data = json.load(f)
        
        # Process the tree to create a simplified structure
        categories = _process_category_tree(tree_data.get("rootCategoryNode", {}), exclude_explicit=exclude_explicit)
        
        category_count = _count_categories_in_tree(categories)
        current_app.logger.info(
            f"[ADULT_FILTER] Sponsor categories - Processed category tree: "
            f"{category_count} categories returned (exclude_explicit={exclude_explicit})"
        )
        
        return jsonify({
            "categories": categories,
            "version": tree_data.get("categoryTreeVersion", "unknown")
        })
    except Exception as e:
        current_app.logger.error(f"Error loading categories: {e}", exc_info=True)
        # Fallback to test catalog structure
        fallback = _get_fallback_categories()
        if exclude_explicit:
            fallback = _filter_adult_categories_from_tree(fallback)
        return jsonify({
            "error": str(e),
            "categories": fallback
        })


def _process_category_tree(node, max_depth=5, exclude_explicit=False):
    """
    Process eBay category tree into a simplified hierarchical structure.
    Only includes leaf categories (categories that can actually be used for filtering).
    Groups leaf categories under their parent categories, skipping duplicate category names.
    """
    from .policies import ADULT_CATEGORY_IDS
    
    adult_categories_skipped = []
    result = {}
    
    def process_node(n, parent_name=None, parent_container=None, depth=0):
        """Recursively process category nodes."""
        if not isinstance(n, dict) or depth > max_depth:
            return
        
        cat = n.get("category", {})
        cat_id = cat.get("categoryId")
        cat_name = cat.get("categoryName", "")
        is_leaf = n.get("leafCategoryTreeNode", False)
        children = n.get("childCategoryTreeNodes", [])
        
        # Skip root
        if cat_id == "0":
            for child in children:
                process_node(child, None, result, 0)
            return
        
        # Skip adult categories ONLY if they are leaf categories
        # For parent categories, continue processing children to find non-adult subcategories
        if exclude_explicit and is_leaf:
            from .policies import ADULT_CATEGORY_KEYWORDS
            # Check by category ID
            if cat_id and str(cat_id) in ADULT_CATEGORY_IDS:
                adult_categories_skipped.append(f"{cat_name} ({cat_id})")
                current_app.logger.debug(
                    f"[ADULT_FILTER] _process_category_tree - Skipping adult leaf category by ID: {cat_name} ({cat_id})"
                )
                return
            # Check by category name keywords
            cat_name_lower = cat_name.lower()
            if any(keyword in cat_name_lower for keyword in ADULT_CATEGORY_KEYWORDS):
                adult_categories_skipped.append(f"{cat_name} ({cat_id})")
                current_app.logger.debug(
                    f"[ADULT_FILTER] _process_category_tree - Skipping adult leaf category by keyword: {cat_name} ({cat_id})"
                )
                return
        
        # Determine the container to use
        # If category name is same as parent name, skip this level and use parent container
        if cat_name == parent_name:
            # Skip this level - use parent container directly
            container = parent_container
        else:
            # Create new level
            container = parent_container if parent_container is not None else result
            if cat_name not in container:
                container[cat_name] = {}
            elif not isinstance(container[cat_name], dict):
                container[cat_name] = {}
            container = container[cat_name]
        
        # If this is a leaf category, add it to the container
        if is_leaf and cat_id and cat_id != "0":
            # Skip adult categories if exclude_explicit is enabled (double-check for safety)
            if exclude_explicit:
                from .policies import ADULT_CATEGORY_KEYWORDS
                # Check by category ID
                if str(cat_id) in ADULT_CATEGORY_IDS:
                    adult_categories_skipped.append(f"{cat_name} ({cat_id})")
                    current_app.logger.debug(
                        f"[ADULT_FILTER] _process_category_tree - Skipping adult leaf category by ID: {cat_name} ({cat_id})"
                    )
                    return
                # Check by category name keywords
                cat_name_lower = cat_name.lower()
                if any(keyword in cat_name_lower for keyword in ADULT_CATEGORY_KEYWORDS):
                    adult_categories_skipped.append(f"{cat_name} ({cat_id})")
                    current_app.logger.debug(
                        f"[ADULT_FILTER] _process_category_tree - Skipping adult leaf category by keyword: {cat_name} ({cat_id})"
                    )
                    return
            # Add ID -> Name mapping under the category name
            # But check if container already has this category name to avoid duplicates
            if cat_name not in container:
                container[cat_name] = {}
            elif not isinstance(container[cat_name], dict):
                container[cat_name] = {}
            # Only add if it's not already there (avoid duplicates)
            if cat_id not in container[cat_name]:
                container[cat_name][cat_id] = cat_name
            return
        
        # Process children (even if parent category ID is in adult list, process children to find non-adult subcategories)
        for child in children:
            process_node(child, cat_name, container, depth + 1)
    
    process_node(node, None, None, 0)
    
    if exclude_explicit and adult_categories_skipped:
        current_app.logger.info(
            f"[ADULT_FILTER] _process_category_tree - Skipped {len(adult_categories_skipped)} adult categories"
        )
        # Only log the filtered categories once, using debug level for individual items
        for skipped in adult_categories_skipped:
            current_app.logger.debug(f"[ADULT_FILTER] Filtered out: {skipped}")
    
    return result


def _filter_adult_categories_from_tree(category_tree):
    """Filter adult categories from a category tree structure."""
    from .policies import ADULT_CATEGORY_IDS
    
    def filter_node(node):
        """Recursively filter adult categories from a node."""
        if not isinstance(node, dict):
            return node
        
        filtered = {}
        for key, value in node.items():
            if isinstance(value, dict):
                # Check if this is a leaf category mapping (ID -> Name)
                if all(isinstance(k, str) and k.isdigit() for k in value.keys()):
                    # This is a leaf category mapping, filter out adult category IDs
                    filtered_value = {k: v for k, v in value.items() if str(k) not in ADULT_CATEGORY_IDS}
                    if filtered_value:  # Only add if there are non-adult categories
                        filtered[key] = filtered_value
                else:
                    # This is a nested structure, recurse
                    filtered_value = filter_node(value)
                    if filtered_value:  # Only add if there are categories after filtering
                        filtered[key] = filtered_value
            else:
                filtered[key] = value
        
        return filtered
    
    return filter_node(category_tree)


def _count_categories_in_tree(category_tree):
    """Count total number of categories in a category tree structure."""
    count = 0
    
    def count_node(node):
        nonlocal count
        if not isinstance(node, dict):
            return
        
        for key, value in node.items():
            if isinstance(value, dict):
                # Check if this is a leaf category mapping (ID -> Name)
                if all(isinstance(k, str) and k.isdigit() for k in value.keys()):
                    # Count leaf categories
                    count += len(value)
                else:
                    # Recurse into nested structure
                    count_node(value)
    
    count_node(category_tree)
    return count


def _deep_merge(dict1, dict2):
    """Deep merge dict2 into dict1."""
    for key, value in dict2.items():
        if key in dict1:
            if isinstance(dict1[key], dict) and isinstance(value, dict):
                _deep_merge(dict1[key], value)
            elif isinstance(value, dict):
                dict1[key] = value.copy()
            else:
                # If both are ID->Name mappings (dict with string values), merge them
                if isinstance(dict1[key], dict) and all(isinstance(v, str) for v in dict1[key].values()):
                    dict1[key].update(value)
                else:
                    dict1[key] = value
        else:
            dict1[key] = value


def _get_fallback_categories():
    """Fallback category structure from test catalog."""
    return {
        "eBay Motors": {
            "Parts & Accessories": {
                "Auto Parts & Accessories": {"6030": "Car & Truck Parts & Accessories", "33615": "Performance & Racing Parts", "10063": "Motorcycle & Scooter Parts & Accessories", "156955": "In-Car Technology, GPS & Security Devices"},
                "Automotive Tools & Supplies": {"34998": "Automotive Tools & Supplies"}
            },
            "Motorcycles": {"10063": "Motorcycles"},
            "Other Vehicles & Trailers": {"180103": "Other Vehicles & Trailers"},
            "Safety & Security Accessories": {"41": "Safety & Security Accessories"},
            "Boats": {"262321": "Boats"},
            "Powersports": {"101179": "Powersports"}
        },
        "Electronics": {
            "Computers/Tablets & Networking": {"58058": "Computers, Tablets & Networking"},
            "Cell Phones & Accessories": {"9355": "Cell Phones & Smartphones"},
            "Video Games & Consoles": {"1249": "Video Games & Consoles"},
            "Cameras & Photo": {"625": "Cameras & Photo"},
            "TV, Video & Home Audio": {"293": "TV, Video & Home Audio"},
            "Portable Audio & Headphones": {"15052": "Portable Audio & Headphones"},
            "Vehicle Electronics & GPS": {"3270": "Car Electronics", "156955": "Car GPS Units"},
            "Surveillance & Smart Home Electronics": {"175673": "Smart Home & Surveillance"},
            "Major Appliances": {"20710": "Major Appliances"},
            "Virtual Reality": {"183067": "Virtual Reality"}
        },
        "Collectibles & Art": {
            "Sports Mem, Cards & Fan Shop": {"64482": "Sports Mem, Cards & Fan Shop"},
            "Collectibles": {"1": "Collectibles"},
            "Dolls & Bears": {"237": "Dolls & Bears"},
            "Vintage & Antique Jewelry": {"262024": "Vintage & Antique Jewelry"},
            "Pottery & Glass": {"870": "Pottery & Glass"},
            "Art": {"550": "Art"},
            "Crafts": {"160636": "Arts & Crafts"},
            "Antiques": {"20081": "Antiques"},
            "Coins & Paper Money": {"11116": "Coins & Paper Money"},
            "Stamps": {"31740": "Stamps"},
            "Entertainment Memorabilia": {"45100": "Entertainment Memorabilia"}
        },
        "Home & Garden": {
            "Home Décor": {"10033": "Home Decor"},
            "Kitchen, Dining & Bar": {"20625": "Kitchen, Dining & Bar"},
            "Yard, Garden & Outdoor Living": {"159912": "Garden & Outdoor Living"},
            "Home Improvement": {"20594": "Home Improvement"},
            "Furniture": {"3197": "Furniture"},
            "Tools & Workshop Equipment": {"631": "Tools & Workshop Equipment"},
            "Bedding": {"20444": "Bedding"},
            "Lamps, Lighting & Ceiling Fans": {"20706": "Lamps, Lighting & Ceiling Fans"},
            "Household Supplies & Cleaning": {"299": "Household Supplies & Cleaning"},
            "Surveillance & Smart Home Electronics": {"175673": "Smart Home & Surveillance"},
            "Bath": {"20452": "Bath"},
            "Rugs & Carpets": {"20571": "Rugs & Carpets"},
            "Major Appliances": {"20710": "Major Appliances"},
            "Candles & Home Fragrance": {"262975": "Candles & Home Fragrance"},
            "Holiday & Seasonal Décor": {"170090": "Holiday & Seasonal Décor"},
            "Food & Beverages": {"14308": "Food & Beverages"},
            "Window Treatments & Hardware": {"63514": "Window Treatments & Hardware"},
            "Pillows": {"83902": "Pillows"},
            "Greeting Cards & Party Supply": {"16086": "Greeting Cards & Party Supply"},
            "Kitchen Fixtures": {"177073": "Kitchen Fixtures"}
        },
        "Clothing, Shoes & Accessories": {
            "Women": {"15724": "Women's Clothing", "3034": "Women's Shoes", "169291": "Women's Handbags & Bags", "4250": "Women's Accessories"},
            "Men": {"1059": "Men's Clothing", "93427": "Men's Shoes", "4251": "Men's Accessories"},
            "Kids": {"147": "Kids & Baby Clothing"},
            "Baby": {"260018": "Baby"},
            "Specialty": {"260033": "Specialty"},
            "Luggage": {"16080": "Luggage"}
        },
        "Toys & Hobbies": {
            "Collectible Card Games": {"2536": "Collectible Card Games"},
            "Action Figures & Accessories": {"246": "Action Figures"},
            "Video Games": {"1249": "Video Games & Consoles"},
            "Building Toys": {"18991": "Building Toys"},
            "Diecast & Toy Vehicles": {"222": "Diecast & Toy Vehicles"},
            "Model Railroads & Trains": {"19107": "Model Trains & Railroads"},
            "Games": {"233": "Games"},
            "Radio Control & Control Line": {"2562": "Radio Control & RC"},
            "Models & Kits": {"1188": "Models & Kits"},
            "Slot Cars": {"19149": "Slot Cars"},
            "Preschool Toys & Pretend Play": {"2617": "Preschool Toys & Pretend Play"},
            "Stuffed Animals": {"436": "Stuffed Animals"},
            "Vintage & Antique Toys": {"717": "Vintage & Antique Toys"},
            "Robots, Monsters & Space Toys": {"19192": "Robots, Monsters & Space Toys"},
            "Puzzles": {"1247": "Puzzles"},
            "Electronic, Battery & Wind-Up": {"19071": "Electronic, Battery & Wind-Up"},
            "Outdoor Toys & Structures": {"11743": "Outdoor Toys & Structures"},
            "Toy Soldiers": {"2631": "Toy Soldiers"},
            "Fast Food & Cereal Premiums": {"19077": "Fast Food & Cereal Premiums"},
            "Beanbag Plush": {"49019": "Beanbag Plush"}
        },
        "Sporting Goods": {
            "Sports Mem, Cards & Fan Shop": {"64482": "Sports Mem, Cards & Fan Shop"},
            "Hunting": {"7301": "Hunting"},
            "Golf": {"1513": "Golf"},
            "Cycling": {"7294": "Cycling"},
            "Fishing": {"1492": "Fishing"},
            "Outdoor Sports": {"159043": "Outdoor Sports"},
            "Team Sports": {"64482": "Team Sports"},
            "Camping & Hiking": {"16034": "Camping & Hiking"},
            "Fitness, Running & Yoga": {"15273": "Exercise & Fitness", "15277": "Yoga & Pilates", "15272": "Running & Jogging"},
            "Winter Sports": {"16058": "Winter Sports"},
            "Indoor Games": {"36274": "Indoor Games"},
            "Tactical & Duty Gear": {"177890": "Tactical & Duty Gear"},
            "Boxing, Martial Arts & MMA": {"179767": "Boxing, Martial Arts & MMA"},
            "Water Sports": {"1497": "Water Sports"},
            "Tennis & Racquet Sports": {"159134": "Tennis & Racquet Sports"},
            "Other Sporting Goods": {"310": "Other Sporting Goods"},
            "Wholesale Lots": {"56080": "Wholesale Lots"}
        },
        "Books, Movies & Music": {
            "Books & Magazines": {"134448": "Books & Magazines"},
            "Music": {"104417": "Music"},
            "Musical Instruments & Gear": {"619": "Musical Instruments & Gear"},
            "Movies & TV": {"11232": "Movies & TV"}
        },
        "Health & Beauty": {
            "Fragrances": {"31411": "Fragrances"},
            "Vitamins & Lifestyle Supplements": {"180959": "Vitamins & Dietary Supplements"},
            "Skin Care": {"11854": "Skin Care"},
            "Hair Care & Styling": {"11854": "Hair Care & Styling"},
            "Makeup": {"31786": "Makeup"},
            "Vision Care": {"31414": "Vision Care"},
            "Medical & Mobility": {"11778": "Medical & Mobility"},
            "Shaving & Hair Removal": {"11855": "Shaving & Hair Removal"},
            "Health Care": {"6197": "Health Care"},
            "Natural & Alternative Remedies": {"67659": "Natural & Alternative Remedies"},
            "Bath & Body": {"51006": "Bath & Body"},
            "Massage": {"36447": "Massage"},
            "Oral Care": {"11338": "Oral Care"},
            "Nail Care, Manicure & Pedicure": {"47945": "Nail Care, Manicure & Pedicure"},
            "Sun Protection & Tanning": {"31772": "Sun Protection & Tanning"},
            "Tattoos & Body Art": {"33914": "Tattoos & Body Art"},
            "Salon & Spa Equipment": {"177731": "Salon & Spa Equipment"},
            "Baby Safety & Health": {"20433": "Baby Safety & Health"},
            "Wholesale Lots": {"56080": "Wholesale Lots"},
            "Other Health & Beauty": {"1277": "Other Health & Beauty"}
        },
        "Business & Industrial": {
            "Healthcare, Lab & Dental": {"11815": "Healthcare, Lab & Dental"},
            "CNC, Metalworking & Manufacturing": {"11804": "CNC, Metalworking & Manufacturing"},
            "Test, Measurement & Inspection": {"181939": "Test, Measurement & Inspection"},
            "Electrical Equipment & Supplies": {"92074": "Electrical Equipment & Supplies"},
            "Office": {"25298": "Office"},
            "Light Equipment & Tools": {"61573": "Light Equipment & Tools"},
            "Industrial Automation & Motion Controls": {"42892": "Industrial Automation & Motion Controls"},
            "Restaurant & Food Service": {"11874": "Restaurant & Food Service"},
            "Heavy Equipment, Parts & Attachments": {"257887": "Heavy Equipment, Parts & Attachments"},
            "Facility Maintenance & Safety": {"11897": "Facility Maintenance & Safety"},
            "HVAC & Refrigeration": {"42909": "HVAC & Refrigeration"},
            "Agriculture & Forestry": {"11748": "Agriculture & Forestry"},
            "Hydraulics, Pneumatics, Pumps & Plumbing": {"183978": "Hydraulics, Pneumatics, Pumps & Plumbing"},
            "Retail & Services": {"11890": "Retail & Services"},
            "Printing & Graphic Arts": {"26238": "Printing & Graphic Arts"},
            "Material Handling": {"26221": "Material Handling"},
            "Building Materials & Supplies": {"41498": "Building Materials & Supplies"},
            "Fasteners & Hardware": {"183900": "Fasteners & Hardware"},
            "Modular & Prefabricated Buildings": {"55805": "Modular & Prefabricated Buildings"},
            "Adhesives, Sealants & Tapes": {"109471": "Adhesives, Sealants & Tapes"}
        },
        "Jewelry & Watches": {
            "Watches, Parts & Accessories": {"281": "Jewelry & Watches"},
            "Fine Jewelry": {"4196": "Fine Jewelry"},
            "Vintage & Antique Jewelry": {"262024": "Vintage & Antique Jewelry"},
            "Fashion Jewelry": {"10968": "Fashion Jewelry"},
            "Ethnic, Regional & Tribal": {"262025": "Ethnic, Regional & Tribal"},
            "Men's Jewelry": {"10290": "Men's Jewelry"},
            "Engagement & Wedding": {"91427": "Engagement & Wedding"},
            "Jewelry Care, Design & Repair": {"164352": "Jewelry Care, Design & Repair"},
            "Jewelry Mixed Lots": {"262022": "Jewelry Mixed Lots"},
            "Handcrafted & Artisan Jewelry": {"110633": "Handcrafted & Artisan Jewelry"},
            "Loose Diamonds & Gemstones": {"491": "Loose Diamonds & Gemstones"},
            "Body Jewelry": {"261986": "Body Jewelry"},
            "Loose Beads": {"261997": "Loose Beads"},
            "Children's Jewelry": {"84605": "Children's Jewelry"},
            "Other Jewelry": {"262023": "Other Jewelry"}
        },
        "Baby Essentials": {
            "Baby": {"260018": "Baby"},
            "Feeding": {"20400": "Feeding"},
            "Diapering": {"45455": "Diapering"},
            "Strollers & Accessories": {"66698": "Strollers & Accessories"},
            "Nursery Bedding": {"20416": "Nursery Bedding"},
            "Toys for Baby": {"19068": "Toys for Baby"},
            "Baby Gear": {"100223": "Baby Gear"},
            "Carriers, Slings & Backpacks": {"100982": "Carriers, Slings & Backpacks"},
            "Car Safety Seats": {"66692": "Car Safety Seats"},
            "Baby Safety & Health": {"20433": "Baby Safety & Health"},
            "Nursery Furniture": {"20422": "Nursery Furniture"},
            "Nursery Décor": {"66697": "Nursery Décor"},
            "Bathing & Grooming": {"20394": "Bathing & Grooming"},
            "Children's Jewelry": {"84605": "Children's Jewelry"},
            "Potty Training": {"37631": "Potty Training"},
            "Keepsakes & Baby Announcements": {"117388": "Keepsakes & Baby Announcements"},
            "Other Baby": {"1261": "Other Baby"},
            "Wholesale Lots": {"56080": "Wholesale Lots"}
        },
        "Pet Supplies": {
            "Dog Supplies": {"20737": "Dog Supplies"},
            "Fish & Aquariums": {"20754": "Fish & Aquarium"},
            "Cat Supplies": {"20738": "Cat Supplies"},
            "Small Animal Supplies": {"3756": "Small Animal Supplies"},
            "Bird Supplies": {"20748": "Bird Supplies"},
            "Reptile Supplies": {"157692": "Reptile & Amphibian Supplies"},
            "Backyard Poultry Supplies": {"177801": "Backyard Poultry Supplies"},
            "Pet Memorials & Urns": {"116391": "Pet Memorials & Urns"},
            "Trackers": {"259319": "Trackers"},
            "Cameras": {"259068": "Cameras"},
            "Wholesale Lots": {"56080": "Wholesale Lots"},
            "Other Pet Supplies": {"301": "Other Pet Supplies"}
        },
        "Tickets & Travel": {
            "Travel": {"3252": "Travel"},
            "Tickets & Experiences": {"1305": "Tickets & Experiences"}
        },
        "Everything Else": {
            "Personal Security": {"102535": "Personal Security"},
            "Metaphysical": {"19266": "Metaphysical"},
            "Religious Products & Supplies": {"102545": "Religious Products & Supplies"},
            "Funeral & Cemetery": {"88739": "Funeral & Cemetery"},
            "Genealogy": {"20925": "Genealogy"},
            "Information Products": {"102480": "Information Products"},
            "Career Development & Education": {"3143": "Career Development & Education"},
            "Personal Development": {"102329": "Personal Development"},
            "eBay Special Offers": {"177600": "eBay Special Offers"},
            "Weird Stuff": {"1466": "Weird Stuff"},
            "Every Other Thing": {"88433": "Every Other Thing"},
            "eBay User Tools": {"20924": "eBay User Tools"}
        },
        "Gift Cards & Coupons": {
            "Gift Cards": {"172009": "Gift Cards"},
            "Coupons": {"172010": "Coupons"},
            "Gift Certificates": {"31411": "Gift Certificates"},
            "Digital Gifts": {"176950": "Digital Gifts"},
            "eBay Gift Cards": {"172036": "eBay Gift Cards"}
        },
        "Real Estate": {
            "Land": {"15841": "Land"},
            "Timeshares for Sale": {"15897": "Timeshares for Sale"},
            "Manufactured Homes": {"94825": "Manufactured Homes"},
            "Residential": {"12605": "Residential"},
            "Commercial": {"15825": "Commercial"},
            "Other Real Estate": {"1607": "Other Real Estate"}
        },
        "Specialty Services": {
            "eBay Auction Services": {"50349": "eBay Auction Services"},
            "Web & Computer Services": {"47104": "Web & Computer Services"},
            "Other Specialty Services": {"317": "Other Specialty Services"},
            "Printing & Personalization": {"20943": "Printing & Personalization"},
            "Home Improvement Services": {"170048": "Home Improvement Services"},
            "Restoration & Repair": {"47119": "Restoration & Repair"},
            "Custom Clothing & Jewelry": {"50343": "Custom Clothing & Jewelry"},
            "Artistic Services": {"47126": "Artistic Services"},
            "Item Based Services": {"175814": "Item Based Services"},
            "Media Editing & Duplication": {"50355": "Media Editing & Duplication"},
            "Graphic & Logo Design": {"47131": "Graphic & Logo Design"}
        }
    }


@bp.post("/report/<string:item_id>")
@login_required
def report_item(item_id: str):
    """Report an inappropriate item (sponsor version - allows null DriverID)."""
    sponsor_id = require_sponsor()
    
    try:
        data = request.get_json()
        reason = data.get("reason", "")
        description = data.get("description", "")
        title = data.get("title", "")
        image = data.get("image", "")
        url = data.get("url", "")
        
        if not reason:
            return jsonify({"ok": False, "message": "Reason is required"}), 400
        
        # For sponsor reports, we need to create a report with a placeholder driver_id
        # Since DriverID is required, we'll use a special marker or find a way to make it work
        # Check if we can use a special system driver ID for sponsor reports
        # For now, let's check the database schema to see if DriverID can be nullable
        
        # Since DriverID is NOT NULL in the schema, we need a different approach
        # Option: Use a system/admin driver ID for sponsor-initiated reports
        # Or: Check if there's a way to make DriverID nullable for sponsor reports
        
        # For now, let's try to get any driver associated with this sponsor
        # If none exists, we'll need to handle this differently
        from ..models import DriverSponsor
        driver_sponsor = DriverSponsor.query.filter_by(SponsorID=sponsor_id).first()
        
        if not driver_sponsor:
            # No drivers associated with this sponsor - we can't create a report with the current schema
            # Return an error or use a system driver ID
            current_app.logger.warning(f"Sponsor {sponsor_id} has no associated drivers - cannot create report with current schema")
            return jsonify({"ok": False, "message": "Cannot create report: no drivers associated with sponsor"}), 400
        
        driver_id = driver_sponsor.DriverID
        
        # Create report
        report = ProductReports(
            DriverID=driver_id,
            SponsorID=sponsor_id,
            ExternalItemID=item_id,
            ItemTitle=title[:500] if title else None,
            ItemImageURL=image[:1000] if image else None,
            ItemURL=url[:1000] if url else None,
            ReportReason=reason[:50],
            ReportDescription=description if description else None,
            Status='pending'
        )
        
        db.session.add(report)
        db.session.commit()
        
        current_app.logger.info(f"Report created by sponsor: {report.ID} for item {item_id} by sponsor {sponsor_id} (via driver {driver_id})")
        
        return jsonify({"ok": True, "message": "Report submitted successfully"})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating report: {e}", exc_info=True)
        return jsonify({"ok": False, "message": "Error submitting report"}), 500