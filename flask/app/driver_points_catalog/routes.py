# app/driver_points_catalog/routes.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

from flask import Blueprint, render_template, request, jsonify, abort, current_app, session
from flask_login import login_required, current_user
from sqlalchemy import text, bindparam
from app.extensions import db

# Your models
from ..models import (
    Account,
    AccountType,
    BlacklistedProduct,
    Driver,
    DriverFavorites,
    DriverSponsor,
    ProductReports,
    Sponsor,
    SponsorPinnedProduct,
)
from ..sponsor_catalog.providers.ebay_provider import EbayProvider
from .services.driver_query_service import (
    compose_effective_rules_for_driver,
    sponsor_enabled_driver_points,
    sponsor_enabled_filters_first,
)
from .services.points_service import price_to_points, get_points_converter, convert_prices_batch
from app.services.product_view_service import ProductViewService
from app.utils.cache import get_cache

bp = Blueprint(
    "driver_points_catalog",
    __name__,
    url_prefix="/driver-catalog",
    template_folder="templates",
    static_folder="static",
)

# ---------- helpers ----------

def _get_attr(obj: Any, *names: str) -> Any:
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def _first_nonempty(*vals):
    for v in vals:
        if v not in (None, "", []):
            return v
    return None


def _query_first_by(model, **candidates) -> Optional[Any]:
    for field, value in candidates.items():
        try:
            row = model.query.filter_by(**{field: value}).first()
            if row:
                return row
        except Exception:
            continue
    return None


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
            t = str(th).upper()
            if "OUT_OF_STOCK" in t or t == "ZERO":
                it.update({"no_stock": True, "stock_qty": 0})
            elif "MORE_THAN" in t:
                try:
                    num = int(t.split("_")[-1])
                    it["stock_qty"] = num + 1
                    it["available"] = num >= 10
                except Exception:
                    it["available"] = True
            elif t in ["LIMITED_QUANTITY", "LOW_STOCK"]:
                it.update({"low_stock": True, "stock_qty": threshold})
            else:
                it["available"] = True


def _inject_favorites_data(items: list[dict], driver_id: str) -> None:
    """Add is_favorite flags for current driver."""
    if not driver_id:
        return
    ids = [str(it.get("id")) for it in items if it.get("id")]
    if not ids:
        return
    favs = DriverFavorites.query.filter(
        DriverFavorites.DriverID == driver_id,
        DriverFavorites.ExternalItemID.in_(ids)
    ).all()
    fav_ids = {f.ExternalItemID for f in favs}
    for it in items:
        it["is_favorite"] = str(it.get("id")) in fav_ids


def _load_favorite_items(
    sponsor_id: str,
    driver_id: str,
    sort: str,
    search: Optional[str],
    categories: Optional[list[str]],
    min_pts: Optional[float],
    max_pts: Optional[float],
) -> list[dict]:
    """Fetch driver's favorite items with fresh catalog data."""
    favorites = (
        DriverFavorites.query.filter_by(DriverID=driver_id)
        .order_by(DriverFavorites.CreatedAt.desc())
        .all()
    )
    if not favorites:
        return []

    provider = EbayProvider()
    # OPTIMIZATION #6: Use cached converter function instead of calling price_to_points directly
    points_converter = get_points_converter(sponsor_id)
    
    # Get blacklisted items
    bl_ids = _get_blacklisted_ids(sponsor_id)
    
    items: list[dict] = []
    search_lower = search.lower() if search else None

    for fav in favorites:
        item_id = str(fav.ExternalItemID)
        
        # Skip blacklisted items
        if item_id in bl_ids:
            current_app.logger.debug(f"Skipping blacklisted favorite item {item_id}")
            continue
        
        data: dict[str, Any] | None = None
        try:
            data = provider.get_item_details(item_id)
        except Exception as exc:
            current_app.logger.warning(f"favorite detail load failed {item_id}: {exc}")

        if not data:
            data = {
                "id": item_id,
                "title": fav.ItemTitle,
                "image": fav.ItemImageURL,
                "points": fav.ItemPoints,
            }
        else:
            data["id"] = str(data.get("id") or item_id)
            data["title"] = data.get("title") or fav.ItemTitle or f"Item {item_id}"
            data["image"] = data.get("image") or fav.ItemImageURL

            price = data.get("price")
            points = None
            if price is not None:
                try:
                    # OPTIMIZATION #6: Use cached converter instead of price_to_points
                    points = points_converter(float(price))
                except Exception as exc:
                    current_app.logger.warning(f"favorite price convert fail {item_id}: {exc}")
            if points is None:
                points = fav.ItemPoints
            data["points"] = points

            data.pop("price", None)
            data.pop("currency", None)

        data["is_favorite"] = True
        if fav.CreatedAt:
            data["_favorite_ts"] = fav.CreatedAt.timestamp()
            data["favorite_added_at"] = fav.CreatedAt.isoformat()
        else:
            data["_favorite_ts"] = 0.0

        items.append(data)

    # Apply initial low stock annotations before filtering/sorting
    try:
        _inject_low_stock_flags(items)
    except Exception as exc:
        current_app.logger.warning(f"favorite low stock inject failed: {exc}")

    # Text search filter
    if search_lower:
        items = [
            it
            for it in items
            if search_lower in (it.get("title") or "").lower()
        ]

    # Category filter (best effort)
    if categories:
        cat_set = {str(c) for c in categories if str(c).strip()}
        if cat_set:
            filtered = []
            for it in items:
                candidates = [
                    it.get("primary_category_id"),
                    it.get("category_id"),
                    it.get("categoryId"),
                ]
                extra = it.get("category_ids") or it.get("categories")
                if isinstance(extra, (list, tuple, set)):
                    candidates.extend(extra)
                if any(str(cid) in cat_set for cid in candidates if cid):
                    filtered.append(it)
            items = filtered

    # Points range filtering
    if min_pts is not None or max_pts is not None:
        filtered = []
        for it in items:
            pts = it.get("points")
            if pts is None:
                continue
            try:
                pts_val = float(pts)
            except Exception:
                continue
            if min_pts is not None and pts_val < min_pts:
                continue
            if max_pts is not None and pts_val > max_pts:
                continue
            filtered.append(it)
        items = filtered

    # Sorting
    def _points_key(it: dict) -> tuple:
        pts = it.get("points")
        try:
            pts_val = float(pts) if pts is not None else None
        except Exception:
            pts_val = None
        return (pts_val is None, pts_val or 0.0)

    def _stock_key(it: dict) -> tuple:
        qty = it.get("stock_qty")
        try:
            qty_val = float(qty) if qty is not None else None
        except Exception:
            qty_val = None
        return (qty_val is None, qty_val or 0.0)

    if sort == "points_asc":
        items.sort(key=_points_key)
    elif sort == "points_desc":
        items.sort(key=_points_key, reverse=True)
    elif sort == "stock_asc":
        items.sort(key=_stock_key)
    elif sort == "stock_desc":
        items.sort(key=_stock_key, reverse=True)
    else:
        # best_match, newest, or any other sorts default to newest favorite first
        items.sort(key=lambda it: it.get("_favorite_ts", 0.0), reverse=True)

    for it in items:
        it.pop("_favorite_ts", None)

    return items


def _get_category_name(category_id: str) -> str:
    """Get category name from category ID."""
    import os
    import json
    
    json_path = __import__("app.utils.ebay_categories_path", fromlist=["get_ebay_categories_path"]).get_ebay_categories_path()
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                tree_data = json.load(f)
            
            # Extract category ID to name mapping
            def extract_categories(node, cat_map):
                cat = node.get("category", {})
                cat_id = cat.get("categoryId")
                cat_name = cat.get("categoryName", "")
                if cat_id and cat_id != "0":
                    cat_map[str(cat_id)] = cat_name
                
                for child in node.get("childCategoryTreeNodes", []):
                    extract_categories(child, cat_map)
            
            category_map = {}
            root = tree_data.get("rootCategoryNode", {})
            extract_categories(root, category_map)
            
            if category_map.get(str(category_id)):
                return category_map[str(category_id)]
        except Exception as e:
            current_app.logger.warning(f"Error loading category name: {e}")
    
    # Fallback: return generic name
    return f"Category {category_id}"


def _get_blacklisted_ids(sponsor_id: str) -> set:
    """
    Get blacklisted item IDs for a sponsor with caching.
    OPTIMIZATION #4: Cache blacklisted items for 5 minutes since they don't change frequently.
    
    Args:
        sponsor_id: The sponsor ID
        
    Returns:
        Set of blacklisted item IDs as strings
    """
    cache = get_cache()
    cache_key = f"blacklist:sponsor:{sponsor_id}"
    
    # Try cache first
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        return cached_ids
    
    # Cache miss - query database
    bl_products = BlacklistedProduct.query.filter_by(SponsorID=sponsor_id).all()
    bl_ids = {str(b.ItemID) for b in bl_products}
    
    current_app.logger.debug(
        f"[BLACKLIST] Loaded {len(bl_ids)} blacklisted items for sponsor {sponsor_id}: {sorted(list(bl_ids))[:10]}"
    )
    
    # Cache for 5 minutes (300 seconds)
    cache.set(cache_key, bl_ids, 300)
    
    return bl_ids


def _fetch_pinned_products(sponsor_id: str, provider: EbayProvider, bl_ids: Optional[set] = None) -> list[dict]:
    """
    Fetch pinned items with live data; skip blacklisted ones.
    OPTIMIZATION #5: Uses parallel API calls to fetch multiple items concurrently.
    
    Args:
        sponsor_id: The sponsor ID
        provider: EbayProvider instance
        bl_ids: Optional pre-fetched set of blacklisted item IDs. If None, will query database.
    
    Returns:
        List of pinned product dictionaries, ordered by PinRank
    """
    import concurrent.futures
    from sqlalchemy import case
    
    # OPTIMIZATION #2 & #4: Use provided blacklist IDs or get from cache
    if bl_ids is None:
        bl_ids = _get_blacklisted_ids(sponsor_id)
    
    pins = (
        SponsorPinnedProduct.query.filter_by(SponsorID=sponsor_id)
        .order_by(
            case((SponsorPinnedProduct.PinRank.is_(None), 1), else_=0),
            SponsorPinnedProduct.PinRank.asc(),
            SponsorPinnedProduct.CreatedAt.desc()
        ).all()
    )
    
    # Filter out blacklisted items upfront and prepare pin metadata
    valid_pins = []
    pin_metadata = {}  # Map item_id -> pin metadata (rank, title, image)
    for p in pins:
        iid = getattr(p, "ItemID", None)
        if not iid or str(iid) in bl_ids:
            continue
        valid_pins.append(iid)
        pin_metadata[str(iid)] = {
            "pin_rank": getattr(p, "PinRank", None),
            "item_title": getattr(p, "ItemTitle", "") or f"Item {iid}",
            "item_image": getattr(p, "ItemImageURL", ""),
        }
    
    if not valid_pins:
        return []
    
    # OPTIMIZATION #5: Fetch items in parallel (limit to 5 concurrent requests to avoid rate limits)
    def fetch_item(item_id: str) -> Optional[dict]:
        """Fetch a single item and add pin metadata."""
        try:
            d = provider.get_item(item_id)
            if d:
                meta = pin_metadata.get(str(item_id), {})
                d.update({
                    "is_pinned": True,
                    "pin_rank": meta.get("pin_rank"),
                })
                return d
        except Exception as e:
            current_app.logger.warning(f"fetch pinned fail {item_id}: {e}")
            # Return fallback data
            meta = pin_metadata.get(str(item_id), {})
            return {
                "id": item_id,
                "title": meta.get("item_title", f"Item {item_id}"),
                "image": meta.get("item_image", ""),
                "is_pinned": True,
                "pin_rank": meta.get("pin_rank"),
                "price": None,
            }
        return None
    
    pinned = []
    # Use ThreadPoolExecutor for parallel fetching
    # Limit to 5 workers to avoid overwhelming eBay API or hitting rate limits
    max_workers = min(5, len(valid_pins))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all fetch tasks
        future_to_item = {executor.submit(fetch_item, item_id): item_id for item_id in valid_pins}
        
        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_item):
            item_id = future_to_item[future]
            try:
                result = future.result()
                if result:
                    pinned.append(result)
            except Exception as e:
                current_app.logger.error(f"Error fetching pinned item {item_id}: {e}")
                # Add fallback entry
                meta = pin_metadata.get(str(item_id), {})
                pinned.append({
                    "id": item_id,
                    "title": meta.get("item_title", f"Item {item_id}"),
                    "image": meta.get("item_image", ""),
                    "is_pinned": True,
                    "pin_rank": meta.get("pin_rank"),
                    "price": None,
                })
    
    # Sort by pin_rank to maintain order (matching SQL: NULL first, then ascending)
    # SQL orders by: case(NULL, 1), PinRank.asc(), CreatedAt.desc()
    # We preserve the order from the database query, so we just need to sort by pin_rank
    # NULL values should come first (as in SQL), then ascending
    pinned.sort(key=lambda x: (
        x.get("pin_rank") is not None,  # False (None) comes before True (has rank)
        x.get("pin_rank") if x.get("pin_rank") is not None else 0  # Then by rank ascending
    ))
    
    return pinned


# ---------- account / role ----------

def _current_account_id() -> Optional[str]:
    return _first_nonempty(
        _get_attr(current_user, "AccountID"),
        _get_attr(current_user, "account_id"),
        _get_attr(current_user, "ID"),
        _get_attr(current_user, "id"),
        current_user.get_id() if hasattr(current_user, "get_id") else None,
    )


def _is_driver() -> bool:
    try:
        d = _first_nonempty(_get_attr(current_user, "account_type"), _get_attr(current_user, "AccountType"))
        if isinstance(d, str) and d.strip().upper() == "DRIVER":
            return True
        acct_id = _current_account_id()
        if not acct_id:
            return False
        acct = _query_first_by(Account, id=acct_id, ID=acct_id, account_id=acct_id, AccountID=acct_id)
        if not acct:
            return False
        account_type = _get_attr(acct, "AccountType") or ""
        return account_type.upper() == "DRIVER"
    except Exception as e:
        current_app.logger.warning(f"is_driver fail: {e}")
        return False


def _current_driver_id() -> Optional[str]:
    try:
        acct_id = _current_account_id()
        if not acct_id:
            return None
        drv = _query_first_by(Driver, AccountID=acct_id, account_id=acct_id, ID=acct_id)
        if not drv:
            return None
        return _first_nonempty(_get_attr(drv, "DriverID"), _get_attr(drv, "driver_id"))
    except Exception as e:
        current_app.logger.warning(f"driver id resolve fail: {e}")
        return None


def _resolve_selected_sponsor_id() -> Optional[str]:
    """
    Get the sponsor ID from the currently selected environment stored in session['driver_sponsor_id'].
    """
    try:
        env_id = session.get("driver_sponsor_id")
        if env_id:
            env = DriverSponsor.query.filter_by(DriverSponsorID=env_id).first()
            if env:
                return _first_nonempty(_get_attr(env, "SponsorID"), _get_attr(env, "sponsor_id"))
        return None
    except Exception as e:
        current_app.logger.warning(f"sponsor resolve fail: {e}")
        return None


def _require_driver_and_sponsor() -> str:
    if not getattr(current_user, "is_authenticated", False):
        abort(401)
    if not _is_driver():
        abort(403)
    sponsor_id = _resolve_selected_sponsor_id()
    if not sponsor_id:
        abort(403)
    if not sponsor_enabled_driver_points(sponsor_id) or not sponsor_enabled_filters_first(sponsor_id):
        abort(404)
    return sponsor_id


# ---------- routes ----------

@bp.get("/")
@login_required
def index():
    sponsor_id = _require_driver_and_sponsor()
    
    # Check if filter set is in "recommended products only" mode
    from .services.driver_query_service import _fetch_selected_set_for_sponsor
    sets = _fetch_selected_set_for_sponsor(sponsor_id)
    
    current_app.logger.info(f"[DRIVER_CATALOG] Index route - sponsor_id: {sponsor_id}")
    current_app.logger.info(f"[DRIVER_CATALOG] Found {len(sets)} filter set(s) for sponsor")
    
    recommended_only = False
    filter_set_info = []
    
    for fs in sets:
        if not fs:
            current_app.logger.warning("[DRIVER_CATALOG] Empty filter set in list")
            continue
        
        fs_id = getattr(fs, "ID", None) or getattr(fs, "id", None)
        fs_name = getattr(fs, "Name", None) or getattr(fs, "name", None)
        blob = getattr(fs, "RulesJSON", None) or getattr(fs, "rules_json", None) or {}
        special_mode = blob.get("special_mode")
        
        filter_set_info.append({
            "id": fs_id,
            "name": fs_name,
            "special_mode": special_mode,
            "rules_keys": list(blob.keys())
        })
        
        current_app.logger.info(f"[DRIVER_CATALOG] Filter set: ID={fs_id}, Name={fs_name}, special_mode={special_mode}")
        current_app.logger.debug(f"[DRIVER_CATALOG] Filter set rules keys: {list(blob.keys())}")
        
        if special_mode == "recommended_only" or special_mode == "pinned_only":
            recommended_only = True
            current_app.logger.info(f"[DRIVER_CATALOG] ✓ Detected recommended_only mode for filter set {fs_id}")
            break
    
    current_app.logger.info(f"[DRIVER_CATALOG] Recommended only mode: {recommended_only}")
    current_app.logger.info(f"[DRIVER_CATALOG] Filter sets summary: {filter_set_info}")
    
    # Always show browse page with sidebar - no redirects
    selected_category = session.get("driver_selected_category")
    category_name = _get_category_name(selected_category) if selected_category else None
    
    # Check if recommended products exist
    has_recommended = False
    recommended_count = 0
    try:
        provider = EbayProvider()
        bl_ids = _get_blacklisted_ids(sponsor_id)
        recommended = _fetch_pinned_products(sponsor_id, provider, bl_ids=bl_ids)
        recommended_count = len(recommended)
        has_recommended = recommended_count > 0
        current_app.logger.info(f"[DRIVER_CATALOG] Found {recommended_count} recommended products")
    except Exception as e:
        current_app.logger.error(f"[DRIVER_CATALOG] Error checking recommended products: {e}", exc_info=True)
    
    # Check if categories are available (not in recommended_only mode)
    has_categories = not recommended_only
    if has_categories:
        # Check if there are actually categories in the filter set
        from ..sponsor_catalog.services.category_service import resolve as resolve_categories
        allowed_category_ids = set()
        for fs in sets:
            rules = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config") or {}
            cats = ((rules.get("categories") or {}).get("include") or [])
            if cats:
                resolved = set(resolve_categories(cats))
                allowed_category_ids = resolved if not allowed_category_ids else (allowed_category_ids & resolved)
        has_categories = len(allowed_category_ids) > 0
    
    # Show browse page (sidebar will handle recommended products and category selection)
    current_app.logger.info(f"[DRIVER_CATALOG] Showing browse page")
    return render_template("driver_points_catalog/browse.html", 
                          selected_category_id=selected_category, 
                          selected_category_name=category_name,
                          recommended_only_mode=recommended_only,
                          has_recommended=has_recommended,
                          recommended_count=recommended_count,
                          has_categories=has_categories)


@bp.get("/browse")
@login_required
def browse():
    sponsor_id = _require_driver_and_sponsor()
    
    # Check if filter set is in "recommended products only" mode
    from .services.driver_query_service import _fetch_selected_set_for_sponsor
    sets = _fetch_selected_set_for_sponsor(sponsor_id)
    
    current_app.logger.info(f"[DRIVER_CATALOG] Browse route - sponsor_id: {sponsor_id}")
    
    recommended_only = False
    for fs in sets:
        if not fs:
            continue
        blob = getattr(fs, "RulesJSON", None) or getattr(fs, "rules_json", None) or {}
        special_mode = blob.get("special_mode")
        current_app.logger.info(f"[DRIVER_CATALOG] Browse - Filter set special_mode: {special_mode}")
        if special_mode == "recommended_only" or special_mode == "pinned_only":
            recommended_only = True
            current_app.logger.info("[DRIVER_CATALOG] Browse - Redirecting to recommended products (recommended_only mode)")
            break
    
    # Always show browse page with sidebar
    selected_category = session.get("driver_selected_category")
    category_name = _get_category_name(selected_category) if selected_category else None
    
    # Check if recommended products exist
    has_recommended = False
    recommended_count = 0
    try:
        provider = EbayProvider()
        bl_ids = _get_blacklisted_ids(sponsor_id)
        recommended = _fetch_pinned_products(sponsor_id, provider, bl_ids=bl_ids)
        recommended_count = len(recommended)
        has_recommended = recommended_count > 0
    except Exception as e:
        current_app.logger.error(f"[DRIVER_CATALOG] Error checking recommended products: {e}", exc_info=True)
    
    # Check if categories are available (not in recommended_only mode)
    has_categories = not recommended_only
    if has_categories:
        # Check if there are actually categories in the filter set
        from ..sponsor_catalog.services.category_service import resolve as resolve_categories
        allowed_category_ids = set()
        for fs in sets:
            rules = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config") or {}
            cats = ((rules.get("categories") or {}).get("include") or [])
            if cats:
                resolved = set(resolve_categories(cats))
                allowed_category_ids = resolved if not allowed_category_ids else (allowed_category_ids & resolved)
        has_categories = len(allowed_category_ids) > 0
    
    return render_template("driver_points_catalog/browse.html", 
                          selected_category_id=selected_category, 
                          selected_category_name=category_name,
                          recommended_only_mode=recommended_only,
                          has_recommended=has_recommended,
                          recommended_count=recommended_count,
                          has_categories=has_categories)


@bp.get("/recommended")
@login_required
def recommended_products():
    """Display recommended products for drivers. (Redirects to browse page with sidebar)"""
    from flask import redirect, url_for
    return redirect(url_for("driver_points_catalog.index"))


@bp.get("/recommended-data")
@login_required
def recommended_data():
    """API endpoint to get recommended products as JSON."""
    sponsor_id = _require_driver_and_sponsor()
    driver_id = _current_driver_id()
    
    try:
        def _parse_num(s):
            try:
                return float(s.strip()) if s and s.strip() else None
            except Exception:
                return None

        min_pts = _parse_num(request.args.get("min_points"))
        max_pts = _parse_num(request.args.get("max_points"))
        
        provider = EbayProvider()
        
        # OPTIMIZATION #2 & #4: Get blacklisted items from cache (5min TTL)
        bl_ids = _get_blacklisted_ids(sponsor_id)
        
        # OPTIMIZATION #1: Load points converter once per request (cached)
        points_converter = get_points_converter(sponsor_id)
        
        # Fetch recommended products
        recommended = _fetch_pinned_products(sponsor_id, provider, bl_ids=bl_ids)
        
        current_app.logger.info(f"[DRIVER_CATALOG] Found {len(recommended)} recommended products")
        
        # OPTIMIZATION #1: Batch convert prices to points
        convert_prices_batch(recommended, points_converter)
        
        # Apply point range filter
        if min_pts is not None or max_pts is not None:
            filtered = []
            for it in recommended:
                pts = it.get("points")
                if pts is None:
                    continue
                try:
                    pts_val = float(pts)
                except Exception:
                    continue
                if min_pts is not None and pts_val < min_pts:
                    continue
                if max_pts is not None and pts_val > max_pts:
                    continue
                filtered.append(it)
            recommended = filtered
        
        # Apply low stock flags
        _inject_low_stock_flags(recommended)
        
        # Inject favorites data
        _inject_favorites_data(recommended, driver_id)
        
        return jsonify({
            "items": recommended,
            "page": 1,
            "page_size": len(recommended),
            "total": len(recommended),
            "has_more": False
        })
    except Exception as e:
        current_app.logger.error(f"[DRIVER_CATALOG] Error loading recommended products: {e}", exc_info=True)
        return jsonify({"items": [], "page": 1, "page_size": 0, "total": 0, "has_more": False})


@bp.get("/favorites")
@login_required
def favorites_page():
    _require_driver_and_sponsor()
    return render_template("driver_points_catalog/favorites.html")


def _extract_parent_category_ids(allowed_category_ids):
    """Extract parent category IDs for categories that have allowed children."""
    import os
    import json
    
    json_path = __import__("app.utils.ebay_categories_path", fromlist=["get_ebay_categories_path"]).get_ebay_categories_path()
    
    parent_map = {}  # Maps parent category name to parent category ID
    
    if not os.path.exists(json_path):
        return parent_map
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            tree_data = json.load(f)
        
        def traverse_tree(node, parent_id=None, parent_name=None):
            """Traverse the eBay category tree and find parent IDs for categories with allowed children."""
            cat = node.get("category", {})
            cat_id = cat.get("categoryId", "")
            cat_name = cat.get("categoryName", "")
            children = node.get("childCategoryTreeNodes", [])
            
            if cat_id and cat_id != "0":
                # Check if any child is in the allowed list
                has_allowed_child = False
                for child in children:
                    child_cat = child.get("category", {})
                    child_id = child_cat.get("categoryId", "")
                    if str(child_id) in allowed_category_ids:
                        has_allowed_child = True
                        break
                    # Also check deeper children
                    if child.get("childCategoryTreeNodes"):
                        if _has_allowed_descendant(child, allowed_category_ids):
                            has_allowed_child = True
                            break
                
                # If this category has allowed children, store it as a selectable parent
                if has_allowed_child and str(cat_id) not in allowed_category_ids:
                    # This is a parent category that can be selected
                    parent_map[cat_name] = str(cat_id)
                
                # Recurse into children
                for child in children:
                    traverse_tree(child, cat_id, cat_name)
        
        def _has_allowed_descendant(node, allowed_ids):
            """Check if any descendant of this node is in the allowed list."""
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


@bp.get("/categories")
@login_required
def get_categories():
    """Get available categories from sponsor's selected filter set."""
    try:
        sponsor_id = _require_driver_and_sponsor()
        
        from .services.driver_query_service import _fetch_selected_set_for_sponsor
        from ..sponsor_catalog.services.category_service import resolve as resolve_categories
        
        # Get selected filter set
        sets = _fetch_selected_set_for_sponsor(sponsor_id)
        
        current_app.logger.debug(f"Driver categories request for sponsor {sponsor_id}: found {len(sets)} filter set(s)")
        
        if not sets:
            current_app.logger.warning(f"No filter sets found for sponsor {sponsor_id}")
            return jsonify({"categories": []})
        
        # Check if this is the "__no_filter__" filter set (allows all categories)
        if sets and len(sets) == 1:
            fs = sets[0]
            filter_set_id = _get_attr(fs, "ID", "id")
            if str(filter_set_id) == "__no_filter__":
                current_app.logger.info(f"[CATEGORIES] No filter set selected - returning all categories")
                # Return all available categories
                from ..sponsor_catalog.ebay_categories import get_all_categories
                all_cats = get_all_categories()
                # Filter out adult categories
                from ..sponsor_catalog.policies import ADULT_CATEGORY_IDS
                adult_ids_set = {str(cid) for cid in ADULT_CATEGORY_IDS}
                filtered_cats = [cat for cat in all_cats if cat["id"] not in adult_ids_set]
                
                # Build parent categories mapping
                parent_categories = {}
                for cat in filtered_cats:
                    if cat.get("parent"):
                        parent_name = cat["parent"]
                        if parent_name not in parent_categories:
                            parent_categories[parent_name] = []
                        parent_categories[parent_name].append(cat)
                
                return jsonify({
                    "categories": filtered_cats,
                    "parent_categories": parent_categories
                })
        
        # Extract categories from filter set
        # Only show categories that are explicitly included in the selected filter set
        category_ids = set()
        for fs in sets:
            filter_set_id = _get_attr(fs, "ID", "id")
            from .services.driver_query_service import _load_json_maybe
            rules_raw = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config")
            rules = _load_json_maybe(rules_raw) if rules_raw else {}
            
            # Debug: Log filter set info
            current_app.logger.debug(f"Processing filter set {filter_set_id} for sponsor {sponsor_id}")
            current_app.logger.debug(f"Rules type: {type(rules)}, Rules keys: {list(rules.keys()) if isinstance(rules, dict) else 'N/A'}")
            
            cats = ((rules.get("categories") or {}).get("include") or [])
            current_app.logger.debug(f"Found {len(cats)} categories in filter set {filter_set_id}")
            
            if cats:
                # Resolve any pseudo-categories to actual category IDs
                resolved = set(resolve_categories(cats))
                # If this is the first filter set, use its categories
                # Otherwise, intersect with existing categories (only show categories in ALL sets)
                if not category_ids:
                    category_ids = resolved
                else:
                    category_ids = category_ids & resolved
        
        # If no categories are defined in the filter set, return empty list
        # Drivers should only see categories explicitly selected by the sponsor
        if not category_ids:
            return jsonify({"categories": []})
        
        # Load category ID to name mapping
        import os
        import json
        json_path = __import__("app.utils.ebay_categories_path", fromlist=["get_ebay_categories_path"]).get_ebay_categories_path()
        
        category_map = {}
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    tree_data = json.load(f)
                
                # Extract category ID to name mapping
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
        
        # Fallback category map (from test catalog)
        if not category_map:
            category_map = {
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
                "6030": "Car & Truck Parts",
                "10063": "Motorcycle Parts",
                "34998": "Automotive Tools & Supplies",
                "156955": "GPS & Security Devices",
                "10058": "Car Care & Detailing",
                "66471": "Tires & Wheels",
                "33615": "Performance & Racing Parts",
                "6028": "Exterior Parts & Accessories",
                "6029": "Interior Parts & Accessories",
                "31411": "Fragrances",
                "31786": "Makeup",
                "11854": "Skin Care",
                "6197": "Health Care",
                "180959": "Vitamins & Dietary Supplements",
                "11338": "Oral Care",
                "11855": "Shaving & Hair Removal",
                "182": "Medical Devices & Equipment",
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
        
        # Check if exclude_explicit is enabled in filter set
        exclude_explicit = False
        for fs in sets:
            rules_raw = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config")
            rules = _load_json_maybe(rules_raw) if rules_raw else {}
            if rules.get("safety", {}).get("exclude_explicit"):
                exclude_explicit = True
                break
        
        # Filter out adult categories if exclude_explicit is enabled
        if exclude_explicit:
            from ..sponsor_catalog.policies import ADULT_CATEGORY_IDS
            original_count = len(category_ids)
            adult_cats_found = category_ids & ADULT_CATEGORY_IDS
            category_ids = category_ids - ADULT_CATEGORY_IDS
            current_app.logger.info(
                f"[ADULT_FILTER] Driver categories - exclude_explicit=True: "
                f"Filtered out {len(adult_cats_found)} adult categories "
                f"({original_count} -> {len(category_ids)}). "
                f"Adult IDs removed: {sorted(adult_cats_found)}"
            )
        else:
            current_app.logger.debug(
                f"[ADULT_FILTER] Driver categories - exclude_explicit=False: "
                f"No filtering applied. Total categories: {len(category_ids)}"
            )
        
        # Extract parent category IDs for categories that have allowed children
        parent_category_map = _extract_parent_category_ids(category_ids)
        
        # Add parent categories to the allowed set (so drivers can select them)
        # But exclude parent categories that are adult categories if exclude_explicit is enabled
        skipped_parents = []
        for parent_name, parent_id in parent_category_map.items():
            if exclude_explicit and str(parent_id) in ADULT_CATEGORY_IDS:
                skipped_parents.append(f"{parent_name} ({parent_id})")
                continue  # Skip adult parent categories
            category_ids.add(parent_id)
            # Also add to category_map if not already there
            if str(parent_id) not in category_map:
                category_map[str(parent_id)] = parent_name
        
        if exclude_explicit and skipped_parents:
            current_app.logger.info(
                f"[ADULT_FILTER] Driver categories - Skipped {len(skipped_parents)} adult parent categories: {skipped_parents}"
            )
        
        # Build category list with IDs and names
        categories = []
        filtered_out_count = 0
        for cat_id in sorted(category_ids, key=lambda x: category_map.get(str(x), str(x))):
            # Double-check: skip adult categories even if they somehow got through
            if exclude_explicit and str(cat_id) in ADULT_CATEGORY_IDS:
                filtered_out_count += 1
                current_app.logger.warning(
                    f"[ADULT_FILTER] Driver categories - Double-check filter caught adult category: {cat_id} "
                    f"({category_map.get(str(cat_id), 'Unknown')})"
                )
                continue
            is_parent = str(cat_id) in parent_category_map.values()
            categories.append({
                "id": str(cat_id),
                "name": category_map.get(str(cat_id), f"Category {cat_id}"),
                "is_parent": is_parent
            })
        
        if exclude_explicit:
            current_app.logger.info(
                f"[ADULT_FILTER] Driver categories - Final result: {len(categories)} categories returned to driver "
                f"(filtered out {filtered_out_count} in final pass)"
            )
        
        return jsonify({
            "categories": categories,
            "parent_categories": {name: id for name, id in parent_category_map.items()}
        })
    except Exception as e:
        current_app.logger.error(f"Error loading categories: {e}", exc_info=True)
        return jsonify({"error": "Failed to load categories.", "categories": []}), 500


@bp.post("/select-category")
@login_required
def select_category():
    """Set the selected category in session. Validates that category is in sponsor's allowed list."""
    try:
        # Force JSON response for AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            # This is an AJAX request, ensure we return JSON
            pass
        
        # Category selection request
        
        # Check authentication first
        if not getattr(current_user, "is_authenticated", False):
            current_app.logger.warning("User not authenticated")
            return jsonify({"ok": False, "message": "Authentication required"}), 401
        
        # Check if user is a driver
        if not _is_driver():
            current_app.logger.warning(f"User {_current_account_id()} is not a driver")
            return jsonify({"ok": False, "message": "Access denied: Driver account required"}), 403
        
        # Get sponsor ID
        sponsor_id = _resolve_selected_sponsor_id()
        if not sponsor_id:
            current_app.logger.warning("No sponsor selected")
            return jsonify({"ok": False, "message": "No sponsor selected"}), 403
        
        # Check if driver points are enabled
        if not sponsor_enabled_driver_points(sponsor_id) or not sponsor_enabled_filters_first(sponsor_id):
            current_app.logger.warning(f"Driver points or filters not enabled for sponsor {sponsor_id}")
            return jsonify({"ok": False, "message": "Catalog not available for this sponsor"}), 404
        
        category_id = request.form.get("category_id") or (request.json.get("category_id") if request.is_json else None)
        
        if not category_id:
            current_app.logger.warning("No category_id provided in request")
            return jsonify({"ok": False, "message": "category_id required"}), 400
        
        category_id = str(category_id)
        
        # Verify the category is in the sponsor's allowed categories
        from .services.driver_query_service import _fetch_selected_set_for_sponsor
        from .services.driver_query_service import _load_json_maybe
        from ..sponsor_catalog.services.category_service import resolve as resolve_categories
        
        sets = _fetch_selected_set_for_sponsor(sponsor_id)
        
        if not sets:
            current_app.logger.warning(f"No filter sets found for sponsor {sponsor_id}")
            return jsonify({"ok": False, "message": "No filter set configured for this sponsor"}), 400
        
        # Extract allowed categories from filter set
        allowed_category_ids = set()
        for fs in sets:
            rules_raw = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config")
            rules = _load_json_maybe(rules_raw) if rules_raw else {}
            cats = ((rules.get("categories") or {}).get("include") or [])
            if cats:
                resolved = set(resolve_categories(cats))
                allowed_category_ids = resolved if not allowed_category_ids else (allowed_category_ids & resolved)
        
        # Validate that the selected category is in the allowed list
        if allowed_category_ids and category_id not in allowed_category_ids:
            current_app.logger.warning(f"Category {category_id} not in allowed categories")
            return jsonify({"ok": False, "message": f"This category is not available for your sponsor's catalog. Allowed: {len(allowed_category_ids)} categories"}), 403
        
        # If no categories are defined in filter set, don't allow selection
        if not allowed_category_ids:
            current_app.logger.warning(f"No categories configured in filter set for sponsor {sponsor_id}")
            return jsonify({"ok": False, "message": "No categories are configured for your sponsor's catalog"}), 400
        
        session["driver_selected_category"] = category_id
        
        # Ensure we return JSON with proper content type
        response = jsonify({"ok": True})
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        current_app.logger.error(f"Error setting category: {e}", exc_info=True)
        response = jsonify({"ok": False, "message": f"Failed to set category: {str(e)}"})
        response.headers['Content-Type'] = 'application/json'
        return response, 500


@bp.post("/set-category")
@login_required
def set_category():
    """Set the selected category in session."""
    try:
        if not getattr(current_user, "is_authenticated", False):
            return jsonify({"ok": False, "message": "Authentication required"}), 401
        
        data = request.json
        category_id = data.get("category_id")
        
        if not category_id:
            return jsonify({"ok": False, "message": "category_id required"}), 400
        
        session["driver_selected_category"] = str(category_id)
        
        return jsonify({"ok": True, "message": "Category set"})
    except Exception as e:
        current_app.logger.error(f"Error setting category: {e}", exc_info=True)
        return jsonify({"ok": False, "message": f"Failed to set category: {str(e)}"}), 500


@bp.post("/clear-category")
@login_required
def clear_category():
    """Clear the selected category from session."""
    
    try:
        # Don't use _require_driver_and_sponsor() here as it might abort with HTML
        # Just check authentication minimally
        if not getattr(current_user, "is_authenticated", False):
            current_app.logger.warning("User not authenticated for clear-category")
            response = jsonify({"ok": False, "message": "Authentication required"})
            response.headers['Content-Type'] = 'application/json'
            return response, 401
        
        # Clear the category from session
        session.pop("driver_selected_category", None)
        
        # Ensure we return JSON
        response = jsonify({"ok": True, "message": "Category cleared"})
        response.headers['Content-Type'] = 'application/json'
        current_app.logger.info("Returning JSON response")
        return response
    except Exception as e:
        current_app.logger.error(f"Error clearing category: {e}", exc_info=True)
        response = jsonify({"ok": False, "message": f"Failed to clear category: {str(e)}"})
        response.headers['Content-Type'] = 'application/json'
        return response, 500


@bp.get("/data")
@login_required
def data():
    try:
        sponsor_id = _require_driver_and_sponsor()
        
        # Get selected category or search_all mode from session
        selected_category = session.get("driver_selected_category")
        search_all_mode = session.get("driver_search_all", False)
        
        page = max(1, int(request.args.get("page", 1)))
        # Always use 24 items per page for consistent pagination
        page_size = max(1, min(100, int(request.args.get("page_size", 24))))
        sort = (request.args.get("sort") or "best_match").strip()
        q = (request.args.get("q") or "").strip() or None
        
        # If a search query is provided, allow searching all products (even without category)
        # This enables searching all eBay products from the recommended products page
        search_all_products = q and q.strip() != ""
        
        if not selected_category and not search_all_mode and not search_all_products:
            return jsonify({"error": "Please select a category or enter a search query.", "items": []}), 400
        
        # Get allowed categories from filter set
        from .services.driver_query_service import _fetch_selected_set_for_sponsor
        from ..sponsor_catalog.services.category_service import resolve as resolve_categories
        
        sets = _fetch_selected_set_for_sponsor(sponsor_id)
        allowed_category_ids = set()
        for fs in sets:
            rules = _get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config") or {}
            cats = ((rules.get("categories") or {}).get("include") or [])
            if cats:
                resolved = set(resolve_categories(cats))
                allowed_category_ids = resolved if not allowed_category_ids else (allowed_category_ids & resolved)
        
        # If searching all products, don't restrict by category
        if search_all_products:
            cats = None  # Search all categories
            current_app.logger.info(f"[DRIVER_CATALOG] Searching all products with query: {q}")
        else:
            # Validate that the selected category is in the allowed list
            if allowed_category_ids and str(selected_category) not in allowed_category_ids:
                # Category not in allowed list - clear it and return error
                session.pop("driver_selected_category", None)
                return jsonify({"error": "Selected category is not available. Please select a different category.", "items": []}), 400
            cats = [selected_category] if selected_category else None
        
        # DEBUG: Log pagination parameters
        current_app.logger.info(f"[PAGINATION DEBUG] Request received - page={page}, page_size={page_size}, sort={sort}, q={q or '(none)'}")
        current_app.logger.info(f"[PAGINATION DEBUG] Request args: {dict(request.args)}")
        
        # OPTIMIZATION #3: Default to fast mode (skip expensive total count calculation)
        # Only use strict_total when explicitly requested (for accurate totals)
        # fast=1 forces fast mode, strict_total=1 forces strict mode, default is fast
        fast_mode_requested = request.args.get("fast", "").strip() == "1"
        strict_total_requested = request.args.get("strict_total", "").strip() == "1"
        # Default to fast mode unless strict_total is explicitly requested
        strict_total = strict_total_requested if strict_total_requested else False
        # But fast mode can override strict_total
        if fast_mode_requested:
            strict_total = False

        def _parse_num(s):
            try:
                return float(s.strip()) if s and s.strip() else None
            except Exception:
                return None

        min_pts = _parse_num(request.args.get("min_points"))
        max_pts = _parse_num(request.args.get("max_points"))
        
        # DEBUG: Log point filter parameters
        current_app.logger.info(f"[POINT_FILTER DEBUG] Point filter parameters: min_pts={min_pts}, max_pts={max_pts}")

        # If searching all products (q provided), override recommended_only mode
        # This allows searching all eBay products from the recommended products page
        if search_all_products:
            # When searching, don't use recommended_only mode - search all products instead
            rules = compose_effective_rules_for_driver(sponsor_id, driver_q=q, driver_cats=None)
            recommended_only = False
            current_app.logger.info(f"[DRIVER_CATALOG] Data route - Searching all products with query: {q}")
        else:
            rules = compose_effective_rules_for_driver(sponsor_id, driver_q=q, driver_cats=cats)
            # Support both old "pinned_only" and new "recommended_only" for backward compatibility
            recommended_only = rules.get("special_mode") == "recommended_only" or rules.get("special_mode") == "pinned_only"
            current_app.logger.info(f"[DRIVER_CATALOG] Data route - recommended_only: {recommended_only}")
        
        # Debug: Log the rules being used for search
        current_app.logger.info(f"[DRIVER_CATALOG] Data route - Driver search rules for sponsor {sponsor_id}")
        current_app.logger.info(f"[DRIVER_CATALOG] Data route - Rules special_mode: {rules.get('special_mode')}")
        current_app.logger.info(f"[DRIVER_CATALOG] Data route - Rules keys: {list(rules.keys())}")
        current_app.logger.debug(f"[DRIVER_CATALOG] Data route - Full rules: {rules}")
        
        provider = EbayProvider()
        
        # OPTIMIZATION #2 & #4: Get blacklisted items from cache (5min TTL)
        bl_ids = _get_blacklisted_ids(sponsor_id)
        
        # OPTIMIZATION #1: Load points converter once per request (cached)
        points_converter = get_points_converter(sponsor_id)
        
        # OPTIMIZATION #2: Pass blacklist IDs to avoid duplicate query
        pinned = _fetch_pinned_products(sponsor_id, provider, bl_ids=bl_ids)
        
        # OPTIMIZATION #2: No need to filter again - _fetch_pinned_products already filters blacklisted items
        valid_pinned = pinned
        
        # OPTIMIZATION #1: Batch convert prices to points
        convert_prices_batch(valid_pinned, points_converter)
        pinned_ids = {str(it.get("id")) for it in valid_pinned}

        if recommended_only:
            # Apply point range filtering to recommended products
            if min_pts is not None or max_pts is not None:
                current_app.logger.info(f"[POINT_FILTER DEBUG] Filtering recommended products: min_pts={min_pts}, max_pts={max_pts}")
                current_app.logger.info(f"[POINT_FILTER DEBUG] Before filtering: {len(valid_pinned)} recommended items")
                filtered_pinned = []
                filtered_out_count = 0
                for it in valid_pinned:
                    pts = it.get("points")
                    if pts is None:
                        filtered_out_count += 1
                        current_app.logger.debug(f"[POINT_FILTER DEBUG] Filtered out recommended item {it.get('id')}: no points")
                        continue
                    try:
                        pts_val = float(pts)
                    except (ValueError, TypeError):
                        filtered_out_count += 1
                        current_app.logger.debug(f"[POINT_FILTER DEBUG] Filtered out recommended item {it.get('id')}: invalid points value")
                        continue
                    if min_pts is not None and pts_val < min_pts:
                        filtered_out_count += 1
                        current_app.logger.debug(f"[POINT_FILTER DEBUG] Filtered out recommended item {it.get('id')}: {pts_val} < {min_pts}")
                        continue
                    if max_pts is not None and pts_val > max_pts:
                        filtered_out_count += 1
                        current_app.logger.debug(f"[POINT_FILTER DEBUG] Filtered out recommended item {it.get('id')}: {pts_val} > {max_pts}")
                        continue
                    filtered_pinned.append(it)
                combined = filtered_pinned
                current_app.logger.info(f"[POINT_FILTER DEBUG] After filtering recommended: {len(combined)} items (filtered out {filtered_out_count})")
            else:
                combined = valid_pinned
            has_more = False  # Recommended items are finite
        else:
            # Use deterministic pagination: always accumulate enough items for the requested page
            # Fetch larger pages and accumulate until we have enough items for the requested page
            # Use a larger multiplier to account for filtering (blacklist, pinned, no prices)
            api_page_size = min(250, max(72, page_size * 3))  # Fetch at least 72 items per eBay page
            items_accumulated = []
            
            # Calculate how many items we need: requested page * page_size
            # Add buffer to account for filtering
            target_item_count = page * page_size
            # Fetch extra pages to ensure we have enough after filtering
            # Estimate: if 30% get filtered, we need ~1.5x more items
            fetch_target = int(target_item_count * 1.5) + (page_size * 2)  # Extra buffer
            
            current_ebay_page = 1
            max_pages_to_fetch = 30  # Increased limit for higher pages
            
            current_app.logger.info(f"[PAGINATION DEBUG] Requesting page {page}, need at least {target_item_count} items after filtering (fetching up to {fetch_target})")
            
            # Fetch pages until we have enough items
            pages_fetched = 0
            has_more_from_ebay = True
            
            while len(items_accumulated) < fetch_target and pages_fetched < max_pages_to_fetch and has_more_from_ebay:
                current_app.logger.info(f"[PAGINATION DEBUG] Fetching eBay page {current_ebay_page} (api_page_size={api_page_size}), accumulated {len(items_accumulated)}/{fetch_target} items")
                
                res = provider.search_extended(
                    rules, page=current_ebay_page, page_size=api_page_size,
                    sort=sort, strict_total=strict_total)
                items = res.get("items", []) or []
                has_more_from_ebay = res.get("has_more", False)
                
                if not items:
                    current_app.logger.info(f"[PAGINATION DEBUG] No items returned from eBay page {current_ebay_page}")
                    break
                
                current_app.logger.info(f"[PAGINATION DEBUG] eBay page {current_ebay_page} returned {len(items)} items")
                
                # Filter items (blacklist, pinned, no prices)
                valid = []
                seen_ids = set()  # Track seen IDs to avoid duplicates
                for it in items:
                    iid = str(it.get("id") or "")
                    # Skip duplicates
                    if iid in seen_ids:
                        continue
                    seen_ids.add(iid)
                    # Skip blacklisted items
                    if iid and iid in bl_ids:
                        continue
                    # Skip recommended/pinned items
                    if iid in pinned_ids:
                        continue
                    # Skip items without prices
                    if it.get('price') is None:
                        continue
                    valid.append(it)
                
                current_app.logger.info(f"[PAGINATION DEBUG] After filtering: {len(valid)} valid items from page {current_ebay_page}")
                
                # Add to accumulated list
                items_accumulated.extend(valid)
                pages_fetched += 1
                current_ebay_page += 1
                
                # If we have enough items, we can stop early
                if len(items_accumulated) >= fetch_target:
                    break
            
            current_app.logger.info(f"[PAGINATION DEBUG] Accumulated {len(items_accumulated)} items from {pages_fetched} eBay pages")
            
            # Remove duplicates by ID (in case eBay returns duplicates across pages)
            seen_final = {}
            deduplicated = []
            for it in items_accumulated:
                iid = str(it.get("id") or "")
                if iid and iid not in seen_final:
                    seen_final[iid] = True
                    deduplicated.append(it)
            items_accumulated = deduplicated
            
            current_app.logger.info(f"[PAGINATION DEBUG] After deduplication: {len(items_accumulated)} unique items")
            
            # Apply price-based sorting AFTER accumulation (for consistent sorting across all items)
            # Map points sorting to price sorting (points are derived from prices)
            actual_sort = sort
            if sort == "points_asc":
                actual_sort = "price_asc"
            elif sort == "points_desc":
                actual_sort = "price_desc"
            
            if actual_sort == "price_asc":
                items_accumulated.sort(key=lambda x: (float(x.get("price", 0) or 0), str(x.get("id", ""))))
                current_app.logger.info(f"[PAGINATION DEBUG] Sorted {len(items_accumulated)} items by price (ascending)")
            elif actual_sort == "price_desc":
                items_accumulated.sort(key=lambda x: (float(x.get("price", 0) or 0), str(x.get("id", ""))), reverse=True)
                current_app.logger.info(f"[PAGINATION DEBUG] Sorted {len(items_accumulated)} items by price (descending)")
            elif actual_sort == "best_match":
                # For best_match, maintain eBay's order but ensure deterministic by sorting by ID as tiebreaker
                items_accumulated.sort(key=lambda x: str(x.get("id", "")))
            
            # OPTIMIZATION #1: Batch convert prices to points
            convert_prices_batch(items_accumulated, points_converter)
            
            # DEBUG: Log items before point filtering
            if min_pts is not None or max_pts is not None:
                current_app.logger.info(f"[POINT_FILTER DEBUG] Before point filtering: {len(items_accumulated)} items")
                sample_before = items_accumulated[:5] if items_accumulated else []
                for idx, item in enumerate(sample_before):
                    current_app.logger.info(f"[POINT_FILTER DEBUG] Sample item {idx+1}: id={item.get('id')}, price={item.get('price')}, points={item.get('points')}")
            
            # Apply point range filtering AFTER converting to points
            if min_pts is not None or max_pts is not None:
                filtered_items = []
                filtered_out_count = 0
                for it in items_accumulated:
                    pts = it.get("points")
                    if pts is None:
                        filtered_out_count += 1
                        continue
                    try:
                        pts_val = float(pts)
                    except (ValueError, TypeError):
                        filtered_out_count += 1
                        continue
                    if min_pts is not None and pts_val < min_pts:
                        filtered_out_count += 1
                        current_app.logger.debug(f"[POINT_FILTER DEBUG] Filtered out item {it.get('id')}: {pts_val} < {min_pts}")
                        continue
                    if max_pts is not None and pts_val > max_pts:
                        filtered_out_count += 1
                        current_app.logger.debug(f"[POINT_FILTER DEBUG] Filtered out item {it.get('id')}: {pts_val} > {max_pts}")
                        continue
                    filtered_items.append(it)
                items_accumulated = filtered_items
                current_app.logger.info(f"[POINT_FILTER DEBUG] After point filtering: {len(items_accumulated)} items (filtered out {filtered_out_count})")
                if items_accumulated:
                    sample_after = items_accumulated[:5]
                    for idx, item in enumerate(sample_after):
                        current_app.logger.info(f"[POINT_FILTER DEBUG] Sample item {idx+1} after filter: id={item.get('id')}, points={item.get('points')}")
            
            # Slice to get the correct page of items
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            combined = items_accumulated[start_idx:end_idx]
            
            current_app.logger.info(f"[PAGINATION DEBUG] Sliced items {start_idx} to {end_idx} for page {page}, returning {len(combined)} items")
            
            # Determine has_more: we have more if we accumulated more than what we're returning
            # OR if eBay indicated there are more pages and we haven't exhausted our fetch limit
            has_more = len(items_accumulated) > end_idx or (has_more_from_ebay and pages_fetched < max_pages_to_fetch)

        # DEBUG: Log final items before injecting flags/favorites
        if min_pts is not None or max_pts is not None:
            current_app.logger.info(f"[POINT_FILTER DEBUG] Final combined items before flags: {len(combined)} items")
            if combined:
                for idx, item in enumerate(combined[:5]):
                    current_app.logger.info(f"[POINT_FILTER DEBUG] Final item {idx+1}: id={item.get('id')}, points={item.get('points')}")
        
        _inject_low_stock_flags(combined)
        driver_id = _current_driver_id()
        _inject_favorites_data(combined, driver_id)
        
        # DEBUG: Log final items after injecting flags/favorites
        if min_pts is not None or max_pts is not None:
            current_app.logger.info(f"[POINT_FILTER DEBUG] Final combined items after flags: {len(combined)} items")
            if combined:
                for idx, item in enumerate(combined[:5]):
                    current_app.logger.info(f"[POINT_FILTER DEBUG] Final item {idx+1} after flags: id={item.get('id')}, points={item.get('points')}")

        # Apply client-side sorting for points-based sorting
        # Note: price_asc and price_desc are handled before points conversion (above)
        # points_asc/points_desc are mapped to price_asc/price_desc in frontend
        if sort == "price_asc":
            # Already sorted before conversion, but sort by points as fallback
            combined.sort(key=lambda x: x.get("points", 0) or 0)
        elif sort == "price_desc":
            # Already sorted before conversion, but sort by points as fallback
            combined.sort(key=lambda x: x.get("points", 0) or 0, reverse=True)
        elif sort == "points_asc":
            # Legacy support - map to price sorting
            combined.sort(key=lambda x: x.get("points", 0) or 0)
        elif sort == "points_desc":
            # Legacy support - map to price sorting
            combined.sort(key=lambda x: x.get("points", 0) or 0, reverse=True)

        # OPTIMIZATION #3: Return total only if strict_total was requested
        # Otherwise return None (frontend uses has_more for pagination)
        response_total = len(combined) if strict_total else None
        
        # DEBUG: Log final response
        current_app.logger.info(f"[PAGINATION DEBUG] Final response: {len(combined)} items, page={page}, has_more={has_more}, total={response_total}")
        if combined:
            sample_final = combined[0]
            current_app.logger.info(f"[PAGINATION DEBUG] Final sample item: id={sample_final.get('id')}, points={sample_final.get('points')}, has_points={sample_final.get('points') is not None}")
            # Log all item IDs to check for duplicates
            item_ids = [str(item.get('id', '')) for item in combined]
            current_app.logger.info(f"[PAGINATION DEBUG] Item IDs on page {page}: {item_ids[:10]}... (showing first 10)")
            
            # Check for items missing points
            items_without_points = [item for item in combined if item.get('points') is None]
            if items_without_points:
                current_app.logger.warning(f"[PAGINATION DEBUG] ⚠️ Page {page} has {len(items_without_points)} items without points!")
                for idx, item in enumerate(items_without_points[:3]):
                    current_app.logger.warning(f"[PAGINATION DEBUG] Item {idx+1} without points: id={item.get('id')}, title={item.get('title', '')[:50]}, price={item.get('price')}")
        
        return jsonify({
            "items": combined,
            "page": page,
            "page_size": page_size,
            "total": response_total,
            "has_more": has_more  # Use has_more from eBay provider for accurate pagination
        })
    except Exception as e:
        current_app.logger.error(f"Error loading catalog data: {e}")
        return jsonify({"error": "Failed to load catalog data."}), 500


@bp.get("/favorites/data")
@login_required
def favorites_data():
    try:
        sponsor_id = _require_driver_and_sponsor()
        driver_id = _current_driver_id()
        if not driver_id:
            abort(403)

        sort = (request.args.get("sort") or "best_match").strip()
        q = (request.args.get("q") or "").strip() or None
        cats = request.args.getlist("cat[]") or request.args.getlist("cat") or None
        if cats:
            cats = [c for c in cats if str(c).strip()]

        def _parse_num(val):
            try:
                return float(val.strip()) if val and val.strip() else None
            except Exception:
                return None

        min_pts = _parse_num(request.args.get("min_points"))
        max_pts = _parse_num(request.args.get("max_points"))

        items = _load_favorite_items(
            sponsor_id, driver_id, sort, q, cats, min_pts, max_pts
        )

        return jsonify({
            "items": items,
            "total": len(items),
            "has_more": False
        })
    except Exception as e:
        current_app.logger.error(f"Error loading favorites: {e}")
        return jsonify({"error": "Failed to load favorites."}), 500


@bp.post("/favorites/<path:item_id>")
@login_required
def add_favorite(item_id: str):
    from urllib.parse import unquote

    try:
        sponsor_id = _require_driver_and_sponsor()
        driver_id = _current_driver_id()
        if not driver_id:
            abort(403)

        decoded_id = unquote(str(item_id))
        existing = DriverFavorites.query.filter_by(DriverID=driver_id, ExternalItemID=decoded_id).first()
        if existing:
            return jsonify({"ok": True, "favorite": decoded_id})

        payload = request.get_json(silent=True) or {}
        favorite = DriverFavorites(
            DriverID=driver_id,
            ExternalItemID=decoded_id,
            ItemTitle=payload.get("title"),
            ItemImageURL=payload.get("image"),
            ItemPoints=payload.get("points"),
        )
        db.session.add(favorite)
        db.session.commit()

        current_app.logger.info(f"Favorite added for driver {driver_id}: {decoded_id}")
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"Error adding favorite {item_id}: {e}")
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to add favorite."}), 500


@bp.delete("/favorites/<path:item_id>")
@login_required
def remove_favorite(item_id: str):
    from urllib.parse import unquote

    try:
        _require_driver_and_sponsor()
        driver_id = _current_driver_id()
        if not driver_id:
            abort(403)

        decoded_id = unquote(str(item_id))
        favorite = DriverFavorites.query.filter_by(DriverID=driver_id, ExternalItemID=decoded_id).first()
        if not favorite:
            return jsonify({"ok": False, "message": "Favorite not found."}), 404

        db.session.delete(favorite)
        db.session.commit()

        current_app.logger.info(f"Favorite removed for driver {driver_id}: {decoded_id}")
        return jsonify({"ok": True})
    except Exception as e:
        current_app.logger.error(f"Error removing favorite {item_id}: {e}")
        db.session.rollback()
        return jsonify({"ok": False, "message": "Failed to remove favorite."}), 500


@bp.get("/product/<path:item_id>")
@login_required
def product_detail(item_id: str):
    """Display detailed product page for drivers with add to cart functionality."""
    from urllib.parse import unquote

    # Decode URL-encoded item ID (handles pipe characters and special chars)
    item_id = unquote(item_id)

    sponsor_id = _require_driver_and_sponsor()
    driver_id = _current_driver_id()

    try:
        provider = EbayProvider()

        # Check if item is blacklisted
        bl_ids = _get_blacklisted_ids(sponsor_id)
        if str(item_id) in bl_ids:
            current_app.logger.warning(f"Driver attempted to view blacklisted item {item_id}")
            abort(404, "Product not found")

        # Fetch full item details from eBay
        current_app.logger.info(f"Driver viewing product details for item_id: {item_id}")
        item_data = provider.get_item_details(item_id)

        if not item_data:
            current_app.logger.error(f"Product not found: {item_id}")
            abort(404, "Product not found")

        current_app.logger.info(f"Product data retrieved: {item_data.get('title', 'No title')}")

        # OPTIMIZATION #6: Use cached converter function for price conversion
        points_converter = get_points_converter(sponsor_id)
        
        # Convert price to points for drivers
        price = item_data.get("price")
        if price:
            try:
                points = points_converter(float(price))
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

        # Check if this product is favorited
        if driver_id:
            favorite = DriverFavorites.query.filter_by(
                DriverID=driver_id,
                ExternalItemID=item_id
            ).first()
            item_data["is_favorite"] = favorite is not None
        else:
            item_data["is_favorite"] = False

        if driver_id:
            try:
                primary_image = item_data.get("image")
                if not primary_image:
                    additional_images = item_data.get("additional_images") or []
                    primary_image = additional_images[0] if additional_images else None

                ProductViewService.record_view(
                    driver_id=driver_id,
                    sponsor_id=sponsor_id,
                    external_item_id=item_id,
                    provider="ebay",
                    title=item_data.get("title") or item_data.get("subtitle"),
                    image_url=primary_image,
                    points=item_data.get("points"),
                    price=item_data.get("price") or item_data.get("price_usd"),
                    currency="USD",
                )
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                current_app.logger.warning(f"Failed to record product view: {exc}")

        # Apply low stock flags
        _inject_low_stock_flags([item_data])

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

            # Filter out current item
            related_items = [
                it for it in related_items
                if str(it.get("id")) != str(item_id)
            ][:5]

            # OPTIMIZATION #6: Batch convert prices to points for related items
            convert_prices_batch(related_items, points_converter)

            current_app.logger.info(f"Showing {len(related_items)} related items after filtering")

            # Apply low stock flags to related items
            _inject_low_stock_flags(related_items)

        except Exception as e:
            current_app.logger.error(f"Error fetching related items: {e}", exc_info=True)

        return render_template(
            "driver_points_catalog/product_detail.html",
            product=item_data,
            related_items=related_items
        )

    except Exception as e:
        current_app.logger.error(f"Error loading product detail: {e}")
        abort(500, "Error loading product details")


@bp.post("/report/<string:item_id>")
@login_required
def report_item(item_id: str):
    """Report an inappropriate item."""
    driver_id = _current_driver_id()
    sponsor_id = _resolve_selected_sponsor_id()
    
    if not driver_id:
        return jsonify({"ok": False, "message": "Driver not found"}), 401
    
    if not sponsor_id:
        return jsonify({"ok": False, "message": "Sponsor not found"}), 400
    
    try:
        data = request.get_json()
        reason = data.get("reason", "")
        description = data.get("description", "")
        title = data.get("title", "")
        image = data.get("image", "")
        url = data.get("url", "")
        
        if not reason:
            return jsonify({"ok": False, "message": "Reason is required"}), 400
        
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
        
        current_app.logger.info(f"Report created: {report.ID} for item {item_id} by driver {driver_id}")
        
        return jsonify({"ok": True, "message": "Report submitted successfully"})
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating report: {e}", exc_info=True)
        return jsonify({"ok": False, "message": "Error submitting report"}), 500
