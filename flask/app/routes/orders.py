"""
Orders routes for viewing driver order history.
"""

from flask import Blueprint, render_template, request, jsonify, abort, current_app, send_file
from flask_login import login_required, current_user
from app.extensions import db
from io import BytesIO
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas

# Import models
from ..models import Account, Driver, Orders, OrderLineItem, PointChange
from app.utils.point_change_actor import derive_point_change_actor_metadata

bp = Blueprint(
    "orders",
    __name__,
    url_prefix="/orders",
    template_folder="templates",
    static_folder="static",
)

def _get_attr(obj, *names):
    """Return the first existing attribute by name variant."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None

def _first_nonempty(*vals):
    for v in vals:
        if v not in (None, "", []):
            return v
    return None

def _current_account_id():
    """Resolve the current account's primary key across naming variants."""
    uid = _first_nonempty(
        _get_attr(current_user, "AccountID"),
        _get_attr(current_user, "account_id"),
        _get_attr(current_user, "ID"),
        _get_attr(current_user, "id"),
        current_user.get_id() if hasattr(current_user, "get_id") else None,
    )
    return uid

def _require_driver():
    """Require that the current user is a driver."""
    if not getattr(current_user, "is_authenticated", False):
        abort(401)

    account_id = _current_account_id()
    if not account_id:
        abort(403)

    # Get driver record
    driver = Driver.query.filter_by(AccountID=account_id).first()
    if not driver:
        abort(403)

    return driver

@bp.route("/")
@login_required
def view_orders():
    """Display the driver's order history."""
    driver = _require_driver()
    
    # Get filter parameters
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    status_filter = request.args.get('status', '')
    
    # Build query with filters
    query = Orders.query.filter_by(DriverID=driver.DriverID)
    
    # Apply date filters
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Orders.CreatedAt >= start_dt)
        except ValueError:
            pass  # Invalid date format, ignore
    
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            # Include the entire end date (up to end of day)
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(Orders.CreatedAt <= end_dt)
        except ValueError:
            pass  # Invalid date format, ignore
    
    # Apply status filter
    if status_filter in ['pending', 'completed', 'refunded', 'cancelled']:
        query = query.filter(Orders.Status == status_filter)
    
    # Get orders
    orders = query.order_by(Orders.CreatedAt.desc()).limit(500).all()  # Increased limit for filtering
    
    # Get line items for all orders in a separate query
    order_ids = [order.OrderID for order in orders]
    line_items = {}
    if order_ids:
        items = OrderLineItem.query.filter(OrderLineItem.OrderID.in_(order_ids)).all()
        for item in items:
            if item.OrderID not in line_items:
                line_items[item.OrderID] = []
            line_items[item.OrderID].append(item)
    
    # Format orders for display
    formatted_orders = []
    pending_window = timedelta(minutes=5)  # 5-minute pending window
    refund_window = timedelta(minutes=5)  # 5-minute refund window
    
    for order in orders:
        # Use local time instead of UTC for calculations
        now = datetime.now()  # Local time
        
        # Order time should be in local time (assuming database stores local time)
        order_time = order.CreatedAt
        if order_time.tzinfo is not None:
            # If order time is timezone-aware, convert to local time
            order_time = order_time.replace(tzinfo=None)
        
        time_since_order = now - order_time
        
        # Determine actual display status
        # If order is marked as 'pending' in DB but more than 5 minutes have passed, treat as completed
        display_status = order.Status
        is_still_pending = False
        
        if order.Status == 'pending':
            if time_since_order <= pending_window:
                # Still within pending window
                is_still_pending = True
                display_status = 'pending'
            else:
                # Pending period has passed, mark as completed
                display_status = 'completed'
                # Update the database status if needed (optional, for consistency)
                if order.Status == 'pending':
                    order.Status = 'completed'
                    db.session.commit()
        
        # Calculate refund eligibility
        # Refund is only available for completed orders within 5 minutes
        can_refund = (
            display_status == 'completed' and 
            time_since_order <= refund_window
        )
        
        # Calculate remaining refund time
        if can_refund:
            remaining_time = refund_window - time_since_order
            refund_time_remaining = int(remaining_time.total_seconds() / 60)
        else:
            refund_time_remaining = 0
        
        # Calculate pending time remaining
        if is_still_pending:
            remaining_pending_time = pending_window - time_since_order
            pending_time_remaining = int(remaining_pending_time.total_seconds() / 60)
        else:
            pending_time_remaining = 0
        
        order_data = {
            'order_id': order.OrderID,
            'order_number': order.OrderNumber,
            'total_points': order.TotalPoints,
            'status': display_status,  # Use display status
            'created_at': order.CreatedAt,
            'can_refund': can_refund,
            'refund_time_remaining': refund_time_remaining,
            'is_pending': is_still_pending,
            'pending_time_remaining': pending_time_remaining,
            'order_items': []
        }
        
        # Add line items with item details
        order_line_items = line_items.get(order.OrderID, [])
        for line_item in order_line_items:
            # Get product details including ExternalItemID
            external_item_id = None
            if line_item.product:
                external_item_id = line_item.product.ExternalItemID
            
            item_data = {
                'title': line_item.Title,
                'unit_points': line_item.UnitPoints,
                'quantity': line_item.Quantity,
                'line_total_points': line_item.LineTotalPoints,
                'created_at': line_item.CreatedAt,
                'external_item_id': external_item_id
            }
            order_data['order_items'].append(item_data)
        
        formatted_orders.append(order_data)
    
    return render_template(
        "orders/view_orders.html",
        orders=formatted_orders,
        driver=driver,
        start_date=start_date,
        end_date=end_date,
        status_filter=status_filter
    )

@bp.route("/refund/<order_id>", methods=["POST"])
@login_required
def refund_order(order_id):
    """Refund a completed order or cancel a pending order within 5 minutes of purchase."""
    driver = _require_driver()
    
    try:
        # Get the order
        order = Orders.query.filter_by(
            OrderID=order_id, 
            DriverID=driver.DriverID
        ).first()
        
        if not order:
            return jsonify({"success": False, "error": "Order not found"}), 404
        
        # Check if order can be refunded/cancelled
        now = datetime.now()  # Local time
        
        order_time = order.CreatedAt
        if order_time.tzinfo is not None:
            order_time = order_time.replace(tzinfo=None)
        
        time_since_order = now - order_time
        refund_window = timedelta(minutes=5)  # 5-minute refund/cancel window
        pending_window = timedelta(minutes=5)  # 5-minute pending window
        
        # Determine actual status (pending orders older than 5 minutes are treated as completed)
        actual_status = order.Status
        if order.Status == 'pending' and time_since_order > pending_window:
            actual_status = 'completed'
            # Update the database status
            order.Status = 'completed'
            db.session.commit()
        
        # Check if order is still within the window
        if time_since_order > refund_window:
            if actual_status == 'pending':
                return jsonify({"success": False, "error": "Cancel window has expired (5 minutes)"}), 400
            else:
                return jsonify({"success": False, "error": "Refund window has expired (5 minutes)"}), 400
        
        # Handle pending orders (cancel)
        is_cancellation = (actual_status == 'pending' or order.Status == 'pending')
        
        # Get the DriverSponsor relationship for this order's sponsor
        # Points are stored environment-specific (per sponsor), not on the driver directly
        from ..models import DriverSponsor
        
        # Use SELECT FOR UPDATE to lock the row and prevent concurrent refunds
        # This ensures we always read the latest balance even with simultaneous requests
        # The lock will be held until the transaction commits, preventing race conditions
        driver_sponsor = db.session.query(DriverSponsor).filter_by(
            DriverID=driver.DriverID,
            SponsorID=order.SponsorID
        ).with_for_update().first()
        
        if not driver_sponsor:
            return jsonify({"success": False, "error": "Driver-Sponsor relationship not found for this order"}), 400
        
        # Process refund
        # Get current balance before refund
        current_balance = driver_sponsor.PointsBalance or 0
        
        # Calculate new balance after refund
        new_balance = current_balance + order.TotalPoints
        
        # Add points back to driver's environment-specific balance
        driver_sponsor.PointsBalance = new_balance
        
        # Update order status
        if is_cancellation:
            order.Status = 'cancelled'
            action_message = "Order cancelled successfully"
            reason_text = f"Cancel for Order #{order.OrderNumber}"
        else:
            order.Status = 'refunded'
            action_message = "Order refunded successfully"
            reason_text = f"Refund for Order #{order.OrderNumber}"
        # UpdatedAt will be set automatically by the model
        
        # Record the point change
        actor_meta = derive_point_change_actor_metadata(current_user)
        point_change = PointChange(
            DriverID=driver.DriverID,
            SponsorID=order.SponsorID,  # Use order's SponsorID captured at purchase time
            DeltaPoints=order.TotalPoints,  # Positive for refund/cancel
            TransactionID=order.OrderID,
            InitiatedByAccountID=driver.AccountID,
            BalanceAfter=new_balance,  # Use calculated new balance explicitly
            Reason=reason_text,
            ActorRoleCode=actor_meta["actor_role_code"],
            ActorLabel=actor_meta["actor_label"],
            ImpersonatedByAccountID=actor_meta["impersonator_account_id"],
            ImpersonatedByRoleCode=actor_meta["impersonator_role_code"],
        )
        db.session.add(point_change)
        
        # Send notification to driver about point refund/cancel
        try:
            from app.services.notification_service import NotificationService
            NotificationService.notify_driver_points_change(
                driver_id=driver.DriverID,
                delta_points=order.TotalPoints,
                reason=reason_text,
                balance_after=new_balance,
            transaction_id=order.OrderNumber,
            sponsor_id=order.SponsorID
            )
        except Exception as e:
            current_app.logger.error(f"Failed to send refund/cancel points notification: {str(e)}")
        
        # Commit changes
        db.session.commit()
        
        if is_cancellation:
            current_app.logger.info(f"Order {order_id} cancelled successfully for driver {driver.DriverID}")
        else:
            current_app.logger.info(f"Order {order_id} refunded successfully for driver {driver.DriverID}")
        
        return jsonify({
            "success": True,
            "message": action_message,
            "refunded_points": order.TotalPoints,
            "new_balance": new_balance
        })
        
    except Exception as e:
        current_app.logger.exception("Error processing refund")
        db.session.rollback()
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@bp.route("/debug")
@login_required
def debug_orders():
    """Debug endpoint to check order statuses and refund eligibility."""
    driver = _require_driver()
    
    # Get recent orders
    orders = Orders.query.filter_by(DriverID=driver.DriverID).order_by(Orders.CreatedAt.desc()).limit(5).all()
    
    debug_info = []
    for order in orders:
        now = datetime.now()  # Local time
        
        order_time = order.CreatedAt
        if order_time.tzinfo is not None:
            order_time = order_time.replace(tzinfo=None)
        
        time_since_order = now - order_time
        refund_window = timedelta(minutes=5)  # 5-minute refund window
        pending_window = timedelta(minutes=5)  # 5-minute pending window
        
        # Determine actual status
        actual_status = order.Status
        if order.Status == 'pending' and time_since_order > pending_window:
            actual_status = 'completed'
        
        can_refund = (
            actual_status == 'completed' and 
            time_since_order <= refund_window
        )
        
        debug_info.append({
            'order_id': order.OrderID,
            'status': order.Status,
            'created_at': order.CreatedAt.isoformat(),
            'time_since_order_seconds': time_since_order.total_seconds(),
            'time_since_order_minutes': time_since_order.total_seconds() / 60,
            'can_refund': can_refund,
            'total_points': order.TotalPoints
        })
    
    return jsonify({
        'driver_id': driver.DriverID,
        'current_time': now.isoformat(),
        'orders': debug_info
    })

@bp.route("/api/summary")
@login_required
def orders_summary():
    """API endpoint to get order summary for navbar."""
    try:
        driver = _require_driver()
        
        # Get recent orders count
        recent_orders = Orders.query.filter_by(DriverID=driver.DriverID).count()
        
        return jsonify({
            "recent_orders": recent_orders
        })
    except Exception as e:
        current_app.logger.error(f"Error getting orders summary: {e}")
        return jsonify({"recent_orders": 0})

@bp.route("/export/pdf")
@login_required
def export_orders_pdf():
    """Export driver's orders to PDF with optional filters."""
    driver = _require_driver()
    
    # Get filter parameters (same as view_orders)
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    status_filter = request.args.get('status', '')
    
    # Build query with filters (same logic as view_orders)
    query = Orders.query.filter_by(DriverID=driver.DriverID)
    
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Orders.CreatedAt >= start_dt)
        except ValueError:
            pass
    
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(Orders.CreatedAt <= end_dt)
        except ValueError:
            pass
    
    if status_filter in ['pending', 'completed', 'refunded', 'cancelled']:
        query = query.filter(Orders.Status == status_filter)
    
    # Get orders
    orders = query.order_by(Orders.CreatedAt.desc()).limit(1000).all()
    
    # Get line items for all orders
    order_ids = [order.OrderID for order in orders]
    line_items = {}
    if order_ids:
        items = OrderLineItem.query.filter(OrderLineItem.OrderID.in_(order_ids)).all()
        for item in items:
            if item.OrderID not in line_items:
                line_items[item.OrderID] = []
            line_items[item.OrderID].append(item)
    
    # Generate PDF
    buffer = BytesIO()
    page_size = landscape(letter)
    pdf = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size
    
    margin = 48
    y = height - margin
    
    # Title
    pdf.setTitle("Order History")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(margin, y, "Order History")
    y -= 24
    
    # Driver info
    pdf.setFont("Helvetica", 10)
    driver_name = f"{driver.Account.FirstName or ''} {driver.Account.LastName or ''}".strip()
    pdf.drawString(margin, y, f"Driver: {driver_name}")
    y -= 16
    
    # Filters info
    filter_parts = []
    if start_date:
        filter_parts.append(f"From: {start_date}")
    if end_date:
        filter_parts.append(f"To: {end_date}")
    if status_filter:
        filter_parts.append(f"Status: {status_filter.title()}")
    if not filter_parts:
        filter_parts.append("All orders")
    
    pdf.drawString(margin, y, "Filters: " + "; ".join(filter_parts))
    y -= 16
    pdf.drawString(margin, y, f"Total Orders: {len(orders)}")
    y -= 20
    
    # Draw order table header
    def draw_header(current_y):
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(margin, current_y, "Date")
        pdf.drawString(margin + 120, current_y, "Order #")
        pdf.drawString(margin + 240, current_y, "Status")
        pdf.drawString(margin + 320, current_y, "Items")
        pdf.drawString(margin + 420, current_y, "Total Points")
        pdf.setFont("Helvetica", 9)
        return current_y - 16
    
    y = draw_header(y)
    y -= 4
    
    # Draw orders
    for order in orders:
        # Check if we need a new page
        if y < margin + 100:  # Leave room for order details
            pdf.showPage()
            y = height - margin
            y = draw_header(y)
            y -= 4
        
        # Order main info
        order_date = order.CreatedAt.strftime('%Y-%m-%d %H:%M') if order.CreatedAt else '—'
        order_num = order.OrderNumber or '—'
        status = order.Status.title() if order.Status else '—'
        total_points = str(order.TotalPoints) if order.TotalPoints else '0'
        
        # Get item count
        order_line_items = line_items.get(order.OrderID, [])
        item_count = sum(item.Quantity for item in order_line_items)
        
        pdf.drawString(margin, y, order_date)
        pdf.drawString(margin + 120, y, order_num)
        pdf.drawString(margin + 240, y, status)
        pdf.drawString(margin + 320, y, str(item_count))
        pdf.drawString(margin + 420, y, total_points)
        y -= 14
        
        # Draw line items (indented)
        for line_item in order_line_items[:5]:  # Limit to 5 items per order in PDF
            if y < margin + 30:
                pdf.showPage()
                y = height - margin
                y -= 4
            
            item_text = f"  • {line_item.Title or 'Item'}"
            if len(item_text) > 60:
                item_text = item_text[:57] + "..."
            pdf.drawString(margin + 20, y, item_text)
            pdf.drawString(margin + 420, y, f"Qty: {line_item.Quantity}, {line_item.LineTotalPoints} pts")
            y -= 12
        
        if len(order_line_items) > 5:
            pdf.drawString(margin + 20, y, f"  ... and {len(order_line_items) - 5} more items")
            y -= 12
        
        y -= 8  # Space between orders
    
    pdf.save()
    buffer.seek(0)
    
    # Generate filename
    filename_parts = ["orders"]
    if start_date:
        filename_parts.append(f"from_{start_date}")
    if end_date:
        filename_parts.append(f"to_{end_date}")
    if status_filter:
        filename_parts.append(status_filter)
    filename = "_".join(filename_parts) + ".pdf"
    
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")
