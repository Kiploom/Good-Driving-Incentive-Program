# app/cart/checkout_routes.py
from __future__ import annotations
from typing import Any, Dict, List

from flask import Blueprint, render_template, request, jsonify, abort, current_app, flash, redirect, url_for, session
from flask_login import login_required, current_user
from app.extensions import db

# Import models
from ..models import (
    Account,
    AccountType,
    Sponsor,
    Driver,
    Cart,
    CartItem,
    Orders,
    OrderLineItem,
    Products,
    PointChange,
    DriverSponsor,
)
from app.utils.point_change_actor import derive_point_change_actor_metadata
from .routes import _get_attr, _first_nonempty, _current_account_id, _is_driver, _get_current_driver, _require_driver
from app.services.shipping_service import ShippingService

bp = Blueprint(
    "checkout",
    __name__,
    url_prefix="/checkout",
    template_folder="templates",
    static_folder="static",
)

# --------- Checkout Routes ----------

@bp.route("/")
@login_required
def checkout():
    """Display the checkout page."""
    driver = _require_driver()
    
    # Get the driver's cart
    cart = Cart.query.filter_by(DriverID=driver.DriverID).first()
    if not cart or cart.items.count() == 0:
        flash("Your cart is empty", "warning")
        return redirect(url_for("cart.view_cart"))
    
    # Load cart items
    cart_items = CartItem.query.filter_by(CartID=cart.CartID).all()
    
    # Check if driver has enough points (environment-specific)
    total_points = cart.total_points
    driver_sponsor_id = session.get('driver_sponsor_id')
    if not driver_sponsor_id:
        flash("No environment selected", "danger")
        return redirect(url_for("driver.select_environment_page"))
    
    env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
    if not env:
        flash("Invalid environment", "danger")
        return redirect(url_for("driver.select_environment_page"))
    
    if env.PointsBalance < total_points:
        flash(f"Insufficient points. You have {env.PointsBalance} points but need {total_points}", "danger")
        return redirect(url_for("cart.view_cart"))
    
    # Get sponsor information from environment
    sponsor = Sponsor.query.filter_by(SponsorID=env.SponsorID).first()
    
    return render_template(
        "cart/checkout.html", 
        cart=cart, 
        cart_items=cart_items,
        driver=driver,
        sponsor=sponsor,
        driver_points=env.PointsBalance
    )

@bp.route("/shipping/estimate", methods=["POST"])
@login_required
def estimate_shipping_cost():
    """Return shipping cost options converted to points using the sponsor's point conversion rules."""
    driver = _require_driver()

    cart = Cart.query.filter_by(DriverID=driver.DriverID).first()
    if not cart or cart.items.count() == 0:
        return jsonify({"success": False, "error": "Cart is empty"}), 400

    data = request.get_json(silent=True) or request.form or {}
    shipping_country = (data.get("shipping_country") or "").strip()
    shipping_state = (data.get("shipping_state") or "").strip()
    shipping_postal = (data.get("shipping_postal") or "").strip()
    estimated_weight = (data.get("estimated_weight") or "medium").strip().lower()

    if not shipping_country:
        return jsonify({"success": False, "error": "Shipping country is required"}), 400

    driver_sponsor_id = session.get('driver_sponsor_id')
    if not driver_sponsor_id:
        return jsonify({"success": False, "error": "No environment selected"}), 400

    env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
    if not env:
        return jsonify({"success": False, "error": "Invalid environment"}), 400

    try:
        options = ShippingService.get_shipping_options(
            shipping_country=shipping_country,
            shipping_state=shipping_state or None,
            item_count=cart.item_count,
            estimated_weight=estimated_weight or "medium",
            sponsor_id=env.SponsorID,
        )
    except Exception as exc:
        current_app.logger.exception("Failed to calculate shipping cost")
        return jsonify({"success": False, "error": str(exc)}), 500

    if not options:
        return jsonify({"success": False, "error": "No shipping options available"}), 400

    formatted_options = []
    for idx, option in enumerate(options):
        option_name = option.get("name", "Shipping Option")
        normalized_name = option_name.lower().strip()
        if idx == 0 or "standard" in normalized_name:
            option_id = "standard"
        elif "express" in normalized_name:
            option_id = "express"
        else:
            option_id = normalized_name.replace(" ", "_") or f"option_{idx}"
        formatted_options.append({
            "id": option_id,
            "name": option_name,
            "method": option.get("method"),
            "cost_points": option.get("cost_points"),
            "cost_usd": option.get("cost_usd"),
            "estimated_days": option.get("days"),
            "description": option.get("description"),
            "region": option.get("region"),
        })

    return jsonify({
        "success": True,
        "options": formatted_options,
        "default_option_id": formatted_options[0]["id"],
        "cart_points": cart.total_points,
        "points_balance": env.PointsBalance,
        "shipping_postal": shipping_postal,
    })

@bp.route("/process", methods=["POST"])
@login_required
def process_checkout():
    """Process the checkout and create an order."""
    driver = _require_driver()
    
    try:
        # Get the driver's cart
        cart = Cart.query.filter_by(DriverID=driver.DriverID).first()
        if not cart or cart.items.count() == 0:
            return jsonify({"success": False, "error": "Cart is empty"}), 400
        
        # Get form data
        data = request.get_json() or request.form
        
        # Validate required fields
        required_fields = [
            'first_name', 'last_name', 'email', 
            'shipping_street', 'shipping_city', 'shipping_state', 
            'shipping_postal', 'shipping_country'
        ]
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400
        
        # Get shipping cost
        shipping_cost_points = int(data.get('shipping_cost_points', 0))
        
        # Calculate total points (items + shipping)
        total_points = cart.total_points + shipping_cost_points
        
        # Get environment-specific points
        driver_sponsor_id = session.get('driver_sponsor_id')
        if not driver_sponsor_id:
            return jsonify({"success": False, "error": "No environment selected"}), 400
        
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if not env:
            return jsonify({"success": False, "error": "Invalid environment"}), 400
        
        # Check if driver has enough points (environment-specific)
        if env.PointsBalance < total_points:
            return jsonify({"success": False, "error": "Insufficient points"}), 400
        
        # Generate order number
        import time
        order_number = f"ORD-{int(time.time())}-{driver.DriverID[:8]}"
        
        # Get sponsor to calculate dollar amount
        from app.models import Sponsor
        sponsor = Sponsor.query.get(env.SponsorID)
        if not sponsor:
            return jsonify({"success": False, "error": "Invalid sponsor"}), 400
        
        # Calculate total dollar amount based on sponsor's point-to-dollar rate
        total_amount = float(total_points) * float(sponsor.PointToDollarRate)
        
        # Create the order (model will use local time automatically)
        # Orders start as 'pending' and will be marked as 'completed' after 5 minutes
        order = Orders(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,  # Use environment-specific sponsor
            OrderNumber=order_number,
            TotalPoints=total_points,
            TotalAmount=total_amount,  # Calculate dollar amount from points
            Status='pending'
        )
        db.session.add(order)
        db.session.flush()  # Get the order ID
        
        # Update driver's shipping information if provided
        if data.get('shipping_street'):
            driver.ShippingStreet = data.get('shipping_street')
            driver.ShippingCity = data.get('shipping_city')
            driver.ShippingState = data.get('shipping_state')
            driver.ShippingPostal = data.get('shipping_postal')
            driver.ShippingCountry = data.get('shipping_country')
        
        # Create order line items from cart items
        for cart_item in cart.items:
            # For external catalog items, we'll create a temporary product entry
            product = Products.query.filter_by(ExternalItemID=cart_item.ExternalItemID).first()
            if not product:
                product = Products(
                    Title=cart_item.ItemTitle,
                    PointsPrice=cart_item.PointsPerUnit,
                    ExternalItemID=cart_item.ExternalItemID,
                )
                db.session.add(product)
                db.session.flush()  # get ProductID

            line_total_points = cart_item.PointsPerUnit * cart_item.Quantity
            
            order_line_item = OrderLineItem(
                OrderID=order.OrderID,
                ProductID=product.ProductID,  # Use the actual ProductID from the Products table
                Title=cart_item.ItemTitle,
                UnitPoints=cart_item.PointsPerUnit,
                Quantity=cart_item.Quantity,
                LineTotalPoints=line_total_points
            )
            db.session.add(order_line_item)
        
        # Add shipping cost as a line item if there's a shipping cost
        if shipping_cost_points > 0:
            # Create a special product for shipping
            shipping_product = Products.query.filter_by(Title="Shipping Cost").first()
            if not shipping_product:
                shipping_product = Products(
                    Title="Shipping Cost",
                    PointsPrice=shipping_cost_points,
                    ExternalItemID="SHIPPING",
                )
                db.session.add(shipping_product)
                db.session.flush()  # get ProductID
            
            shipping_line_item = OrderLineItem(
                OrderID=order.OrderID,
                ProductID=shipping_product.ProductID,
                Title="Shipping Cost",
                UnitPoints=shipping_cost_points,
                Quantity=1,
                LineTotalPoints=shipping_cost_points
            )
            db.session.add(shipping_line_item)
        
        # Deduct points from environment-specific balance
        env.PointsBalance -= total_points
        
        # Record the point change
        actor_meta = derive_point_change_actor_metadata(current_user)

        point_change = PointChange(
            DriverID=driver.DriverID,
            SponsorID=env.SponsorID,  # Use environment-specific sponsor
            DeltaPoints=-total_points,
            TransactionID=order.OrderID,
            InitiatedByAccountID=driver.AccountID,
            BalanceAfter=env.PointsBalance,  # Use environment-specific balance
            Reason=f"Order #{order.OrderNumber} - Points Payment",
            ActorRoleCode=actor_meta["actor_role_code"],
            ActorLabel=actor_meta["actor_label"],
            ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
            ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
        )
        db.session.add(point_change)
        
        # Send notifications
        try:
            from app.services.notification_service import NotificationService
            from app.models import NotificationPreferences
            
            # Send point deduction notification (simple points change)
            NotificationService.notify_driver_points_change(
                driver_id=driver.DriverID,
                delta_points=-total_points,
                reason=f"Order #{order.OrderNumber} - Points Payment",
                balance_after=env.PointsBalance,
            transaction_id=order.OrderNumber,
            sponsor_id=env.SponsorID
            )
            
            # Check for low points alert
            prefs = NotificationPreferences.query.filter_by(DriverID=driver.DriverID).first()
            if prefs and prefs.LowPointsAlertEnabled and prefs.LowPointsThreshold is not None:
                if env.PointsBalance < prefs.LowPointsThreshold:
                    NotificationService.notify_driver_low_points(
                        driver_id=driver.DriverID,
                        current_balance=env.PointsBalance,
                        threshold=prefs.LowPointsThreshold
                    )
            
            # Send order confirmation notification (detailed order info)
            NotificationService.notify_driver_order_confirmation(order_id=order.OrderID)
            
            # Send sponsor notification about new order
            NotificationService.notify_sponsor_new_order(order_id=order.OrderID)
            
        except Exception as e:
            current_app.logger.error(f"Failed to send checkout notifications: {str(e)}")
        
        # Clear the cart
        CartItem.query.filter_by(CartID=cart.CartID).delete()
        
        # Commit all changes
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Order placed successfully",
            "order_id": order.OrderID,
            "redirect_url": url_for("checkout.order_confirmation", order_id=order.OrderID)
        })
        
    except Exception as e:
        current_app.logger.exception("Error processing checkout")
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/confirmation/<order_id>")
@login_required
def order_confirmation(order_id):
    """Display order confirmation page."""
    driver = _require_driver()
    
    # Get the order
    order = Orders.query.filter_by(OrderID=order_id, DriverID=driver.DriverID).first()
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for("cart.view_cart"))
    
    # Load order line items
    order_items = OrderLineItem.query.filter_by(OrderID=order.OrderID).all()
    
    # Get environment-specific points balance
    driver_sponsor_id = session.get('driver_sponsor_id')
    driver_points = 0
    if driver_sponsor_id:
        from app.models import DriverSponsor
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if env:
            driver_points = env.PointsBalance or 0
    
    return render_template(
        "cart/order_confirmation.html", 
        order=order, 
        order_items=order_items,
        driver=driver,
        driver_points=driver_points
    )

@bp.route("/orders/<order_id>")
@login_required
def order_details(order_id):
    """Display order details page."""
    driver = _require_driver()
    
    # SECURITY FIX: Validate order_id format to prevent injection
    if not order_id or not isinstance(order_id, str) or len(order_id) > 50:
        flash("Invalid order ID", "danger")
        return redirect(url_for("orders.view_orders"))
    
    # Get the order - this prevents unauthorized access to other drivers' orders
    order = Orders.query.filter_by(OrderID=order_id, DriverID=driver.DriverID).first()
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for("orders.view_orders"))
    
    # Load order line items
    order_items = OrderLineItem.query.filter_by(OrderID=order.OrderID).all()
    
    # Get environment-specific points balance
    driver_sponsor_id = session.get('driver_sponsor_id')
    driver_points = 0
    if driver_sponsor_id:
        from app.models import DriverSponsor
        env = DriverSponsor.query.filter_by(DriverSponsorID=driver_sponsor_id).first()
        if env:
            driver_points = env.PointsBalance or 0
    
    return render_template(
        "cart/order_details.html", 
        order=order, 
        order_items=order_items,
        driver=driver,
        driver_points=driver_points
    )
