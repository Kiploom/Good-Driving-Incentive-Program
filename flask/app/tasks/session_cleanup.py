"""
Session Cleanup Background Task
Periodically cleans up expired and inactive sessions
"""

from app.extensions import db
from flask import current_app
from datetime import datetime, timedelta

def _notify_refund_expirations(app):
    """Identify orders whose refund window just expired and notify drivers.

    We use the same 30-minute window defined in orders routes and only notify once by
    checking a soft flag via Orders.Status or a separate heuristic (no dedicated column).
    Since we can't alter schema, we notify when:
      - order.Status == 'completed'
      - CreatedAt < now - 30 minutes
      - and we haven't already logged a notification (best-effort: rely on CreatedAt minute boundary)
    """
    try:
        with app.app_context():
            from app.models import Orders, Account, Driver
            from app.services.notification_service import NotificationService

            now = datetime.now()
            cutoff = now - timedelta(minutes=30)

            # Fetch recently expired (completed) orders in the last 5 minutes window to avoid spamming
            window_start = now - timedelta(minutes=5)
            candidates = (
                Orders.query
                .filter(Orders.Status == 'completed')
                .filter(Orders.CreatedAt <= cutoff)
                .filter(Orders.CreatedAt > cutoff - timedelta(minutes=5))
                .all()
            )

            for order in candidates:
                driver = Driver.query.filter_by(DriverID=order.DriverID).first()
                if not driver:
                    continue
                account = Account.query.filter_by(AccountID=driver.AccountID).first()
                if not account:
                    continue
                try:
                    # Check driver preferences
                    from app.models import NotificationPreferences
                    prefs = NotificationPreferences.get_or_create_for_driver(driver.DriverID)
                    if prefs and prefs.RefundWindowAlerts and prefs.EmailEnabled:
                        NotificationService.notify_driver_refund_window_expired(account, order.OrderNumber)
                except Exception as e:
                    current_app.logger.error(f"Failed to send refund expiry for order {order.OrderID}: {e}")
    except Exception as e:
        try:
            current_app.logger.error(f"Refund expiry task failed: {e}")
        except Exception:
            pass
from app.services.session_management_service import SessionManagementService
from app import create_app


def cleanup_sessions():
    """
    Clean up expired and inactive sessions
    This should be called periodically (e.g., every 5 minutes)
    """
    app = create_app()
    with app.app_context():
        try:
            count = SessionManagementService.cleanup_expired_sessions()
            print(f"Cleaned up {count} expired/inactive sessions")
            return count
        except Exception as e:
            print(f"Error cleaning up sessions: {e}")
            return 0


if __name__ == "__main__":
    cleanup_sessions()
