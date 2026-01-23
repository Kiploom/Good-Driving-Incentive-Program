#!/usr/bin/env python3
"""
Script to fetch all eBay category IDs and names from eBay Taxonomy API.
Outputs a JSON file with the complete category tree.

Usage:
    python fetch_ebay_categories.py

Output:
    ebay_categories.json - Complete category tree with IDs and names
    ebay_categories_flat.json - Flat list of all categories for easy lookup
"""

import os
import sys
import json
import requests
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv, find_dotenv

# Add flask app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load environment variables
load_dotenv(find_dotenv())

# Import eBay OAuth manager
try:
    from app.ebay_oauth import EbayOAuthManager
    # Create a new instance for this script
    oauth_manager = EbayOAuthManager()
except ImportError:
    print("Error: Could not import EbayOAuthManager. Make sure you're running from the flask directory.")
    sys.exit(1)


def get_bearer_token() -> Optional[str]:
    """Get OAuth bearer token."""
    try:
        token = oauth_manager.get_token()
        if token:
            return f"Bearer {token}"
        
        # Fallback to environment variable
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
    """
    Fetch the complete category tree from eBay Taxonomy API.
    
    Args:
        category_tree_id: The category tree ID (0 = US marketplace)
    
    Returns:
        Category tree data or None if failed
    """
    bearer_token = get_bearer_token()
    if not bearer_token:
        print("Error: No OAuth token available. Please set EBAY_OAUTH_TOKEN in your .env file.")
        return None
    
    marketplace_id = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    
    url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{category_tree_id}"
    headers = {
        "Authorization": bearer_token,
        "Accept": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id
    }
    
    print(f"Fetching category tree from eBay API...")
    print(f"URL: {url}")
    print(f"Marketplace: {marketplace_id}")
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching category tree: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response text: {e.response.text[:500]}")
        return None


def parse_category_tree(tree_data: Dict[str, Any], parent_path: str = "") -> List[Dict[str, Any]]:
    """
    Recursively parse the category tree to extract all categories.
    
    Args:
        tree_data: The category tree data from eBay API
        parent_path: Path of parent categories (for hierarchy)
    
    Returns:
        List of category dictionaries with id, name, and full_path
    """
    categories = []
    
    if not isinstance(tree_data, dict):
        return categories
    
    # Get root category
    root_category = tree_data.get("rootCategoryNode", {})
    
    def traverse_node(node: Dict[str, Any], path: str = ""):
        """Recursively traverse category nodes."""
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
        
        # Traverse child categories
        child_nodes = node.get("childCategoryTreeNodes", [])
        current_path = f"{path} > {category_name}" if path else category_name
        
        for child in child_nodes:
            traverse_node(child, current_path)
    
    # Start traversal from root
    traverse_node(root_category)
    
    return categories


def build_hierarchical_structure(categories: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a hierarchical structure from flat category list.
    Groups categories by their path hierarchy.
    """
    hierarchy = {}
    
    for cat in categories:
        path_parts = cat["full_path"].split(" > ")
        
        # Build nested structure
        current = hierarchy
        for i, part in enumerate(path_parts):
            is_last = (i == len(path_parts) - 1)
            
            if part not in current:
                if is_last:
                    # Leaf node - store ID mapping
                    current[part] = {cat["id"]: cat["name"]}
                else:
                    # Parent node - create nested dict
                    current[part] = {}
            else:
                # Node already exists
                if is_last:
                    # If it's a dict (parent), convert to ID mapping
                    if isinstance(current[part], dict) and not any(isinstance(v, str) for v in current[part].values()):
                        # It's a parent container, add the ID mapping
                        current[part][cat["id"]] = cat["name"]
                    elif isinstance(current[part], dict):
                        # Already has ID mappings, add this one
                        current[part][cat["id"]] = cat["name"]
            
            # Move to next level
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
    print()
    
    # Fetch category tree
    tree_data = fetch_category_tree("0")  # 0 = US marketplace
    
    if not tree_data:
        print("Failed to fetch category tree. Exiting.")
        sys.exit(1)
    
    print("Successfully fetched category tree!")
    print("Parsing category tree...")
    
    # Parse categories
    categories = parse_category_tree(tree_data)
    
    print(f"Found {len(categories)} categories!")
    print()
    
    # Build hierarchical structure
    print("Building hierarchical structure...")
    hierarchy = build_hierarchical_structure(categories)
    
    # Save outputs
    output_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Save complete tree structure
    tree_file = os.path.join(output_dir, "ebay_categories_tree.json")
    with open(tree_file, 'w', encoding='utf-8') as f:
        json.dump(tree_data, f, indent=2, ensure_ascii=False)
    print(f"Saved complete tree to: {tree_file}")
    
    # 2. Save flat list (easy to search)
    flat_file = os.path.join(output_dir, "ebay_categories_flat.json")
    with open(flat_file, 'w', encoding='utf-8') as f:
        json.dump(categories, f, indent=2, ensure_ascii=False)
    print(f"Saved flat list to: {flat_file}")
    
    # 3. Save hierarchical structure (for easy integration)
    hierarchy_file = os.path.join(output_dir, "ebay_categories_hierarchy.json")
    with open(hierarchy_file, 'w', encoding='utf-8') as f:
        json.dump(hierarchy, f, indent=2, ensure_ascii=False)
    print(f"Saved hierarchy to: {hierarchy_file}")
    
    # 4. Save ID to name mapping (simple lookup)
    id_map_file = os.path.join(output_dir, "ebay_categories_id_map.json")
    id_to_name = {cat["id"]: cat["name"] for cat in categories}
    with open(id_map_file, 'w', encoding='utf-8') as f:
        json.dump(id_to_name, f, indent=2, ensure_ascii=False)
    print(f"Saved ID mapping to: {id_map_file}")
    
    # 5. Print summary
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total categories found: {len(categories)}")
    print(f"Categories with IDs: {len([c for c in categories if c.get('id')])}")
    print()
    print("Sample categories (first 10):")
    for cat in categories[:10]:
        print(f"  [{cat['id']}] {cat['full_path']}")
    print()
    print("Files created:")
    print(f"  - {tree_file}")
    print(f"  - {flat_file}")
    print(f"  - {hierarchy_file}")
    print(f"  - {id_map_file}")
    print()
    print("You can now use these files to populate the category browser!")


if __name__ == "__main__":
    main()

