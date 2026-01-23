# app/sponsor_catalog/providers/ebay_provider.py
from __future__ import annotations

import os
import json
import logging
from typing import Dict, Any, Optional, List, Tuple
from threading import Lock

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv, find_dotenv

from app.sponsor_catalog.policies import is_explicit, ADULT_CATEGORY_IDS
from app.ebay_oauth import get_ebay_token

# Load a .env regardless of current working directory
load_dotenv(find_dotenv())

logger = logging.getLogger(__name__)

# Try to import cache helper
try:
    from app.utils.cache import get_cache, make_cache_key
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False
    logger.warning("Cache utils not available - caching disabled")


class EbayProvider:
    """
    Minimal eBay Browse provider with robust rule handling.

    Environment/config:
    - Env selection: PRODUCTION (default) or SANDBOX via EBAY_ENV
    - OAuth token: EBAY_OAUTH_TOKEN (client-credentials "application" token)
    - Marketplace: EBAY_MARKETPLACE_ID (defaults to EBAY_US)
    - Optional explicit base override: EBAY_BROWSE_BASE
    - Returns structured debug info instead of throwing on HTTP errors
    """

    def __init__(self, app=None):
        cfg = getattr(app, "config", {}) if app else {}

        env = (cfg.get("EBAY_ENV") or os.getenv("EBAY_ENV") or "PRODUCTION").upper()
        explicit_base = cfg.get("EBAY_BROWSE_BASE") or os.getenv("EBAY_BROWSE_BASE")

        if explicit_base:
            base = explicit_base.rstrip("/")
        else:
            base = "https://api.sandbox.ebay.com" if env == "SANDBOX" else "https://api.ebay.com"

        # Browse Search endpoint
        self.search_url = f"{base}/buy/browse/v1/item_summary/search"
        # Get Item endpoint
        self.item_url = f"{base}/buy/browse/v1/item"

        # OAuth bearer token & marketplace
        self.token = cfg.get("EBAY_OAUTH_TOKEN") or os.getenv("EBAY_OAUTH_TOKEN")
        self.marketplace_id = (
            cfg.get("EBAY_MARKETPLACE_ID")
            or os.getenv("EBAY_MARKETPLACE_ID")
            or "EBAY_US"
        )

        # Network timeout (seconds): 3s connect, 6s read
        self.connect_timeout = 3
        self.read_timeout = 6
        self.timeout = (self.connect_timeout, self.read_timeout)
        
        # Create session with connection pooling and retry logic
        self._session = None
        self._session_lock = Lock()
    
    def _get_session(self) -> requests.Session:
        """
        Get or create a thread-safe requests Session with:
        - HTTP keep-alive (connection pooling)
        - Exponential backoff retry on 429/5xx (up to 2 retries)
        """
        if self._session is None:
            with self._session_lock:
                if self._session is None:  # Double-check locking
                    session = requests.Session()
                    
                    # Configure retries with exponential backoff
                    retry_strategy = Retry(
                        total=2,  # Up to 2 retries
                        backoff_factor=0.5,  # 0.5s, 1s delays
                        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
                        allowed_methods=["GET", "POST"],  # Retry GET and POST
                    )
                    
                    adapter = HTTPAdapter(
                        max_retries=retry_strategy,
                        pool_connections=10,  # Connection pool size
                        pool_maxsize=20,  # Max pooled connections
                    )
                    
                    session.mount("http://", adapter)
                    session.mount("https://", adapter)
                    
                    self._session = session
        
        return self._session

    # -------------------- internal helpers --------------------

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
        }
        # Use memoized bearer header (cached for 55 minutes)
        from app.ebay_oauth import oauth_manager
        bearer_header = oauth_manager.get_bearer_header()
        if bearer_header:
            headers["Authorization"] = bearer_header
        elif self.token:
            # Fallback to instance token
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _normalize_keywords(val: Any) -> str:
        """
        Accepts string | dict | list/tuple/set and returns a single search phrase.
        Supports shapes like:
          "bluetooth headset"
          {"q": "..."} {"include": "..."} {"any": ["a","b"]} {"phrase":"..."} {"must":[...]}
          ["a","b"]
        """
        if val is None:
            return ""
        if isinstance(val, str):
            return val

        if isinstance(val, dict):
            # single-string forms first
            for k in ("q", "include", "phrase"):
                v = val.get(k)
                if isinstance(v, str) and v.strip():
                    return v
            # list-ish forms
            for k in ("any", "must", "include"):
                v = val.get(k)
                if isinstance(v, (list, tuple, set)) and v:
                    return " ".join(str(x) for x in v if str(x).strip())
            return ""

        if isinstance(val, (list, tuple, set)):
            return " ".join(str(x) for x in val if str(x).strip())

        return str(val)

    @staticmethod
    def _normalize_categories(val: Any) -> List[str]:
        """
        Accepts:
          "9355,123" | ["9355","123"] | {"ids":[...]} | {"id":"..."}
          {"categories":{"include":[...]}}  <-- sponsor/driver filter-set shape
          int / other scalars
        Returns a list[str] of category ids.
        """
        if not val:
            return []

        # Common sponsor/driver rules shape
        if isinstance(val, dict) and "categories" in val:
            cats = val.get("categories") or {}
            inc = cats.get("include") or []
            if isinstance(inc, str):
                return [c.strip() for c in inc.split(",") if c.strip()]
            if isinstance(inc, (list, tuple, set)):
                return [str(c).strip() for c in inc if str(c).strip()]

        # Original supported shapes
        if isinstance(val, str):
            return [c.strip() for c in val.split(",") if c.strip()]
        if isinstance(val, (list, tuple, set)):
            return [str(c).strip() for c in val if str(c).strip()]
        if isinstance(val, dict):
            ids = val.get("ids") or val.get("id")
            return EbayProvider._normalize_categories(ids)

        # scalars
        return [str(val).strip()]

    @staticmethod
    def _build_price_filter(price_min: Any, price_max: Any) -> Optional[str]:
        """
        Build a Browse "filter=price:[lo..hi]" segment.
        """
        try:
            lo = None if price_min is None else float(price_min)
        except (TypeError, ValueError):
            lo = None
        try:
            hi = None if price_max is None else float(price_max)
        except (TypeError, ValueError):
            hi = None

        if lo is None and hi is None:
            return None

        lo_s = "" if lo is None else f"{lo:.2f}".rstrip("0").rstrip(".")
        hi_s = "" if hi is None else f"{hi:.2f}".rstrip("0").rstrip(".")
        return f"price:[{lo_s}..{hi_s}]"

    def _no_token_response(self) -> Dict[str, Any]:
        return {
            "items": [],
            "total": 0,
            "has_more": False,
            "debug": {"reason": "missing EBAY_OAUTH_TOKEN"},
        }

    # -------- post-filter helpers (enforce rules Browse may ignore) --------

    @staticmethod
    def _str_set(val) -> List[str]:
        if not val:
            return []
        if isinstance(val, str):
            return [v.strip() for v in val.split(",") if v.strip()]
        if isinstance(val, (list, tuple, set)):
            return [str(v).strip() for v in val if str(v).strip()]
        return [str(val).strip()]

    @staticmethod
    def _lc(s: Optional[str]) -> str:
        return (s or "").lower()
    
    def _apply_stock_flags_to_variation(self, variant_info: Dict[str, Any]) -> None:
        """
        Apply stock flags to a specific variation based on its availability data.
        Uses the same logic as _inject_low_stock_flags but for individual variations.
        """
        try:
            from flask import current_app
            threshold = int(current_app.config.get("LOW_STOCK_THRESHOLD", 10))
        except:
            threshold = 10
        
        # Get eBay availability data for this variation
        estimated_qty = variant_info.get("estimated_quantity")
        availability_threshold = variant_info.get("availability_threshold")
        
        # Default values
        variant_info["stock_qty"] = None
        variant_info["low_stock"] = False
        variant_info["no_stock"] = False
        variant_info["available"] = False
        
        # If eBay provides exact quantity, use that
        if estimated_qty is not None:
            try:
                qty = int(estimated_qty)
                variant_info["stock_qty"] = qty
                
                if qty == 0:
                    variant_info["no_stock"] = True
                    variant_info["low_stock"] = False
                    variant_info["available"] = False
                elif 0 < qty < threshold:
                    variant_info["low_stock"] = True
                    variant_info["no_stock"] = False
                    variant_info["available"] = False
                elif qty >= 10:
                    variant_info["low_stock"] = False
                    variant_info["no_stock"] = False
                    variant_info["available"] = True
                else:
                    # Between threshold and 10 (e.g., 5-9 items)
                    variant_info["low_stock"] = False
                    variant_info["no_stock"] = False
                    variant_info["available"] = False
            except (ValueError, TypeError):
                pass
        
        # Otherwise, interpret eBay's threshold type
        elif availability_threshold:
            threshold_type = str(availability_threshold).upper()
            
            if "OUT_OF_STOCK" in threshold_type or threshold_type == "ZERO":
                variant_info["no_stock"] = True
                variant_info["low_stock"] = False
                variant_info["available"] = False
                variant_info["stock_qty"] = 0
            elif "MORE_THAN" in threshold_type:
                # "MORE_THAN_10" means plenty of stock - show available tag
                variant_info["low_stock"] = False
                variant_info["no_stock"] = False
                variant_info["available"] = True
                # Extract number if possible (e.g., "MORE_THAN_10" -> 10+)
                try:
                    num = int(threshold_type.split("_")[-1])
                    variant_info["stock_qty"] = num + 1
                    # Only show available if MORE_THAN_10 or higher
                    if num >= 10:
                        variant_info["available"] = True
                    else:
                        variant_info["available"] = False
                except (ValueError, IndexError):
                    variant_info["stock_qty"] = None
                    variant_info["available"] = True  # Assume available for MORE_THAN
            elif threshold_type in ["LIMITED_QUANTITY", "LOW_STOCK"]:
                # Limited quantity = low stock warning
                variant_info["low_stock"] = True
                variant_info["no_stock"] = False
                variant_info["available"] = False
                variant_info["stock_qty"] = threshold  # Estimate at threshold
            else:
                # Unknown threshold type - assume available
                variant_info["low_stock"] = False
                variant_info["no_stock"] = False
                variant_info["available"] = True

    def _any_in_text(self, needles: List[str], hay: str) -> bool:
        hay_l = self._lc(hay)
        return any(n and self._lc(n) in hay_l for n in needles)

    def _all_in_text(self, needles: List[str], hay: str) -> bool:
        hay_l = self._lc(hay)
        return all(n and self._lc(n) in hay_l for n in needles)

    def _seller_ok(self, it: Dict[str, Any], rules: Dict[str, Any]) -> bool:
        seller = it.get("seller") or {}
        if not seller:
            return True
        r = rules.get("seller") or {}
        min_score = r.get("min_feedback_score")
        min_pct = r.get("min_positive_percent")
        if min_score is not None:
            try:
                if int(seller.get("feedbackScore") or 0) < int(min_score):
                    return False
            except Exception:
                pass
        if min_pct is not None:
            try:
                pct_val = seller.get("feedbackPercentage")
                if isinstance(pct_val, str) and pct_val.endswith("%"):
                    pct = float(pct_val.rstrip("%"))
                else:
                    pct = float(pct_val or 0.0)
                if pct < float(min_pct):
                    return False
            except Exception:
                pass
        return True

    def _free_shipping_ok(self, it: Dict[str, Any]) -> bool:
        ship = it.get("shipping")
        if ship is None:
            # Some Browse items omit shipping cost; treat as unknown (allow)
            return True
        try:
            return float(ship) == 0.0
        except Exception:
            return False

    def _brand_from_raw(self, it_raw: Dict[str, Any]) -> Optional[str]:
        # Best-effort extraction; different categories expose brand differently
        for key in ("brand", "brandName"):
            if it_raw.get(key):
                return str(it_raw.get(key))
        # Look inside item aspects if present
        for aspects_key in ("localizedAspects", "itemLocationAspects", "additionalProductIdentities"):
            arr = it_raw.get(aspects_key)
            if isinstance(arr, list):
                for a in arr:
                    name = self._lc(a.get("name") or a.get("aspectName") or "")
                    if name == "brand":
                        vals = a.get("value") or a.get("values") or []
                        if isinstance(vals, list) and vals:
                            return str(vals[0])
                        if isinstance(vals, str) and vals.strip():
                            return vals
        return None

    def _extract_kw_sets(self, rules: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """
        Return (must, must_not) keyword lists from rules["keywords"] in a defensive way.
        Handles str | list | dict | None.
        """
        raw = rules.get("keywords")
        if raw is None:
            return [], []
        # If a simple string, treat as a single MUST token
        if isinstance(raw, str):
            return [raw], []
        # If list-ish, treat the whole list as MUST tokens
        if isinstance(raw, (list, tuple, set)):
            return [str(x) for x in raw if str(x).strip()], []
        # If dict, collect must / must_not with common synonyms
        if isinstance(raw, dict):
            must = self._str_set(raw.get("must") or raw.get("include") or raw.get("any"))
            must_not = self._str_set(raw.get("must_not") or raw.get("exclude"))
            return must, must_not
        # Fallback: coerce to string
        return [str(raw)], []

    def _post_filter(self, items: List[Dict[str, Any]], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
        # categories: only read excludes if categories is a dict
        cats_raw = rules.get("categories") or {}
        cat_ex = set()
        if isinstance(cats_raw, dict):
            cat_ex = set(self._str_set(cats_raw.get("exclude")))

        brands = rules.get("brands") or {}
        b_inc = self._str_set(brands.get("include"))
        b_exc = self._str_set(brands.get("exclude"))

        must, must_not = self._extract_kw_sets(rules)

        shipping_rules = rules.get("shipping") or {}
        listing_rules = rules.get("listing") or {}
        safety = rules.get("safety") or {}
        
        exclude_explicit = safety.get("exclude_explicit", False)
        adult_filtered_count = 0
        explicit_filtered_count = 0

        out = []
        for it in items:
            title = it.get("title") or ""
            cat_id = str(it.get("category_id") or "")
            brand = (it.get("brand") or "") or ""
            seller_ok = self._seller_ok(it, rules)

            # category excludes (guard, in case API category filter misses)
            if cat_id and cat_id in cat_ex:
                continue

            # keyword must/must_not (title-only best-effort)
            if must and not self._all_in_text(must, title):
                continue
            if must_not and self._any_in_text(must_not, title):
                continue

            # brand includes/excludes (title or extracted brand)
            title_or_brand = f"{title} {brand}".strip()
            if b_inc and not self._any_in_text(b_inc, title_or_brand):
                continue
            if b_exc and self._any_in_text(b_exc, title_or_brand):
                continue

            # free shipping only (if requested)
            if shipping_rules.get("free_shipping_only") is True and not self._free_shipping_ok(it):
                continue

            # buy-it-now only (if requested)
            if listing_rules.get("buy_it_now_only") is True:
                bo = it.get("buyingOptions") or []
                if "FIXED_PRICE" not in bo:
                    continue

            # safety: explicit titles / adult categories
            if exclude_explicit:
                is_explicit_content = is_explicit(it)
                is_adult_category = cat_id and cat_id in ADULT_CATEGORY_IDS
                if is_explicit_content or is_adult_category:
                    if is_adult_category:
                        adult_filtered_count += 1
                        logger.debug(
                            f"[ADULT_FILTER] Post-filter - Excluded item {it.get('id', 'unknown')} "
                            f"({it.get('title', 'No title')[:50]}) due to adult category {cat_id}"
                        )
                    if is_explicit_content:
                        explicit_filtered_count += 1
                    continue

            if not seller_ok:
                continue

            out.append(it)
        
        # Log filtering summary
        if exclude_explicit and (adult_filtered_count > 0 or explicit_filtered_count > 0):
            logger.info(
                f"[ADULT_FILTER] Post-filter summary - exclude_explicit=True: "
                f"Filtered {adult_filtered_count} items with adult categories, "
                f"{explicit_filtered_count} items with explicit content. "
                f"Results: {len(out)}/{len(items)} items passed"
            )
        
        return out

    # -------------------- public API --------------------
    
    def search_cached(
        self,
        merged_rules: Dict[str, Any],
        page: int,
        page_size: int,
        sort: str,
        keyword_overlay: Optional[str] = None,
        strict_total: bool = True,
        cache_ttl: int = 120,
    ) -> Dict[str, Any]:
        """
        Cached wrapper around search() with read-through caching.
        
        Args:
            cache_ttl: Time-to-live for cache in seconds (default 120s for list pages)
        """
        if not CACHE_AVAILABLE:
            # Fallback to uncached search
            return self.search(merged_rules, page, page_size, sort, keyword_overlay, strict_total)
        
        try:
            # Generate cache key from all parameters
            # Normalize rules by sorting JSON to ensure consistent keys
            normalized_rules = json.dumps(merged_rules, sort_keys=True)
            cache_key = make_cache_key(
                "ebay_search",
                normalized_rules,
                page,
                page_size,
                sort,
                keyword_overlay or "",
                strict_total,
            )
            
            # Try to get from cache
            cache = get_cache()
            cached_result = cache.get(cache_key)
            
            if cached_result is not None:
                logger.debug(f"Cache HIT for search (page={page}, sort={sort})")
                return cached_result
            
            # Cache miss - call actual search
            logger.debug(f"Cache MISS for search (page={page}, sort={sort})")
            result = self.search(merged_rules, page, page_size, sort, keyword_overlay, strict_total)
            
            # Cache the result
            cache.set(cache_key, result, cache_ttl)
            
            return result
            
        except Exception as e:
            # If caching fails, fallback to uncached search
            logger.warning(f"Cache error, falling back to uncached search: {e}")
            return self.search(merged_rules, page, page_size, sort, keyword_overlay, strict_total)

    def search_extended(
        self,
        merged_rules: Dict[str, Any],
        page: int,
        page_size: int,
        sort: str,
        keyword_overlay: Optional[str] = None,
        strict_total: bool = True,
        max_pages: int = 1000,
    ) -> Dict[str, Any]:
        """
        Extended search that can generate up to 1000 pages by using multiple search strategies.
        
        This works around eBay's 100-page limit (10,000 items) by:
        1. Using different search strategies (keyword variations, category splits, etc.)
        2. Aggregating results from multiple searches
        3. Caching results to avoid duplicate API calls
        
        Args:
            max_pages: Maximum number of pages to generate (default 1000)
        """
        # If page is within normal eBay limits, use regular search
        if page <= 100:
            return self.search_cached(merged_rules, page, page_size, sort, keyword_overlay, strict_total)
        
        # For pages beyond 100, we need to use extended strategies
        return self._search_extended_strategies(
            merged_rules, page, page_size, sort, keyword_overlay, strict_total, max_pages
        )
    
    def _search_extended_strategies(
        self,
        merged_rules: Dict[str, Any],
        target_page: int,
        page_size: int,
        sort: str,
        keyword_overlay: Optional[str] = None,
        strict_total: bool = True,
        max_pages: int = 1000,
    ) -> Dict[str, Any]:
        """
        Use multiple search strategies to generate results beyond eBay's 100-page limit.
        """
        # Calculate which search strategy and page we need
        strategy_info = self._calculate_search_strategy(target_page, page_size)
        
        # Get the base search parameters
        base_rules = merged_rules.copy()
        base_keyword = keyword_overlay or base_rules.get("keywords", "")
        
        # Apply strategy-specific modifications
        strategy_rules, strategy_keyword = self._apply_search_strategy(
            base_rules, base_keyword, strategy_info["strategy"], strategy_info["strategy_index"]
        )
        
        # Execute the strategy-specific search
        result = self.search_cached(
            strategy_rules, 
            strategy_info["page"], 
            page_size, 
            sort, 
            strategy_keyword, 
            strict_total
        )
        
        # Update the result to reflect the target page
        result["page"] = target_page
        result["debug"]["extended_search"] = True
        result["debug"]["strategy"] = strategy_info["strategy"]
        result["debug"]["strategy_index"] = strategy_info["strategy_index"]
        result["debug"]["strategy_page"] = strategy_info["page"]
        
        return result
    
    def _calculate_search_strategy(self, target_page: int, page_size: int) -> Dict[str, Any]:
        """
        Calculate which search strategy and page to use for a given target page.
        
        Strategies:
        1. Pages 1-100: Regular search
        2. Pages 101-200: Keyword variations (adding common words)
        3. Pages 201-300: Category subcategories
        4. Pages 301-400: Price range splits
        5. Pages 401-500: Brand variations
        6. Pages 501-600: Sort variations
        7. Pages 601-700: Date range splits
        8. Pages 701-800: Condition variations
        9. Pages 801-900: Seller variations
        10. Pages 901-1000: Location variations
        """
        if target_page <= 100:
            return {"strategy": "regular", "strategy_index": 0, "page": target_page}
        
        # Calculate strategy and page within that strategy
        strategy_pages = 100  # Each strategy can generate 100 pages
        strategy_number = (target_page - 1) // strategy_pages
        page_within_strategy = ((target_page - 1) % strategy_pages) + 1
        
        strategies = [
            "keyword_variations",
            "category_splits", 
            "price_splits",
            "brand_variations",
            "sort_variations",
            "date_splits",
            "condition_variations",
            "seller_variations",
            "location_variations"
        ]
        
        if strategy_number >= len(strategies):
            # If we exceed all strategies, cycle through them
            strategy_number = strategy_number % len(strategies)
        
        return {
            "strategy": strategies[strategy_number],
            "strategy_index": strategy_number,
            "page": page_within_strategy
        }
    
    def _apply_search_strategy(
        self, 
        base_rules: Dict[str, Any], 
        base_keyword: str, 
        strategy: str, 
        strategy_index: int
    ) -> Tuple[Dict[str, Any], str]:
        """
        Apply a specific search strategy to modify the search parameters.
        """
        rules = base_rules.copy()
        keyword = base_keyword
        
        if strategy == "keyword_variations":
            # Add common keywords to expand search
            variations = [
                "new", "used", "vintage", "collectible", "rare", "popular", 
                "trending", "best", "top", "quality", "premium", "discount",
                "sale", "deal", "offer", "special", "limited", "exclusive"
            ]
            if strategy_index < len(variations):
                keyword = f"{base_keyword} {variations[strategy_index]}"
        
        elif strategy == "category_splits":
            # Split categories into subcategories
            category_splits = [
                "electronics", "clothing", "home", "sports", "toys",
                "automotive", "books", "music", "movies", "games"
            ]
            if strategy_index < len(category_splits):
                keyword = f"{base_keyword} {category_splits[strategy_index]}"
        
        elif strategy == "price_splits":
            # Split into different price ranges
            price_ranges = [
                (0, 10), (10, 25), (25, 50), (50, 100), (100, 250),
                (250, 500), (500, 1000), (1000, 2500), (2500, 5000), (5000, None)
            ]
            if strategy_index < len(price_ranges):
                price_min, price_max = price_ranges[strategy_index]
                rules["price_min"] = price_min
                rules["price_max"] = price_max
        
        elif strategy == "brand_variations":
            # Add brand-related keywords
            brand_keywords = [
                "brand", "manufacturer", "original", "authentic", "genuine",
                "official", "licensed", "designer", "premium", "luxury"
            ]
            if strategy_index < len(brand_keywords):
                keyword = f"{base_keyword} {brand_keywords[strategy_index]}"
        
        elif strategy == "sort_variations":
            # Use different sort orders to get different results
            sort_keywords = [
                "best_match", "price_low", "price_high", "newest", "popular",
                "trending", "featured", "recommended", "top_rated", "best_seller"
            ]
            if strategy_index < len(sort_keywords):
                keyword = f"{base_keyword} {sort_keywords[strategy_index]}"
        
        elif strategy == "date_splits":
            # Split by different time periods
            date_keywords = [
                "recent", "latest", "new", "old", "vintage", "antique",
                "modern", "contemporary", "classic", "traditional"
            ]
            if strategy_index < len(date_keywords):
                keyword = f"{base_keyword} {date_keywords[strategy_index]}"
        
        elif strategy == "condition_variations":
            # Add condition-related keywords
            conditions = [
                "excellent", "very_good", "good", "fair", "poor",
                "like_new", "open_box", "refurbished", "new_other", "used"
            ]
            if strategy_index < len(conditions):
                keyword = f"{base_keyword} {conditions[strategy_index]}"
        
        elif strategy == "seller_variations":
            # Add seller-related keywords
            seller_keywords = [
                "top_rated", "power_seller", "store", "wholesale", "retail",
                "private", "individual", "business", "dealer", "merchant"
            ]
            if strategy_index < len(seller_keywords):
                keyword = f"{base_keyword} {seller_keywords[strategy_index]}"
        
        elif strategy == "location_variations":
            # Add location-related keywords
            locations = [
                "usa", "worldwide", "international", "domestic", "local",
                "shipping", "delivery", "pickup", "store", "warehouse"
            ]
            if strategy_index < len(locations):
                keyword = f"{base_keyword} {locations[strategy_index]}"
        
        return rules, keyword

    def search(
        self,
        merged_rules: Dict[str, Any],
        page: int,
        page_size: int,
        sort: str,
        keyword_overlay: Optional[str] = None,
        strict_total: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a Browse search using merged sponsor rules.

        merged_rules may include:
          - keywords: str | dict | list | {"must":[...], "must_not":[...]}
          - category_ids / category / categories: str | list | dict
          - price_min / price_max OR price: {min,max}
          - shipping.free_shipping_only (bool)
          - listing.buy_it_now_only (bool)
          - brands.include / brands.exclude (post-filtered)
          - seller thresholds (post-filtered)
        
        Args:
            strict_total: If False, skip expensive total count and return total=None.
                         Relies on has_more flag only for pagination.
        """
        if not self.token:
            return self._no_token_response()

        params: Dict[str, Any] = {}

        # ---- Keywords (q) ----
        raw_kw = keyword_overlay if keyword_overlay is not None else merged_rules.get("keywords")
        kw = self._normalize_keywords(raw_kw).strip()
        # Also blend brand includes into q (helps server-side narrowing without risking excludes syntax)
        brand_includes = self._str_set((merged_rules.get("brands") or {}).get("include"))
        if brand_includes:
            extra = " ".join(b for b in brand_includes if b)
            kw = (kw + " " + extra).strip() if kw else extra
        if kw:
            params["q"] = kw

        # ---- Categories ----
        raw_cats = merged_rules.get("category_ids") or merged_rules.get("category") or merged_rules.get("categories")
        cat_ids = self._normalize_categories(raw_cats)
        # Filter out adult categories if exclude_explicit is enabled
        safety = merged_rules.get("safety") or {}
        if safety.get("exclude_explicit") and cat_ids:
            original_cat_ids = cat_ids.copy()
            adult_cats_in_query = [cid for cid in cat_ids if str(cid) in ADULT_CATEGORY_IDS]
            cat_ids = [cid for cid in cat_ids if str(cid) not in ADULT_CATEGORY_IDS]
            if adult_cats_in_query:
                logger.info(
                    f"[ADULT_FILTER] eBay search - exclude_explicit=True: "
                    f"Filtered {len(adult_cats_in_query)} adult categories from category_ids "
                    f"({len(original_cat_ids)} -> {len(cat_ids)}). "
                    f"Adult IDs removed: {adult_cats_in_query}"
                )
        if cat_ids:
            params["category_ids"] = ",".join(cat_ids)
            logger.debug(f"[ADULT_FILTER] eBay search - Final category_ids param: {params['category_ids']}")

        # Browse requires either q or category_ids
        if not params.get("q") and not params.get("category_ids"):
            return {
                "items": [],
                "total": 0,
                "has_more": False,
                "debug": {"reason": "missing query and category_ids (Browse requires one)"},
            }

        # ---- Pagination ----
        page = max(1, int(page or 1))
        page_size = max(1, min(100, int(page_size or 24)))
        params["limit"] = page_size
        params["offset"] = (page - 1) * page_size

        # ---- Price ----
        price_min = merged_rules.get("price_min")
        price_max = merged_rules.get("price_max")
        if price_min is None or price_max is None:
            price_dict = merged_rules.get("price") or {}
            if price_min is None:
                price_min = price_dict.get("min")
            if price_max is None:
                price_max = price_dict.get("max")

        # ---- Sort mapping (needed to check if sorting by price) ----
        sort_map = {
            "best_match": None,     # default relevance
            "price_asc": "price",
            "price_desc": "-price",
            "newest": "-new",
        }
        sort_param = sort_map.get(sort)
        is_price_sort = sort_param in ("price", "-price")
        
        filters: List[str] = []
        price_segment = self._build_price_filter(price_min, price_max)
        
        # IMPORTANT: eBay API has issues with price filter + price sort combination
        # When sorting by price, skip API-level price filter and rely on client-side filtering
        # This prevents the API from returning HTTP errors (400/500) for certain price ranges
        # The client-side filtering in preview_service.py will handle the price filtering
        if price_segment and not is_price_sort:
            filters.append(price_segment)
            logger.debug(f"[EBAY PROVIDER] Adding price filter: {price_segment}")
        elif price_segment and is_price_sort:
            logger.info(f"[EBAY PROVIDER] Skipping API-level price filter when sorting by price (sort={sort_param}) - "
                      f"will use client-side filtering instead. Price range: {price_segment}")

        # ---- Free shipping / Buy-it-now (safe server-side filters)
        if (merged_rules.get("shipping") or {}).get("free_shipping_only") is True:
            filters.append("freeShippingOnly:true")
        if (merged_rules.get("listing") or {}).get("buy_it_now_only") is True:
            filters.append("buyingOptions:{FIXED_PRICE}")

        if filters:
            params["filter"] = ",".join(filters)
            logger.debug(f"[EBAY PROVIDER] Applied filters: {params['filter']}")

        if sort_param:
            params["sort"] = sort_param
            logger.debug(f"[EBAY PROVIDER] Applied sort: {sort_param}")

        # ---- HTTP call ----
        try:
            session = self._get_session()
            r = session.get(
                self.search_url,
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None) if hasattr(e, 'response') else None
            text = (getattr(e.response, "text", "") if hasattr(e, 'response') else "")[:800]
            logger.error(f"[EBAY PROVIDER] HTTP error from eBay API: status={status}, error={e}, response_text={text[:200]}, params={params}")
            return {
                "items": [],
                "total": None if not strict_total else 0,
                "has_more": False,
                "debug": {
                    "http_status": status,
                    "response": text,
                    "url": self.search_url,
                    "params": params,
                    "marketplace": self.marketplace_id,
                },
            }
        except Exception as e:
            logger.error(f"eBay search error: {e}", exc_info=True)
            return {
                "items": [],
                "total": None if not strict_total else 0,
                "has_more": False,
                "debug": {
                    "exception": str(e),
                    "url": self.search_url,
                    "params": params,
                    "marketplace": self.marketplace_id,
                },
            }

        # ---- Normalize results (capture condition/category/brand/seller/buyingOptions too)
        raw_items = data.get("itemSummaries") or []
        items: List[Dict[str, Any]] = []
        for it in raw_items:
            price_obj = it.get("price") or {}
            image_obj = it.get("image") or {}
            shipping_opts = it.get("shippingOptions") or []
            first_ship = shipping_opts[0] if shipping_opts else {}
            ship_cost = (first_ship.get("shippingCost") or {}).get("value")
            
            # Extract stock availability from eBay API
            # eBay provides estimatedAvailabilities with availabilityThreshold and estimatedAvailableQuantity
            estimated_avail = it.get("estimatedAvailabilities", [])
            availability_threshold = None
            estimated_quantity = None
            
            if estimated_avail and len(estimated_avail) > 0:
                avail_data = estimated_avail[0]  # First delivery option
                availability_threshold = avail_data.get("availabilityThresholdType")  # e.g., "MORE_THAN_10"
                estimated_quantity = avail_data.get("estimatedAvailableQuantity")  # Exact number when available
            
            # Skip items that eBay explicitly marks as OUT_OF_STOCK
            # This filters out unavailable items when eBay provides that information
            if availability_threshold:
                threshold_upper = str(availability_threshold).upper()
                if "OUT_OF_STOCK" in threshold_upper or threshold_upper == "ZERO":
                    continue  # Skip this item - it's not available for purchase
            
            # Also skip if quantity is explicitly 0
            if estimated_quantity is not None:
                try:
                    if int(estimated_quantity) == 0:
                        continue  # Skip items with 0 quantity
                except (ValueError, TypeError):
                    pass
            
            items.append(
                {
                    "id": it.get("itemId"),
                    "title": it.get("title"),
                    "subtitle": it.get("shortDescription", ""),  # Description from eBay (if available)
                    "price": price_obj.get("value"),
                    "currency": price_obj.get("currency"),
                    "image": image_obj.get("imageUrl"),
                    "url": it.get("itemWebUrl"),
                    "shipping": ship_cost,
                    "condition": it.get("condition"),
                    "category_id": it.get("categoryId"),
                    "brand": self._brand_from_raw(it),
                    "seller": it.get("seller") or {},
                    "buyingOptions": it.get("buyingOptions") or [],
                    # eBay real-time availability data
                    "availability_threshold": availability_threshold,
                    "estimated_quantity": estimated_quantity,
                }
            )

        # ---- Local post-filter for rules Browse doesn't (reliably) enforce
        filtered = self._post_filter(items, merged_rules)

        # Calculate total and has_more based on strict_total flag
        if strict_total:
            # Compute exact total (more expensive)
            total = len(filtered)
        else:
            # Skip total count, return None (fast path)
            total = None
        
        # has_more is based on API's total, not our filtered count
        api_total = int(data.get("total") or 0)
        has_more = (params["offset"] + page_size) < api_total

        return {
            "items": filtered,
            "total": total,
            "has_more": has_more,
            "debug": {
                "env": os.getenv("EBAY_ENV"),
                "search_url": self.search_url,
                "marketplace": self.marketplace_id,
                "params": params,
                "strict_total": strict_total,
            },
        }

    def get_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single item by its eBay item ID.
        Returns item data or None if not found/error.
        """
        try:
            # URL-encode the item_id to handle pipe characters (eBay uses v1|legacyId|legacyId format)
            from urllib.parse import quote
            encoded_item_id = quote(item_id, safe='')  # Encode all special chars including pipes
            url = f"{self.item_url}/{encoded_item_id}"
            session = self._get_session()
            response = session.get(
                url,
                headers=self._headers(),
                timeout=self.timeout
            )
            
            if response.status_code == 404:
                return None
                
            response.raise_for_status()
            data = response.json()
            
            # Transform to match search result format
            item = {
                "id": data.get("itemId"),
                "title": data.get("title", ""),
                "price": None,
                "currency": None,
                "image": None,
                "url": data.get("itemWebUrl", ""),
                "condition": data.get("condition", ""),
                "subtitle": data.get("shortDescription", ""),
                "description": data.get("description", ""),
            }
            
            # Extract price
            if "price" in data:
                price_obj = data["price"]
                if isinstance(price_obj, dict):
                    item["price"] = float(price_obj.get("value", 0))
                    item["currency"] = price_obj.get("currency", "USD")
            
            # Extract image
            if "image" in data:
                image_obj = data["image"]
                if isinstance(image_obj, dict):
                    item["image"] = image_obj.get("imageUrl")
            elif "image" in data and isinstance(data["image"], str):
                item["image"] = data["image"]
            
            # Extract availability
            if "estimatedAvailabilities" in data and data["estimatedAvailabilities"]:
                avail = data["estimatedAvailabilities"][0]
                item["estimated_quantity"] = avail.get("estimatedAvailableQuantity")
                item["availability_threshold"] = avail.get("availabilityThresholdType")
                
                # Skip if explicitly OUT_OF_STOCK
                threshold = item["availability_threshold"]
                if threshold:
                    threshold_upper = str(threshold).upper()
                    if "OUT_OF_STOCK" in threshold_upper or threshold_upper == "ZERO":
                        return None  # Item is not available
                
                # Skip if quantity is 0
                qty = item["estimated_quantity"]
                if qty is not None:
                    try:
                        if int(qty) == 0:
                            return None  # Item has 0 quantity
                    except (ValueError, TypeError):
                        pass
            
            return item
            
        except requests.exceptions.RequestException as e:
            return None
        except (KeyError, ValueError, TypeError):
            return None

    def get_item_details(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch full item details including variants, additional images, and item specifics.
        Returns detailed item data or None if not found/error.
        """
        try:
            # URL-encode the item_id to handle pipe characters (eBay uses v1|legacyId|legacyId format)
            from urllib.parse import quote
            import logging
            logger = logging.getLogger(__name__)
            
            # Request with fieldgroups to get complete data including variations
            encoded_item_id = quote(item_id, safe='')  # Encode all special chars including pipes
            url = f"{self.item_url}/{encoded_item_id}"
            params = {
                "fieldgroups": "PRODUCT"  # Get product details including variations (EXTENDED is not valid)
            }
            
            logger.info(f"Fetching item details from eBay - Item ID: {item_id}, Encoded URL: {url}")
            
            session = self._get_session()
            response = session.get(
                url,
                params=params,
                headers=self._headers(),
                timeout=self.timeout
            )
            
            logger.info(f"eBay response status: {response.status_code}")
            
            if response.status_code == 404:
                logger.warning(f"eBay returned 404 for item {item_id}")
                return None
                
            if response.status_code != 200:
                logger.error(f"eBay API error for item {item_id}: {response.status_code} - {response.text[:200]}")
                
            response.raise_for_status()
            data = response.json()
            
            # Log the raw response to debug variant extraction
            logger.info(f"eBay API response keys: {list(data.keys())}")
            if "localizedAspects" in data:
                logger.info(f"Found {len(data['localizedAspects'])} localizedAspects")
                for aspect in data.get("localizedAspects", [])[:3]:  # Log first 3
                    logger.info(f"  Aspect: {aspect.get('name')} = {aspect.get('value')}, constraint: {aspect.get('aspectConstraint')}")
            
            # Build comprehensive item details
            item = {
                "id": data.get("itemId"),
                "title": data.get("title", ""),
                "subtitle": data.get("shortDescription", ""),
                "description": data.get("description", ""),
                "price": None,
                "currency": None,
                "image": None,
                "additional_images": [],
                "url": data.get("itemWebUrl", ""),
                "condition": data.get("condition", ""),
                "category_id": data.get("categoryId", ""),
                "brand": self._brand_from_raw(data),
                "seller": data.get("seller") or {},
                "item_specifics": {},
                "variants": {},
                "variant_options": [],  # Detailed variant data with prices/images
            }
            
            # Extract price
            if "price" in data:
                price_obj = data["price"]
                if isinstance(price_obj, dict):
                    item["price"] = float(price_obj.get("value", 0))
                    item["currency"] = price_obj.get("currency", "USD")
            
            # Extract main image and additional images
            if "image" in data:
                image_obj = data["image"]
                if isinstance(image_obj, dict):
                    item["image"] = image_obj.get("imageUrl")
            elif "image" in data and isinstance(data["image"], str):
                item["image"] = data["image"]
            
            # Additional images
            if "additionalImages" in data and isinstance(data["additionalImages"], list):
                item["additional_images"] = [
                    img.get("imageUrl") if isinstance(img, dict) else img
                    for img in data["additionalImages"]
                ][:10]  # Limit to 10 additional images
            
            # Item specifics (product details) - separate variation aspects from regular specs
            variation_aspect_names = set()
            if "localizedAspects" in data and isinstance(data["localizedAspects"], list):
                # First pass: identify variation aspects
                for aspect in data["localizedAspects"]:
                    if isinstance(aspect, dict):
                        constraint = aspect.get("aspectConstraint", {})
                        # Variation aspects have aspectMode = "SELECTION_ONLY" or aspectRequired = True with multiple values
                        if constraint.get("aspectMode") == "SELECTION_ONLY" or constraint.get("aspectApplicableTo") == ["ITEM"]:
                            variation_aspect_names.add(aspect.get("name", ""))
                
                # Second pass: populate item_specifics (excluding variations)
                for aspect in data["localizedAspects"]:
                    if isinstance(aspect, dict):
                        name = aspect.get("name", "")
                        value = aspect.get("value", "")
                        if name and value and name not in variation_aspect_names:
                            item["item_specifics"][name] = value
            
            # Check if this item has variations via primaryItemGroup
            # This is the ONLY reliable source of actual selectable variations
            # Other sources (product.aspects, localizedAspects) may contain multiple values
            # that are NOT selectable variations (e.g., multiple publishers listed in item specifics)
            if "primaryItemGroup" in data and isinstance(data["primaryItemGroup"], dict):
                item_group = data["primaryItemGroup"]
                item_group_href = item_group.get("itemGroupHref")
                
                if item_group_href:
                    logger.info(f"Item has variations - fetching item group: {item_group_href}")
                    
                    try:
                        # Fetch all variations in the group
                        session = self._get_session()
                        group_response = session.get(
                            item_group_href,
                            headers=self._headers(),
                            timeout=self.timeout
                        )
                        
                        if group_response.status_code == 200:
                            group_data = group_response.json()
                            items_in_group = group_data.get("items", [])
                            
                            # Extract all unique values for each variation dimension
                            variation_map = {}
                            # Store detailed variation info (image, price, etc. per variant combo)
                            variation_details = []
                            
                            for variation_item in items_in_group:
                                aspects = variation_item.get("localizedAspects", [])
                                
                                # Build variation detail object
                                variant_info = {
                                    "item_id": variation_item.get("itemId"),
                                    "price": None,
                                    "image": None,
                                    "additional_images": [],
                                    "url": variation_item.get("itemWebUrl"),
                                    "variants": {},
                                    # Stock data for this specific variation
                                    "estimated_quantity": None,
                                    "availability_threshold": None,
                                    "stock_qty": None,
                                    "low_stock": False,
                                    "no_stock": False,
                                    "available": False
                                }
                                
                                # Extract price
                                if "price" in variation_item:
                                    price_obj = variation_item["price"]
                                    if isinstance(price_obj, dict):
                                        variant_info["price"] = float(price_obj.get("value", 0))
                                
                                # Extract image
                                if "image" in variation_item:
                                    image_obj = variation_item["image"]
                                    if isinstance(image_obj, dict):
                                        variant_info["image"] = image_obj.get("imageUrl")
                                    elif isinstance(image_obj, str):
                                        variant_info["image"] = image_obj
                                
                                # Extract additional images
                                if "additionalImages" in variation_item and isinstance(variation_item["additionalImages"], list):
                                    variant_info["additional_images"] = [
                                        img.get("imageUrl") if isinstance(img, dict) else img
                                        for img in variation_item["additionalImages"]
                                    ][:5]  # Limit to 5 additional images for variants
                                
                                # Extract stock data for this specific variation
                                if "estimatedAvailabilities" in variation_item and variation_item["estimatedAvailabilities"]:
                                    avail = variation_item["estimatedAvailabilities"][0]
                                    variant_info["estimated_quantity"] = avail.get("estimatedAvailableQuantity")
                                    variant_info["availability_threshold"] = avail.get("availabilityThresholdType")
                                
                                # Apply low stock flags to this variation
                                self._apply_stock_flags_to_variation(variant_info)
                                
                                # Extract variation aspects
                                for aspect in aspects:
                                    if isinstance(aspect, dict):
                                        name = aspect.get("name", "")
                                        value = aspect.get("value", "")
                                        
                                        # Support ANY variation type, not just hard-coded ones
                                        if name and value:
                                            # Use the original name as-is for maximum flexibility
                                            # This supports variations like "Choose Your Card", "Character", "Edition", etc.
                                            if name not in variation_map:
                                                variation_map[name] = set()
                                            variation_map[name].add(value)
                                            variant_info["variants"][name] = value
                                
                                variation_details.append(variant_info)
                            
                            # Convert sets to sorted lists
                            for name, values in variation_map.items():
                                item["variants"][name] = sorted(list(values))
                            
                            # Store variation details for client-side lookup
                            item["variation_details"] = variation_details
                            
                            logger.info(f"Extracted variants from item group: {item['variants']}")
                            logger.info(f"Stored {len(variation_details)} variation details")
                    except Exception as e:
                        logger.warning(f"Failed to fetch item group variations: {e}")
            
            # Fallback: Extract from localizedAspects ONLY if explicitly marked as SELECTION_ONLY
            # This ensures we only show actual selectable variations, not just item specifics with multiple values
            if not item["variants"] and "localizedAspects" in data:
                for aspect in data["localizedAspects"]:
                    if isinstance(aspect, dict):
                        aspect_constraint = aspect.get("aspectConstraint", {})
                        name = aspect.get("name", "")
                        value = aspect.get("value", "")
                        
                        # ONLY treat as variation if eBay explicitly marks it as SELECTION_ONLY
                        # This is eBay's way of indicating a selectable variation option
                        if aspect_constraint.get("aspectMode") == "SELECTION_ONLY":
                            # Extract variation values
                            variation_values = []
                            
                            # Method 1: aspectValues array (preferred format)
                            if "aspectValues" in aspect:
                                aspect_values = aspect["aspectValues"]
                                if isinstance(aspect_values, list) and len(aspect_values) > 1:
                                    variation_values = [
                                        v.get("value") if isinstance(v, dict) else str(v)
                                        for v in aspect_values
                                    ]
                            
                            # Method 2: Single value (still a variation if SELECTION_ONLY)
                            elif value:
                                variation_values = [value]
                            
                            # Only add if we have valid variation values
                            if name and variation_values:
                                item["variants"][name] = variation_values
                                logger.info(f"Extracted SELECTION_ONLY variation: {name} = {variation_values}")
                
                if item["variants"]:
                    logger.info(f"Extracted variants from localizedAspects (SELECTION_ONLY only): {item['variants']}")
            
            # Store raw variation data for client-side handling
            # eBay doesn't always provide per-variation prices in the item call
            # We'll handle variation selection client-side with the available data
            if "itemCreationOptions" in data:
                item["variant_options"] = data["itemCreationOptions"]
            
            # Availability data
            if "estimatedAvailabilities" in data and data["estimatedAvailabilities"]:
                avail = data["estimatedAvailabilities"][0]
                item["estimated_quantity"] = avail.get("estimatedAvailableQuantity")
                item["availability_threshold"] = avail.get("availabilityThresholdType")
            
            return item
            
        except requests.exceptions.RequestException as e:
            return None
        except (KeyError, ValueError, TypeError) as e:
            return None

