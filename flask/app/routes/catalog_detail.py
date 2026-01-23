"""
Catalog detail view optimization endpoint.

Provides instant-loading item details with:
- Dedicated detail endpoint with 15-minute caching
- Stale-while-revalidate background refresh
- ETags and Cache-Control headers for CDN/browser caching
- Lightweight response format for fast delivery
"""

from flask import Blueprint, jsonify, request, Response
from flask_login import login_required
import hashlib
import json
import logging
import threading
from queue import SimpleQueue
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from app.sponsor_catalog.providers.ebay_provider import EbayProvider
from app.driver_points_catalog.services.points_service import price_to_points

logger = logging.getLogger(__name__)

bp = Blueprint("catalog_detail", __name__)

# Background refresh queue
_refresh_queue = SimpleQueue()
_refresh_worker_started = False


def _start_background_worker():
    """Start background worker thread for cache refresh."""
    global _refresh_worker_started
    if _refresh_worker_started:
        return
    
    def worker():
        while True:
            try:
                task = _refresh_queue.get(timeout=1)
                if task is None:  # Shutdown signal
                    break
                
                # Execute refresh
                cache_key, fetch_func = task
                try:
                    result = fetch_func()
                    # Update cache with new data
                    from app.utils.cache import get_cache
                    cache = get_cache()
                    cache.set(cache_key, result, 900)  # 15 minutes
                    logger.debug(f"Background refresh completed: {cache_key}")
                except Exception as e:
                    logger.warning(f"Background refresh failed: {e}")
            except:
                pass  # Timeout, continue
    
    thread = threading.Thread(target=worker, daemon=True, name="cache-refresh-worker")
    thread.start()
    _refresh_worker_started = True
    logger.info("Started background cache refresh worker")


def _get_cached_with_refresh(
    cache_key: str,
    fetch_func: callable,
    ttl: int = 900,
    refresh_after: int = 300
) -> tuple[Any, bool]:
    """
    Get cached value with stale-while-revalidate behavior.
    
    Args:
        cache_key: Cache key
        fetch_func: Function to fetch fresh data
        ttl: Total TTL (15 minutes = 900s)
        refresh_after: Trigger background refresh after (5 minutes = 300s)
    
    Returns:
        (data, is_stale) tuple
    """
    try:
        from app.utils.cache import get_cache
        cache = get_cache()
        
        # Try to get from cache
        cached = cache.get(cache_key)
        
        if cached is not None:
            cached_time = cached.get('_cached_at')
            
            if cached_time:
                age = (datetime.utcnow() - datetime.fromisoformat(cached_time)).total_seconds()
                
                # If older than refresh_after, trigger background refresh
                if age > refresh_after:
                    logger.debug(f"Cache stale ({age:.0f}s old), triggering background refresh")
                    _start_background_worker()
                    _refresh_queue.put((cache_key, fetch_func))
                    return cached, True
                
                return cached, False
        
        # Cache miss - fetch synchronously
        logger.debug(f"Cache miss: {cache_key}")
        result = fetch_func()
        result['_cached_at'] = datetime.utcnow().isoformat()
        cache.set(cache_key, result, ttl)
        return result, False
        
    except Exception as e:
        logger.error(f"Cache error: {e}", exc_info=True)
        # Fallback to direct fetch
        return fetch_func(), False


def _compute_etag(data: Dict[str, Any]) -> str:
    """Compute ETag from data content."""
    # Remove timestamp fields for stable hash
    stable_data = {k: v for k, v in data.items() if not k.startswith('_')}
    content = json.dumps(stable_data, sort_keys=True)
    return hashlib.md5(content.encode()).hexdigest()


@bp.route("/catalog/item/<provider>/<path:item_id>/detail", methods=["GET"])
@login_required
def get_item_detail(provider: str, item_id: str):
    """
    Get detailed item information optimized for instant loading.
    
    Features:
    - 15-minute cache TTL with stale-while-revalidate
    - ETag support for 304 responses
    - Cache-Control headers for CDN/browser caching
    - Lightweight response (heavy fields on demand)
    
    Response format:
    {
        "id": "item_id",
        "title": "Product Title",
        "price": 29.99,  // or "points" for drivers
        "quantity": 5,
        "availability": "IN_STOCK",
        "canonical_url": "https://...",
        "images": ["url1", "url2", ...],
        "short_desc": "Brief description",
        "long_desc": "Full description (optional)",
        "item_specifics": {...},
        "condition": "New",
        "brand": "BrandName",
        "variants": {...}  // if applicable
    }
    """
    # Validate provider
    if provider not in ['ebay']:
        return jsonify({"error": "Invalid provider"}), 400
    
    # URL decode item_id
    from urllib.parse import unquote
    item_id = unquote(item_id)
    
    # Determine if user is driver or sponsor
    from flask import session
    is_driver = bool(session.get('driver_id'))
    sponsor_id = session.get('sponsor_id')
    
    # Build cache key
    cache_key_base = f"detail:{provider}:{item_id}"
    if is_driver and sponsor_id:
        cache_key = f"{cache_key_base}:driver:{sponsor_id}"
    else:
        cache_key = cache_key_base
    
    # Fetch function
    def fetch_detail():
        try:
            ebay = EbayProvider()
            item_data = ebay.get_item_details(item_id)
            
            if not item_data:
                return None
            
            # Build response
            response_data = {
                "id": item_data.get("id"),
                "title": item_data.get("title"),
                "subtitle": item_data.get("subtitle"),
                "condition": item_data.get("condition"),
                "brand": item_data.get("brand"),
                "canonical_url": item_data.get("url"),
                "images": [item_data.get("image")] + item_data.get("additional_images", []),
                "short_desc": item_data.get("subtitle") or item_data.get("title"),
                "item_specifics": item_data.get("item_specifics", {}),
                "variants": item_data.get("variants", {}),
                "variation_details": item_data.get("variation_details", []),
            }
            
            # Add price or points based on user type
            if is_driver and sponsor_id:
                # Convert price to points for drivers
                price = item_data.get("price")
                if price:
                    try:
                        points = price_to_points(sponsor_id, float(price))
                        response_data["points"] = points
                        response_data["price_usd"] = price  # Keep original for reference
                    except Exception as e:
                        logger.warning(f"Error converting price to points: {e}")
                        response_data["points"] = None
                else:
                    response_data["points"] = None
            else:
                # Sponsors see price
                response_data["price"] = item_data.get("price")
                response_data["currency"] = item_data.get("currency", "USD")
            
            # Availability info
            response_data["availability"] = "IN_STOCK"  # Default
            response_data["quantity"] = item_data.get("estimated_quantity")
            
            if item_data.get("availability_threshold"):
                threshold = str(item_data["availability_threshold"]).upper()
                if "OUT_OF_STOCK" in threshold:
                    response_data["availability"] = "OUT_OF_STOCK"
                elif "LIMITED" in threshold or "LOW" in threshold:
                    response_data["availability"] = "LIMITED"
            
            # Long description (optional, may be expensive)
            # Only include if explicitly requested or if small
            long_desc = item_data.get("description", "")
            if len(long_desc) < 5000 or request.args.get("include_long_desc") == "1":
                response_data["long_desc"] = long_desc
            
            return response_data
            
        except Exception as e:
            logger.error(f"Error fetching item detail: {e}", exc_info=True)
            return None
    
    # Get cached data with stale-while-revalidate
    data, is_stale = _get_cached_with_refresh(
        cache_key,
        fetch_detail,
        ttl=900,  # 15 minutes
        refresh_after=300  # 5 minutes
    )
    
    if data is None:
        return jsonify({"error": "Item not found"}), 404
    
    # Compute ETag
    etag = _compute_etag(data)
    
    # Check If-None-Match header for 304 response
    client_etag = request.headers.get('If-None-Match')
    if client_etag == etag:
        response = Response(status=304)
        response.headers['ETag'] = etag
        response.headers['Cache-Control'] = 'public, max-age=60'
        return response
    
    # Build response
    response = jsonify(data)
    response.headers['ETag'] = etag
    response.headers['Cache-Control'] = 'public, max-age=60'
    
    # Add age header if stale
    if is_stale:
        response.headers['X-Cache-Status'] = 'stale'
    else:
        response.headers['X-Cache-Status'] = 'fresh'
    
    return response


@bp.route("/catalog/item/<provider>/<path:item_id>/images", methods=["GET"])
@login_required
def get_item_images(provider: str, item_id: str):
    """
    Get item image gallery (CDN-friendly).
    Separate endpoint for lazy loading images.
    """
    from urllib.parse import unquote
    item_id = unquote(item_id)
    
    if provider != 'ebay':
        return jsonify({"error": "Invalid provider"}), 400
    
    # Use same caching as detail
    cache_key = f"images:{provider}:{item_id}"
    
    def fetch_images():
        try:
            ebay = EbayProvider()
            item_data = ebay.get_item_details(item_id)
            
            if not item_data:
                return None
            
            images = [item_data.get("image")] + item_data.get("additional_images", [])
            images = [img for img in images if img]  # Remove None/empty
            
            return {"images": images}
        except Exception as e:
            logger.error(f"Error fetching images: {e}")
            return None
    
    data, _ = _get_cached_with_refresh(cache_key, fetch_images, ttl=900)
    
    if data is None:
        return jsonify({"error": "Item not found"}), 404
    
    response = jsonify(data)
    response.headers['Cache-Control'] = 'public, max-age=86400'  # 24 hours for images
    return response

