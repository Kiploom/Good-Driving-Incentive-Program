# app/routes/test_catalog.py
"""
Temporary test catalog route to showcase eBay Browse API capabilities.
This page does not require login and demonstrates all filtering and sorting features.
"""
from flask import Blueprint, render_template, request, jsonify, current_app
from typing import Dict, Any, Optional, List
import requests
import os
from dotenv import load_dotenv, find_dotenv
from app.ebay_oauth import oauth_manager

load_dotenv(find_dotenv())

# Mapping of eBay condition values to normalized filter values
# eBay Browse API may return various formats, so we normalize them
CONDITION_MAPPING = {
    # Standard eBay condition values
    "NEW": "NEW",
    "NEW_OTHER": "NEW_OTHER",
    "NEW_WITH_DEFECTS": "NEW_WITH_DEFECTS",
    "MANUFACTURER_REFURBISHED": "MANUFACTURER_REFURBISHED",
    "CERTIFIED_REFURBISHED": "MANUFACTURER_REFURBISHED",  # Alias
    "SELLER_REFURBISHED": "SELLER_REFURBISHED",
    "USED_EXCELLENT": "USED_EXCELLENT",
    "USED_VERY_GOOD": "USED_VERY_GOOD",
    "USED_GOOD": "USED_GOOD",
    "USED_ACCEPTABLE": "USED_ACCEPTABLE",
    "FOR_PARTS_OR_NOT_WORKING": "FOR_PARTS_OR_NOT_WORKING",
    # Alternative formats eBay might return
    "NEW_OPEN_BOX": "NEW_OTHER",
    "REFURBISHED": "MANUFACTURER_REFURBISHED",
    "USED": "USED_GOOD",  # Default used condition
}

# Human-readable condition names
CONDITION_DISPLAY_NAMES = {
    "NEW": "New",
    "NEW_OTHER": "New Other (Open Box)",
    "NEW_WITH_DEFECTS": "New With Defects",
    "MANUFACTURER_REFURBISHED": "Manufacturer Refurbished",
    "SELLER_REFURBISHED": "Seller Refurbished",
    "USED_EXCELLENT": "Used - Excellent",
    "USED_VERY_GOOD": "Used - Very Good",
    "USED_GOOD": "Used - Good",
    "USED_ACCEPTABLE": "Used - Acceptable",
    "FOR_PARTS_OR_NOT_WORKING": "For Parts or Not Working",
}


def normalize_condition(condition: Optional[str]) -> Optional[str]:
    """Normalize eBay condition value to match our filter options."""
    if not condition:
        return None
    condition_upper = condition.strip().upper()
    # Direct match
    if condition_upper in CONDITION_MAPPING:
        return CONDITION_MAPPING[condition_upper]
    # Check if it's already a valid filter value
    if condition_upper in CONDITION_DISPLAY_NAMES:
        return condition_upper
    # Try mapping
    return CONDITION_MAPPING.get(condition_upper)


def get_condition_display_name(condition: Optional[str]) -> str:
    """Get human-readable name for a condition value."""
    if not condition:
        return ""
    normalized = normalize_condition(condition)
    if normalized:
        return CONDITION_DISPLAY_NAMES.get(normalized, condition)
    return condition


# Mapping of normalized condition values to eBay conditionIds
CONDITION_ID_MAP = {
    "NEW": "1000",
    "NEW_OTHER": "1500",
    "MANUFACTURER_REFURBISHED": "2000",
    "SELLER_REFURBISHED": "2500",
    "USED_EXCELLENT": "4000",
    "USED_VERY_GOOD": "4000",  # eBay uses 4000 for "Very Good"
    "USED_GOOD": "5000",
    "USED_ACCEPTABLE": "6000",
    "FOR_PARTS_OR_NOT_WORKING": "7000",
}


def get_ebay_api_url() -> str:
    """Get the eBay Browse API URL."""
    env = os.getenv("EBAY_ENV", "PRODUCTION").upper()
    explicit_base = os.getenv("EBAY_BROWSE_BASE")
    
    if explicit_base:
        base = explicit_base.rstrip("/")
    else:
        base = "https://api.sandbox.ebay.com" if env == "SANDBOX" else "https://api.ebay.com"
    
    return f"{base}/buy/browse/v1/item_summary/search"


def get_ebay_api_headers() -> Dict[str, str]:
    """Get headers for eBay API requests."""
    headers = {
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US"),
    }
    
    # Get bearer token from oauth_manager
    bearer_header = oauth_manager.get_bearer_header()
    if bearer_header:
        headers["Authorization"] = bearer_header
    else:
        # Fallback to direct token
        token = os.getenv("EBAY_OAUTH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    
    return headers


def build_price_filter(price_min: Optional[float], price_max: Optional[float]) -> Optional[str]:
    """Build eBay price filter string: price:[min..max]"""
    if price_min is None and price_max is None:
        return None
    
    min_str = "" if price_min is None else f"{price_min:.2f}".rstrip("0").rstrip(".")
    max_str = "" if price_max is None else f"{price_max:.2f}".rstrip("0").rstrip(".")
    
    return f"price:[{min_str}..{max_str}]"


def build_ebay_filters(
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    condition: Optional[str] = None,
    purchase_type: Optional[str] = None,
    free_shipping_only: bool = False,
) -> List[str]:
    """Build list of eBay filter expressions."""
    filters = []
    
    # Price filter
    price_filter = build_price_filter(price_min, price_max)
    if price_filter:
        filters.append(price_filter)
    
    # Condition filter
    if condition:
        normalized_condition = normalize_condition(condition)
        condition_id = CONDITION_ID_MAP.get(normalized_condition)
        if condition_id:
            filters.append(f"conditionIds:{{{condition_id}}}")
    
    # Purchase type filter
    if purchase_type == 'FIXED_PRICE':
        filters.append("buyingOptions:{FIXED_PRICE}")
    elif purchase_type == 'AUCTION':
        filters.append("buyingOptions:{AUCTION}")
    
    # Free shipping filter
    if free_shipping_only:
        filters.append("freeShippingOnly:true")
    
    return filters


def parse_ebay_response(response_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse eBay API response and format items."""
    items = []
    for item in response_data.get("itemSummaries", []):
        # Extract price
        price_obj = item.get("price", {})
        price_value = price_obj.get("value") if price_obj else None
        
        # Extract condition
        condition = item.get("condition", "")
        
        # Extract buying options
        buying_options = item.get("buyingOptions", [])
        
        # Extract shipping
        shipping_options = item.get("shippingOptions", [])
        free_shipping = any(opt.get("shippingCostType") == "FREE" for opt in shipping_options)
        
        # Extract image
        image_url = None
        if item.get("image"):
            image_url = item["image"].get("imageUrl")
        
        # Extract seller
        seller = {}
        if item.get("seller"):
            seller = {
                "username": item["seller"].get("username", ""),
                "feedbackScore": item["seller"].get("feedbackScore", 0),
            }
        
        formatted_item = {
            "item_id": item.get("itemId", ""),
            "title": item.get("title", ""),
            "url": item.get("itemWebUrl", ""),
            "image": image_url or "",
            "price": float(price_value) if price_value else None,
            "currency": price_obj.get("currency", "USD") if price_obj else "USD",
            "condition": condition,
            "category_id": item.get("categoryId", ""),
            "buyingOptions": buying_options,
            "shipping": {
                "free_shipping": free_shipping,
            },
            "seller": seller,
        }
        items.append(formatted_item)
    
    return {
        "items": items,
        "total": response_data.get("total"),
        "has_more": len(items) > 0,  # eBay doesn't provide has_more directly, estimate from items
    }


bp = Blueprint('test_catalog', __name__)

# Category ID to name mapping (from sponsor_catalog)
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


def get_category_names(category_ids: Optional[List[str]]) -> List[str]:
    """Convert category IDs to readable names."""
    if not category_ids:
        return []
    names = []
    for cat_id in category_ids:
        name = CATEGORY_MAP.get(str(cat_id), f"Category {cat_id}")
        names.append(name)
    return names


@bp.route('/testCatalog')
def test_catalog():
    """Display the test catalog page with all filters and sorting options."""
    return render_template('test_catalog.html')


@bp.route('/testCatalog/api/search')
def test_catalog_api():
    """
    API endpoint for fetching eBay items with comprehensive filtering and sorting.
    Supports all eBay Browse API features:
    - Keywords search
    - Category filtering
    - Price range filtering
    - Free shipping filter
    - Buy it now filter
    - Multiple sort options
    - Pagination
    """
    try:
        # Parse query parameters
        page = max(1, int(request.args.get('page', 1)))
        # Always return 24 items per page after filtering
        target_page_size = 24
        # Request more items initially to account for post-filtering
        api_page_size = max(1, min(100, int(request.args.get('page_size', 72))))
        sort = request.args.get('sort', 'best_match').strip()
        
        # Search query
        q = request.args.get('q', '').strip() or None
        
        # Category search (eBay only supports one category at a time)
        category_id = request.args.get('category_id', '').strip() or None
        
        # Price range
        price_min = request.args.get('price_min', '').strip()
        price_max = request.args.get('price_max', '').strip()
        try:
            price_min = float(price_min) if price_min else None
        except (ValueError, TypeError):
            price_min = None
        try:
            price_max = float(price_max) if price_max else None
        except (ValueError, TypeError):
            price_max = None
        
        # Boolean filters
        free_shipping_only = request.args.get('free_shipping', '').lower() == 'true'
        
        # Condition filter
        condition = request.args.get('condition', '').strip() or None
        
        # Purchase type filter (FIXED_PRICE for Buy It Now, AUCTION for Auction)
        purchase_type = request.args.get('purchase_type', '').strip() or None
        
        # Debug logging for price filters and sort
        current_app.logger.info(f"Price Filter Settings - price_min={price_min}, price_max={price_max}, sort={sort}")
        
        # eBay Browse API requires either q (keywords) or category_id
        if not q and not category_id:
            return jsonify({
                'error': 'Please provide either a search query (q) or a category ID. eBay Browse API requires at least one.',
                'items': [],
                'page': page,
                'page_size': page_size,
                'total': 0,
                'has_more': False,
            }), 400
        
        # Get eBay API URL and headers
        api_url = get_ebay_api_url()
        api_headers = get_ebay_api_headers()
        
        # Get the actual eBay API total first (before the main search loop)
        # This ensures we get the accurate total from eBay with filters applied
        total = None
        try:
            # Build search parameters
            api_params = {}
            if q:
                api_params['q'] = q
            if category_id:
                api_params['category_ids'] = category_id
            
            # Build filters using direct eBay API format
            api_filters = build_ebay_filters(
                price_min=price_min,
                price_max=price_max,
                condition=condition,  # Include condition in API call
                purchase_type=purchase_type,
                free_shipping_only=free_shipping_only,
            )
            
            if api_filters:
                api_params['filter'] = ",".join(api_filters)
                current_app.logger.info(f"Total API call - Full filter string: {api_params['filter']}")
            
            api_params['limit'] = 1  # Minimal to just get total
            api_params['offset'] = 0
            
            # Log the full API request for debugging
            current_app.logger.info(f"Total API call - Full params: {api_params}")
            
            # Make direct API call to get total
            api_response = requests.get(
                api_url,
                headers=api_headers,
                params=api_params,
                timeout=10
            )
            api_response.raise_for_status()
            api_json = api_response.json()
            
            # Extract total from eBay API response
            total = api_json.get('total')
            current_app.logger.info(f"eBay API Total extracted from direct call: {total} (with price_min={price_min}, price_max={price_max}, condition={condition}, purchase_type={purchase_type})")
            
        except Exception as e:
            current_app.logger.error(f"Error getting total from eBay API: {e}", exc_info=True)
            total = None
        
        # Collect filtered items across multiple API pages to ensure we have enough for the requested page
        # We need to accumulate items starting from page 1 to properly paginate filtered results
        all_filtered_items = []
        current_api_page = 1
        # Increase max pages when we have price filters, as post-filtering may remove many items
        # Especially important for price_desc + price_max where early pages are all filtered out
        has_price_filter = price_min is not None or price_max is not None
        # Use even more pages when we have both price filter and price sorting (worst case scenario)
        has_price_sort = sort in ['price_asc', 'price_desc']
        max_pages_to_fetch = 100 if (has_price_filter and has_price_sort) else (50 if has_price_filter else 10)
        pages_fetched = 0
        api_has_more = True
        
        # Track raw items seen for total estimation when price filters are active
        # eBay's API may not respect price filters in the total count, so we estimate based on ratio
        total_raw_items_seen = 0
        debug = {}
        consecutive_empty_batches = 0  # Track consecutive empty batches
        
        # Calculate how many filtered items we need total (for all pages up to and including requested page)
        # We need enough items for the requested page, plus one more page to determine if there are more pages
        items_needed = page * target_page_size
        items_to_fetch = items_needed + target_page_size  # Fetch one extra page to check has_more
        
        current_app.logger.info(f"Starting item accumulation - need {items_needed} items for page {page}, fetching up to {items_to_fetch} items, max_pages={max_pages_to_fetch}, has_price_filter={has_price_filter}")
        
        # Continue fetching until we have enough items OR we've exhausted available pages OR hit max limit
        # For price filters, be more aggressive - continue even if api_has_more is False (might need to skip many pages)
        # We fetch one extra page worth of items to determine if there are more pages available
        while len(all_filtered_items) < items_to_fetch and pages_fetched < max_pages_to_fetch:
            # Only check api_has_more if we don't have price filters (price filters may need to skip many pages)
            if not has_price_filter and not api_has_more:
                current_app.logger.info(f"API has no more pages and no price filter, stopping")
                break
            
            # Build API parameters for this page
            api_params = {}
            if q:
                api_params['q'] = q
            if category_id:
                api_params['category_ids'] = category_id
            
            # Build filters using direct eBay API format
            api_filters = build_ebay_filters(
                price_min=price_min,
                price_max=price_max,
                condition=condition,
                purchase_type=purchase_type,
                free_shipping_only=free_shipping_only,
            )
            
            if api_filters:
                api_params['filter'] = ",".join(api_filters)
            
            # Pagination
            api_params['limit'] = api_page_size
            api_params['offset'] = (current_api_page - 1) * api_page_size
            
            # Sort mapping
            sort_map = {
                "best_match": None,     # default relevance
                "price_asc": "price",
                "price_desc": "-price",
                "newest": "-new",
            }
            sort_param = sort_map.get(sort)
            if sort_param:
                api_params['sort'] = sort_param
            
            # Log eBay API search parameters with detailed price/sort info
            current_app.logger.info(f"eBay API Search - Page {current_api_page}:")
            current_app.logger.info(f"  Params: {api_params}")
            current_app.logger.info(f"  Price filters: price_min={price_min}, price_max={price_max}")
            current_app.logger.info(f"  Sort: {sort}")
            current_app.logger.info(f"  Page size: {api_page_size}")
            
            # Perform direct API call for current page
            try:
                api_response = requests.get(
                    api_url,
                    headers=api_headers,
                    params=api_params,
                    timeout=10
                )
                api_response.raise_for_status()
                api_json = api_response.json()
                
                # Parse response
                result = parse_ebay_response(api_json)
                
                # Determine has_more based on items returned and total
                # If we got fewer items than requested, likely no more pages
                items_returned = len(result.get('items', []))
                api_has_more = items_returned >= api_page_size
                
                # Also check against total if available
                if total is not None:
                    items_seen_so_far = (current_api_page - 1) * api_page_size + items_returned
                    api_has_more = items_seen_so_far < total
                    current_app.logger.info(f"API has_more check - items_returned={items_returned}, api_page_size={api_page_size}, items_seen_so_far={items_seen_so_far}, total={total}, api_has_more={api_has_more}")
                else:
                    current_app.logger.info(f"API has_more check (no total) - items_returned={items_returned}, api_page_size={api_page_size}, api_has_more={api_has_more}")
                
                result['has_more'] = api_has_more
                
            except Exception as e:
                current_app.logger.error(f"Error calling eBay API for page {current_api_page}: {e}", exc_info=True)
                result = {
                    "items": [],
                    "total": None,
                    "has_more": False,
                }
            
            # Log search results with price info
            raw_items_count = len(result.get('items', []))
            raw_items_prices = [item.get('price') for item in result.get('items', []) if item.get('price') is not None]
            current_app.logger.info(f"eBay API Response - Page {current_api_page}:")
            current_app.logger.info(f"  Items returned: {raw_items_count}")
            current_app.logger.info(f"  Prices from API (first 10): {raw_items_prices[:10]}")
            current_app.logger.info(f"  All prices from API: {raw_items_prices}")
            current_app.logger.info(f"  Has more: {result.get('has_more', False)}")
            
            raw_items = result.get('items', [])
            api_has_more = result.get('has_more', False)
            
            # Track total raw items seen for total estimation when price filters are active
            total_raw_items_seen += len(raw_items)
            
            if not debug:
                debug = result.get('debug', {})
            
            # Don't break on empty raw_items if we have price filters and haven't gotten enough items yet
            # This handles the case where price_desc + price_max causes early pages to be empty
            if not raw_items:
                if has_price_filter and len(all_filtered_items) < items_to_fetch and pages_fetched < max_pages_to_fetch:
                    current_app.logger.info(f"No items returned from API page {current_api_page}, but continuing due to price filter (have {len(all_filtered_items)}/{items_needed} items, pages_fetched={pages_fetched})...")
                    current_api_page += 1
                    pages_fetched += 1
                    # Update api_has_more from the result
                    api_has_more = result.get('has_more', False)
                    continue
                elif not has_price_filter:
                    current_app.logger.info(f"No items returned and no price filter, stopping")
                    break
                else:
                    current_app.logger.warning(f"No items returned, stopping despite price filter (pages_fetched={pages_fetched}, max={max_pages_to_fetch})")
                    break
            
            # Post-filter for auction-only if requested (condition filtering is handled by provider)
            if purchase_type == 'AUCTION':
                filtered_batch = [
                    item for item in raw_items
                    if 'AUCTION' in (item.get('buyingOptions') or []) and 'FIXED_PRICE' not in (item.get('buyingOptions') or [])
                ]
            else:
                filtered_batch = raw_items
            
            # Post-filter for price range (eBay API might not apply price filters correctly)
            if (price_min is not None or price_max is not None) and filtered_batch:
                price_filtered = []
                for item in filtered_batch:
                    item_price = item.get('price')
                    if item_price is None:
                        continue  # Skip items without prices
                    try:
                        price_val = float(item_price)
                        # Check if price is within range
                        if price_min is not None and price_val < price_min:
                            continue
                        if price_max is not None and price_val > price_max:
                            continue
                        price_filtered.append(item)
                    except (ValueError, TypeError):
                        # Skip items with invalid prices
                        continue
                filtered_batch = price_filtered
                filtered_out = len(raw_items) - len(filtered_batch)
                current_app.logger.info(f"Price post-filter applied - {len(raw_items)} -> {len(filtered_batch)} items (filtered out {filtered_out}, min={price_min}, max={price_max})")
                
                # Track if we got an empty batch after filtering
                if len(filtered_batch) == 0:
                    consecutive_empty_batches += 1
                    current_app.logger.warning(f"Empty batch after price filtering (consecutive: {consecutive_empty_batches})")
                else:
                    consecutive_empty_batches = 0
            
            # Additional post-filter for condition to ensure exact matching after normalization
            # This ensures that even if eBay returns condition variations (e.g., CERTIFIED_REFURBISHED vs MANUFACTURER_REFURBISHED),
            # we filter correctly by normalizing both the filter value and item conditions
            if condition and filtered_batch:
                normalized_filter_condition = normalize_condition(condition)
                if normalized_filter_condition:
                    filtered_batch = [
                        item for item in filtered_batch
                        if normalize_condition(item.get('condition', '')) == normalized_filter_condition
                    ]
                else:
                    # Fallback: case-insensitive string matching if normalization fails
                    condition_upper = condition.strip().upper()
                    filtered_batch = [
                        item for item in filtered_batch
                        if (item.get('condition') or '').strip().upper() == condition_upper
                    ]
            
            all_filtered_items.extend(filtered_batch)
            current_api_page += 1
            pages_fetched += 1
            
            # Log progress
            current_app.logger.info(f"Accumulation progress - Page {current_api_page-1}: {len(filtered_batch)} items added, total accumulated: {len(all_filtered_items)}/{items_to_fetch}")
            
            # If we've had many consecutive empty batches but still need more items, continue fetching
            # This is especially important for price_desc + price_max where early pages are all filtered out
            if consecutive_empty_batches >= 3 and len(all_filtered_items) < items_to_fetch:
                current_app.logger.warning(f"Many consecutive empty batches ({consecutive_empty_batches}), but continuing to fetch more pages...")
                # Don't break - continue the loop to fetch more pages
            
            # Additional check: if we have price filters and very few items, increase fetch limit
            if has_price_filter and len(all_filtered_items) < items_to_fetch and pages_fetched >= max_pages_to_fetch - 10:
                current_app.logger.warning(f"Approaching max pages limit ({pages_fetched}/{max_pages_to_fetch}) but only have {len(all_filtered_items)}/{items_to_fetch} items. Consider increasing limit.")
        
        # Apply sorting to accumulated items if needed (for price sorting)
        # eBay API should handle sorting, but we need to re-sort after accumulating multiple pages
        # This is especially important when we have price filters, as eBay might return items
        # sorted by price but we need to re-sort after filtering
        if sort in ['price_asc', 'price_desc']:
            def get_price_for_sort(item):
                price = item.get('price')
                try:
                    return float(price) if price is not None else float('inf') if sort == 'price_desc' else float('-inf')
                except (ValueError, TypeError):
                    return float('inf') if sort == 'price_desc' else float('-inf')
            
            reverse = (sort == 'price_desc')
            all_filtered_items.sort(key=get_price_for_sort, reverse=reverse)
            current_app.logger.info(f"Re-sorted {len(all_filtered_items)} items by price ({sort})")
        
        # Log final accumulation result
        current_app.logger.info(f"Final accumulation - Got {len(all_filtered_items)} filtered items from {pages_fetched} API pages (needed {items_needed} for page {page}, fetched up to {items_to_fetch})")
        
        # Estimate total when price filters are active (eBay API may not respect price filters in total count)
        if has_price_filter and total is not None and total_raw_items_seen > 0 and len(all_filtered_items) > 0:
            # Calculate the ratio of filtered items to raw items we've seen
            # This gives us an estimate of what percentage of items pass the price filter
            filter_ratio = len(all_filtered_items) / total_raw_items_seen
            # Estimate total filtered items = original total * filter ratio
            # This assumes the ratio we've seen is representative of the entire dataset
            estimated_total = int(total * filter_ratio)
            current_app.logger.info(f"Price filter total estimation - Original total: {total}, Raw items seen: {total_raw_items_seen}, Filtered items: {len(all_filtered_items)}, Ratio: {filter_ratio:.4f}, Estimated total: {estimated_total}")
            total = estimated_total
        
        # Extract the items for the requested page (24 items)
        start_idx = (page - 1) * target_page_size
        end_idx = start_idx + target_page_size
        items = all_filtered_items[start_idx:end_idx]
        
        # Determine if there are more pages available
        # Calculate total pages based on total count
        total_pages = None
        if total is not None:
            total_pages = max(1, (total + target_page_size - 1) // target_page_size)  # Ceiling division
        
        # We have more if:
        # 1. We have enough items for the next page (we fetched one extra page worth) OR
        # 2. We haven't exceeded the total pages (if total is known) AND API has more
        has_enough_items = len(all_filtered_items) > end_idx  # We have more than what's needed for current page
        within_total_pages = total_pages is None or page < total_pages
        
        if total_pages is not None:
            # When we know the total, check both accumulated items and total pages
            # If we have enough accumulated items, we definitely have more
            # Otherwise, check if we're within total pages and API has more
            has_more = has_enough_items or (within_total_pages and api_has_more)
            current_app.logger.info(f"Pagination check - page={page}, total_pages={total_pages}, accumulated_items={len(all_filtered_items)}, end_idx={end_idx}, has_enough_items={has_enough_items}, within_total_pages={within_total_pages}, api_has_more={api_has_more}, has_more={has_more}")
        else:
            # When total is unknown, use accumulated items and API has_more
            has_more = has_enough_items or (api_has_more and pages_fetched < max_pages_to_fetch)
            current_app.logger.info(f"Pagination check (no total) - page={page}, accumulated_items={len(all_filtered_items)}, end_idx={end_idx}, has_enough_items={has_enough_items}, api_has_more={api_has_more}, pages_fetched={pages_fetched}, max_pages={max_pages_to_fetch}, has_more={has_more}")
        
        # Get category name for the selected category
        filter_category_name = None
        if category_id:
            names = get_category_names([category_id])
            filter_category_name = names[0] if names else None
        
        # Format items for display
        formatted_items = []
        item_prices = []  # Collect prices for debugging
        for item in items:
            item_category_id = item.get('category_id')
            item_category_name = None
            if item_category_id:
                item_category_name = CATEGORY_MAP.get(str(item_category_id), f"Category {item_category_id}")
            
            # Normalize and format condition for display
            raw_condition = item.get('condition', '')
            normalized_condition = normalize_condition(raw_condition)
            condition_display = get_condition_display_name(raw_condition) if raw_condition else ''
            
            item_price = item.get('price')
            # Ensure price is a number, not a string
            try:
                if item_price is not None:
                    item_price = float(item_price)
            except (ValueError, TypeError):
                item_price = None
            
            item_prices.append(item_price)  # Collect for debugging
            
            formatted_items.append({
                'id': item.get('id'),
                'title': item.get('title', 'No title'),
                'subtitle': item.get('subtitle', ''),
                'price': item_price,
                'currency': item.get('currency', 'USD'),
                'image': item.get('image', ''),
                'url': item.get('url', ''),
                'shipping': item.get('shipping'),
                'condition': normalized_condition or raw_condition,  # Use normalized value for consistency
                'condition_display': condition_display,  # Human-readable name
                'category_id': item_category_id,
                'category_name': item_category_name,
                'brand': item.get('brand', ''),
                'seller': item.get('seller', {}),
                'buyingOptions': item.get('buyingOptions', []),
                'estimated_quantity': item.get('estimated_quantity'),
                'availability_threshold': item.get('availability_threshold'),
            })
        
        # Debug logging: Print prices in order and filter/sort settings
        current_app.logger.info(f"=== PRICE DEBUG INFO ===")
        current_app.logger.info(f"Price Filter: min={price_min}, max={price_max}")
        current_app.logger.info(f"Sort Order: {sort}")
        current_app.logger.info(f"Number of items: {len(formatted_items)}")
        current_app.logger.info(f"Prices in order (first 10): {item_prices[:10]}")
        current_app.logger.info(f"All prices: {item_prices}")
        current_app.logger.info(f"Price range: min={min([p for p in item_prices if p is not None] or [0])}, max={max([p for p in item_prices if p is not None] or [0])}")
        current_app.logger.info(f"=== END PRICE DEBUG ===")
        
        # Debug logging before returning response
        current_app.logger.info(f"Test Catalog Response - total={total}, total_type={type(total)}, items_count={len(formatted_items)}, has_more={has_more}")
        
        return jsonify({
            'items': formatted_items,
            'page': page,
            'page_size': target_page_size,
            'total': total,
            'has_more': has_more,
            'category_id': category_id,
            'category_name': filter_category_name,
            'debug': debug,
        })
    
    except Exception as e:
        current_app.logger.error(f"Error in test catalog API: {e}", exc_info=True)
        return jsonify({
            'error': str(e),
            'items': [],
            'page': 1,
            'page_size': 24,
            'total': 0,
            'has_more': False,
        }), 500

