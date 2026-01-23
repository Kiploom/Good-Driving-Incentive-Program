from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import current_app

from app.extensions import db
from app.models import DriverNotification, NotificationPreferences


class DriverNotificationService:
    """Helper utilities for creating and retrieving driver notifications."""

    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    @staticmethod
    def create_notification(
        driver_id: str,
        notif_type: str,
        title: str,
        body: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
        delivered_via: str = "in_app",
    ) -> Optional[DriverNotification]:
        """Persist a notification row for the driver."""
        if not driver_id:
            return None

        try:
            notification = DriverNotification(
                DriverID=driver_id,
                Type=(notif_type or "general")[:50],
                Title=(title or "Notification")[:255],
                Body=body,
                Metadata=metadata or {},
                DeliveredVia=delivered_via,
            )
            db.session.add(notification)
            db.session.commit()
            return notification
        except Exception as exc:  # pragma: no cover - defensive logging
            db.session.rollback()
            current_app.logger.error(
                "Failed to create driver notification for %s: %s", driver_id, exc
            )
            return None

    @staticmethod
    def fetch_notifications(
        driver_id: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        unread_only: bool = False,
        since: Optional[datetime] = None,
    ) -> Tuple[List[DriverNotification], int]:
        """Return notifications plus total count."""
        page = max(1, page)
        page_size = max(1, min(page_size, DriverNotificationService.MAX_PAGE_SIZE))

        query = DriverNotification.query.filter_by(DriverID=driver_id)
        if unread_only:
            query = query.filter_by(IsRead=False)
        if since:
            query = query.filter(DriverNotification.CreatedAt >= since)

        total = query.count()
        items = (
            query.order_by(DriverNotification.CreatedAt.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    @staticmethod
    def mark_notifications_read(
        driver_id: str, notification_ids: Optional[Iterable[str]] = None
    ) -> int:
        query = DriverNotification.query.filter_by(DriverID=driver_id)
        if notification_ids:
            query = query.filter(
                DriverNotification.NotificationID.in_(list(notification_ids))
            )

        updated = 0
        for notification in query.all():
            if not notification.IsRead:
                notification.mark_read()
                updated += 1

        if updated:
            db.session.commit()
        return updated

    @staticmethod
    def mark_all_read(driver_id: str) -> int:
        return DriverNotificationService.mark_notifications_read(driver_id, None)

    @staticmethod
    def serialize_notification(notification: DriverNotification) -> Dict[str, Any]:
        metadata = notification.Metadata or {}
        return {
            "id": notification.NotificationID,
            "type": notification.Type,
            "title": notification.Title,
            "body": notification.Body,
            "metadata": metadata,
            "sponsorContext": DriverNotificationService._extract_sponsor_context(metadata),
            "deliveredVia": notification.DeliveredVia,
            "isRead": notification.IsRead,
            "createdAt": notification.CreatedAt.isoformat()
            if notification.CreatedAt
            else None,
            "readAt": notification.ReadAt.isoformat() if notification.ReadAt else None,
        }

    @staticmethod
    def _extract_sponsor_context(metadata: Dict[str, Any]) -> Dict[str, Any]:
        sponsor_id = metadata.get("sponsorId") or metadata.get("sponsor_id")
        sponsor_name = metadata.get("sponsorName") or metadata.get("sponsor_name")
        sponsor_company_name = (
            metadata.get("sponsorCompanyName")
            or metadata.get("sponsor_company_name")
        )
        raw_flag = metadata.get("isSponsorSpecific")
        is_specific = bool(raw_flag) if raw_flag is not None else bool(
            sponsor_id or sponsor_name or sponsor_company_name
        )
        return {
            "sponsorId": sponsor_id,
            "sponsorName": sponsor_name,
            "sponsorCompanyName": sponsor_company_name,
            "isSponsorSpecific": is_specific,
        }

    @staticmethod
    def serialize_preferences(prefs: NotificationPreferences) -> Dict[str, Any]:
        return {
            "pointChanges": prefs.PointChanges,
            "orderConfirmations": prefs.OrderConfirmations,
            "applicationUpdates": prefs.ApplicationUpdates,
            "ticketUpdates": prefs.TicketUpdates,
            "refundWindowAlerts": prefs.RefundWindowAlerts,
            "accountStatusChanges": prefs.AccountStatusChanges,
            "sensitiveInfoResets": prefs.SensitiveInfoResets,
            "emailEnabled": prefs.EmailEnabled,
            "inAppEnabled": prefs.InAppEnabled,
            "quietHours": {
                "enabled": prefs.QuietHoursEnabled,
                "start": prefs.QuietHoursStart.isoformat()
                if prefs.QuietHoursStart
                else None,
                "end": prefs.QuietHoursEnd.isoformat() if prefs.QuietHoursEnd else None,
            },
            "lowPoints": {
                "enabled": prefs.LowPointsAlertEnabled,
                "threshold": prefs.LowPointsThreshold or 0,
            },
        }

    @staticmethod
    def update_preferences_from_payload(
        prefs: NotificationPreferences, payload: Dict[str, Any]
    ) -> NotificationPreferences:
        bool_fields = [
            "PointChanges",
            "OrderConfirmations",
            "ApplicationUpdates",
            "TicketUpdates",
            "RefundWindowAlerts",
            "AccountStatusChanges",
            "SensitiveInfoResets",
            "EmailEnabled",
            "InAppEnabled",
        ]

        for field in bool_fields:
            json_key = field[0].lower() + field[1:]
            if json_key in payload:
                setattr(prefs, field, bool(payload[json_key]))

        low_points = payload.get("lowPoints")
        if isinstance(low_points, dict):
            if "enabled" in low_points:
                prefs.LowPointsAlertEnabled = bool(low_points["enabled"])
            if "threshold" in low_points:
                try:
                    threshold = int(low_points["threshold"])
                    prefs.LowPointsThreshold = max(0, threshold)
                except (TypeError, ValueError):
                    pass

        quiet_hours = payload.get("quietHours")
        if isinstance(quiet_hours, dict):
            if "enabled" in quiet_hours:
                prefs.QuietHoursEnabled = bool(quiet_hours["enabled"])

            def _parse_time(value: str):
                if not value:
                    return None
                value = value.strip()
                fmt = "%H:%M:%S" if len(value.split(":")) == 3 else "%H:%M"
                return datetime.strptime(value, fmt).time()

            try:
                if quiet_hours.get("start"):
                    prefs.QuietHoursStart = _parse_time(quiet_hours["start"])
                if quiet_hours.get("end"):
                    prefs.QuietHoursEnd = _parse_time(quiet_hours["end"])
            except (ValueError, TypeError):
                current_app.logger.warning("Invalid quiet hours payload: %s", quiet_hours)

        db.session.commit()
        return prefs

