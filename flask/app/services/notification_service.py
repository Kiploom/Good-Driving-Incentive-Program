"""
Notification service for sending emails about driver applications and other events.
Uses Ethereal Mail for notifications while keeping MailTrap for other emails.
"""

from flask import current_app
from flask_mail import Mail, Message
from app.models import (
    Account,
    Sponsor,
    SponsorCompany,
    Application,
    Driver,
    DriverSponsor,
    NotificationPreferences,
)
from app.services.driver_notification_service import DriverNotificationService
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class NotificationService:
    """Service for sending various types of notifications via email"""
    
    @staticmethod
    def _is_quiet_hours(driver_id: str, is_critical: bool = False) -> bool:
        """
        Check if it's currently quiet hours for a driver.
        
        Args:
            driver_id: The ID of the driver
            is_critical: Whether this is a critical notification (always sent, even during quiet hours)
        
        Returns:
            True if it's quiet hours and the notification is non-critical, False otherwise
        """
        # Critical notifications always bypass quiet hours
        if is_critical:
            return False
        
        try:
            prefs = NotificationPreferences.query.filter_by(DriverID=driver_id).first()
            if not prefs or not prefs.QuietHoursEnabled:
                return False
            
            if not prefs.QuietHoursStart or not prefs.QuietHoursEnd:
                return False
            
            # Get current local time
            from datetime import datetime, time
            now = datetime.now().time()
            start_time = prefs.QuietHoursStart
            end_time = prefs.QuietHoursEnd
            
            # Handle quiet hours that span midnight (e.g., 22:00 to 07:00)
            if start_time > end_time:
                # Quiet hours span midnight (e.g., 10 PM to 7 AM)
                # It's quiet hours if current time is >= start_time OR current time is < end_time
                is_quiet = now >= start_time or now < end_time
            else:
                # Quiet hours within same day (e.g., 14:00 to 16:00)
                # It's quiet hours if current time is between start and end
                is_quiet = start_time <= now < end_time
            
            return is_quiet
            
        except Exception as e:
            logger.error(f"Error checking quiet hours for driver {driver_id}: {str(e)}")
            # On error, don't suppress notifications (fail open)
            return False
    
    @staticmethod
    def _create_ethereal_mail():
        """Create a separate Mail instance configured for Ethereal Mail"""
        ethereal_mail = Mail()
        ethereal_mail.init_app(current_app)
        
        # Override config for Ethereal Mail
        ethereal_mail.server = current_app.config['MAIL_SERVER']
        ethereal_mail.port = current_app.config['MAIL_PORT']
        ethereal_mail.use_tls = current_app.config['MAIL_USE_TLS']
        ethereal_mail.username = current_app.config['MAIL_USERNAME']
        ethereal_mail.password = current_app.config['MAIL_PASSWORD']
        ethereal_mail.default_sender = current_app.config['MAIL_DEFAULT_SENDER']
        
        return ethereal_mail

    @staticmethod
    def _record_driver_notification(
        driver_id: str,
        notif_type: str,
        title: str,
        body: str,
        *,
        metadata: dict | None = None,
        channels: list[str] | None = None,
    ) -> None:
        """Persist a driver notification for in-app/mobile consumption."""
        if not driver_id:
            return
        delivered_channels = channels or ["in_app"]
        if not delivered_channels:
            return
        delivered_via = ",".join(filter(None, delivered_channels))
        try:
            metadata_payload = dict(metadata or {})
            if "isSponsorSpecific" not in metadata_payload:
                metadata_payload["isSponsorSpecific"] = False
            DriverNotificationService.create_notification(
                driver_id,
                notif_type,
                title,
                body,
                metadata=metadata_payload,
                delivered_via=delivered_via,
            )
        except Exception as exc:  # pragma: no cover - defensive log
            logger.error(
                "Failed to record driver notification %s for driver %s: %s",
                notif_type,
                driver_id,
                exc,
            )

    @staticmethod
    def _with_sponsor_metadata(
        metadata: dict | None,
        *,
        sponsor_id: str | None = None,
        sponsor_name: str | None = None,
        sponsor_company_name: str | None = None,
        is_sponsor_specific: bool | None = None,
    ) -> dict:
        """
        Append standard sponsor context keys to notification metadata.
        """
        meta = dict(metadata or {})
        if sponsor_id:
            meta["sponsorId"] = sponsor_id
        if sponsor_name:
            meta["sponsorName"] = sponsor_name
        if sponsor_company_name:
            meta["sponsorCompanyName"] = sponsor_company_name

        if is_sponsor_specific is not None:
            meta["isSponsorSpecific"] = bool(is_sponsor_specific)
        elif sponsor_id or sponsor_name or sponsor_company_name:
            meta["isSponsorSpecific"] = True
        else:
            meta.setdefault("isSponsorSpecific", False)
        return meta

    @staticmethod
    def _resolve_driver_sponsor_details(
        driver: Driver,
        sponsor_id_override: str | None = None,
    ) -> dict[str, object | None]:
        """
        Determine the most relevant sponsor and sponsor company for a driver.

        Returns a dictionary with keys:
            - sponsor_id
            - sponsor (Sponsor | None)
            - sponsor_company (SponsorCompany | None)
            - sponsor_name (str)
        """
        sponsor_company_id = driver.SponsorCompanyID
        resolved_sponsor_id = sponsor_id_override

        if not resolved_sponsor_id:
            active_env = (
                DriverSponsor.query
                .filter_by(DriverID=driver.DriverID, Status="ACTIVE")
                .order_by(DriverSponsor.UpdatedAt.desc(), DriverSponsor.CreatedAt.desc())
                .first()
            )
            if active_env:
                resolved_sponsor_id = active_env.SponsorID
                sponsor_company_id = sponsor_company_id or active_env.SponsorCompanyID

        sponsor = Sponsor.query.get(resolved_sponsor_id) if resolved_sponsor_id else None
        if sponsor and not sponsor_company_id:
            sponsor_company_id = sponsor.SponsorCompanyID

        sponsor_company = (
            SponsorCompany.query.get(sponsor_company_id) if sponsor_company_id else None
        )

        sponsor_name = (
            sponsor_company.CompanyName
            if sponsor_company
            else sponsor.Company if sponsor else None
        ) or "your sponsor"

        return {
            "sponsor_id": resolved_sponsor_id,
            "sponsor": sponsor,
            "sponsor_company": sponsor_company,
            "sponsor_name": sponsor_name,
        }
    
    @staticmethod
    def send_simple_email(recipients, subject, body, sender=None):
        """
        Send a basic plaintext email using the Ethereal transport.
        """
        if not recipients:
            logger.warning("send_simple_email called with empty recipients")
            return False

        try:
            ethereal_mail = NotificationService._create_ethereal_mail()
            msg = Message(
                subject=subject,
                recipients=list(recipients),
                body=body,
                sender=sender or current_app.config["MAIL_DEFAULT_SENDER"],
            )
            ethereal_mail.send(msg)
            return True
        except Exception as exc:
            logger.error(f"Failed to send simple email to {recipients}: {exc}")
            return False
    
    @staticmethod
    def notify_sponsor_new_application(application_id: int):
        """
        Send notification to sponsor about a new driver application.
        
        Args:
            application_id: The ID of the application that was submitted
        """
        try:
            # Get application details
            app = Application.query.get(application_id)
            if not app:
                logger.error(f"Application {application_id} not found")
                return False
            
            # Get sponsor details
            sponsor = Sponsor.query.get(app.SponsorID)
            if not sponsor:
                logger.error(f"Sponsor {app.SponsorID} not found for application {application_id}")
                return False
            
            # Get sponsor's account for email
            sponsor_account = Account.query.get(sponsor.AccountID)
            if not sponsor_account:
                logger.error(f"Sponsor account {sponsor.AccountID} not found for application {application_id}")
                return False
            
            # Get driver account details
            driver_account = Account.query.get(app.AccountID)
            if not driver_account:
                logger.error(f"Driver account {app.AccountID} not found for application {application_id}")
                return False
            
            # Create email content
            subject = f"New Driver Application - {driver_account.FirstName} {driver_account.LastName}"
            
            # Format application details
            cdl_class = app.CDLClass or "Not specified"
            experience = f"{app.ExperienceYears or 0} years, {app.ExperienceMonths or 0} months"
            transmission = app.Transmission or "Not specified"
            preferred_hours = app.PreferredWeeklyHours or "Not specified"
            violations = app.ViolationsCount3Y or 0
            suspensions = "Yes" if app.Suspensions5Y else "No"
            
            body = f"""
A new driver has applied to join {sponsor.Company}!

Driver Information:
- Name: {driver_account.FirstName} {driver_account.LastName}
- Email: {driver_account.Email}
- Phone: {driver_account.phone_plain if hasattr(driver_account, 'phone_plain') else 'Not provided'}

Application Details:
- CDL Class: {cdl_class}
- Experience: {experience}
- Transmission: {transmission}
- Preferred Weekly Hours: {preferred_hours}
- Violations (3 years): {violations}
- Suspensions (5 years): {suspensions}

Application submitted on: {app.SubmittedAt.strftime('%B %d, %Y at %I:%M %p')}

Please review this application in your sponsor dashboard.

Best regards,
Driver Rewards System
            """.strip()
            
            # Create and send email
            ethereal_mail = NotificationService._create_ethereal_mail()
            msg = Message(
                subject=subject,
                recipients=[sponsor.BillingEmail or sponsor_account.Email],
                body=body,
                sender=current_app.config['MAIL_DEFAULT_SENDER']
            )
            
            ethereal_mail.send(msg)
            logger.info(f"Notification sent to sponsor {sponsor.Company} for application {application_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send sponsor notification for application {application_id}: {str(e)}")
            return False
    
    @staticmethod
    def notify_driver_application_received(application_id: int):
        """
        Send confirmation to driver that their application was received.
        
        Args:
            application_id: The ID of the application that was submitted
        """
        try:
            # Get application details
            app = Application.query.get(application_id)
            if not app:
                logger.error(f"Application {application_id} not found")
                return False
            
            # Get driver account details
            driver_account = Account.query.get(app.AccountID)
            if not driver_account:
                logger.error(f"Driver account {app.AccountID} not found for application {application_id}")
                return False
            
            # Get sponsor details
            sponsor = Sponsor.query.get(app.SponsorID)
            sponsor_name = sponsor.Company if sponsor else "the selected sponsor"
            
            # Create email content
            subject = "Application Received - Driver Rewards"
            
            body = f"""
Dear {driver_account.FirstName},

Thank you for submitting your driver application to {sponsor_name}!

Your application has been received and is currently under review. Here are the details:

Application ID: {application_id}
Submitted on: {app.SubmittedAt.strftime('%B %d, %Y at %I:%M %p')}
Sponsor: {sponsor_name}

You will be notified once your application has been reviewed. In the meantime, you can check your application status by logging into your account.

If you have any questions, please contact the sponsor directly or reach out to our support team.

Best regards,
Driver Rewards System
            """.strip()
            
            # Create and send email
            ethereal_mail = NotificationService._create_ethereal_mail()
            msg = Message(
                subject=subject,
                recipients=[driver_account.Email],
                body=body,
                sender=current_app.config['MAIL_DEFAULT_SENDER']
            )
            
            ethereal_mail.send(msg)
            logger.info(f"Confirmation sent to driver {driver_account.Email} for application {application_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send driver confirmation for application {application_id}: {str(e)}")
            return False
    
    @staticmethod
    def notify_application_decision(application_id: int, decision: str, reason: str = None):
        """
        Send notification to driver about application decision.
        
        Args:
            application_id: The ID of the application
            decision: 'accepted' or 'rejected'
            reason: Optional reason for the decision
        """
        try:
            # Get application details
            app = Application.query.get(application_id)
            if not app:
                logger.error(f"Application {application_id} not found")
                return False
            
            # Get driver account details
            driver_account = Account.query.get(app.AccountID)
            if not driver_account:
                logger.error(f"Driver account {app.AccountID} not found for application {application_id}")
                return False
            
            # Get driver notification preferences
            driver = Driver.query.filter_by(AccountID=app.AccountID).first()
            if driver:
                prefs = NotificationPreferences.query.filter_by(DriverID=driver.DriverID).first()
                if prefs and not prefs.ApplicationUpdates:
                    logger.info(f"Application update notifications disabled for driver {driver.DriverID}, skipping notification")
                    return True  # Return True since this is expected behavior, not an error
                
                # Check if it's quiet hours (non-critical notification)
                if NotificationService._is_quiet_hours(driver.DriverID, is_critical=False):
                    logger.info(f"Quiet hours active for driver {driver.DriverID}, suppressing application decision notification")
                    return True  # Return True since this is expected behavior, not an error
            
            # Get sponsor details
            sponsor = Sponsor.query.get(app.SponsorID)
            sponsor_name = sponsor.Company if sponsor else "the sponsor"
            
            # Create email content
            if decision.lower() == 'accepted':
                subject = f"Application Accepted - Welcome to {sponsor_name}!"
                body = f"""
Dear {driver_account.FirstName},

Great news! Your application to join {sponsor_name} has been accepted!

You are now an active driver and can start earning points through the Driver Rewards program. 

{f'Reason: {reason}' if reason else ''}

You can now:
- Browse the driver catalog
- View your points balance
- Access exclusive rewards
- Track your progress

Welcome to the team!

Best regards,
{sponsor_name} Team
Driver Rewards System
                """.strip()
            else:  # rejected
                subject = f"Application Update - {sponsor_name}"
                body = f"""
Dear {driver_account.FirstName},

Thank you for your interest in joining {sponsor_name}. After careful review, we have decided not to move forward with your application at this time.

{f'Reason: {reason}' if reason else 'We appreciate your interest and encourage you to apply again in the future.'}

If you have any questions about this decision, please contact us directly.

Best regards,
{sponsor_name} Team
Driver Rewards System
                """.strip()
            
            # Create and send email
            ethereal_mail = NotificationService._create_ethereal_mail()
            msg = Message(
                subject=subject,
                recipients=[driver_account.Email],
                body=body,
                sender=current_app.config['MAIL_DEFAULT_SENDER']
            )
            
            ethereal_mail.send(msg)
            logger.info(f"Decision notification sent to driver {driver_account.Email} for application {application_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send decision notification for application {application_id}: {str(e)}")
            return False
    
    @staticmethod
    def notify_driver_points_change(driver_id: str, delta_points: int, reason: str, balance_after: int, transaction_id: str = None, sponsor_id: str | None = None):
        """
        Send notification to driver about points added or deducted.
        
        Args:
            driver_id: The ID of the driver
            delta_points: The change in points (positive for addition, negative for deduction)
            reason: The reason for the point change
            balance_after: The new balance after the change
            transaction_id: Optional transaction ID (e.g., order number)
        """
        try:
            # Get driver details
            driver = Driver.query.get(driver_id)
            if not driver:
                logger.error(f"Driver {driver_id} not found for points notification")
                return False
            
            # Get driver account details
            driver_account = Account.query.get(driver.AccountID)
            if not driver_account:
                logger.error(f"Driver account {driver.AccountID} not found for points notification")
                return False
            
            prefs = NotificationPreferences.query.filter_by(DriverID=driver_id).first()
            if not prefs:
                prefs = NotificationPreferences.get_or_create_for_driver(driver_id)

            quiet_hours = NotificationService._is_quiet_hours(
                driver_id, is_critical=False
            )
            send_driver_email = bool(prefs and prefs.PointChanges and prefs.EmailEnabled)
            in_app_enabled = bool(prefs and prefs.InAppEnabled)
            
            # Detailed logging for debugging
            if not prefs:
                logger.warning(f"Driver {driver_id} has no notification preferences, using defaults")
            elif not prefs.PointChanges:
                logger.info(f"Driver {driver_id} has PointChanges disabled in preferences")
            elif not prefs.EmailEnabled:
                logger.info(f"Driver {driver_id} has EmailEnabled disabled in preferences")
            if quiet_hours:
                logger.info(f"Driver {driver_id} is in quiet hours, email will be suppressed")

            # Get sponsor details (prefer explicit sponsor_id override, fall back to driver environments/company)
            sponsor_context = NotificationService._resolve_driver_sponsor_details(driver, sponsor_id)
            resolved_sponsor_id = sponsor_context["sponsor_id"]
            sponsor = sponsor_context["sponsor"]
            sponsor_name = sponsor_context["sponsor_name"]  # already defaults to "your sponsor"
            
            # Determine if it's an addition or deduction
            is_addition = delta_points > 0
            action = "added" if is_addition else "deducted"
            points_abs = abs(delta_points)
            
            # Create email content
            if is_addition:
                subject = f"Points Added - {points_abs} points credited to your account"
                body = f"""
Dear {driver_account.FirstName},

Great news! {points_abs} points have been added to your account.

Points Transaction:
- Points added: {points_abs}
- Reason: {reason}
- New balance: {balance_after} points
- Sponsor: {sponsor_name}
{f'- Transaction ID: {transaction_id}' if transaction_id else ''}

You can use these points to browse and purchase items from the driver catalog.

Best regards,
{sponsor_name} Team
Driver Rewards System
                """.strip()
            else:
                subject = f"Points Deducted - {points_abs} points used from your account"
                body = f"""
Dear {driver_account.FirstName},

{points_abs} points have been deducted from your account.

Points Transaction:
- Points deducted: {points_abs}
- Reason: {reason}
- New balance: {balance_after} points
- Sponsor: {sponsor_name}
{f'- Transaction ID: {transaction_id}' if transaction_id else ''}

Thank you for using the Driver Rewards program!

Best regards,
{sponsor_name} Team
Driver Rewards System
                """.strip()

            sponsor_company_name = None
            sponsor_company = sponsor_context.get("sponsor_company")
            if sponsor_company and getattr(sponsor_company, "CompanyName", None):
                sponsor_company_name = sponsor_company.CompanyName
            metadata = NotificationService._with_sponsor_metadata(
                {
                    "deltaPoints": delta_points,
                    "balanceAfter": balance_after,
                    "reason": reason,
                    "transactionId": transaction_id,
                    "sponsorName": sponsor_name,
                    "direction": "credit" if is_addition else "debit",
                },
                sponsor_id=resolved_sponsor_id,
                sponsor_name=sponsor_name,
                sponsor_company_name=sponsor_company_name,
                is_sponsor_specific=True,
            )
            
            # Create and send email to driver (if enabled)
            ethereal_mail = NotificationService._create_ethereal_mail()
            email_sent = False
            if send_driver_email and not quiet_hours:
                try:
                    msg = Message(
                        subject=subject,
                        recipients=[driver_account.Email],
                        body=body,
                        sender=current_app.config['MAIL_DEFAULT_SENDER']
                    )
                    ethereal_mail.send(msg)
                    logger.info(f"Points change notification sent to driver {driver_account.Email} for {delta_points} points")
                    email_sent = True
                except Exception as email_error:
                    logger.error(f"Failed to send points change email to {driver_account.Email}: {str(email_error)}", exc_info=True)
                    email_sent = False
            elif send_driver_email and quiet_hours:
                logger.info(
                    f"Quiet hours active for driver {driver_id}, suppressing point change email"
                )
            else:
                reason_parts = []
                if not prefs:
                    reason_parts.append("no preferences")
                elif not prefs.PointChanges:
                    reason_parts.append("PointChanges disabled")
                elif not prefs.EmailEnabled:
                    reason_parts.append("EmailEnabled disabled")
                reason_str = ", ".join(reason_parts) if reason_parts else "unknown reason"
                logger.info(f"Driver point change email suppressed for driver {driver_id}: {reason_str}")

            delivery_channels: list[str] = []
            if in_app_enabled:
                delivery_channels.append("in_app")
            if email_sent:
                delivery_channels.append("email")
            if delivery_channels:
                NotificationService._record_driver_notification(
                    driver_id,
                    "points_change",
                    subject,
                    body,
                    metadata=metadata,
                    channels=delivery_channels,
                )

            # If large points change (>= 1000), notify sponsor (if enabled)
            try:
                if abs(delta_points) >= 1000:
                    from app.models import SponsorNotificationPreferences
                    if not sponsor and resolved_sponsor_id:
                        # best-effort fetch
                        sponsor = Sponsor.query.get(resolved_sponsor_id)
                    if not sponsor or not resolved_sponsor_id:
                        logger.info("No sponsor found for large points change alert; skipping sponsor email")
                        return True
                    sponsor_prefs = SponsorNotificationPreferences.get_or_create_for_sponsor(resolved_sponsor_id)
                    if sponsor_prefs and sponsor_prefs.DriverPointsChanges and sponsor_prefs.EmailEnabled:
                        sponsor_account = Account.query.get(sponsor.AccountID) if sponsor else None
                        if sponsor_account and sponsor_account.Email:
                            s_subject = (
                                f"Large Points Change Alert - {driver_account.FirstName} {driver_account.LastName}"
                            )
                            s_body = f"""
Sponsor Alert:

Driver: {driver_account.FirstName} {driver_account.LastName} ({driver_account.Email})
Change: {'+' if delta_points > 0 else ''}{delta_points} points
Reason: {reason}
New Balance: {balance_after} points
{('Transaction ID: ' + str(transaction_id)) if transaction_id else ''}

This automated alert is sent for point changes of 1000 or more.
                            """.strip()
                            s_msg = Message(
                                subject=s_subject,
                                recipients=[sponsor_account.Email],
                                body=s_body,
                                sender=current_app.config['MAIL_DEFAULT_SENDER']
                            )
                            ethereal_mail.send(s_msg)
                            logger.info(
                                f"Sponsor large-change alert sent to {sponsor_account.Email} for driver {driver_account.Email}"
                            )
            except Exception as e:
                logger.error(f"Failed to send sponsor large points change alert: {e}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send points change notification for driver {driver_id}: {str(e)}")
            return False
    
    @staticmethod
    def notify_driver_order_confirmation(order_id: str):
        """
        Send order confirmation notification to driver with detailed order information.
        
        Args:
            order_id: The ID of the order
        """
        try:
            from app.models import Orders, OrderLineItem, Account, Driver, Sponsor
            
            # Get order details
            order = Orders.query.get(order_id)
            if not order:
                logger.error(f"Order {order_id} not found for confirmation notification")
                return False
            
            # Get driver details
            driver = Driver.query.get(order.DriverID)
            if not driver:
                logger.error(f"Driver {order.DriverID} not found for order confirmation")
                return False
            
            # Get driver account details
            driver_account = Account.query.get(driver.AccountID)
            if not driver_account:
                logger.error(f"Driver account {driver.AccountID} not found for order confirmation")
                return False
            
            # Check driver's notification preferences
            prefs = NotificationPreferences.query.filter_by(DriverID=driver.DriverID).first()
            if not prefs:
                prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
            
            # Check if order confirmation notifications are enabled
            if not prefs.OrderConfirmations:
                logger.info(f"Order confirmation notifications disabled for driver {driver.DriverID}, skipping notification")
                return True
            
            quiet_hours = NotificationService._is_quiet_hours(
                driver.DriverID, is_critical=False
            )
            in_app_enabled = bool(prefs.InAppEnabled)
            
            # Get sponsor details
            sponsor = Sponsor.query.get(order.SponsorID)
            sponsor_name = sponsor.Company if sponsor else "your sponsor"
            
            # Get order line items
            line_items = OrderLineItem.query.filter_by(OrderID=order.OrderID).all()
            
            # Build order details
            order_details = []
            for item in line_items:
                order_details.append(f"- {item.Title} (Qty: {item.Quantity}) - {item.LineTotalPoints} points")
            
            order_details_text = "\n".join(order_details) if order_details else "No items found"
            
            # Create email content
            subject = f"Order Confirmation - {order.OrderNumber}"
            
            body = f"""
Dear {driver_account.FirstName},

Thank you for your order! Your purchase has been confirmed and is being processed.

Order Details:
- Order Number: {order.OrderNumber}
- Order Date: {order.CreatedAt.strftime('%B %d, %Y at %I:%M %p')}
- Total Points: {order.TotalPoints}
- Sponsor: {sponsor_name}

Items Ordered:
{order_details_text}

Shipping Information:
- Name: {driver_account.FirstName} {driver_account.LastName}
- Address: {driver.ShippingStreet or 'Not provided'}
- City: {driver.ShippingCity or 'Not provided'}
- State: {driver.ShippingState or 'Not provided'}
- Postal Code: {driver.ShippingPostal or 'Not provided'}
- Country: {driver.ShippingCountry or 'Not provided'}

Your order will be processed and shipped according to the sponsor's fulfillment timeline.

Best regards,
{sponsor_name} Team
Driver Rewards System
            """.strip()
            
            # Create and send email
            ethereal_mail = NotificationService._create_ethereal_mail()
            email_sent = False
            if not quiet_hours:
                msg = Message(
                    subject=subject,
                    recipients=[driver_account.Email],
                    body=body,
                    sender=current_app.config['MAIL_DEFAULT_SENDER']
                )
                
                ethereal_mail.send(msg)
                email_sent = True
                logger.info(f"Order confirmation sent to driver {driver_account.Email} for order {order.OrderNumber}")
            else:
                logger.info(
                    f"Quiet hours active for driver {driver.DriverID}, suppressing order confirmation email"
                )

            sponsor_company_name = None
            if sponsor and getattr(sponsor, "sponsor_company", None):
                sponsor_company_name = sponsor.sponsor_company.CompanyName
            metadata = NotificationService._with_sponsor_metadata(
                {
                    "orderId": order.OrderID,
                    "orderNumber": order.OrderNumber,
                    "totalPoints": order.TotalPoints,
                    "items": [
                        {"title": item.Title, "quantity": item.Quantity}
                        for item in line_items
                    ],
                },
                sponsor_id=order.SponsorID,
                sponsor_name=sponsor.Company if sponsor else None,
                sponsor_company_name=sponsor_company_name,
                is_sponsor_specific=True,
            )
            delivery_channels = []
            if in_app_enabled:
                delivery_channels.append("in_app")
            if email_sent:
                delivery_channels.append("email")
            if delivery_channels:
                NotificationService._record_driver_notification(
                    driver.DriverID,
                    "order_confirmation",
                    subject,
                    body,
                    metadata=metadata,
                    channels=delivery_channels,
                )
            return True
            
        except Exception as e:
            logger.error(f"Failed to send order confirmation notification for order {order_id}: {str(e)}")
            return False

    @staticmethod
    def notify_driver_refund_window_expired(driver_account: Account, order_number: str):
        """Notify the driver that the refund window for an order has expired."""
        try:
            if not driver_account or not driver_account.Email:
                return False
            
            # Check quiet hours (non-critical notification)
            try:
                from app.models import Driver
                driver = Driver.query.filter_by(AccountID=driver_account.AccountID).first()
                if driver:
                    if NotificationService._is_quiet_hours(driver.DriverID, is_critical=False):
                        logger.info(f"Quiet hours active for driver {driver.DriverID}, suppressing refund window expired notification")
                        return True
            except Exception:
                pass  # Continue if check fails
            
            subject = f"Refund window expired for Order {order_number}"
            body = f"""
Dear {driver_account.FirstName or 'Driver'},

The refund window for your order {order_number} has expired. The order can no longer be canceled or refunded via self-service.

If you believe this is an error, please contact support.

Best regards,
Driver Rewards System
            """.strip()
            ethereal_mail = NotificationService._create_ethereal_mail()
            msg = Message(subject=subject, recipients=[driver_account.Email], body=body,
                          sender=current_app.config['MAIL_DEFAULT_SENDER'])
            ethereal_mail.send(msg)
            logger.info(f"Refund window expiry notice sent to {driver_account.Email} for order {order_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to send refund window expired notice: {e}")
            return False
    
    @staticmethod
    def notify_sponsor_new_order(order_id: str):
        """
        Send notification to sponsor about a new order placed by a driver.
        
        Args:
            order_id: The ID of the order
        """
        try:
            from app.models import Orders, OrderLineItem, Account, Driver, Sponsor
            
            # Get order details
            order = Orders.query.get(order_id)
            if not order:
                logger.error(f"Order {order_id} not found for sponsor notification")
                return False
            
            # Get sponsor details
            sponsor = Sponsor.query.get(order.SponsorID)
            if not sponsor:
                logger.error(f"Sponsor {order.SponsorID} not found for order notification")
                return False
            
            # Get sponsor account details
            sponsor_account = Account.query.get(sponsor.AccountID)
            if not sponsor_account:
                logger.error(f"Sponsor account {sponsor.AccountID} not found for order notification")
                return False
            
            # Get driver details
            driver = Driver.query.get(order.DriverID)
            if not driver:
                logger.error(f"Driver {order.DriverID} not found for order notification")
                return False
            
            # Get driver account details
            driver_account = Account.query.get(driver.AccountID)
            if not driver_account:
                logger.error(f"Driver account {driver.AccountID} not found for order notification")
                return False
            
            # Get order line items
            line_items = OrderLineItem.query.filter_by(OrderID=order.OrderID).all()
            
            # Build order details
            order_details = []
            for item in line_items:
                order_details.append(f"- {item.Title} (Qty: {item.Quantity}) - {item.LineTotalPoints} points")
            
            order_details_text = "\n".join(order_details) if order_details else "No items found"
            
            # Create email content
            subject = f"New Order Received - {order.OrderNumber}"
            
            body = f"""
A new order has been placed by one of your drivers!

Order Details:
- Order Number: {order.OrderNumber}
- Order Date: {order.CreatedAt.strftime('%B %d, %Y at %I:%M %p')}
- Total Points: {order.TotalPoints}
- Status: {order.Status}

Driver Information:
- Name: {driver_account.FirstName} {driver_account.LastName}
- Email: {driver_account.Email}
- Phone: {driver_account.phone_plain if hasattr(driver_account, 'phone_plain') else 'Not provided'}

Items Ordered:
{order_details_text}

Shipping Information:
- Name: {driver_account.FirstName} {driver_account.LastName}
- Address: {driver.ShippingStreet or 'Not provided'}
- City: {driver.ShippingCity or 'Not provided'}
- State: {driver.ShippingState or 'Not provided'}
- Postal Code: {driver.ShippingPostal or 'Not provided'}
- Country: {driver.ShippingCountry or 'Not provided'}

Please process this order according to your fulfillment timeline.

Best regards,
Driver Rewards System
            """.strip()
            
            # Create and send email
            ethereal_mail = NotificationService._create_ethereal_mail()
            msg = Message(
                subject=subject,
                recipients=[sponsor.BillingEmail or sponsor_account.Email],
                body=body,
                sender=current_app.config['MAIL_DEFAULT_SENDER']
            )
            
            ethereal_mail.send(msg)
            logger.info(f"New order notification sent to sponsor {sponsor.Company} for order {order.OrderNumber}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send sponsor order notification for order {order_id}: {str(e)}")
            return False
    
    @staticmethod
    def notify_driver_account_status_change(driver_account: Account, new_status: str, changed_by: str = ""):
        """Send an email to a driver when their account status changes.

        Args:
            driver_account: Account row for the driver (must contain Email/FirstName/LastName)
            new_status: One-letter status code (A/I/H/P)
            changed_by: A short descriptor of who changed it (e.g., "Admin", sponsor company)
        """
        try:
            if not driver_account or not driver_account.Email:
                logger.error("notify_driver_account_status_change: missing driver account/email")
                return False

            driver_id = None
            prefs = None
            send_email = True
            in_app_enabled = True
            try:
                from app.models import Driver, NotificationPreferences
                drv = Driver.query.filter_by(AccountID=driver_account.AccountID).first()
                if drv:
                    driver_id = drv.DriverID
                    prefs = NotificationPreferences.get_or_create_for_driver(drv.DriverID)
                    if not (prefs and prefs.AccountStatusChanges):
                        logger.info("Account status change notifications disabled for driver; skipping")
                        return True
                    send_email = bool(prefs.EmailEnabled)
                    in_app_enabled = bool(prefs.InAppEnabled)
            except Exception:
                pass

            status_names = {
                'A': 'Active',
                'I': 'Inactive',
                'H': 'Archived',
                'P': 'Pending',
            }
            friendly = status_names.get((new_status or '').upper(), new_status)

            actor = (changed_by or "").strip() or "an administrator"

            subject = f"Your Driver Rewards account status was changed to {friendly}"

            body = f"""
Dear {driver_account.FirstName or 'Driver'},

This is a notice that your Driver Rewards account status has been changed by {actor}.

New status: {friendly}

{('If your account is Inactive, please contact support to reactivate.' if (new_status or '').upper() == 'I' else '')}
{('Your account is archived and permanently closed.' if (new_status or '').upper() == 'H' else '')}

If you believe this was a mistake, please reply to this email or contact your sponsor.

Best regards,
Driver Rewards System
            """.strip()

            email_sent = False
            if send_email:
                ethereal_mail = NotificationService._create_ethereal_mail()
                msg = Message(
                    subject=subject,
                    recipients=[driver_account.Email],
                    body=body,
                    sender=current_app.config['MAIL_DEFAULT_SENDER']
                )

                ethereal_mail.send(msg)
                email_sent = True
                logger.info(f"Status change notification sent to driver {driver_account.Email} -> {friendly}")

            if driver_id and (in_app_enabled or email_sent):
                channels = []
                if in_app_enabled:
                    channels.append("in_app")
                if email_sent:
                    channels.append("email")
                NotificationService._record_driver_notification(
                    driver_id,
                    "account_status",
                    subject,
                    body,
                    metadata=NotificationService._with_sponsor_metadata(
                        {"newStatus": friendly, "changedBy": actor},
                        is_sponsor_specific=False,
                    ),
                    channels=channels or ["email"],
                )
            return True
        except Exception as e:
            logger.error(f"Failed to send driver status change notification: {str(e)}")
            return False

    @staticmethod
    def notify_driver_email_changed(old_email: str, new_email: str, driver_account: Account):
        """Alert the driver that their email was changed."""
        try:
            if not driver_account or not (old_email or new_email):
                return False
            driver_id = None
            prefs = None
            send_email = True
            in_app_enabled = True
            try:
                from app.models import Driver
                drv = Driver.query.filter_by(AccountID=driver_account.AccountID).first()
                if drv:
                    driver_id = drv.DriverID
                    prefs = NotificationPreferences.get_or_create_for_driver(drv.DriverID)
                    if not (prefs and prefs.SensitiveInfoResets):
                        return True
                    send_email = bool(prefs.EmailEnabled)
                    in_app_enabled = bool(prefs.InAppEnabled)
            except Exception:
                pass
            subject = "Your Driver Rewards email was changed"
            body = f"""
Dear {driver_account.FirstName or 'Driver'},

Your account email address was changed.

Previous email: {old_email or '(unknown)'}
New email: {new_email or '(unknown)'}

If you did not make this change, please contact support immediately.

Best regards,
Driver Rewards Security
            """.strip()

            email_sent = False
            if send_email:
                ethereal_mail = NotificationService._create_ethereal_mail()
                recipients = []
                if new_email and new_email not in recipients:
                    recipients.append(new_email)
                if old_email and old_email != new_email and old_email not in recipients:
                    recipients.append(old_email)
                if not recipients:
                    recipients = [driver_account.Email]

                msg = Message(
                    subject=subject,
                    recipients=recipients,
                    body=body,
                    sender=current_app.config['MAIL_DEFAULT_SENDER'],
                )
                ethereal_mail.send(msg)
                email_sent = True
                logger.info(f"Email change alert sent to driver {new_email or driver_account.Email}")

            if driver_id and (in_app_enabled or email_sent):
                channels = []
                if in_app_enabled:
                    channels.append("in_app")
                if email_sent:
                    channels.append("email")
                NotificationService._record_driver_notification(
                    driver_id,
                    "email_changed",
                    subject,
                    body,
                    metadata=NotificationService._with_sponsor_metadata(
                        {"oldEmail": old_email, "newEmail": new_email},
                        is_sponsor_specific=False,
                    ),
                    channels=channels or ["email"],
                )
            return True
        except Exception as e:
            logger.error(f"Failed to send driver email change alert: {e}")
            return False

    @staticmethod
    def notify_driver_password_changed(driver_account: Account):
        """Alert the driver that their password was changed."""
        try:
            if not driver_account or not driver_account.Email:
                return False
            driver_id = None
            prefs = None
            send_email = True
            in_app_enabled = True
            try:
                from app.models import Driver
                drv = Driver.query.filter_by(AccountID=driver_account.AccountID).first()
                if drv:
                    driver_id = drv.DriverID
                    prefs = NotificationPreferences.get_or_create_for_driver(drv.DriverID)
                    if not (prefs and prefs.SensitiveInfoResets):
                        return True
                    send_email = bool(prefs.EmailEnabled)
                    in_app_enabled = bool(prefs.InAppEnabled)
            except Exception:
                pass
            subject = "Your Driver Rewards password was changed"
            body = f"""
Dear {driver_account.FirstName or 'Driver'},

This is a confirmation that your account password was changed.

If you did not make this change, please reset your password immediately and contact support.

Best regards,
Driver Rewards Security
            """.strip()
            email_sent = False
            if send_email:
                ethereal_mail = NotificationService._create_ethereal_mail()
                msg = Message(subject=subject, recipients=[driver_account.Email], body=body,
                              sender=current_app.config['MAIL_DEFAULT_SENDER'])
                ethereal_mail.send(msg)
                email_sent = True
                logger.info(f"Password change alert sent to driver {driver_account.Email}")

            if driver_id and (in_app_enabled or email_sent):
                channels = []
                if in_app_enabled:
                    channels.append("in_app")
                if email_sent:
                    channels.append("email")
                NotificationService._record_driver_notification(
                    driver_id,
                    "password_changed",
                    subject,
                    body,
                    metadata=NotificationService._with_sponsor_metadata(
                        {"event": "password_change"},
                        is_sponsor_specific=False,
                    ),
                    channels=channels or ["email"],
                )
            return True
        except Exception as e:
            logger.error(f"Failed to send driver password change alert: {e}")
            return False
    @staticmethod
    def notify_driver_low_points(driver_id: str, current_balance: int, threshold: int):
        """
        Send notification to driver when their points balance drops below the threshold.
        
        Args:
            driver_id: The ID of the driver
            current_balance: The current points balance
            threshold: The threshold that was crossed
        """
        try:
            # Get driver details
            driver = Driver.query.get(driver_id)
            if not driver:
                logger.error(f"Driver {driver_id} not found for low points notification")
                return False
            
            # Get driver account details
            driver_account = Account.query.get(driver.AccountID)
            if not driver_account:
                logger.error(f"Driver account {driver.AccountID} not found for low points notification")
                return False
            
            prefs = NotificationPreferences.query.filter_by(DriverID=driver_id).first()
            if not prefs:
                prefs = NotificationPreferences.get_or_create_for_driver(driver_id)
            
            if not (prefs and prefs.LowPointsAlertEnabled):
                logger.info(f"Low points alert disabled for driver {driver_id}, skipping notification")
                return True
            
            quiet_hours = NotificationService._is_quiet_hours(
                driver_id, is_critical=False
            )
            
            # Get sponsor/company context (if available)
            sponsor_context = NotificationService._resolve_driver_sponsor_details(driver, None)
            sponsor_name = sponsor_context["sponsor_name"]
            
            # Create email content
            subject = f"Low Points Alert - Your balance is below {threshold} points"
            
            body = f"""
Dear {driver_account.FirstName},

This is an alert that your points balance has dropped below your specified threshold.

Current Balance: {current_balance} points
Threshold: {threshold} points

You may want to check your recent transactions or contact {sponsor_name} if you have any questions about your points balance.

Best regards,
Driver Rewards System
            """.strip()
            
            email_sent = False
            if prefs.EmailEnabled and not quiet_hours:
                ethereal_mail = NotificationService._create_ethereal_mail()
                msg = Message(
                    subject=subject,
                    recipients=[driver_account.Email],
                    body=body,
                    sender=current_app.config['MAIL_DEFAULT_SENDER']
                )
                
                ethereal_mail.send(msg)
                email_sent = True
                logger.info(f"Low points alert sent to driver {driver_account.Email} (balance: {current_balance}, threshold: {threshold})")
            elif prefs.EmailEnabled and quiet_hours:
                logger.info(
                    f"Quiet hours active for driver {driver_id}, suppressing low points email"
                )

            sponsor_company_name = None
            sponsor_company = sponsor_context.get("sponsor_company")
            if sponsor_company and getattr(sponsor_company, "CompanyName", None):
                sponsor_company_name = sponsor_company.CompanyName
            metadata = NotificationService._with_sponsor_metadata(
                {
                    "currentBalance": current_balance,
                    "threshold": threshold,
                    "sponsorName": sponsor_name,
                },
                sponsor_id=sponsor_context.get("sponsor_id"),
                sponsor_name=sponsor_name,
                sponsor_company_name=sponsor_company_name,
                is_sponsor_specific=True,
            )
            delivery_channels = []
            if prefs.InAppEnabled:
                delivery_channels.append("in_app")
            if email_sent:
                delivery_channels.append("email")
            if delivery_channels:
                NotificationService._record_driver_notification(
                    driver_id,
                    "low_points",
                    subject,
                    body,
                    metadata=metadata,
                    channels=delivery_channels,
                )
            return True
            
        except Exception as e:
            logger.error(f"Failed to send low points notification for driver {driver_id}: {str(e)}")
            return False
    
    @staticmethod
    def notify_ticket_response(ticket_id: str):
        """
        Send notification to driver or sponsor when an admin responds to their support ticket.
        
        Args:
            ticket_id: The ID of the support ticket
        """
        logger.info(f"notify_ticket_response called for ticket {ticket_id}")
        try:
            from app.models import SupportTicket, SupportMessage, Account, Driver, Sponsor
            
            # Get ticket details
            ticket = SupportTicket.query.get(ticket_id)
            if not ticket:
                logger.error(f"Support ticket {ticket_id} not found")
                return False
            
            # Get the latest admin message
            admin_messages = SupportMessage.query.filter_by(
                TicketID=ticket_id, 
                AuthorRole='admin'
            ).order_by(SupportMessage.CreatedAt.desc()).limit(1).all()
            
            if not admin_messages:
                logger.error(f"No admin messages found for ticket {ticket_id}")
                return False
            
            admin_message = admin_messages[0]
            
            driver_notification_ctx = None
            send_email = True
            # Get ticket owner based on source
            if ticket.Source == 'driver':
                logger.info(f"Processing driver ticket {ticket_id}")
                driver = Driver.query.get(ticket.OwnerID)
                if not driver:
                    logger.error(f"Driver {ticket.OwnerID} not found for ticket {ticket_id}")
                    return False
                
                driver_account = Account.query.get(driver.AccountID)
                if not driver_account:
                    logger.error(f"Driver account {driver.AccountID} not found for ticket {ticket_id}")
                    return False
                
                # Check driver's notification preferences
                prefs = NotificationPreferences.query.filter_by(DriverID=driver.DriverID).first()
                if not prefs:
                    prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
                
                # Check if ticket update notifications are enabled
                # Handle gracefully if TicketUpdates column doesn't exist yet
                try:
                    ticket_updates_enabled = prefs.TicketUpdates
                except AttributeError:
                    logger.info(f"TicketUpdates column doesn't exist yet, defaulting to True")
                    ticket_updates_enabled = True
                
                if not ticket_updates_enabled:
                    logger.info(f"Ticket update notifications disabled for driver {driver.DriverID}, skipping notification")
                    return True
                
                quiet_hours = NotificationService._is_quiet_hours(
                    driver.DriverID, is_critical=False
                )
                if quiet_hours:
                    logger.info(f"Quiet hours active for driver {driver.DriverID}, suppressing ticket response email")
                    send_email = False
                
                recipient_email = driver_account.Email
                recipient_name = driver_account.FirstName or "Driver"
                logger.info(f"Preparing to send email to driver {recipient_email}")
                driver_notification_ctx = {
                    "driver_id": driver.DriverID,
                    "prefs": prefs,
                }
                
            elif ticket.Source == 'sponsor':
                logger.info(f"Processing sponsor ticket {ticket_id}")
                sponsor = Sponsor.query.get(ticket.OwnerID)
                if not sponsor:
                    logger.error(f"Sponsor {ticket.OwnerID} not found for ticket {ticket_id}")
                    return False
                
                sponsor_account = Account.query.get(sponsor.AccountID)
                if not sponsor_account:
                    logger.error(f"Sponsor account {sponsor.AccountID} not found for ticket {ticket_id}")
                    return False
                
                # Check sponsor's notification preferences
                from app.models import SponsorNotificationPreferences
                prefs = SponsorNotificationPreferences.query.filter_by(SponsorID=sponsor.SponsorID).first()
                if not prefs:
                    prefs = SponsorNotificationPreferences.get_or_create_for_sponsor(sponsor.SponsorID)
                
                # Check if ticket update notifications are enabled
                # Handle gracefully if TicketUpdates column doesn't exist yet
                try:
                    ticket_updates_enabled = prefs.TicketUpdates
                except AttributeError:
                    logger.info(f"TicketUpdates column doesn't exist yet, defaulting to True")
                    ticket_updates_enabled = True
                
                if not ticket_updates_enabled:
                    logger.info(f"Ticket update notifications disabled for sponsor {sponsor.SponsorID}, skipping notification")
                    return True
                
                recipient_email = sponsor.BillingEmail or sponsor_account.Email
                recipient_name = sponsor.Company or sponsor_account.FirstName or "Sponsor"
                logger.info(f"Preparing to send email to sponsor {recipient_email}")
                
            else:
                logger.error(f"Unknown ticket source: {ticket.Source}")
                return False
            
            # Create email content
            subject = f"New Response to Your Support Ticket: {ticket.Title}"
            
            body = f"""
Dear {recipient_name},

An admin has responded to your support ticket.

Ticket Details:
- Title: {ticket.Title}
- Ticket ID: {ticket_id}
- Status: {ticket.Status}

Admin Response:
{admin_message.Body}

You can view and reply to this ticket by logging into your account and visiting your support dashboard.

Best regards,
Support Team
Driver Rewards System
            """.strip()
            
            # Create and send email
            email_sent = False
            if send_email:
                ethereal_mail = NotificationService._create_ethereal_mail()
                msg = Message(
                    subject=subject,
                    recipients=[recipient_email],
                    body=body,
                    sender=current_app.config['MAIL_DEFAULT_SENDER']
                )
                
                logger.info(f"Sending email to {recipient_email}")
                ethereal_mail.send(msg)
                email_sent = True
                logger.info(f"✓ Ticket response notification sent to {recipient_email} for ticket {ticket_id}")
            else:
                logger.info(
                    f"Email suppressed for ticket {ticket_id} due to quiet hours, notification will rely on in-app delivery"
                )

            if driver_notification_ctx:
                prefs = driver_notification_ctx.get("prefs")
                driver_id = driver_notification_ctx.get("driver_id")
                if driver_id:
                    channels = []
                    if prefs and prefs.InAppEnabled:
                        channels.append("in_app")
                    if email_sent:
                        channels.append("email")
                    if channels:
                        NotificationService._record_driver_notification(
                            driver_id,
                            "support_ticket",
                            subject,
                            body,
                            metadata=NotificationService._with_sponsor_metadata(
                                {
                                    "ticketId": ticket_id,
                                    "title": ticket.Title,
                                    "adminMessage": admin_message.Body,
                                },
                                is_sponsor_specific=False,
                            ),
                            channels=channels,
                        )
            return True
            
        except Exception as e:
            logger.error(f"Failed to send ticket response notification for ticket {ticket_id}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
