import copy

def merge(rules_list: list[dict]) -> dict:
    if not rules_list:
        return {}
    # Start with first normalized
    merged = copy.deepcopy(rules_list[0])
    def get(path, d):
        cur=d
        for p in path: cur = cur.get(p, {})
        return cur

    for rules in rules_list[1:]:
        # Price: tightest band
        p1, p2 = merged.get("price",{}), rules.get("price",{})
        if p2:
            merged.setdefault("price",{})
            if "min" in p2: merged["price"]["min"] = max(p1.get("min",0), p2["min"])
            if "max" in p2: merged["price"]["max"] = min(p1.get("max",10**9), p2["max"])
            merged["price"]["currency"]="USD"

        # Categories/brands/keywords: union includes & must; union excludes/must_not
        for top, keys in [("categories",("include","exclude")), ("brands",("include","exclude"))]:
            a=merged.setdefault(top, {"include":[],"exclude":[]})
            b=rules.get(top, {})
            for k in keys:
                vals=set(a.get(k,[]) or []) | set((b.get(k,[]) or []))
                a[k]=list(vals)

        # Conditions: union
        cond=set(merged.get("conditions",[]) or []) | set(rules.get("conditions",[]) or [])
        if cond: merged["conditions"]=list(cond)

        # Seller thresholds: stricter wins
        for k in ("min_feedback_score","min_positive_percent"):
            v1=(merged.get("seller") or {}).get(k)
            v2=(rules.get("seller") or {}).get(k)
            if v1 is None and v2 is not None:
                merged.setdefault("seller",{})[k]=v2
            elif v2 is not None:
                merged.setdefault("seller",{})[k]=max(v1 or 0, v2)

        # Shipping: stricter wins
        if (rules.get("shipping") or {}).get("free_shipping_only"):
            merged.setdefault("shipping",{})["free_shipping_only"]=True
        if (rules.get("shipping") or {}).get("max_handling_days") is not None:
            cur = (merged.get("shipping") or {}).get("max_handling_days")
            new = rules["shipping"]["max_handling_days"]
            merged.setdefault("shipping",{})["max_handling_days"] = min(cur or new, new)

        # Listing flags: stricter wins
        if (rules.get("listing") or {}).get("buy_it_now_only"):
            merged.setdefault("listing",{})["buy_it_now_only"]=True

        # Keywords
        k1 = merged.setdefault("keywords", {"must":[],"must_not":[]})
        k2 = rules.get("keywords", {})
        for key in ("must","must_not"):
            k1[key] = list(set(k1.get(key,[])) | set(k2.get(key,[])))

        # Safety always on
        merged.setdefault("safety", {})["exclude_explicit"]=True

    return merged
