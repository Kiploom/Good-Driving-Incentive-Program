# app/cart/routes.py
from __future__ import annotations
from typing import Any, Dict, List, Optional

from flask import Blueprint, render_template, request, jsonify, abort, current_app, flash, redirect, url_for, session
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload
from app.extensions import db

# Import models
from ..models import Account, AccountType, Sponsor, Driver, Cart, CartItem, Orders, OrderLineItem, PointChange, Products, DriverSponsor
from ..driver_points_catalog.services.points_service import price_to_points
from flask import session

bp = Blueprint(
    "cart",
    __name__,
    url_prefix="/cart",
    template_folder="templates",
    static_folder="static",
)

# Helper function to get environment-specific points balance
def _get_driver_points_balance():
    """Get the current driver's points balance from their selected environment."""
    try:
        driver_sponsor_id = session.get('driver_sponsor_id')
        if driver_sponsor_id:
            env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
            if env:
                return env.PointsBalance or 0
    except Exception:
        pass
    return 0

# --------- Helper functions ----------

def _get_attr(obj: Any, *names: str) -> Any:
    """Return the first existing attribute (truthy or falsy allowed) by name variant."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None

def _first_nonempty(*vals):
    for v in vals:
        if v not in (None, "", []):
            return v
    return None

def _current_account_id() -> Optional[str]:
    """Resolve the current account's primary key across naming variants."""
    current_app.logger.info(f"Current user object: {current_user}")
    current_app.logger.info(f"Current user attributes: {dir(current_user)}")
    current_app.logger.info(f"Current user AccountID: {getattr(current_user, 'AccountID', 'NOT_FOUND')}")
    current_app.logger.info(f"Current user get_id(): {current_user.get_id() if hasattr(current_user, 'get_id') else 'NO_GET_ID'}")
    
    uid = _first_nonempty(
        _get_attr(current_user, "AccountID"),
        _get_attr(current_user, "account_id"),
        _get_attr(current_user, "ID"),
        _get_attr(current_user, "id"),
        current_user.get_id() if hasattr(current_user, "get_id") else None,
    )
    current_app.logger.info(f"Resolved account ID: {uid}")
    return uid

def _is_driver() -> bool:
    """True if the logged-in Account's AccountType is 'Driver'."""
    try:
        account_id = _current_account_id()
        current_app.logger.info(f"Driver check - Account ID: {account_id}")
        if not account_id:
            current_app.logger.warning("No account ID found")
            return False

        acct = Account.query.filter_by(AccountID=account_id).first()
        current_app.logger.info(f"Driver check - Account: {acct.AccountID if acct else 'None'}")
        if not acct:
            current_app.logger.warning("No account found")
            return False

        # Updated driver check logic with logs for clarity
        account_type = (_get_attr(acct, "AccountType") or "").strip().upper()
        current_app.logger.info(f"Driver check - AccountType: {account_type}")

        if not account_type:
            current_app.logger.warning("No account type value found on account")
            return False

        return account_type == "DRIVER"
    except Exception as e:
        current_app.logger.warning("is_driver check failed: %s", e)
        return False

def _get_current_driver() -> Optional[Driver]:
    """Get the current driver record."""
    try:
        account_id = _current_account_id()
        if not account_id:
            return None
        return Driver.query.filter_by(AccountID=account_id).first()
    except Exception as e:
        current_app.logger.warning("get_current_driver failed: %s", e)
        return None

def _get_or_create_cart(driver_id: str) -> Cart:
    """Get existing cart or create a new one for the driver."""
    cart = Cart.query.filter_by(DriverID=driver_id).first()
    if not cart:
        cart = Cart(DriverID=driver_id)
        db.session.add(cart)
        db.session.commit()
    return cart

def _require_driver() -> Driver:
    """Require that the current user is a driver."""
    if not getattr(current_user, "is_authenticated", False):
        abort(401)

    if not _is_driver():
        current_app.logger.warning("Cart 403: user not recognized as DRIVER")
        abort(403)

    driver = _get_current_driver()
    if not driver:
        current_app.logger.warning("Cart 403: no driver record found")
        abort(403)

    return driver

# --------- Cart Routes ----------

@bp.route("/test")
@login_required
def test_cart():
    """Test endpoint to check cart functionality."""
    try:
        current_app.logger.info(f"Test cart - Current user: {current_user}")
        current_app.logger.info(f"Test cart - Session: {dict(session)}")
        current_app.logger.info(f"Test cart - User authenticated: {getattr(current_user, 'is_authenticated', False)}")
        
        driver = _require_driver()
        return jsonify({
            "success": True,
            "message": "Cart test successful",
            "driver_id": driver.DriverID,
            "user_authenticated": getattr(current_user, 'is_authenticated', False),
            "session": dict(session)
        })
    except Exception as e:
        current_app.logger.error(f"Test cart error: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "user_authenticated": getattr(current_user, 'is_authenticated', False),
            "session": dict(session)
        }), 500

@bp.route("/")
@login_required
def view_cart():
    """Display the cart page."""
    driver = _require_driver()
    cart = _get_or_create_cart(driver.DriverID)
    
    # Load cart items with their details
    cart_items = CartItem.query.filter_by(CartID=cart.CartID).all()
    
    return render_template("cart/view_cart.html", 
                         cart=cart, 
                         cart_items=cart_items,
                         driver=driver,
                         driver_points=_get_driver_points_balance())

@bp.route("/add", methods=["POST"])
@login_required
def add_to_cart():
    """Add an item to the cart."""
    from flask import current_app
    current_app.logger.info(f"Add to cart request - User: {current_user.AccountID if current_user else 'None'}")
    current_app.logger.info(f"Add to cart request - Session: {dict(session)}")
    current_app.logger.info("Add to cart request received")

    try:
        driver = _require_driver()
        current_app.logger.info(f"Add to cart request - Driver: {driver.DriverID if driver else 'None'}")
    except Exception as e:
        current_app.logger.error(f"Driver authentication failed: {e}")
        return jsonify({"success": False, "error": "Authentication failed"}), 401

    
    try:
        data = request.get_json() or request.form
        current_app.logger.info(f"Request data: {data}")
        
        external_item_id = data.get("external_item_id")
        item_title = data.get("item_title", "")
        item_image_url = data.get("item_image_url", "")
        item_url = data.get("item_url", "")
        
        # SECURITY FIX: Validate and sanitize input data to prevent injection attacks
        if not external_item_id or not isinstance(external_item_id, str):
            current_app.logger.warning(f"Invalid item ID: {external_item_id}")
            return jsonify({"success": False, "error": "Invalid item ID"}), 400
            
        # Sanitize string inputs to prevent XSS
        external_item_id = external_item_id.strip()[:100]  # Limit length
        item_title = item_title.strip()[:500] if item_title else ""
        item_image_url = item_image_url.strip()[:1000] if item_image_url else ""
        item_url = item_url.strip()[:1000] if item_url else ""
        
        # Validate numeric inputs
        try:
            points_per_unit = int(data.get("points_per_unit", 0))
            quantity = int(data.get("quantity", 1))
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid numeric data"}), 400
        
        if points_per_unit <= 0 or quantity <= 0 or quantity > 100:  # Reasonable quantity limit
            return jsonify({"success": False, "error": "Invalid item data"}), 400
        
        # Get or create cart
        cart = _get_or_create_cart(driver.DriverID)
        
        # Check if item already exists in cart
        existing_item = CartItem.query.filter_by(
            CartID=cart.CartID, 
            ExternalItemID=external_item_id
        ).first()
        
        if existing_item:
            # Update quantity
            existing_item.Quantity += quantity
            existing_item.UpdatedAt = db.func.now()
        else:
            # Create new cart item
            cart_item = CartItem(
                CartID=cart.CartID,
                ExternalItemID=external_item_id,
                ItemTitle=item_title,
                ItemImageURL=item_image_url,
                ItemURL=item_url,
                PointsPerUnit=points_per_unit,
                Quantity=quantity
            )
            db.session.add(cart_item)
        
        db.session.commit()
        current_app.logger.info(f"Item added to cart successfully: {external_item_id}")
        
        return jsonify({
            "success": True, 
            "message": "Item added to cart",
            "cart_total": cart.total_points,
            "item_count": cart.item_count
        })
        
    except Exception as e:
        current_app.logger.exception("Error adding item to cart")
        current_app.logger.error(f"Cart error details - User: {current_user}, Authenticated: {getattr(current_user, 'is_authenticated', False)}")
        db.session.rollback()
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@bp.route("/update", methods=["POST"])
@login_required
def update_cart_item():
    """Update the quantity of a cart item."""
    driver = _require_driver()
    
    try:
        data = request.get_json() or request.form
        cart_item_id = data.get("cart_item_id")
        quantity = int(data.get("quantity", 1))
        
        if not cart_item_id or quantity < 0:
            return jsonify({"success": False, "error": "Invalid data"}), 400
        
        # Get the cart item
        cart_item = CartItem.query.filter_by(CartItemID=cart_item_id).first()
        if not cart_item:
            return jsonify({"success": False, "error": "Item not found"}), 404
        
        # Verify the item belongs to the current driver's cart
        cart = Cart.query.filter_by(CartID=cart_item.CartID, DriverID=driver.DriverID).first()
        if not cart:
            return jsonify({"success": False, "error": "Unauthorized"}), 403
        
        if quantity == 0:
            # Remove item
            db.session.delete(cart_item)
        else:
            # Update quantity
            cart_item.Quantity = quantity
            cart_item.UpdatedAt = db.func.now()
        
        db.session.commit()
        
        # Refresh cart data
        cart = _get_or_create_cart(driver.DriverID)
        
        return jsonify({
            "success": True,
            "message": "Cart updated",
            "cart_total": cart.total_points,
            "item_count": cart.item_count
        })
        
    except Exception as e:
        current_app.logger.exception("Error updating cart item")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/remove", methods=["POST"])
@login_required
def remove_from_cart():
    """Remove an item from the cart."""
    driver = _require_driver()
    
    try:
        data = request.get_json() or request.form
        cart_item_id = data.get("cart_item_id")
        
        if not cart_item_id:
            return jsonify({"success": False, "error": "Item ID required"}), 400
        
        # Get the cart item
        cart_item = CartItem.query.filter_by(CartItemID=cart_item_id).first()
        if not cart_item:
            return jsonify({"success": False, "error": "Item not found"}), 404
        
        # Verify the item belongs to the current driver's cart
        cart = Cart.query.filter_by(CartID=cart_item.CartID, DriverID=driver.DriverID).first()
        if not cart:
            return jsonify({"success": False, "error": "Unauthorized"}), 403
        
        # Remove the item
        db.session.delete(cart_item)
        db.session.commit()
        
        # Refresh cart data
        cart = _get_or_create_cart(driver.DriverID)
        
        return jsonify({
            "success": True,
            "message": "Item removed from cart",
            "cart_total": cart.total_points,
            "item_count": cart.item_count
        })
        
    except Exception as e:
        current_app.logger.exception("Error removing item from cart")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/clear", methods=["POST"])
@login_required
def clear_cart():
    """Clear all items from the cart."""
    driver = _require_driver()
    
    try:
        cart = _get_or_create_cart(driver.DriverID)
        
        # Delete all cart items
        CartItem.query.filter_by(CartID=cart.CartID).delete()
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Cart cleared",
            "cart_total": 0,
            "item_count": 0
        })
        
    except Exception as e:
        current_app.logger.exception("Error clearing cart")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/api/summary")
@login_required
def cart_summary():
    """Get cart summary for AJAX updates."""
    driver = _require_driver()
    cart = _get_or_create_cart(driver.DriverID)
    
    return jsonify({
        "cart_total": cart.total_points,
        "item_count": cart.item_count,
        "driver_points": _get_driver_points_balance()
    })
