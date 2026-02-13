import os
import sys
import uuid

# Ensure app package importable
TESTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
FLASK_DIR = os.path.join(PROJECT_ROOT, "flask")
if FLASK_DIR not in sys.path:
    sys.path.insert(0, FLASK_DIR)

import pytest
from flask import Flask

from app.extensions import db
from app.models import Account, Driver, DriverNotification
from app.services.driver_notification_service import DriverNotificationService


@pytest.fixture()
def app_context():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()
        driver = _create_driver()
        yield driver
        db.session.remove()
        db.drop_all()


def _create_driver():
    account = Account(
        AccountID=str(uuid.uuid4()),
        Username=f"driver_{uuid.uuid4().hex[:4]}",
        Email="driver@example.com",
        PasswordHash="hash",
    )
    db.session.add(account)
    db.session.flush()

    driver = Driver(
        DriverID=str(uuid.uuid4()),
        AccountID=account.AccountID,
        Status="ACTIVE",
    )
    db.session.add(driver)
    db.session.commit()
    return driver


def test_create_and_fetch_notifications(app_context):
    driver = app_context
    created = DriverNotificationService.create_notification(
        driver.DriverID,
        notif_type="points_change",
        title="Points Added",
        body="You received points",
        metadata={"points": 50},
        delivered_via="in_app,email",
    )
    assert created is not None
    notifications, total = DriverNotificationService.fetch_notifications(driver.DriverID)
    assert total == 1
    assert notifications[0].Title == "Points Added"
    assert notifications[0].Metadata["points"] == 50


def test_mark_notifications_read(app_context):
    driver = app_context
    for _ in range(2):
        DriverNotificationService.create_notification(
            driver.DriverID,
            notif_type="order",
            title="Order Update",
            body="Order shipped",
        )
    unread = DriverNotification.query.filter_by(IsRead=False).count()
    assert unread == 2
    first_id = DriverNotification.query.first().NotificationID
    updated = DriverNotificationService.mark_notifications_read(driver.DriverID, [first_id])
    assert updated == 1
    remaining = DriverNotification.query.filter_by(IsRead=False).count()
    assert remaining == 1
    DriverNotificationService.mark_notifications_read(driver.DriverID, None)
    assert DriverNotification.query.filter_by(IsRead=False).count() == 0


def test_serialize_notification_includes_sponsor_context(app_context):
    driver = app_context
    notif = DriverNotificationService.create_notification(
        driver.DriverID,
        notif_type="points_change",
        title="Points Added",
        body="Sponsor awarded points",
        metadata={
            "sponsorId": "s-123",
            "sponsorName": "Acme Logistics",
            "sponsorCompanyName": "Acme Holdings",
            "isSponsorSpecific": True,
        },
        delivered_via="in_app",
    )
    serialized = DriverNotificationService.serialize_notification(notif)
    assert serialized["sponsorContext"]["sponsorId"] == "s-123"
    assert serialized["sponsorContext"]["sponsorName"] == "Acme Logistics"
    assert serialized["sponsorContext"]["isSponsorSpecific"] is True
