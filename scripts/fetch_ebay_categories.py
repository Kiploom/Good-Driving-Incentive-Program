#!/usr/bin/env python3
"""
Script to fetch all eBay category IDs and names from eBay Taxonomy API.
Outputs a JSON file with the complete category tree.

Usage (from project root):
    python scripts/fetch_ebay_categories.py

Output (in scripts/ folder):
    ebay_categories_tree.json - Complete category tree
    ebay_categories_flat.json - Flat list of all categories
    ebay_categories_hierarchy.json - Hierarchical structure
    ebay_categories_id_map.json - ID to name mapping
"""

import os
import sys
import json
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

# Paths: script lives in scripts/, project root is parent
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
FLASK_DIR = PROJECT_ROOT / "flask"

# Add flask to path for app imports
sys.path.insert(0, str(FLASK_DIR))

# Load .env from flask directory
load_dotenv(FLASK_DIR / ".env")

# Import eBay OAuth manager
try:
    from app.ebay_oauth import EbayOAuthManager
    oauth_manager = EbayOAuthManager()
except ImportError:
    print("Error: Could not import EbayOAuthManager. Make sure flask app is at flask/.")
    sys.exit(1)


def get_bearer_token() -> Optional[str]:
    """Get OAuth bearer token."""
    try:
        token = oauth_manager.get_token()
        if token:
            return f"Bearer {token}"
        token = os.getenv("EBAY_OAUTH_TOKEN")
        if token:
            return f"Bearer {token}"
        return None
    except Exception as e:
        print(f"Warning: Could not get OAuth token: {e}")
        token = os.getenv("EBAY_OAUTH_TOKEN")
        if token:
            return f"Bearer {token}"
        return None


def fetch_category_tree(category_tree_id: str = "0") -> Optional[Dict[str, Any]]:
    """Fetch the complete category tree from eBay Taxonomy API."""
    bearer_token = get_bearer_token()
    if not bearer_token:
        print("Error: No OAuth token available. Please set EBAY_OAUTH_TOKEN in flask/.env")
        return None

    marketplace_id = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{category_tree_id}"
    headers = {
        "Authorization": bearer_token,
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id
    }

    print(f"Fetching category tree from eBay API...")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching category tree: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
        return None


def parse_category_tree(tree_data: Dict[str, Any], parent_path: str = "") -> List[Dict[str, Any]]:
    """Recursively parse the category tree to extract all categories."""
    categories = []
    if not isinstance(tree_data, dict):
        return categories

    root_category = tree_data.get("rootCategoryNode", {})

    def traverse_node(node: Dict[str, Any], path: str = ""):
        category_id = node.get("categoryId")
        category_name = node.get("categoryName", "")
        if category_id and category_name:
            full_path = f"{path} > {category_name}" if path else category_name
            categories.append({
                "id": str(category_id),
                "name": category_name,
                "full_path": full_path,
                "leaf": node.get("leafCategoryTreeNode", False),
                "level": len([p for p in full_path.split(" > ") if p])
            })
        child_nodes = node.get("childCategoryTreeNodes", [])
        current_path = f"{path} > {category_name}" if path else category_name
        for child in child_nodes:
            traverse_node(child, current_path)

    traverse_node(root_category)
    return categories


def build_hierarchical_structure(categories: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a hierarchical structure from flat category list."""
    hierarchy = {}
    for cat in categories:
        path_parts = cat["full_path"].split(" > ")
        current = hierarchy
        for i, part in enumerate(path_parts):
            is_last = (i == len(path_parts) - 1)
            if part not in current:
                if is_last:
                    current[part] = {cat["id"]: cat["name"]}
                else:
                    current[part] = {}
            else:
                if is_last and isinstance(current[part], dict):
                    current[part][cat["id"]] = cat["name"]
            if isinstance(current.get(part), dict):
                current = current[part]
            else:
                break
    return hierarchy


def main():
    """Main function to fetch and save categories."""
    print("=" * 60)
    print("eBay Category ID Fetcher")
    print("=" * 60)

    tree_data = fetch_category_tree("0")
    if not tree_data:
        sys.exit(1)

    categories = parse_category_tree(tree_data)
    hierarchy = build_hierarchical_structure(categories)

    output_dir = SCRIPT_DIR
    tree_file = output_dir / "ebay_categories_tree.json"
    flat_file = output_dir / "ebay_categories_flat.json"
    hierarchy_file = output_dir / "ebay_categories_hierarchy.json"
    id_map_file = output_dir / "ebay_categories_id_map.json"

    with open(tree_file, 'w', encoding='utf-8') as f:
        json.dump(tree_data, f, indent=2, ensure_ascii=False)
    with open(flat_file, 'w', encoding='utf-8') as f:
        json.dump(categories, f, indent=2, ensure_ascii=False)
    with open(hierarchy_file, 'w', encoding='utf-8') as f:
        json.dump(hierarchy, f, indent=2, ensure_ascii=False)
    id_to_name = {cat["id"]: cat["name"] for cat in categories}
    with open(id_map_file, 'w', encoding='utf-8') as f:
        json.dump(id_to_name, f, indent=2, ensure_ascii=False)

    print(f"Saved to {output_dir}")
    print(f"  - {tree_file.name}")
    print(f"  - {flat_file.name}")
    print(f"  - {hierarchy_file.name}")
    print(f"  - {id_map_file.name}")
    print(f"Total categories: {len(categories)}")


if __name__ == "__main__":
    main()
