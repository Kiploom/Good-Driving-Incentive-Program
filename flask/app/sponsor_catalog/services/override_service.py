# app/sponsor_catalog/services/override_service.py
from __future__ import annotations

from sqlalchemy import case
import logging

from app.extensions import db
from app.models_sponsor_catalog import (
    SponsorCatalogInclusion,
    SponsorCatalogExclusion,
    BlacklistedProduct,
    SponsorPinnedProduct,
)

logger = logging.getLogger(__name__)

def _nulls_last(col):
    # Emulate "ORDER BY col ASC NULLS LAST" on MySQL:
    #   1) rows with NULL sort key go last
    #   2) non-NULL sort by col ASC
    return case((col.is_(None), 1), else_=0), col.asc()

def list_pinned_inclusions(sponsor_id: str):
    """
    Get pinned products for a sponsor.
    Uses SponsorPinnedProduct table which has ItemTitle and ItemImageURL.
    Falls back to SponsorCatalogInclusion for backward compatibility.
    """
    # Try SponsorPinnedProduct first (has ItemTitle and ItemImageURL)
    pinned_products = (
        SponsorPinnedProduct.query
        .filter_by(SponsorID=sponsor_id)
        .order_by(*_nulls_last(SponsorPinnedProduct.PinRank))
        .all()
    )
    
    logger.info(f"[OVERRIDE SERVICE] Found {len(pinned_products)} pinned products from SponsorPinnedProduct for sponsor {sponsor_id}")
    
    # Also check SponsorCatalogInclusion for backward compatibility
    legacy_pinned = (
        SponsorCatalogInclusion.query
        .filter_by(sponsor_id=sponsor_id, is_pinned=True)
        .order_by(*_nulls_last(SponsorCatalogInclusion.pin_rank))
        .all()
    )
    
    logger.info(f"[OVERRIDE SERVICE] Found {len(legacy_pinned)} legacy pinned items from SponsorCatalogInclusion")
    
    # Return SponsorPinnedProduct items (they have ItemTitle and ItemImageURL)
    return pinned_products

def list_inclusions(sponsor_id: str):
    return (
        SponsorCatalogInclusion.query
        .filter_by(sponsor_id=sponsor_id, is_pinned=False)
        .all()
    )

def list_exclusions(sponsor_id: str):
    return (
        SponsorCatalogExclusion.query
        .filter_by(sponsor_id=sponsor_id)
        .all()
    )

def list_blacklisted(sponsor_id: str):
    """Get all blacklisted products for a sponsor."""
    return (
        BlacklistedProduct.query
        .filter_by(SponsorID=sponsor_id)
        .all()
    )

def compose_with_inclusions_exclusions(sponsor_id: str, items: list[dict], exclude_pinned: bool = False) -> list[dict]:
    """
    Apply overrides to a provider result list:
      - Pinned inclusions are placed first (by pin_rank, NULLs last) - UNLESS exclude_pinned=True
      - Non-pinned inclusions are inserted next (deduped)
      - Remaining provider items follow, excluding anything explicitly excluded OR blacklisted
    
    Args:
        exclude_pinned: If True, skip pinned/recommended products (e.g., when browsing by category)
    """
    pinned_rows = list_pinned_inclusions(sponsor_id)
    inc_rows    = list_inclusions(sponsor_id)
    exc_rows    = list_exclusions(sponsor_id)
    blacklist_rows = list_blacklisted(sponsor_id)

    # Handle both SponsorPinnedProduct (ItemID) and SponsorCatalogInclusion (item_id)
    pinned_ids = [getattr(r, 'ItemID', None) or getattr(r, 'item_id', None) for r in pinned_rows if getattr(r, 'ItemID', None) or getattr(r, 'item_id', None)]
    inc_ids    = [getattr(r, 'ItemID', None) or getattr(r, 'item_id', None) for r in inc_rows if getattr(r, 'ItemID', None) or getattr(r, 'item_id', None)]
    exc_ids    = set(getattr(r, 'ItemID', None) or getattr(r, 'item_id', None) for r in exc_rows if getattr(r, 'ItemID', None) or getattr(r, 'item_id', None))
    blacklist_ids = set(r.ItemID for r in blacklist_rows)  # Use ItemID for BlacklistedProduct

    logger.info(f"[OVERRIDE SERVICE] compose_with_inclusions_exclusions: pinned_ids={len(pinned_ids)}, inc_ids={len(inc_ids)}, exc_ids={len(exc_ids)}, blacklist_ids={len(blacklist_ids)}")

    # index incoming items by id for quick lookup
    by_id = {it.get("id"): it for it in items if it.get("id")}
    logger.info(f"[OVERRIDE SERVICE] Indexed {len(by_id)} items by id")

    out: list[dict] = []

    # 1) pinned (in pin_rank order), if present in provider results keep provider data; else synthesize minimal card
    # Skip pinned items if exclude_pinned is True (e.g., when browsing by category)
    if exclude_pinned:
        logger.info(f"[OVERRIDE SERVICE] Skipping pinned items (exclude_pinned=True, category browsing active)")
    else:
        logger.info(f"[OVERRIDE SERVICE] Including pinned items (exclude_pinned=False)")
    
    for r in pinned_rows:
        if exclude_pinned:
            logger.debug(f"[OVERRIDE SERVICE] Skipping pinned item {getattr(r, 'ItemID', None) or getattr(r, 'item_id', None)} (category browsing)")
            continue
        item_id = getattr(r, 'ItemID', None) or getattr(r, 'item_id', None)
        if not item_id:
            logger.warning(f"[OVERRIDE SERVICE] Pinned row missing item_id: {r}")
            continue
            
        # Skip if blacklisted
        if item_id in blacklist_ids:
            logger.debug(f"[OVERRIDE SERVICE] Skipping blacklisted pinned item {item_id}")
            continue
            
        # Try to get title/image from SponsorPinnedProduct, fallback to provider data or minimal dict
        item_title = getattr(r, 'ItemTitle', None) or getattr(r, 'item_title', None) or "(Pinned item)"
        item_image = getattr(r, 'ItemImageURL', None) or getattr(r, 'item_image_url', None)
        
        it = by_id.get(item_id)
        if not it:
            # Create minimal item dict if not in provider results
            it = {
                "id": item_id,
                "title": item_title,
                "image": item_image,
                "price": None,
                "is_pinned": True  # Mark as pinned
            }
        else:
            # Use provider data but ensure title/image are set if missing
            if not it.get("title") and item_title:
                it["title"] = item_title
            if not it.get("image") and item_image:
                it["image"] = item_image
            # Mark as pinned
            it["is_pinned"] = True
        
        out.append(it)
        logger.debug(f"[OVERRIDE SERVICE] Added pinned item {item_id}: {it.get('title', '')[:50]}")

    # 2) non-pinned inclusions (skip ones already pinned or blacklisted)
    for iid in inc_ids:
        if iid in pinned_ids or iid in blacklist_ids:
            continue
        it = by_id.get(iid) or {"id": iid, "title": "(Included item)", "price": None}
        # avoid duplicates
        if not any(x.get("id") == iid for x in out):
            out.append(it)

    # 3) remaining provider items (exclude pinned/included already present, explicit exclusions, AND blacklisted products)
    skip = set(pinned_ids) | set(inc_ids) | exc_ids | blacklist_ids
    
    # If exclude_pinned is True, also skip any items that are in pinned_ids (even if they came from provider)
    if exclude_pinned:
        logger.info(f"[OVERRIDE SERVICE] Excluding {len(pinned_ids)} pinned items from provider results (category browsing active)")
    
    for it in items:
        iid = it.get("id")
        if not iid:
            continue
        
        # Skip if in skip set OR if exclude_pinned and this is a pinned item
        if iid in skip:
            if exclude_pinned and iid in pinned_ids:
                logger.debug(f"[OVERRIDE SERVICE] Skipping provider item {iid} (pinned item, category browsing active)")
            continue
        
        # Double-check: if exclude_pinned and this item is pinned, skip it
        if exclude_pinned and iid in pinned_ids:
            logger.debug(f"[OVERRIDE SERVICE] Skipping provider item {iid} (pinned item, category browsing active)")
            continue
            
        out.append(it)

    logger.info(f"[OVERRIDE SERVICE] Final output: {len(out)} items (exclude_pinned={exclude_pinned})")
    return out
