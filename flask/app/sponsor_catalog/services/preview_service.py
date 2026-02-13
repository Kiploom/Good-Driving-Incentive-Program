# app/sponsor_catalog/services/preview_service.py
from __future__ import annotations

from typing import Dict, Any, List, Tuple, Optional

from app.models import SponsorCatalogFilterSet
from .override_service import compose_with_inclusions_exclusions
from .cache_service import fingerprint as fp_hash, get_cached, set_cached
from app.sponsor_catalog.providers.ebay_provider import EbayProvider

from flask import current_app
from sqlalchemy import text, bindparam
from app.extensions import db


def _inject_low_stock_flags(items: list[dict]) -> None:
    """
    Inject stock flags based on real-time eBay API availability data.
    Uses eBay's estimatedAvailableQuantity and availabilityThresholdType fields.
    """
    threshold = int(current_app.config.get("LOW_STOCK_THRESHOLD", 10))
    
    for it in items:
        # Get eBay availability data
        estimated_qty = it.get("estimated_quantity")
        availability_threshold = it.get("availability_threshold")
        
        # Default values
        it["stock_qty"] = None
        it["low_stock"] = False
        it["no_stock"] = False
        it["available"] = False
        
        # If eBay provides exact quantity, use that
        if estimated_qty is not None:
            try:
                qty = int(estimated_qty)
                it["stock_qty"] = qty
                
                if qty == 0:
                    it["no_stock"] = True
                    it["low_stock"] = False
                    it["available"] = False
                elif 0 < qty < threshold:
                    it["low_stock"] = True
                    it["no_stock"] = False
                    it["available"] = False
                elif qty >= 10:
                    it["low_stock"] = False
                    it["no_stock"] = False
                    it["available"] = True
                else:
                    # Between threshold and 10 (e.g., 5-9 items)
                    it["low_stock"] = False
                    it["no_stock"] = False
                    it["available"] = False
            except (ValueError, TypeError):
                pass
        
        # Otherwise, interpret eBay's threshold type
        elif availability_threshold:
            threshold_type = str(availability_threshold).upper()
            
            if "OUT_OF_STOCK" in threshold_type or threshold_type == "ZERO":
                it["no_stock"] = True
                it["low_stock"] = False
                it["available"] = False
                it["stock_qty"] = 0
            elif "MORE_THAN" in threshold_type:
                # "MORE_THAN_10" means plenty of stock - show available tag
                it["low_stock"] = False
                it["no_stock"] = False
                it["available"] = True
                # Extract number if possible (e.g., "MORE_THAN_10" -> 10+)
                try:
                    num = int(threshold_type.split("_")[-1])
                    it["stock_qty"] = num + 1
                    # Only show available if MORE_THAN_10 or higher
                    if num >= 10:
                        it["available"] = True
                    else:
                        it["available"] = False
                except (ValueError, IndexError):
                    it["stock_qty"] = None
                    it["available"] = True  # Assume available for MORE_THAN
            elif threshold_type in ["LIMITED_QUANTITY", "LOW_STOCK"]:
                # Limited quantity = low stock warning
                it["low_stock"] = True
                it["no_stock"] = False
                it["available"] = False
                it["stock_qty"] = threshold  # Estimate at threshold
            else:
                # Unknown threshold type - assume available
                it["low_stock"] = False
                it["no_stock"] = False
                it["available"] = True


def active_rules_for(sponsor_id: str) -> List[dict]:
    """Return the list of active rule objects sorted by Priority for a sponsor."""
    rows = (
        SponsorCatalogFilterSet.query
        .filter_by(sponsor_id=sponsor_id, is_active=True)
        .order_by(SponsorCatalogFilterSet.priority)
        .all()
    )
    return [r.rules_json or {} for r in rows]


def merge(rules_list: List[dict]) -> dict:
    """
    Merge multiple rule dicts into one.
    Later rules override earlier ones for scalars.
    For list-like keys, do an ordered union.
    """
    out: dict = {}
    for r in rules_list:
        for k, v in (r or {}).items():
            if v is None:
                continue
            if k in ("category_ids", "include_keywords", "exclude_keywords"):
                existing = out.get(k) or []
                if isinstance(existing, (list, tuple)) and isinstance(v, (list, tuple)):
                    seen = set(existing)
                    merged = list(existing) + [x for x in v if x not in seen]
                    out[k] = merged
                else:
                    out[k] = v
            else:
                out[k] = v
    return out


def provider() -> EbayProvider:
    return EbayProvider()


def preview(
    sponsor_id: str,
    page: int,
    page_size: int,
    sort: str,
    keyword_overlay: Optional[str] = None,
    rules_overlay: Optional[dict] = None,   # optional single chosen filter-set
    no_filter: bool = False,  # if True, bypass all filters
    strict_total: bool = True,  # if False, skip expensive total count (fast mode)
) -> Tuple[dict, Optional[dict]]:
    """
    Build a preview payload for the sponsor:
    - Merge active rules + optional overlay (from a chosen filter set)
    - Query provider
    - Apply overrides (pins/inclusions/exclusions)
    - Cache normalized results
    
    Args:
        strict_total: If False, uses fast mode with cached search and skips total count.
    Returns: (final_payload, cache_info_or_none)
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[PREVIEW SERVICE] Starting preview for sponsor {sponsor_id}, page {page}, "
                f"no_filter={no_filter}, rules_overlay={rules_overlay}, keyword_overlay={keyword_overlay}")
    
    # 1) gather rules (skip if no_filter is True)
    if no_filter:
        merged = {}
        # Even in no_filter mode, apply rules_overlay if provided (for category/price filters from UI)
        if rules_overlay:
            merged = dict(rules_overlay)
            logger.info(f"[PREVIEW SERVICE] No filter mode: applied rules_overlay, merged={merged}")
            
            # IMPORTANT: Ensure special_mode is preserved in merged for recommended_only detection
            if rules_overlay.get("special_mode"):
                merged["special_mode"] = rules_overlay["special_mode"]
                logger.info(f"[PREVIEW SERVICE] Preserved special_mode={merged['special_mode']} in merged (no_filter mode)")
            
            # Ensure categories are properly formatted for eBay provider
            if "categories" in merged and isinstance(merged["categories"], dict):
                include_cats = merged["categories"].get("include", [])
                if include_cats:
                    # Also set category_ids at top level for eBay provider compatibility
                    merged["category_ids"] = include_cats if isinstance(include_cats, list) else [include_cats]
                    logger.info(f"[PREVIEW SERVICE] Set category_ids for eBay provider: {merged['category_ids']}")
        else:
            logger.info(f"[PREVIEW SERVICE] No filter mode: no rules_overlay, merged={merged}")
    else:
        rules = active_rules_for(sponsor_id)
        logger.info(f"[PREVIEW SERVICE] Active rules count: {len(rules)}")

        # add overlay (single chosen filter set) if provided
        if rules_overlay:
            rules.append(rules_overlay)
            logger.info(f"[PREVIEW SERVICE] Added rules_overlay to active rules")

        merged = merge(rules)
        logger.info(f"[PREVIEW SERVICE] Merged rules keys: {list(merged.keys())}")
        
        # Ensure categories are properly formatted for eBay provider
        if "categories" in merged and isinstance(merged["categories"], dict):
            include_cats = merged["categories"].get("include", [])
            if include_cats:
                # Also set category_ids at top level for eBay provider compatibility
                merged["category_ids"] = include_cats if isinstance(include_cats, list) else [include_cats]
                logger.info(f"[PREVIEW SERVICE] Set category_ids for eBay provider: {merged['category_ids']}")

        # ✅ Map include/exclude keyword lists into a single keywords object
        # so the provider actually sees usable keyword constraints.
        inc_kw = merged.pop("include_keywords", None)
        exc_kw = merged.pop("exclude_keywords", None)
        if inc_kw or exc_kw:
            merged["keywords"] = {
                "must": list(inc_kw or []),
                "must_not": list(exc_kw or []),
            }
            logger.info(f"[PREVIEW SERVICE] Mapped keywords: must={inc_kw}, must_not={exc_kw}")

    # Check if recommended_only mode is enabled BEFORE doing provider search
    # BUT: if categories are specified in merged rules, we should NOT use recommended_only mode
    # Category browsing should show products from that category, not just pinned items
    recommended_only = False
    
    # Check rules_overlay first (this is set when filter_set_id == "__recommended_only__")
    if rules_overlay:
        # Don't use recommended_only if categories are specified (category browsing takes precedence)
        has_categories = bool(
            merged.get("categories", {}).get("include") or 
            merged.get("categories", {}).get("exclude") or
            rules_overlay.get("categories", {}).get("include") or
            rules_overlay.get("categories", {}).get("exclude")
        )
        if not has_categories:
            recommended_only = (
                rules_overlay.get("special_mode") == "recommended_only" or
                rules_overlay.get("filter_mode") == "pinned_only" or
                rules_overlay.get("special_mode") == "pinned_only"
            )
            logger.info(f"[PREVIEW SERVICE] Checking rules_overlay for recommended_only: special_mode={rules_overlay.get('special_mode')}, recommended_only={recommended_only}")
        else:
            logger.info(f"[PREVIEW SERVICE] Categories specified, skipping recommended_only mode")
    
    # Also check merged rules (in case special_mode was merged in)
    if not recommended_only and merged.get("special_mode") == "recommended_only":
        recommended_only = True
        logger.info(f"[PREVIEW SERVICE] Recommended_only mode detected in merged rules")
    
    logger.info(f"[PREVIEW SERVICE] Final recommended_only check: {recommended_only}, rules_overlay={rules_overlay}, merged_keys={list(merged.keys())}")
    
    # If in recommended_only mode, skip provider search and get pinned items directly
    if recommended_only:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[PREVIEW SERVICE] Recommended_only mode detected for sponsor {sponsor_id}")
        
        from .override_service import list_pinned_inclusions, list_blacklisted
        pinned_rows = list_pinned_inclusions(sponsor_id)
        blacklist_rows = list_blacklisted(sponsor_id)
        # Handle both ItemID (BlacklistedProduct) and item_id (if different model)
        blacklist_ids = {getattr(r, 'ItemID', None) or getattr(r, 'item_id', None) for r in blacklist_rows if getattr(r, 'ItemID', None) or getattr(r, 'item_id', None)}
        
        logger.info(f"[PREVIEW SERVICE] Found {len(pinned_rows)} pinned items, {len(blacklist_ids)} blacklisted items")
        
        if len(pinned_rows) == 0:
            logger.warning(f"[PREVIEW SERVICE] No pinned items found for sponsor {sponsor_id}! Returning empty result.")
            return {
                "items": [],
                "total": 0,
                "total_pages": 1,
                "page": page,
                "page_size": page_size,
                "has_more": False,
                "debug": {"merged_rules": merged, "mode": "recommended_only", "pinned_count": 0, "message": "No pinned items found"},
            }, {"cache": "miss", "fingerprint": "recommended_only"}
        
        # Build items list from pinned items only
        # Fetch prices from eBay API for pinned items
        pr = provider()
        items = []
        for r in pinned_rows:
            # Handle both SponsorPinnedProduct and SponsorCatalogInclusion models
            item_id = getattr(r, 'ItemID', None) or getattr(r, 'item_id', None)
            if not item_id:
                logger.warning(f"[PREVIEW SERVICE] Pinned row missing item_id: {r}")
                continue
                
            if item_id in blacklist_ids:
                logger.debug(f"[PREVIEW SERVICE] Skipping blacklisted item {item_id}")
                continue
            
            # Get attributes - SponsorPinnedProduct has ItemTitle/ItemImageURL, SponsorCatalogInclusion doesn't
            item_title = getattr(r, 'ItemTitle', None) or getattr(r, 'item_title', None) or "(Recommended item)"
            item_image = getattr(r, 'ItemImageURL', None) or getattr(r, 'item_image_url', None)
            pin_rank = getattr(r, 'PinRank', None) or getattr(r, 'pin_rank', None)
            note = getattr(r, 'Note', None) or getattr(r, 'note', None)
            created_at = getattr(r, 'CreatedAt', None) or getattr(r, 'created_at', None)
            
            # Fetch price from eBay API
            price = None
            try:
                # Try with full item_id first (get_item handles v1|legacyId|legacyId format)
                # If that fails, try extracting just the numeric eBay item ID
                logger.debug(f"[PREVIEW SERVICE] Fetching price for pinned item: full_id={item_id}")
                item_data = pr.get_item(item_id)
                
                # If that didn't work, try extracting just the numeric eBay item ID
                if not item_data and '|' in item_id:
                    ebay_item_id = item_id.split('|')[1]
                    logger.debug(f"[PREVIEW SERVICE] Retrying with extracted eBay ID: {ebay_item_id}")
                    item_data = pr.get_item(ebay_item_id)
                if item_data:
                    price_val = item_data.get("price")
                    logger.info(f"[PREVIEW SERVICE] get_item returned data for {item_id}, price_val={price_val}, type={type(price_val)}, item_data_keys={list(item_data.keys())}")
                    # Format price as string with 2 decimal places to match regular search results format
                    if price_val is not None and price_val != 0:
                        try:
                            price = f"{float(price_val):.2f}"
                            logger.info(f"[PREVIEW SERVICE] Successfully formatted price for pinned item {item_id}: {price}")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"[PREVIEW SERVICE] Error formatting price {price_val} for {item_id}: {e}")
                            price = str(price_val) if price_val is not None else None
                    else:
                        logger.warning(f"[PREVIEW SERVICE] No price value in item_data for pinned item {item_id} (price_val={price_val})")
                    # Also update title/image if not already set (in case they're more up-to-date)
                    if not item_title and item_data.get("title"):
                        item_title = item_data.get("title")
                    if not item_image and item_data.get("image"):
                        item_image = item_data.get("image")
                else:
                    logger.warning(f"[PREVIEW SERVICE] get_item returned None for pinned item {item_id}")
            except Exception as e:
                logger.error(f"[PREVIEW SERVICE] Exception fetching price for pinned item {item_id}: {e}", exc_info=True)
            
            logger.debug(f"[PREVIEW SERVICE] Processing pinned item: id={item_id}, title={item_title[:50] if item_title else 'None'}, "
                        f"image={bool(item_image)}, price={price}, pin_rank={pin_rank}")
            
            # Create item dict with fetched price
            items.append({
                "id": item_id,
                "title": item_title,
                "image": item_image,
                "price": price,  # Now fetched from eBay API
                "is_pinned": True,
                "pin_rank": pin_rank,
                "note": note,
                "created_at": created_at.isoformat() if created_at else None,
            })
        
        logger.info(f"[PREVIEW SERVICE] Built {len(items)} items from pinned rows (after blacklist filter)")
        
        # Apply sorting
        if sort == "price_asc":
            items.sort(key=lambda x: float(x.get("price") or 0))
        elif sort == "price_desc":
            items.sort(key=lambda x: float(x.get("price") or 0), reverse=True)
        elif sort == "newest":
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        elif sort == "stock_asc":
            items.sort(key=lambda x: int(x.get("stock_qty") or 0))
        elif sort == "stock_desc":
            items.sort(key=lambda x: int(x.get("stock_qty") or 0), reverse=True)
        else:  # best_match or default - sort by pin_rank
            items.sort(key=lambda x: (x.get("pin_rank") is None, x.get("pin_rank") or 0))
        
        # Apply keyword filter if present
        if keyword_overlay:
            keyword_lower = keyword_overlay.lower()
            items = [it for it in items if keyword_lower in (it.get("title") or "").lower()]
        
        # Apply price filters if present in merged rules
        if merged.get("price"):
            min_price = merged["price"].get("min")
            max_price = merged["price"].get("max")
            if min_price is not None or max_price is not None:
                filtered_items = []
                for it in items:
                    price = it.get("price")
                    if price is None:
                        continue  # Skip items without price in recommended mode
                    price_val = float(price)
                    if min_price is not None and price_val < min_price:
                        continue
                    if max_price is not None and price_val > max_price:
                        continue
                    filtered_items.append(it)
                items = filtered_items
        
        # Apply category filter if present
        if merged.get("categories", {}).get("include"):
            include_cats = merged["categories"]["include"]
            # Note: pinned items might not have category_id, so we'd need to fetch it
            # For now, skip category filtering in recommended_only mode
            pass
        
        # Pagination
        total_filtered = len(items)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_items = items[start_idx:end_idx]
        total_pages = max(1, (total_filtered + page_size - 1) // page_size)
        
        logger.info(f"[PREVIEW SERVICE] Recommended_only pagination: total={total_filtered}, "
                    f"page={page}, page_size={page_size}, start_idx={start_idx}, end_idx={end_idx}, "
                    f"paginated_items={len(paginated_items)}")
        
        result = {
            "items": paginated_items,
            "total": total_filtered,
            "total_pages": total_pages,
            "page": page,
            "page_size": page_size,
            "has_more": len(paginated_items) == page_size and total_filtered > page * page_size,
            "debug": {"merged_rules": merged, "mode": "recommended_only", "pinned_count": len(pinned_rows)},
        }
        
        logger.info(f"[PREVIEW SERVICE] Returning recommended_only result: {len(paginated_items)} items")
        return result, {"cache": "miss", "fingerprint": "recommended_only"}
    
    # allow keyword overlay (temporary manual search box)
    if keyword_overlay:
        merged = dict(merged)
        # overlay replaces keywords entirely for this call
        merged["keywords"] = keyword_overlay

    # 2) fingerprint & cache
    # IMPORTANT: Don't use cache when category filter is active and we need to exclude pinned items
    # The cache might contain pinned items that should be filtered out
    # Also skip cache when no_filter=True to ensure pinned items are always included (cache might be stale)
    key = fp_hash({"merged": merged, "sort": sort})
    has_category_filter = bool(merged.get("categories", {}).get("include") or merged.get("category_ids"))
    
    # Skip cache when category filter is active to ensure pinned items are excluded
    # Also skip cache when no_filter=True to ensure pinned items are included (cache might not have them)
    if has_category_filter:
        logger.info(f"[PREVIEW SERVICE] Skipping cache (category filter active, need to exclude pinned items)")
    elif no_filter:
        logger.info(f"[PREVIEW SERVICE] Skipping cache (no_filter mode, need to ensure pinned items are included)")
    elif cached := get_cached(sponsor_id, key, page, sort):
        cached.setdefault("page", page)
        cached.setdefault("page_size", page_size)
        logger.info(f"[PREVIEW SERVICE] Using cached result")
        return cached, {"cache": "hit", "fingerprint": key}

    # 3) provider search with buffer to account for blacklist filtering
    logger.info(f"[PREVIEW SERVICE] Starting provider search for sponsor {sponsor_id}, page {page}, merged rules: {merged}")
    
    # PRICE FILTER DEBUGGING: Log what's being passed to provider
    if merged.get("price"):
        logger.info(f"[PRICE FILTER] Price filter in merged rules being passed to provider: {merged.get('price')}")
        logger.info(f"[PRICE FILTER] Merged rules full structure: {merged}")
    else:
        logger.info(f"[PRICE FILTER] No price filter in merged rules (merged keys: {list(merged.keys())})")
        if merged:
            logger.info(f"[PRICE FILTER] Full merged rules: {merged}")
    
    pr = provider()
    
    # Determine if price filtering will be applied client-side
    has_price_filter = bool(merged.get("price") and (merged["price"].get("min") is not None or merged["price"].get("max") is not None))
    is_price_sort = sort in ("price_asc", "price_desc")
    
    # When price filtering is active, we need to fetch MORE items because filtering happens client-side
    # When sorting by price, we skip API-level price filter, so we need even MORE items to ensure
    # we get enough items that pass the client-side filter
    if has_price_filter:
        if is_price_sort:
            # When sorting by price + price filter, fetch maximum items (1000) to ensure we get enough
            # that pass the client-side filter, since API-level filter is skipped
            # The challenge: when sorting DESC with a low max_price, we need to fetch past all items > max_price
            # Always fetch the maximum (1000) to maximize our chances of getting items in the price range
            fetch_size = 1000  # Maximum to ensure we get enough items
            fetch_page = 1
            logger.info(f"[PREVIEW SERVICE] Price filter + price sort active - fetching {fetch_size} items from page {fetch_page} "
                       f"(API filter skipped, need maximum items for client-side filtering, requested page: {page})")
        else:
            # Price filter but not sorting by price - API filter is applied, so normal buffer is enough
            estimated_items_needed = page * page_size * 5
            fetch_size = min(1000, max(page_size * 10, estimated_items_needed))
            fetch_page = 1
            logger.info(f"[PREVIEW SERVICE] Price filter active (no price sort) - fetching {fetch_size} items from page {fetch_page} to account for client-side filtering (requested page: {page})")
    else:
        # Normal case: 3x buffer, capped at 250, use requested page
        fetch_size = min(250, page_size * 3)
        fetch_page = page
        logger.info(f"[PREVIEW SERVICE] No price filter - fetching {fetch_size} items from page {fetch_page}")
    
    logger.info(f"[PREVIEW SERVICE] Calling search_extended with fetch_size={fetch_size}, page={fetch_page}, sort={sort}, strict_total={strict_total}, has_price_filter={has_price_filter}")
    
    # Use extended search for up to 1000 pages with strict_total parameter for fast mode
    res = pr.search_extended(
        merged, 
        fetch_page,  # Use calculated fetch_page (1 when price filtering, actual page otherwise)
        fetch_size, 
        sort, 
        keyword_overlay=None, 
        strict_total=strict_total
    )
    items = res.get("items") or []
    
    # Check for debug info indicating an error from eBay API
    if res.get("debug"):
        debug_info = res["debug"]
        http_status = debug_info.get("http_status")
        if http_status and http_status >= 400:
            logger.error(f"[PREVIEW SERVICE] eBay API returned HTTP error {http_status}. Debug info: {debug_info}")
            # If we got an HTTP error and we're using price filter + price sort,
            # this might be because eBay doesn't support that combination
            # Return empty results gracefully - the frontend will handle it
            if has_price_filter and is_price_sort:
                logger.warning(f"[PREVIEW SERVICE] eBay API error with price filter + price sort. "
                             f"This might indicate the API doesn't support this combination. "
                             f"Consider skipping API-level price filter for price sorts.")
        # Log any other debug info (like exceptions)
        if debug_info.get("exception"):
            logger.error(f"[PREVIEW SERVICE] eBay API exception: {debug_info.get('exception')}")
    
    logger.info(f"[PREVIEW SERVICE] Provider returned {len(items)} items. Response keys: {list(res.keys())}")
    
    # Log initial fetch results for debugging when price filtering + price sorting
    if has_price_filter and is_price_sort:
        logger.info(f"[PREVIEW SERVICE] Initial fetch returned {len(items)} items (fetch_size={fetch_size}, sort={sort})")
        if items:
            # Log sample prices to understand what range we're getting
            sample_prices = []
            for it in items[:20]:  # First 20 items to get better sense of price distribution
                price = it.get("price")
                if price:
                    try:
                        if isinstance(price, str):
                            price_clean = price.replace('$', '').replace(',', '').strip()
                            price_val = float(price_clean)
                        else:
                            price_val = float(price)
                        sample_prices.append(price_val)
                    except (ValueError, TypeError):
                        pass
            if sample_prices:
                price_min = merged.get("price", {}).get("min")
                price_max = merged.get("price", {}).get("max")
                logger.info(f"[PREVIEW SERVICE] Sample prices from first 20 items: min={min(sample_prices):.2f}, max={max(sample_prices):.2f}, "
                          f"avg={sum(sample_prices)/len(sample_prices):.2f}, target_range=[{price_min}, {price_max}]")
                # Check if we're getting items in the target price range
                if price_min is not None or price_max is not None:
                    in_range_count = sum(1 for p in sample_prices 
                                       if (price_min is None or p >= price_min) and (price_max is None or p <= price_max))
                    logger.info(f"[PREVIEW SERVICE] Items in price range [{price_min}, {price_max}] in first 20: {in_range_count}/{len(sample_prices)}")
        else:
            logger.warning(f"[PREVIEW SERVICE] Got 0 items from eBay API with price filter + price sort. "
                         f"This might indicate an issue with the eBay API request.")
    
    if items:
        logger.debug(f"[PREVIEW SERVICE] First item sample: id={items[0].get('id')}, title={items[0].get('title', '')[:50]}, price={items[0].get('price')}, price_type={type(items[0].get('price'))}")
        # PRICE FILTER DEBUGGING: Log sample prices
        if has_price_filter:
            sample_prices = [it.get('price') for it in items[:5]]
            logger.info(f"[PRICE FILTER] Sample prices from provider (first 5): {sample_prices}")
    
    # 4) apply overrides (pins/inclusions/exclusions - includes blacklist filtering)
    # When browsing by category, exclude pinned/recommended products
    has_category_filter = bool(merged.get("categories", {}).get("include") or merged.get("category_ids"))
    logger.info(f"[PREVIEW SERVICE] Applying overrides (pins/inclusions/exclusions) to {len(items)} items, "
                f"has_category_filter={has_category_filter}")
    items = compose_with_inclusions_exclusions(sponsor_id, items, exclude_pinned=has_category_filter)
    logger.info(f"[PREVIEW SERVICE] After overrides: {len(items)} items")
    
    # 4.5) Fetch prices for pinned items that don't have prices yet
    # Reuse the provider instance already created above
    pinned_items_without_price = [it for it in items if it.get("is_pinned") and (it.get("price") is None or it.get("price") == 0)]
    if pinned_items_without_price:
        logger.info(f"[PREVIEW SERVICE] Fetching prices for {len(pinned_items_without_price)} pinned items without prices")
        for it in pinned_items_without_price:
            item_id = it.get("id")
            if not item_id:
                continue
            try:
                # Try with full item_id first (get_item handles v1|legacyId|legacyId format)
                item_data = pr.get_item(item_id)
                
                # If that didn't work, try extracting just the numeric eBay item ID
                if not item_data and '|' in item_id:
                    ebay_item_id = item_id.split('|')[1]
                    item_data = pr.get_item(ebay_item_id)
                
                if item_data:
                    price_val = item_data.get("price")
                    if price_val is not None and price_val != 0:
                        try:
                            it["price"] = f"{float(price_val):.2f}"
                            logger.debug(f"[PREVIEW SERVICE] Fetched price for pinned item {item_id}: {it['price']}")
                        except (ValueError, TypeError):
                            pass
            except Exception as e:
                logger.debug(f"[PREVIEW SERVICE] Error fetching price for pinned item {item_id}: {e}")

    # 4.5) add low-stock flags from Products table (best-effort)
    _inject_low_stock_flags(items)

    # 4.6) Apply price filters if present in merged rules
    # IMPORTANT: Apply price filtering BEFORE any sorting to ensure consistent results
    # When sorting by price, the eBay API handles both filtering and sorting, but we still
    # need client-side filtering as a backup in case the API filter doesn't work correctly
    if merged.get("price"):
        min_price = merged["price"].get("min")
        max_price = merged["price"].get("max")
        if min_price is not None or max_price is not None:
            logger.info(f"[PREVIEW SERVICE] Applying price filter: min_price={min_price}, max_price={max_price}, sort={sort}, items_before={len(items)}")
            filtered_items = []
            skipped_no_price = 0
            skipped_below_min = 0
            skipped_above_max = 0
            for it in items:
                price = it.get("price")
                if price is None:
                    # Skip items without price when price filter is active
                    skipped_no_price += 1
                    continue
                try:
                    # Handle both string and numeric prices
                    if isinstance(price, str):
                        # Remove currency symbols and whitespace
                        price_clean = price.replace('$', '').replace(',', '').strip()
                        price_val = float(price_clean)
                    else:
                        price_val = float(price)
                    
                    # Apply min price filter
                    if min_price is not None and price_val < min_price:
                        skipped_below_min += 1
                        logger.debug(f"[PREVIEW SERVICE] Item {it.get('id')} price {price_val} below min {min_price}")
                        continue
                    
                    # Apply max price filter
                    if max_price is not None and price_val > max_price:
                        skipped_above_max += 1
                        logger.debug(f"[PREVIEW SERVICE] Item {it.get('id')} price {price_val} above max {max_price}")
                        continue
                    
                    filtered_items.append(it)
                except (ValueError, TypeError) as e:
                    logger.warning(f"[PREVIEW SERVICE] Error parsing price '{price}' (type: {type(price)}) for item {it.get('id')}: {e}")
                    # Skip items with invalid price when price filter is active
                    skipped_no_price += 1
                    continue
            items = filtered_items
            logger.info(f"[PREVIEW SERVICE] Price filter applied: items_after={len(items)}, "
                       f"skipped_no_price={skipped_no_price}, skipped_below_min={skipped_below_min}, skipped_above_max={skipped_above_max}, "
                       f"sort={sort}, is_price_sort={is_price_sort}")
            
            # If we have very few items after filtering and we're sorting by price, we might need to fetch more
            # This can happen when the price range is narrow and items in that range are not in the first batch
            if is_price_sort and len(items) < page_size and len(items) < page_size * 2:
                logger.warning(f"[PREVIEW SERVICE] Only {len(items)} items after price filtering with price sort. "
                             f"This might indicate that items in the price range are not in the first {fetch_size} items returned by eBay. "
                             f"Consider fetching more items or using a different approach.")
            
            # If sorting by price and we have filtered items, re-sort them by price
            # (eBay API should have sorted them, but we do it again to be safe)
            if sort in ("price_asc", "price_desc") and items:
                logger.info(f"[PREVIEW SERVICE] Re-sorting {len(items)} filtered items by price ({sort})")
                def price_sort_key(it):
                    price = it.get("price")
                    if price is None:
                        return float('inf') if sort == "price_asc" else float('-inf')
                    try:
                        if isinstance(price, str):
                            price_clean = price.replace('$', '').replace(',', '').strip()
                            return float(price_clean)
                        return float(price)
                    except (ValueError, TypeError):
                        return float('inf') if sort == "price_asc" else float('-inf')
                
                items.sort(key=price_sort_key, reverse=(sort == "price_desc"))
                logger.info(f"[PREVIEW SERVICE] Re-sorted items by price")

    # ----- Stock-based sorting -----
    if sort in ("stock_asc", "stock_desc"):
        missing_val = float("inf") if sort == "stock_asc" else float("-inf")
        def stock_key(it):
            v = it.get("stock_qty")
            try:
                return int(v) if v is not None else missing_val
            except (TypeError, ValueError):
                return missing_val
        items.sort(key=stock_key, reverse=(sort == "stock_desc"))

    # Calculate accurate pagination based on filtered results
    # IMPORTANT: When price filtering is active, we've already filtered items above
    # So we need to paginate the filtered results, not the raw API results
    total_filtered = len(items)
    
    if has_price_filter:
        # When price filtering, paginate the filtered results
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        
        logger.info(f"[PREVIEW SERVICE] Paginating filtered items: total_filtered={total_filtered}, page={page}, page_size={page_size}, start_idx={start_idx}, end_idx={end_idx}")
        
        # Get the items for this page
        paginated_items = items[start_idx:end_idx]
        
        # Calculate total pages based on filtered results
        total_pages = max(1, (total_filtered + page_size - 1) // page_size)
        
        # Estimate total: if we have a full page, there might be more items available
        # Use a conservative estimate based on the filtered count
        if len(paginated_items) == page_size:
            # If we got a full page, estimate there are at least 5x more items available
            estimated_total = max(total_filtered, len(paginated_items) * 5 * page)
            total_filtered = estimated_total
            total_pages = max(total_pages, (estimated_total + page_size - 1) // page_size)
        
        logger.info(f"[PREVIEW SERVICE] Price filter pagination: showing {len(paginated_items)} items on page {page} of {total_pages} (total estimated: {total_filtered})")
        items = paginated_items
    else:
        # Normal pagination: truncate to exactly page_size items for this page
        logger.info(f"[PREVIEW SERVICE] Before truncation: {len(items)} items, will truncate to {page_size}")
        items = items[:page_size]
        logger.info(f"[PREVIEW SERVICE] After truncation: {len(items)} items")
        
        # Use consistent total estimation based on search context
        if keyword_overlay is None or keyword_overlay.strip() == "":
            total_filtered = 50000  # Fixed total for browse mode
        else:
            total_filtered = 100000  # Fixed total for search mode
        
        # Only use actual results if they exceed our fixed estimates
        actual_results = len(items)
        if actual_results > total_filtered:
            total_filtered = actual_results
        
        total_pages = max(1, (total_filtered + page_size - 1) // page_size)
        logger.info(f"[PREVIEW SERVICE] Final pagination: total={total_filtered}, total_pages={total_pages}, "
                   f"page={page}, items_count={len(items)}")

    # 5) normalize final shape
    # Calculate has_more based on whether we have more items available
    if has_price_filter:
        # For price filtering, has_more means we have more filtered items beyond current page
        has_more = len(items) == page_size and (page * page_size) < total_filtered
    else:
        # Normal case: has_more if we got a full page and total exceeds current page
        has_more = len(items) == page_size and total_filtered > page * page_size
    
    final = {
        "items": items,
        "total": total_filtered,
        "total_pages": total_pages,
        "page": page,
        "page_size": page_size,
        "has_more": has_more,
        "debug": {"merged_rules": merged, "has_price_filter": has_price_filter, "filtered_count": len(items) if has_price_filter else total_filtered},
    }
    
    logger.info(f"[PREVIEW SERVICE] Final result: items_count={len(items)}, total={total_filtered}, "
                f"total_pages={total_pages}, page={page}, has_more={final['has_more']}")

    # 6) cache result
    set_cached(sponsor_id, key, page, sort, final)

    return final, {"cache": "miss", "fingerprint": key}
