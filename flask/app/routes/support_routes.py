"""
Support Tickets API Routes
Handles all API endpoints for support ticket functionality
"""

from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from app.models import db, SupportCategory, SupportTicket, SupportMessage, Sponsor, Driver, Admin
from app.decorators.session_security import require_role
from datetime import datetime
import uuid

bp = Blueprint('support_bp', __name__, url_prefix='/api/support')

def get_user_info():
    """Get current user info based on AccountType"""
    if current_user.AccountType == 'ADMIN':
        # Find the admin record for this account
        admin = Admin.query.filter_by(AccountID=current_user.AccountID).first()
        return admin.AdminID if admin else None, 'admin'
    elif current_user.AccountType == 'SPONSOR':
        # Find the sponsor record for this account
        sponsor = Sponsor.query.filter_by(AccountID=current_user.AccountID).first()
        return sponsor.SponsorID if sponsor else None, 'sponsor'
    elif current_user.AccountType == 'DRIVER':
        # Find the driver record for this account
        driver = Driver.query.filter_by(AccountID=current_user.AccountID).first()
        return driver.DriverID if driver else None, 'driver'
    return None, None

def get_owner_info(owner_id, source):
    """Get owner name and email for display"""
    try:
        if source == 'sponsor':
            sponsor = Sponsor.query.get(owner_id)
            return sponsor.CompanyName if sponsor else "Unknown Sponsor", sponsor.Email if sponsor else "Unknown"
        elif source == 'driver':
            driver = Driver.query.get(owner_id)
            return f"{driver.FirstName} {driver.LastName}" if driver else "Unknown Driver", driver.Email if driver else "Unknown"
    except:
        pass
    return "Unknown", "Unknown"

@bp.route('/tickets', methods=['POST'])
@login_required
@require_role(['sponsor', 'driver'])
def create_ticket():
    """Create a new support ticket"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        title = data.get('title', '').strip()
        body = data.get('body', '').strip()
        category_id = data.get('category_id')
        
        if not title or not body:
            return jsonify({'error': 'Title and body are required'}), 400
        
        if len(title) > 200:
            return jsonify({'error': 'Title too long (max 200 characters)'}), 400
        
        # Validate category if provided
        if category_id:
            category = SupportCategory.query.get(category_id)
            if not category:
                return jsonify({'error': 'Invalid category'}), 400
        
        # Get current user info
        owner_id, source = get_user_info()
        if not owner_id:
            return jsonify({'error': 'User not found'}), 400
        
        # Create ticket
        ticket = SupportTicket(
            Source=source,
            OwnerID=owner_id,
            Title=title,
            Body=body,
            CategoryID=category_id,
            Status='new'
        )
        
        db.session.add(ticket)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'ticket_id': ticket.TicketID,
            'message': 'Ticket created successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating ticket: {str(e)}")
        return jsonify({'error': 'Failed to create ticket'}), 500

@bp.route('/tickets', methods=['GET'])
@login_required
@require_role(['sponsor', 'driver'])
def get_tickets():
    """Get tickets for current user with filtering"""
    try:
        # Get current user info
        owner_id, source = get_user_info()
        if not owner_id:
            return jsonify({'error': 'User not found'}), 400
        
        # Get query parameters
        status = request.args.get('status')
        category_id = request.args.get('category_id')
        q = request.args.get('q', '').strip()
        from_date = request.args.get('from')
        to_date = request.args.get('to')
        show_closed = request.args.get('show_closed', 'false').lower() == 'true'
        
        # Build query
        query = SupportTicket.query.filter_by(OwnerID=owner_id, Source=source)
        
        # Apply filters
        if status:
            query = query.filter_by(Status=status)
        
        if category_id:
            query = query.filter_by(CategoryID=category_id)
        
        if q:
            query = query.filter(
                db.or_(
                    SupportTicket.Title.contains(q),
                    SupportTicket.Body.contains(q)
                )
            )
        
        if from_date:
            try:
                from_dt = datetime.strptime(from_date, '%Y-%m-%d')
                query = query.filter(SupportTicket.CreatedAt >= from_dt)
            except ValueError:
                return jsonify({'error': 'Invalid from_date format'}), 400
        
        if to_date:
            try:
                to_dt = datetime.strptime(to_date, '%Y-%m-%d')
                # Add time to end of day
                to_dt = to_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(SupportTicket.CreatedAt <= to_dt)
            except ValueError:
                return jsonify({'error': 'Invalid to_date format'}), 400
        
        if not show_closed:
            query = query.filter(SupportTicket.Status != 'closed')
        
        # Order by creation date (newest first)
        query = query.order_by(SupportTicket.CreatedAt.desc())
        
        tickets = query.all()
        
        # Format response
        result = []
        for ticket in tickets:
            ticket_data = {
                'ticket_id': ticket.TicketID,
                'title': ticket.Title,
                'body': ticket.Body,
                'status': ticket.Status,
                'source': ticket.Source,
                'created_at': ticket.CreatedAt.isoformat(),
                'updated_at': ticket.UpdatedAt.isoformat(),
                'closed_at': ticket.ClosedAt.isoformat() if ticket.ClosedAt else None,
                'category': {
                    'id': ticket.category.CategoryID,
                    'name': ticket.category.Name
                } if ticket.category else None,
                'message_count': ticket.messages.count()
            }
            result.append(ticket_data)
        
        return jsonify({
            'success': True,
            'tickets': result,
            'count': len(result)
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting tickets: {str(e)}")
        return jsonify({'error': 'Failed to get tickets'}), 500

@bp.route('/tickets/<ticket_id>', methods=['GET'])
@login_required
@require_role(['sponsor', 'driver'])
def get_ticket(ticket_id):
    """Get a specific ticket with messages"""
    try:
        # Get current user info
        owner_id, source = get_user_info()
        if not owner_id:
            return jsonify({'error': 'User not found'}), 400
        
        # Get ticket
        ticket = SupportTicket.query.filter_by(
            TicketID=ticket_id,
            OwnerID=owner_id,
            Source=source
        ).first()
        
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        
        # Get messages
        messages = SupportMessage.query.filter_by(TicketID=ticket_id).order_by(SupportMessage.CreatedAt.asc()).all()
        
        # Format messages
        message_list = []
        for msg in messages:
            message_data = {
                'message_id': msg.MessageID,
                'author_role': msg.AuthorRole,
                'author_id': msg.AuthorID,
                'body': msg.Body,
                'created_at': msg.CreatedAt.isoformat()
            }
            message_list.append(message_data)
        
        # Format ticket response
        ticket_data = {
            'ticket_id': ticket.TicketID,
            'title': ticket.Title,
            'body': ticket.Body,
            'status': ticket.Status,
            'source': ticket.Source,
            'created_at': ticket.CreatedAt.isoformat(),
            'updated_at': ticket.UpdatedAt.isoformat(),
            'closed_at': ticket.ClosedAt.isoformat() if ticket.ClosedAt else None,
            'category': {
                'id': ticket.category.CategoryID,
                'name': ticket.category.Name
            } if ticket.category else None,
            'messages': message_list
        }
        
        return jsonify({
            'success': True,
            'ticket': ticket_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting ticket: {str(e)}")
        return jsonify({'error': 'Failed to get ticket'}), 500

@bp.route('/tickets/<ticket_id>/messages', methods=['POST'])
@login_required
@require_role(['sponsor', 'driver'])
def add_message(ticket_id):
    """Add a message to a ticket"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        body = data.get('body', '').strip()
        if not body:
            return jsonify({'error': 'Message body is required'}), 400
        
        # Get current user info
        owner_id, source = get_user_info()
        if not owner_id:
            return jsonify({'error': 'User not found'}), 400
        
        # Get ticket
        ticket = SupportTicket.query.filter_by(
            TicketID=ticket_id,
            OwnerID=owner_id,
            Source=source
        ).first()
        
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        
        if ticket.Status == 'closed':
            return jsonify({'error': 'Cannot add message to closed ticket'}), 400
        
        # Create message
        message = SupportMessage(
            TicketID=ticket_id,
            AuthorRole=source,
            AuthorID=owner_id,
            Body=body
        )
        
        db.session.add(message)
        
        # Update ticket status if it was waiting for user reply
        if ticket.Status == 'waiting':
            ticket.Status = 'open'
            ticket.UpdatedAt = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message_id': message.MessageID,
            'message': 'Message added successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding message: {str(e)}")
        return jsonify({'error': 'Failed to add message'}), 500

@bp.route('/tickets/<ticket_id>/close', methods=['POST'])
@login_required
@require_role(['sponsor', 'driver'])
def close_ticket(ticket_id):
    """Close a ticket (only if resolved)"""
    try:
        # Get current user info
        owner_id, source = get_user_info()
        if not owner_id:
            return jsonify({'error': 'User not found'}), 400
        
        # Get ticket
        ticket = SupportTicket.query.filter_by(
            TicketID=ticket_id,
            OwnerID=owner_id,
            Source=source
        ).first()
        
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        
        if ticket.Status != 'resolved':
            return jsonify({'error': 'Can only close resolved tickets'}), 400
        
        # Close ticket
        ticket.Status = 'closed'
        ticket.ClosedAt = datetime.utcnow()
        ticket.UpdatedAt = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Ticket closed successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error closing ticket: {str(e)}")
        return jsonify({'error': 'Failed to close ticket'}), 500

# Admin API routes
@bp.route('/admin/tickets', methods=['GET'])
@login_required
@require_role(['admin'])
def admin_get_tickets():
    """Get all tickets for admin with filtering"""
    try:
        # Get query parameters
        source = request.args.get('source')
        status = request.args.get('status')
        category_id = request.args.get('category_id')
        q = request.args.get('q', '').strip()
        from_date = request.args.get('from')
        to_date = request.args.get('to')
        show_closed = request.args.get('show_closed', 'false').lower() == 'true'
        
        # Build query
        query = SupportTicket.query
        
        # Apply filters
        if source:
            query = query.filter_by(Source=source)
        
        if status:
            query = query.filter_by(Status=status)
        
        if category_id:
            query = query.filter_by(CategoryID=category_id)
        
        if q:
            query = query.filter(
                db.or_(
                    SupportTicket.Title.contains(q),
                    SupportTicket.Body.contains(q)
                )
            )
        
        if from_date:
            try:
                from_dt = datetime.strptime(from_date, '%Y-%m-%d')
                query = query.filter(SupportTicket.CreatedAt >= from_dt)
            except ValueError:
                return jsonify({'error': 'Invalid from_date format'}), 400
        
        if to_date:
            try:
                to_dt = datetime.strptime(to_date, '%Y-%m-%d')
                to_dt = to_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(SupportTicket.CreatedAt <= to_dt)
            except ValueError:
                return jsonify({'error': 'Invalid to_date format'}), 400
        
        if not show_closed:
            query = query.filter(SupportTicket.Status != 'closed')
        
        # Order by creation date (newest first)
        query = query.order_by(SupportTicket.CreatedAt.desc())
        
        tickets = query.all()
        
        # Format response with owner info
        result = []
        for ticket in tickets:
            owner_name, owner_email = get_owner_info(ticket.OwnerID, ticket.Source)
            
            ticket_data = {
                'ticket_id': ticket.TicketID,
                'title': ticket.Title,
                'body': ticket.Body,
                'status': ticket.Status,
                'source': ticket.Source,
                'created_at': ticket.CreatedAt.isoformat(),
                'updated_at': ticket.UpdatedAt.isoformat(),
                'closed_at': ticket.ClosedAt.isoformat() if ticket.ClosedAt else None,
                'category': {
                    'id': ticket.category.CategoryID,
                    'name': ticket.category.Name
                } if ticket.category else None,
                'owner_name': owner_name,
                'owner_email': owner_email,
                'message_count': ticket.messages.count()
            }
            result.append(ticket_data)
        
        return jsonify({
            'success': True,
            'tickets': result,
            'count': len(result)
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting admin tickets: {str(e)}")
        return jsonify({'error': 'Failed to get tickets'}), 500

@bp.route('/admin/tickets/<ticket_id>', methods=['GET'])
@login_required
@require_role(['admin'])
def admin_get_ticket(ticket_id):
    """Get a specific ticket for admin with messages"""
    try:
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        
        # Get messages
        messages = SupportMessage.query.filter_by(TicketID=ticket_id).order_by(SupportMessage.CreatedAt.asc()).all()
        
        # Format messages
        message_list = []
        for msg in messages:
            message_data = {
                'message_id': msg.MessageID,
                'author_role': msg.AuthorRole,
                'author_id': msg.AuthorID,
                'body': msg.Body,
                'created_at': msg.CreatedAt.isoformat()
            }
            message_list.append(message_data)
        
        # Get owner info
        owner_name, owner_email = get_owner_info(ticket.OwnerID, ticket.Source)
        
        # Format ticket response
        ticket_data = {
            'ticket_id': ticket.TicketID,
            'title': ticket.Title,
            'body': ticket.Body,
            'status': ticket.Status,
            'source': ticket.Source,
            'created_at': ticket.CreatedAt.isoformat(),
            'updated_at': ticket.UpdatedAt.isoformat(),
            'closed_at': ticket.ClosedAt.isoformat() if ticket.ClosedAt else None,
            'category': {
                'id': ticket.category.CategoryID,
                'name': ticket.category.Name
            } if ticket.category else None,
            'owner_name': owner_name,
            'owner_email': owner_email,
            'messages': message_list
        }
        
        return jsonify({
            'success': True,
            'ticket': ticket_data
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting admin ticket: {str(e)}")
        return jsonify({'error': 'Failed to get ticket'}), 500

@bp.route('/admin/tickets/<ticket_id>/status', methods=['PATCH'])
@login_required
@require_role(['admin'])
def admin_update_ticket_status(ticket_id):
    """Update ticket status (admin only)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        status = data.get('status')
        if not status or status not in ['new', 'open', 'waiting', 'resolved', 'closed']:
            return jsonify({'error': 'Invalid status'}), 400
        
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        
        # Update status
        ticket.Status = status
        ticket.UpdatedAt = datetime.utcnow()
        
        # Set closed_at if closing
        if status == 'closed' and not ticket.ClosedAt:
            ticket.ClosedAt = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Status updated successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating ticket status: {str(e)}")
        return jsonify({'error': 'Failed to update status'}), 500

@bp.route('/admin/tickets/<ticket_id>/category', methods=['PATCH'])
@login_required
@require_role(['admin'])
def admin_update_ticket_category(ticket_id):
    """Update ticket category (admin only)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        category_id = data.get('category_id')
        
        # Validate category if provided
        if category_id:
            category = SupportCategory.query.get(category_id)
            if not category:
                return jsonify({'error': 'Invalid category'}), 400
        
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        
        # Update category
        ticket.CategoryID = category_id
        ticket.UpdatedAt = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Category updated successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating ticket category: {str(e)}")
        return jsonify({'error': 'Failed to update category'}), 500

@bp.route('/admin/tickets/<ticket_id>/messages', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_add_message(ticket_id):
    """Add a message to a ticket (admin only)"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        body = data.get('body', '').strip()
        if not body:
            return jsonify({'error': 'Message body is required'}), 400
        
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            return jsonify({'error': 'Ticket not found'}), 404
        
        if ticket.Status == 'closed':
            return jsonify({'error': 'Cannot add message to closed ticket'}), 400
        
        # Get admin info
        admin_id = current_user.AdminID
        
        # Create message
        message = SupportMessage(
            TicketID=ticket_id,
            AuthorRole='admin',
            AuthorID=admin_id,
            Body=body
        )
        
        db.session.add(message)
        
        # Update ticket status to waiting for user reply
        if ticket.Status in ['new', 'open']:
            ticket.Status = 'waiting'
            ticket.UpdatedAt = datetime.utcnow()
        
        db.session.commit()
        
        # Send email notification to ticket owner
        try:
            from app.services.notification_service import NotificationService
            NotificationService.notify_ticket_response(ticket_id)
        except Exception as e:
            current_app.logger.error(f"Failed to send ticket response notification: {str(e)}")
        
        return jsonify({
            'success': True,
            'message_id': message.MessageID,
            'message': 'Message added successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding admin message: {str(e)}")
        return jsonify({'error': 'Failed to add message'}), 500

# Category management routes
@bp.route('/admin/categories', methods=['GET'])
@login_required
@require_role(['admin'])
def admin_get_categories():
    """Get all support categories"""
    try:
        categories = SupportCategory.query.order_by(SupportCategory.Name.asc()).all()
        
        result = []
        for category in categories:
            category_data = {
                'category_id': category.CategoryID,
                'name': category.Name,
                'created_at': category.CreatedAt.isoformat(),
                'ticket_count': category.tickets.count()
            }
            result.append(category_data)
        
        return jsonify({
            'success': True,
            'categories': result
        })
        
    except Exception as e:
        current_app.logger.error(f"Error getting categories: {str(e)}")
        return jsonify({'error': 'Failed to get categories'}), 500

@bp.route('/admin/categories', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_create_category():
    """Create a new support category"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Category name is required'}), 400
        
        if len(name) > 100:
            return jsonify({'error': 'Category name too long (max 100 characters)'}), 400
        
        # Check if category already exists
        existing = SupportCategory.query.filter_by(Name=name).first()
        if existing:
            return jsonify({'error': 'Category already exists'}), 400
        
        # Create category
        category = SupportCategory(Name=name)
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'category_id': category.CategoryID,
            'message': 'Category created successfully'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating category: {str(e)}")
        return jsonify({'error': 'Failed to create category'}), 500

@bp.route('/admin/categories/<category_id>', methods=['PUT'])
@login_required
@require_role(['admin'])
def admin_update_category(category_id):
    """Update a support category"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Category name is required'}), 400
        
        if len(name) > 100:
            return jsonify({'error': 'Category name too long (max 100 characters)'}), 400
        
        # Get category
        category = SupportCategory.query.get(category_id)
        if not category:
            return jsonify({'error': 'Category not found'}), 404
        
        # Check if name already exists (excluding current category)
        existing = SupportCategory.query.filter(
            SupportCategory.Name == name,
            SupportCategory.CategoryID != category_id
        ).first()
        if existing:
            return jsonify({'error': 'Category name already exists'}), 400
        
        # Update category
        category.Name = name
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Category updated successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating category: {str(e)}")
        return jsonify({'error': 'Failed to update category'}), 500

@bp.route('/admin/categories/<category_id>', methods=['DELETE'])
@login_required
@require_role(['admin'])
def admin_delete_category(category_id):
    """Delete a support category"""
    try:
        # Get category
        category = SupportCategory.query.get(category_id)
        if not category:
            return jsonify({'error': 'Category not found'}), 404
        
        # Check if category has tickets
        ticket_count = category.tickets.count()
        if ticket_count > 0:
            return jsonify({'error': f'Cannot delete category with {ticket_count} tickets'}), 400
        
        # Delete category
        db.session.delete(category)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Category deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting category: {str(e)}")
        return jsonify({'error': 'Failed to delete category'}), 500