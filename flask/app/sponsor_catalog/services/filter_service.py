def normalize_rules(rules: dict) -> dict:
    # minimal normalization; extend as you like
    rules = rules or {}
    b = rules.get("brands", {})
    if "include" in b: b["include"] = [x.strip() for x in b["include"] if x]
    if "exclude" in b: b["exclude"] = [x.strip() for x in b["exclude"] if x]
    rules["brands"]=b
    rules.setdefault("safety", {})["exclude_explicit"]=True
    return rules
