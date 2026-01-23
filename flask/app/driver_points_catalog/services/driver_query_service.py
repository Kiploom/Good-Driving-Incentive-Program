# app/driver_points_catalog/services/driver_query_service.py
from __future__ import annotations
from typing import Dict, Any, List, Set, Optional
import json

from ...models import Sponsor
from ...models_sponsor_catalog import SponsorCatalogFilterSet, SponsorActiveFilterSelection
from ...sponsor_catalog.services.filter_service import normalize_rules
from ...sponsor_catalog.services.merge_service import merge
from ...sponsor_catalog.services.category_service import resolve as resolve_categories


# ---------- generic helpers (schema-name tolerant) ----------

def _get_attr(obj, *candidates):
    for name in candidates:
        if hasattr(obj, name):
            return getattr(obj, name)
    return None

def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(v)

def _load_json_maybe(val) -> Dict[str, Any]:
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return {}

# ---------- feature flags (tolerant) ----------

def _load_features(s: Sponsor) -> Dict[str, Any]:
    if not s:
        return {}
    return _load_json_maybe(
        _get_attr(
            s,
            "Features", "features",
            "FeaturesJSON", "FeatureJSON",
            "Settings", "SettingsJSON",
            "Config", "ConfigJSON",
        )
    )

def sponsor_enabled_driver_points(sponsor_id: str) -> bool:
    s = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
    feats = _load_features(s)
    # Default enabled unless explicitly disabled
    return bool(feats.get("driverPointsView", True))

def sponsor_enabled_filters_first(sponsor_id: str) -> bool:
    s = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
    feats = _load_features(s)
    return bool(feats.get("filtersFirstCatalog", True))

# ---------- filter-set merging (tolerant to column names) ----------

def _fetch_active_sets_for_sponsor(sponsor_id: str) -> List[SponsorCatalogFilterSet]:
    """
    Avoid brittle filter_by() with unknown column names by loading then filtering in Python.
    Expected columns on each row (any naming variant):
      SponsorID, IsActive, Priority, RulesJSON
    """
    all_sets = SponsorCatalogFilterSet.query.all()

    def _row_belongs(fs) -> bool:
        fs_sponsor = _get_attr(fs, "SponsorID", "sponsor_id", "sponsorId", "SponsorId")
        if str(fs_sponsor) != str(sponsor_id):
            return False
        active = _get_attr(fs, "IsActive", "is_active", "active")
        return _bool(active)

    actives = [fs for fs in all_sets if _row_belongs(fs)]

    def _prio(fs) -> int:
        p = _get_attr(fs, "Priority", "priority", "order", "sort_order")
        try:
            return int(p)
        except Exception:
            return 0

    actives.sort(key=_prio)
    return actives

def _extract_allowed_categories(active_sets: List[SponsorCatalogFilterSet]) -> Set[str]:
    allowed: Set[str] = set()
    for fs in active_sets:
        rules = _load_json_maybe(_get_attr(fs, "RulesJSON", "rules_json", "Rules", "ConfigJSON", "Config"))
        cats = ((rules.get("categories") or {}).get("include") or [])
        if cats:
            resolved = set(resolve_categories(cats))  # returns set of ids
            allowed = resolved if not allowed else (allowed & resolved)
    return allowed

def _fetch_selected_set_for_sponsor(sponsor_id: str):
    """Return the single selected filter set for this sponsor.
       Fallback: if no selection exists (new sponsor), take the lowest-priority active one once."""
    from flask import current_app
    
    current_app.logger.info(f"[FILTER_SET] Fetching selected filter set for sponsor {sponsor_id}")
    
    sel = SponsorActiveFilterSelection.query.get(sponsor_id)
    if sel:
        filter_set_id = _get_attr(sel, "FilterSetID", "filter_set_id")
        current_app.logger.info(f"[FILTER_SET] Found selection record with FilterSetID: {filter_set_id}")
        
        if filter_set_id:
            # Handle special filter set IDs
            if str(filter_set_id) == "__no_filter__":
                current_app.logger.info(f"[FILTER_SET] ✓ No filter set selected - allowing all categories")
                # Query for the dummy filter set we created (empty rules = no filtering)
                fs = SponsorCatalogFilterSet.query.filter_by(ID="__no_filter__", SponsorID=sponsor_id).first()
                if fs:
                    current_app.logger.info(f"[FILTER_SET] ✓ Found __no_filter__ filter set for sponsor {sponsor_id}")
                    # Return the filter set object (with empty rules = no category restrictions)
                    return [fs]
                else:
                    # Fallback: return a dummy object if filter set doesn't exist yet
                    current_app.logger.warning(f"[FILTER_SET] __no_filter__ filter set not found, using dummy object")
                    class DummyFilterSet:
                        def __init__(self):
                            self.ID = "__no_filter__"
                            self.Name = "No Filter Set"
                            self.RulesJSON = {}  # Empty rules = no restrictions
                            self.rules_json = {}
                    return [DummyFilterSet()]
            
            if str(filter_set_id) == "__recommended_only__":
                current_app.logger.info(f"[FILTER_SET] ✓ Recommended products only mode selected")
                # Query for the dummy filter set we created
                fs = SponsorCatalogFilterSet.query.filter_by(ID="__recommended_only__", SponsorID=sponsor_id).first()
                if fs:
                    fs_id = getattr(fs, "ID", None) or getattr(fs, "id", None)
                    fs_name = getattr(fs, "Name", None) or getattr(fs, "name", None)
                    rules = getattr(fs, "RulesJSON", None) or getattr(fs, "rules_json", None) or {}
                    current_app.logger.info(f"[FILTER_SET] ✓ Found recommended_only filter set: ID={fs_id}, Name={fs_name}")
                    return [fs]
                else:
                    # Fallback: return a dummy object if the filter set doesn't exist yet
                    current_app.logger.warning(f"[FILTER_SET] Recommended_only filter set not found, using dummy object")
                    class DummyFilterSet:
                        def __init__(self):
                            self.ID = "__recommended_only__"
                            self.Name = "Recommended Products Only"
                            self.RulesJSON = {"special_mode": "recommended_only"}
                            self.rules_json = {"special_mode": "recommended_only"}
                    return [DummyFilterSet()]
            
            # Try multiple ways to query in case of type mismatches
            fs = SponsorCatalogFilterSet.query.filter_by(ID=filter_set_id, SponsorID=sponsor_id).first()
            if not fs:
                # Try with string conversion
                current_app.logger.debug(f"[FILTER_SET] Trying string conversion for filter_set_id: {filter_set_id}")
                fs = SponsorCatalogFilterSet.query.filter_by(
                    ID=str(filter_set_id), 
                    SponsorID=str(sponsor_id)
                ).first()
            if fs:
                fs_id = getattr(fs, "ID", None) or getattr(fs, "id", None)
                fs_name = getattr(fs, "Name", None) or getattr(fs, "name", None)
                rules = getattr(fs, "RulesJSON", None) or getattr(fs, "rules_json", None) or {}
                special_mode = rules.get("special_mode")
                current_app.logger.info(f"[FILTER_SET] ✓ Found selected filter set: ID={fs_id}, Name={fs_name}, special_mode={special_mode}")
                current_app.logger.debug(f"[FILTER_SET] Filter set rules: {rules}")
                return [fs]
            else:
                current_app.logger.warning(f"[FILTER_SET] ✗ Filter set {filter_set_id} not found for sponsor {sponsor_id}")
        else:
            # NULL or empty means no filter set selected yet (use legacy fallback)
            current_app.logger.info(f"[FILTER_SET] No FilterSetID found in selection, using fallback")
    else:
        current_app.logger.info(f"[FILTER_SET] No selection record found for sponsor {sponsor_id}, using fallback")

    # backward-compatible fallback (keeps things working until sponsor chooses)
    legacy = (
        SponsorCatalogFilterSet.query
        .filter_by(SponsorID=sponsor_id, IsActive=True)
        .order_by(SponsorCatalogFilterSet.Priority.asc(), SponsorCatalogFilterSet.UpdatedAt.desc())
        .first()
    )
    if legacy:
        legacy_id = getattr(legacy, "ID", None) or getattr(legacy, "id", None)
        legacy_name = getattr(legacy, "Name", None) or getattr(legacy, "name", None)
        legacy_rules = getattr(legacy, "RulesJSON", None) or getattr(legacy, "rules_json", None) or {}
        legacy_special_mode = legacy_rules.get("special_mode")
        current_app.logger.info(f"[FILTER_SET] Using legacy fallback filter set: ID={legacy_id}, Name={legacy_name}, special_mode={legacy_special_mode}")
    else:
        current_app.logger.warning(f"[FILTER_SET] ✗ No active filter sets found for sponsor {sponsor_id}")
    return [legacy] if legacy else []


def compose_effective_rules_for_driver(sponsor_id: str, driver_q: Optional[str], driver_cats: Optional[List[str]]) -> Dict[str, Any]:
    """
    NEW behavior:
    1) Load the sponsor's single selected filter set
    2) Check if it's a "pinned_only" mode (special filter)
    3) Overlay driver's query/categories
    4) Safety guard
    """
    sets = _fetch_selected_set_for_sponsor(sponsor_id)

    # If no filter set (empty list), allow all categories
    if not sets:
        from flask import current_app
        current_app.logger.info(f"[FILTER_SET] No filter set selected - allowing all categories")
        merged = {
            "conditions": ["NEW"],
            "listing": {"buy_it_now_only": True},
            "safety": {"exclude_explicit": True}
        }
        # No category restrictions - allow all (except adult categories)
        exclude_explicit = True
        if exclude_explicit:
            from ...sponsor_catalog.policies import ADULT_CATEGORY_IDS
            # We'll filter adult categories later if driver_cats is provided
            pass
        
        if driver_cats:
            chosen = {str(c).strip() for c in driver_cats if str(c).strip()}
            # Filter out adult categories if exclude_explicit is enabled
            if exclude_explicit:
                adult_in_chosen = chosen & ADULT_CATEGORY_IDS
                chosen = chosen - ADULT_CATEGORY_IDS
                if adult_in_chosen:
                    current_app.logger.info(
                        f"[ADULT_FILTER] Driver query (no filter set) - Filtered {len(adult_in_chosen)} adult categories from driver selection "
                        f"({len(chosen) + len(adult_in_chosen)} -> {len(chosen)}). Adult IDs: {sorted(adult_in_chosen)}"
                    )
            if chosen:
                merged["category_ids"] = list(chosen)
                merged.setdefault("categories", {}).setdefault("include", list(chosen))
        return merged

    # Check if this is the "__no_filter__" filter set (allows all categories)
    if sets and len(sets) == 1:
        fs = sets[0]
        filter_set_id = _get_attr(fs, "ID", "id")
        if str(filter_set_id) == "__no_filter__":
            from flask import current_app
            current_app.logger.info(f"[FILTER_SET] No filter set selected (__no_filter__) - allowing all categories")
            merged = {
                "conditions": ["NEW"],
                "listing": {"buy_it_now_only": True},
                "safety": {"exclude_explicit": True}
            }
            # No category restrictions - allow all (except adult categories)
            exclude_explicit = True
            if driver_cats:
                chosen = {str(c).strip() for c in driver_cats if str(c).strip()}
                # Filter out adult categories if exclude_explicit is enabled
                if exclude_explicit:
                    from ...sponsor_catalog.policies import ADULT_CATEGORY_IDS
                    adult_in_chosen = chosen & ADULT_CATEGORY_IDS
                    chosen = chosen - ADULT_CATEGORY_IDS
                    if adult_in_chosen:
                        current_app.logger.info(
                            f"[ADULT_FILTER] Driver query (__no_filter__) - Filtered {len(adult_in_chosen)} adult categories from driver selection "
                            f"({len(chosen) + len(adult_in_chosen)} -> {len(chosen)}). Adult IDs: {sorted(adult_in_chosen)}"
                        )
                if chosen:
                    merged["category_ids"] = list(chosen)
                    merged.setdefault("categories", {}).setdefault("include", list(chosen))
            return merged

    rules_list: List[Dict[str, Any]] = []
    pinned_only_mode = False
    
    for fs in sets:
        if not fs:
            continue
        blob = getattr(fs, "RulesJSON", None) or getattr(fs, "rules_json", None) or {}
        
        # Check for special "recommended_only" mode (support both old "pinned_only" and new "recommended_only" for backward compatibility)
        if blob.get("special_mode") == "recommended_only" or blob.get("special_mode") == "pinned_only":
            pinned_only_mode = True
            # Return a filter that will be used to show only recommended items
            # Enforce defaults: only new buy it now items
            return {
                "special_mode": "recommended_only",
                "keywords": {"must": driver_q.split() if driver_q else []},
                "conditions": ["NEW"],
                "listing": {"buy_it_now_only": True},
                "safety": {"exclude_explicit": True}
            }
        
        rules_list.append(normalize_rules(blob))

    merged: Dict[str, Any] = merge(rules_list)

    allowed = _extract_allowed_categories(sets)  # will use the single set's categories if present
    
    # Always filter adult content (explicit content filtering is always enabled)
    exclude_explicit = True
    from flask import current_app
    
    if exclude_explicit:
        from ...sponsor_catalog.policies import ADULT_CATEGORY_IDS
        original_allowed_count = len(allowed)
        adult_in_allowed = allowed & ADULT_CATEGORY_IDS
        # Filter out adult categories from allowed set
        allowed = allowed - ADULT_CATEGORY_IDS
        current_app.logger.info(
            f"[ADULT_FILTER] Driver query - exclude_explicit=True: "
            f"Filtered {len(adult_in_allowed)} adult categories from allowed set "
            f"({original_allowed_count} -> {len(allowed)}). "
            f"Adult IDs removed: {sorted(adult_in_allowed)}"
        )
    
    if driver_cats:
        chosen = {str(c).strip() for c in driver_cats if str(c).strip()}
        original_chosen_count = len(chosen)
        if allowed:
            chosen &= allowed
        # Filter out adult categories if exclude_explicit is enabled
        if exclude_explicit:
            from ...sponsor_catalog.policies import ADULT_CATEGORY_IDS
            adult_in_chosen = chosen & ADULT_CATEGORY_IDS
            chosen = chosen - ADULT_CATEGORY_IDS
            if adult_in_chosen:
                current_app.logger.info(
                    f"[ADULT_FILTER] Driver query - Filtered {len(adult_in_chosen)} adult categories from driver selection "
                    f"({original_chosen_count} -> {len(chosen)}). Adult IDs: {sorted(adult_in_chosen)}"
                )
        if chosen:
            # Set category_ids directly (like test catalog) for eBay Browse API
            # eBay Browse API requires category_ids as a list, but only uses the first one
            merged["category_ids"] = list(chosen)
            current_app.logger.debug(
                f"[ADULT_FILTER] Driver query - Final category_ids: {merged['category_ids']}"
            )
            # Also set in categories.include format for consistency
            merged.setdefault("categories", {}).setdefault("include", [])
            base = set(merged["categories"]["include"] or [])
            merged["categories"]["include"] = list(base & chosen if base else chosen)
    elif allowed and exclude_explicit:
        # If no driver categories selected but exclude_explicit is enabled,
        # ensure adult categories are excluded from the base categories
        from ...sponsor_catalog.policies import ADULT_CATEGORY_IDS
        merged.setdefault("categories", {}).setdefault("include", [])
        base = set(merged["categories"]["include"] or [])
        original_base_count = len(base)
        adult_in_base = base & ADULT_CATEGORY_IDS
        filtered_base = base - ADULT_CATEGORY_IDS
        merged["categories"]["include"] = list(filtered_base)
        if adult_in_base:
            current_app.logger.info(
                f"[ADULT_FILTER] Driver query - Filtered {len(adult_in_base)} adult categories from base categories "
                f"({original_base_count} -> {len(filtered_base)}). Adult IDs: {sorted(adult_in_base)}"
            )

    if driver_q:
        merged.setdefault("keywords", {}).setdefault("must", [])
        merged["keywords"]["must"].append(driver_q)

    # Enforce defaults: only new buy it now items, always exclude explicit content
    merged["conditions"] = ["NEW"]
    merged.setdefault("listing", {})["buy_it_now_only"] = True
    # Always enforce explicit content filtering (cannot be disabled)
    merged["safety"] = {"exclude_explicit": True}
    return merged