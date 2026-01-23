"""
Support Tickets UI Routes
Handles all UI endpoints for support ticket functionality
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from flask_mail import Message
from app.models import db, SupportCategory, SupportTicket, SupportMessage, Sponsor, Driver, Admin, Account
from app.decorators.session_security import require_role
from datetime import datetime
import uuid

bp = Blueprint('support_ui', __name__, url_prefix='/support')

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
            if sponsor:
                # Get username from Account table
                account = Account.query.get(sponsor.AccountID)
                username = account.Username if account else "Unknown"
                return f"{sponsor.Company} ({username})", sponsor.BillingEmail if sponsor else "Unknown"
            return "Unknown Sponsor", "Unknown"
        elif source == 'driver':
            driver = Driver.query.get(owner_id)
            if driver:
                # Get username and name from Account table
                account = Account.query.get(driver.AccountID)
                username = account.Username if account else "Unknown"
                first_name = account.FirstName if account else "Unknown"
                last_name = account.LastName if account else "Unknown"
                return f"{first_name} {last_name} ({username})", account.Email if account else "Unknown"
            return "Unknown Driver", "Unknown"
    except Exception as e:
        print(f"Error getting owner info: {e}")
        pass
    return "Unknown", "Unknown"

def get_author_name(author_id, author_role):
    """Get author name for message display"""
    try:
        if author_role == 'admin':
            admin = Admin.query.get(author_id)
            return admin.FirstName + " " + admin.LastName if admin else "Admin"
        elif author_role == 'sponsor':
            sponsor = Sponsor.query.get(author_id)
            return sponsor.CompanyName if sponsor else "Sponsor"
        elif author_role == 'driver':
            driver = Driver.query.get(author_id)
            return f"{driver.FirstName} {driver.LastName}" if driver else "Driver"
    except:
        pass
    return author_role.capitalize()

# User UI Routes (Sponsor/Driver)
@bp.route('/')
@login_required
@require_role(['sponsor', 'driver'])
def support_hub():
    """Support hub for drivers and sponsors"""
    # Get current user info
    owner_id, source = get_user_info()
    if not owner_id:
        flash('User not found', 'error')
        return redirect(url_for('support_ui.support_hub'))
    
    # Get recent tickets (last 5, excluding closed)
    recent_tickets = SupportTicket.query.filter_by(
        OwnerID=owner_id, 
        Source=source
    ).filter(
        SupportTicket.Status != 'closed'
    ).order_by(
        SupportTicket.CreatedAt.desc()
    ).limit(5).all()
    
    # Get ticket counts by status
    ticket_counts = {
        'total': SupportTicket.query.filter_by(OwnerID=owner_id, Source=source).count(),
        'new': SupportTicket.query.filter_by(OwnerID=owner_id, Source=source, Status='new').count(),
        'open': SupportTicket.query.filter_by(OwnerID=owner_id, Source=source, Status='open').count(),
        'waiting': SupportTicket.query.filter_by(OwnerID=owner_id, Source=source, Status='waiting').count(),
        'resolved': SupportTicket.query.filter_by(OwnerID=owner_id, Source=source, Status='resolved').count(),
        'closed': SupportTicket.query.filter_by(OwnerID=owner_id, Source=source, Status='closed').count()
    }
    
    return render_template('support/support_hub.html', 
                         recent_tickets=recent_tickets,
                         ticket_counts=ticket_counts)

@bp.route('/new')
@login_required
@require_role(['sponsor', 'driver'])
def new_ticket():
    """New ticket form"""
    categories = SupportCategory.query.order_by(SupportCategory.Name.asc()).all()
    return render_template('support/new_ticket.html', categories=categories)

@bp.route('/tickets')
@login_required
@require_role(['sponsor', 'driver'])
def my_tickets():
    """My tickets list with filters"""
    # Get current user info
    owner_id, source = get_user_info()
    print(f"DEBUG my_tickets: owner_id='{owner_id}', source='{source}'")
    
    if not owner_id:
        print("DEBUG my_tickets: No owner_id found")
        flash('User not found', 'error')
        return redirect(url_for('support_ui.support_hub'))
    
    # Get query parameters
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category_id', '')
    q_filter = request.args.get('q', '')
    from_date = request.args.get('from', '')
    to_date = request.args.get('to', '')
    show_closed = request.args.get('show_closed', 'false').lower() == 'true'
    if status_filter == 'closed':
        show_closed = True
    
    # Build query
    query = SupportTicket.query.filter_by(OwnerID=owner_id, Source=source)
    
    # Apply filters
    if status_filter:
        query = query.filter_by(Status=status_filter)
    
    if category_filter:
        query = query.filter_by(CategoryID=category_filter)
    
    if q_filter:
        query = query.filter(
            db.or_(
                SupportTicket.Title.contains(q_filter),
                SupportTicket.Body.contains(q_filter)
            )
        )
    
    if from_date:
        try:
            from_dt = datetime.strptime(from_date, '%Y-%m-%d')
            query = query.filter(SupportTicket.CreatedAt >= from_dt)
        except ValueError:
            flash('Invalid from date format', 'error')
    
    if to_date:
        try:
            to_dt = datetime.strptime(to_date, '%Y-%m-%d')
            to_dt = to_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(SupportTicket.CreatedAt <= to_dt)
        except ValueError:
            flash('Invalid to date format', 'error')
    
    if not show_closed:
        query = query.filter(SupportTicket.Status != 'closed')
    
    # Order by creation date (newest first)
    query = query.order_by(SupportTicket.CreatedAt.desc())
    
    tickets = query.all()
    print(f"DEBUG my_tickets: Found {len(tickets)} tickets")
    for ticket in tickets:
        print(f"DEBUG my_tickets: Ticket {ticket.TicketID} - {ticket.Title} (Status: {ticket.Status})")
    
    categories = SupportCategory.query.order_by(SupportCategory.Name.asc()).all()
    
    return render_template('support/my_tickets.html',
                         tickets=tickets,
                         categories=categories,
                         status_filter=status_filter,
                         category_filter=category_filter,
                         q_filter=q_filter,
                         from_date=from_date,
                         to_date=to_date,
                         show_closed=show_closed)

@bp.route('/tickets/<ticket_id>')
@login_required
@require_role(['sponsor', 'driver'])
def ticket_detail(ticket_id):
    """Ticket detail view"""
    # Get current user info
    owner_id, source = get_user_info()
    if not owner_id:
        flash('User not found', 'error')
        return redirect(url_for('support_ui.support_hub'))
    
    # Get ticket
    ticket = SupportTicket.query.filter_by(
        TicketID=ticket_id,
        OwnerID=owner_id,
        Source=source
    ).first()
    
    if not ticket:
        flash('Ticket not found', 'error')
        return redirect(url_for('support_ui.my_tickets'))
    
    # Get messages with author names
    messages = SupportMessage.query.filter_by(TicketID=ticket_id).order_by(SupportMessage.CreatedAt.asc()).all()
    for message in messages:
        message.author_name = get_author_name(message.AuthorID, message.AuthorRole)
    
    return render_template('support/ticket_detail.html', ticket=ticket, messages=messages)

# Admin UI Routes
@bp.route('/admin')
@login_required
@require_role(['admin'])
def admin_support_hub():
    """Admin support hub"""
    # Get query parameters for filtering
    source_filter = request.args.get('source', '')
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category_id', '')
    q_filter = request.args.get('q', '')
    from_date = request.args.get('from', '')
    to_date = request.args.get('to', '')
    show_closed = request.args.get('show_closed', 'false').lower() == 'true'
    if status_filter == 'closed':
        show_closed = True
    
    # Build query for all tickets
    query = SupportTicket.query
    
    # Apply filters
    if source_filter:
        query = query.filter_by(Source=source_filter)
    
    if status_filter:
        query = query.filter_by(Status=status_filter)
    
    if category_filter:
        query = query.filter_by(CategoryID=category_filter)
    
    if q_filter:
        query = query.filter(
            db.or_(
                SupportTicket.Title.contains(q_filter),
                SupportTicket.Body.contains(q_filter)
            )
        )
    
    if from_date:
        try:
            from_dt = datetime.strptime(from_date, '%Y-%m-%d')
            query = query.filter(SupportTicket.CreatedAt >= from_dt)
        except ValueError:
            pass
    
    if to_date:
        try:
            to_dt = datetime.strptime(to_date, '%Y-%m-%d')
            query = query.filter(SupportTicket.CreatedAt <= to_dt)
        except ValueError:
            pass
    
    if not show_closed:
        query = query.filter(SupportTicket.Status != 'closed')
    
    # Order by creation date (newest first)
    query = query.order_by(SupportTicket.CreatedAt.desc())
    
    # Get recent tickets (limit to 10 for the hub)
    recent_tickets = query.limit(10).all()
    
    # Get all tickets for statistics
    all_tickets = SupportTicket.query.all()
    
    # Get ticket counts by status
    ticket_counts = {
        'total': len(all_tickets),
        'new': len([t for t in all_tickets if t.Status == 'new']),
        'open': len([t for t in all_tickets if t.Status == 'open']),
        'waiting': len([t for t in all_tickets if t.Status == 'waiting']),
        'resolved': len([t for t in all_tickets if t.Status == 'resolved']),
        'closed': len([t for t in all_tickets if t.Status == 'closed'])
    }
    
    # Get ticket counts by source
    source_counts = {
        'sponsor': len([t for t in all_tickets if t.Source == 'sponsor']),
        'driver': len([t for t in all_tickets if t.Source == 'driver'])
    }
    
    # Add owner info to recent tickets
    for ticket in recent_tickets:
        ticket.owner_name, ticket.owner_email = get_owner_info(ticket.OwnerID, ticket.Source)
    
    categories = SupportCategory.query.order_by(SupportCategory.Name.asc()).all()
    
    return render_template('support/admin_hub.html',
                         recent_tickets=recent_tickets,
                         ticket_counts=ticket_counts,
                         source_counts=source_counts,
                         categories=categories,
                         source_filter=source_filter,
                         status_filter=status_filter,
                         category_filter=category_filter,
                         q_filter=q_filter,
                         from_date=from_date,
                         to_date=to_date,
                         show_closed=show_closed)

@bp.route('/admin/tickets')
@login_required
@require_role(['admin'])
def admin_tickets_list():
    """Admin tickets list with filters"""
    # Get query parameters
    source_filter = request.args.get('source', '')
    status_filter = request.args.get('status', '')
    category_filter = request.args.get('category_id', '')
    q_filter = request.args.get('q', '')
    from_date = request.args.get('from', '')
    to_date = request.args.get('to', '')
    show_closed = request.args.get('show_closed', 'false').lower() == 'true'
    if status_filter == 'closed':
        show_closed = True
    
    # Build query
    query = SupportTicket.query
    
    # Apply filters
    if source_filter:
        query = query.filter_by(Source=source_filter)
    
    if status_filter:
        query = query.filter_by(Status=status_filter)
    
    if category_filter:
        query = query.filter_by(CategoryID=category_filter)
    
    if q_filter:
        query = query.filter(
            db.or_(
                SupportTicket.Title.contains(q_filter),
                SupportTicket.Body.contains(q_filter)
            )
        )
    
    if from_date:
        try:
            from_dt = datetime.strptime(from_date, '%Y-%m-%d')
            query = query.filter(SupportTicket.CreatedAt >= from_dt)
        except ValueError:
            flash('Invalid from date format', 'error')
    
    if to_date:
        try:
            to_dt = datetime.strptime(to_date, '%Y-%m-%d')
            to_dt = to_dt.replace(hour=23, minute=59, second=59)
            query = query.filter(SupportTicket.CreatedAt <= to_dt)
        except ValueError:
            flash('Invalid to date format', 'error')
    
    if not show_closed:
        query = query.filter(SupportTicket.Status != 'closed')
    
    # Order by creation date (newest first)
    query = query.order_by(SupportTicket.CreatedAt.desc())
    
    tickets = query.all()
    categories = SupportCategory.query.order_by(SupportCategory.Name.asc()).all()
    
    # Add owner info to tickets
    for ticket in tickets:
        ticket.owner_name, ticket.owner_email = get_owner_info(ticket.OwnerID, ticket.Source)
    
    return render_template('support/admin_tickets.html',
                         tickets=tickets,
                         categories=categories,
                         source_filter=source_filter,
                         status_filter=status_filter,
                         category_filter=category_filter,
                         q_filter=q_filter,
                         from_date=from_date,
                         to_date=to_date,
                         show_closed=show_closed)

@bp.route('/admin/tickets/<ticket_id>')
@login_required
@require_role(['admin'])
def admin_ticket_detail(ticket_id):
    """Admin ticket detail view"""
    # Get ticket
    ticket = SupportTicket.query.get(ticket_id)
    if not ticket:
        flash('Ticket not found', 'error')
        return redirect(url_for('support_ui.admin_support_hub'))
    
    # Get messages with author names
    messages = SupportMessage.query.filter_by(TicketID=ticket_id).order_by(SupportMessage.CreatedAt.asc()).all()
    for message in messages:
        message.author_name = get_author_name(message.AuthorID, message.AuthorRole)
    
    # Get owner info
    ticket.owner_name, ticket.owner_email = get_owner_info(ticket.OwnerID, ticket.Source)
    
    # Get categories for dropdown
    categories = SupportCategory.query.order_by(SupportCategory.Name.asc()).all()
    
    return render_template('support/admin_ticket_detail.html',
                         ticket=ticket,
                         messages=messages,
                         categories=categories)

@bp.route('/admin/categories')
@login_required
@require_role(['admin'])
def admin_categories():
    """Admin categories management"""
    categories = SupportCategory.query.order_by(SupportCategory.Name.asc()).all()
    return render_template('support/admin_categories.html', categories=categories)

# Form submission handlers
@bp.route('/create', methods=['POST'])
@login_required
@require_role(['sponsor', 'driver'])
def create_ticket():
    """Handle new ticket creation"""
    try:
        print(f"DEBUG: create_ticket called with form data: {request.form}")
        
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()
        category_id = request.form.get('category_id')
        
        print(f"DEBUG: title='{title}', body='{body}', category_id='{category_id}'")
        
        if not title or not body:
            print("DEBUG: Missing title or body")
            flash('Title and body are required', 'error')
            return redirect(url_for('support_ui.new_ticket'))
        
        if len(title) > 200:
            print("DEBUG: Title too long")
            flash('Title too long (max 200 characters)', 'error')
            return redirect(url_for('support_ui.new_ticket'))
        
        # Validate category if provided
        if category_id:
            category = SupportCategory.query.get(category_id)
            if not category:
                print("DEBUG: Invalid category")
                flash('Invalid category', 'error')
                return redirect(url_for('support_ui.new_ticket'))
        
        # Get current user info
        owner_id, source = get_user_info()
        print(f"DEBUG: owner_id='{owner_id}', source='{source}'")
        
        if not owner_id:
            print("DEBUG: No owner_id found")
            flash('User not found', 'error')
            return redirect(url_for('support_ui.support_hub'))
        
        # Create ticket
        print("DEBUG: Creating ticket...")
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
        
        print(f"DEBUG: Ticket created with ID: {ticket.TicketID}")
        flash('Ticket created successfully', 'success')
        return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket.TicketID))
        
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: Exception in create_ticket: {str(e)}")
        current_app.logger.error(f"Error creating ticket: {str(e)}")
        flash('Failed to create ticket', 'error')
        return redirect(url_for('support_ui.new_ticket'))

@bp.route('/tickets/<ticket_id>/reply', methods=['POST'])
@login_required
@require_role(['sponsor', 'driver'])
def add_message(ticket_id):
    print(f"DEBUG: add_message route called with ticket_id={ticket_id}")
    """Handle adding message to ticket"""
    try:
        print(f"DEBUG add_message: ticket_id={ticket_id}")
        print(f"DEBUG add_message: form data={request.form}")
        
        body = request.form.get('message_body', '').strip()
        print(f"DEBUG add_message: body='{body}'")
        
        if not body:
            print("DEBUG add_message: No body provided")
            flash('Message body is required', 'error')
            return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket_id))
        
        # Get current user info
        owner_id, source = get_user_info()
        print(f"DEBUG add_message: owner_id={owner_id}, source={source}")
        
        if not owner_id:
            print("DEBUG add_message: No owner_id found")
            flash('User not found', 'error')
            return redirect(url_for('support_ui.support_hub'))
        
        # Get ticket
        ticket = SupportTicket.query.filter_by(
            TicketID=ticket_id,
            OwnerID=owner_id,
            Source=source
        ).first()
        
        print(f"DEBUG add_message: Looking for ticket {ticket_id} with OwnerID={owner_id}, Source={source}")
        print(f"DEBUG add_message: Found ticket: {ticket}")
        
        if not ticket:
            print("DEBUG add_message: Ticket not found with those parameters")
            # Let's try to find the ticket without the owner/source filter to see if it exists
            any_ticket = SupportTicket.query.filter_by(TicketID=ticket_id).first()
            print(f"DEBUG add_message: Ticket exists in DB: {any_ticket}")
            if any_ticket:
                print(f"DEBUG add_message: Ticket OwnerID={any_ticket.OwnerID}, Source={any_ticket.Source}")
            flash('Ticket not found', 'error')
            return redirect(url_for('support_ui.my_tickets'))
        
        if ticket.Status == 'closed':
            flash('Cannot add message to closed ticket', 'error')
            return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket_id))
        
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
        
        print(f"DEBUG add_message: Message created successfully")
        flash('Message added successfully', 'success')
        return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket_id))
        
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG add_message: Exception occurred: {str(e)}")
        current_app.logger.error(f"Error adding message: {str(e)}")
        flash('Failed to add message', 'error')
        return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket_id))

@bp.route('/tickets/<ticket_id>/close', methods=['POST'])
@login_required
@require_role(['sponsor', 'driver'])
def close_ticket(ticket_id):
    """Handle closing ticket"""
    try:
        # Get current user info
        owner_id, source = get_user_info()
        if not owner_id:
            flash('User not found', 'error')
            return redirect(url_for('support_ui.support_hub'))
        
        # Get ticket
        ticket = SupportTicket.query.filter_by(
            TicketID=ticket_id,
            OwnerID=owner_id,
            Source=source
        ).first()
        
        if not ticket:
            flash('Ticket not found', 'error')
            return redirect(url_for('support_ui.my_tickets'))
        
        if ticket.Status != 'resolved':
            flash('Can only close resolved tickets', 'error')
            return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket_id))
        
        # Close ticket
        ticket.Status = 'closed'
        ticket.ClosedAt = datetime.utcnow()
        ticket.UpdatedAt = datetime.utcnow()
        
        db.session.commit()
        
        flash('Ticket closed successfully', 'success')
        return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error closing ticket: {str(e)}")
        flash('Failed to close ticket', 'error')
        return redirect(url_for('support_ui.ticket_detail', ticket_id=ticket_id))

# Admin form submission handlers
@bp.route('/admin/tickets/<ticket_id>/status', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_update_ticket_status(ticket_id):
    """Handle admin status update"""
    try:
        status = request.form.get('status')
        if not status or status not in ['new', 'open', 'waiting', 'resolved', 'closed']:
            flash('Invalid status', 'error')
            return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            flash('Ticket not found', 'error')
            return redirect(url_for('support_ui.admin_support_hub'))
        
        # Update status
        ticket.Status = status
        ticket.UpdatedAt = datetime.utcnow()
        
        # Set closed_at if closing
        if status == 'closed' and not ticket.ClosedAt:
            ticket.ClosedAt = datetime.utcnow()
        
        db.session.commit()
        
        flash('Status updated successfully', 'success')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating ticket status: {str(e)}")
        flash('Failed to update status', 'error')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

@bp.route('/admin/tickets/<ticket_id>/category', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_update_ticket_category(ticket_id):
    """Handle admin category update"""
    try:
        category_id = request.form.get('category_id')
        
        # Validate category if provided
        if category_id:
            category = SupportCategory.query.get(category_id)
            if not category:
                flash('Invalid category', 'error')
                return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            flash('Ticket not found', 'error')
            return redirect(url_for('support_ui.admin_support_hub'))
        
        # Update category
        ticket.CategoryID = category_id
        ticket.UpdatedAt = datetime.utcnow()
        
        db.session.commit()
        
        flash('Category updated successfully', 'success')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating ticket category: {str(e)}")
        flash('Failed to update category', 'error')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

@bp.route('/admin/tickets/<ticket_id>/update', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_update_ticket(ticket_id):
    """Handle unified admin ticket update (status, category, message)"""
    try:
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            flash('Ticket not found', 'error')
            return redirect(url_for('support_ui.admin_support_hub'))
        
        if ticket.Status == 'closed':
            flash('Cannot modify closed ticket', 'error')
            return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
        # Get form data
        new_status = request.form.get('status', '').strip()
        new_category_id = request.form.get('category_id', '').strip()
        message_body = request.form.get('message_body', '').strip()
        
        # Validate status
        if new_status and new_status in ['new', 'open', 'waiting', 'resolved', 'closed']:
            ticket.Status = new_status
            ticket.UpdatedAt = datetime.utcnow()
            
            # Set closed date if status is closed
            if new_status == 'closed':
                ticket.ClosedAt = datetime.utcnow()
        
        # Update category
        if new_category_id:
            # Validate category exists
            category = SupportCategory.query.get(new_category_id)
            if category:
                ticket.CategoryID = new_category_id
            else:
                flash('Invalid category selected', 'error')
                return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        else:
            ticket.CategoryID = None
        
        # Add message if provided
        if message_body:
            admin_id, _ = get_user_info()
            if admin_id:
                message = SupportMessage(
                    TicketID=ticket_id,
                    AuthorRole='admin',
                    AuthorID=admin_id,
                    Body=message_body
                )
                db.session.add(message)
                
                # Update status to waiting if admin replied to new/open ticket
                if ticket.Status in ['new', 'open']:
                    ticket.Status = 'waiting'
                    ticket.UpdatedAt = datetime.utcnow()
        
        db.session.commit()
        
        # Send email notification if a message was added
        if message_body:
            current_app.logger.info(f"Sending notification for ticket {ticket_id}, message body length: {len(message_body)}")
            try:
                from app.services.notification_service import NotificationService
                NotificationService.notify_ticket_response(ticket_id)
            except Exception as e:
                current_app.logger.error(f"Failed to send ticket response notification: {str(e)}")
                import traceback
                current_app.logger.error(traceback.format_exc())
        
        flash('Ticket updated successfully', 'success')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating ticket: {str(e)}")
        flash('Failed to update ticket', 'error')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

@bp.route('/admin/tickets/<ticket_id>/email', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_email_ticket_owner(ticket_id):
    """Send an email to the ticket owner (driver or sponsor)."""
    subject = (request.form.get('email_subject') or '').strip()
    body = (request.form.get('email_body') or '').strip()
    log_email = request.form.get('log_email') is not None

    if not body:
        flash('Email body is required.', 'error')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

    # Fetch the ticket and owner details
    ticket = SupportTicket.query.get(ticket_id)
    if not ticket:
        flash('Ticket not found.', 'error')
        return redirect(url_for('support_ui.admin_support_hub'))

    owner_name, owner_email = get_owner_info(ticket.OwnerID, ticket.Source)
    if not owner_email or owner_email.lower() == 'unknown':
        flash('Ticket owner email address is not available.', 'error')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

    if not subject:
        subject = f"Re: {ticket.Title}"

    try:
        from app.services.notification_service import NotificationService

        mailer = NotificationService._create_ethereal_mail()
        msg = Message(
            subject=subject,
            recipients=[owner_email],
            body=body,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER')
        )
        mailer.send(msg)
        current_app.logger.info(f"Support email sent to {owner_email} for ticket {ticket_id}")
    except Exception as e:
        current_app.logger.error(f"Failed to send support email for ticket {ticket_id}: {e}")
        flash('Failed to send email. Please try again later.', 'error')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

    if log_email:
        try:
            admin_id, _ = get_user_info()
            if admin_id:
                email_message = SupportMessage(
                    TicketID=ticket_id,
                    AuthorRole='admin',
                    AuthorID=admin_id,
                    Body=f"[Email Sent]\nSubject: {subject}\n\n{body}"
                )
                db.session.add(email_message)
                ticket.UpdatedAt = datetime.utcnow()
                db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Email sent but failed to log message for ticket {ticket_id}: {e}")
            flash('Email sent, but failed to save a copy to the ticket history.', 'warning')
            return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

    flash(f'Email sent to {owner_email}.', 'success')
    return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

@bp.route('/admin/tickets/<ticket_id>/reply', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_add_message(ticket_id):
    """Handle admin adding message (legacy route for backward compatibility)"""
    try:
        body = request.form.get('body', '').strip()
        if not body:
            flash('Message body is required', 'error')
            return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
        # Get ticket
        ticket = SupportTicket.query.get(ticket_id)
        if not ticket:
            flash('Ticket not found', 'error')
            return redirect(url_for('support_ui.admin_support_hub'))
        
        if ticket.Status == 'closed':
            flash('Cannot add message to closed ticket', 'error')
            return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
        # Get admin info
        admin_id, _ = get_user_info()
        if not admin_id:
            flash('Admin not found', 'error')
            return redirect(url_for('support_ui.admin_support_hub'))
        
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
        
        flash('Message added successfully', 'success')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error adding admin message: {str(e)}")
        flash('Failed to add message', 'error')
        return redirect(url_for('support_ui.admin_ticket_detail', ticket_id=ticket_id))

# Category management handlers
@bp.route('/admin/categories/create', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_create_category():
    """Handle category creation"""
    try:
        name = request.form.get('name', '').strip()
        if not name:
            flash('Category name is required', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        if len(name) > 100:
            flash('Category name too long (max 100 characters)', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        # Check if category already exists
        existing = SupportCategory.query.filter_by(Name=name).first()
        if existing:
            flash('Category already exists', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        # Create category
        category = SupportCategory(Name=name)
        db.session.add(category)
        db.session.commit()
        
        flash('Category created successfully', 'success')
        return redirect(url_for('support_ui.admin_categories'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating category: {str(e)}")
        flash('Failed to create category', 'error')
        return redirect(url_for('support_ui.admin_categories'))

@bp.route('/admin/categories/<category_id>/update', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_update_category(category_id):
    """Handle category update"""
    try:
        name = request.form.get('name', '').strip()
        if not name:
            flash('Category name is required', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        if len(name) > 100:
            flash('Category name too long (max 100 characters)', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        # Get category
        category = SupportCategory.query.get(category_id)
        if not category:
            flash('Category not found', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        # Check if name already exists (excluding current category)
        existing = SupportCategory.query.filter(
            SupportCategory.Name == name,
            SupportCategory.CategoryID != category_id
        ).first()
        if existing:
            flash('Category name already exists', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        # Update category
        category.Name = name
        db.session.commit()
        
        flash('Category updated successfully', 'success')
        return redirect(url_for('support_ui.admin_categories'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating category: {str(e)}")
        flash('Failed to update category', 'error')
        return redirect(url_for('support_ui.admin_categories'))

@bp.route('/admin/categories/<category_id>/delete', methods=['POST'])
@login_required
@require_role(['admin'])
def admin_delete_category(category_id):
    """Handle category deletion"""
    try:
        # Get category
        category = SupportCategory.query.get(category_id)
        if not category:
            flash('Category not found', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        # Check if category has tickets
        ticket_count = category.tickets.count()
        if ticket_count > 0:
            flash(f'Cannot delete category with {ticket_count} tickets', 'error')
            return redirect(url_for('support_ui.admin_categories'))
        
        # Delete category
        db.session.delete(category)
        db.session.commit()
        
        flash('Category deleted successfully', 'success')
        return redirect(url_for('support_ui.admin_categories'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting category: {str(e)}")
        flash('Failed to delete category', 'error')
        return redirect(url_for('support_ui.admin_categories'))