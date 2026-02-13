"""
Resolve path to ebay_categories_tree.json.
Looks in scripts/ (project root) first, then flask/ for backward compatibility.
"""
import os
from pathlib import Path

# Flask app root (flask/)
_FLASK_DIR = Path(__file__).resolve().parent.parent.parent
# Project root (parent of flask)
_PROJECT_ROOT = _FLASK_DIR.parent
_SCRIPTS_PATH = _PROJECT_ROOT / "scripts" / "ebay_categories_tree.json"
_LEGACY_PATH = _FLASK_DIR / "ebay_categories_tree.json"


def get_ebay_categories_path() -> str:
    """Return path to ebay_categories_tree.json."""
    if _SCRIPTS_PATH.exists():
        return str(_SCRIPTS_PATH)
    return str(_LEGACY_PATH)
