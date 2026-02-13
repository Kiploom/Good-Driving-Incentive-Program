import os
import sys
import uuid

# Ensure app package importable (conftest adds flask to path, but keep for direct runs)
TESTS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
FLASK_DIR = os.path.join(PROJECT_ROOT, "flask")
if FLASK_DIR not in sys.path:
    sys.path.insert(0, FLASK_DIR)

import pytest
from flask import Flask

from app.extensions import db
from app.models import (
    Achievement,
    Account,
    AccountType,
    Driver,
    DriverAchievement,
    DriverSponsor,
    Sponsor,
    SponsorCompany,
)
from app.services.achievement_service import AchievementService


@pytest.fixture(scope="function")
def app_context():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    with app.app_context():
        db.create_all()

        # Seed account types required by foreign keys
        driver_type = AccountType(
            AccountTypeID=str(uuid.uuid4()),
            AccountTypeCode='DRIVER',
        )
        db.session.add(driver_type)
        sponsor_type = AccountType(
            AccountTypeID=str(uuid.uuid4()),
            AccountTypeCode='SPONSOR',
        )
        db.session.add(sponsor_type)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


def _create_driver(points: int = 0) -> Driver:
    account = Account(
        AccountID=str(uuid.uuid4()),
        AccountTypeID=AccountType.query.filter_by(AccountTypeCode='DRIVER').first().AccountTypeID,
        Username=f"driver_{uuid.uuid4().hex[:6]}",
        AccountType='DRIVER',
        Email=f"driver_{uuid.uuid4().hex[:6]}@example.com",
        PasswordHash='hash',
        Status='A',
    )
    db.session.add(account)
    db.session.flush()

    driver = Driver(
        DriverID=str(uuid.uuid4()),
        AccountID=account.AccountID,
        Status='ACTIVE',
    )
    db.session.add(driver)
    db.session.flush()

    sponsor_company = SponsorCompany(
        SponsorCompanyID=str(uuid.uuid4()),
        CompanyName=f"SponsorCo_{uuid.uuid4().hex[:6]}",
    )
    db.session.add(sponsor_company)
    db.session.flush()

    driver.SponsorCompanyID = sponsor_company.SponsorCompanyID

    sponsor_account = Account(
        AccountID=str(uuid.uuid4()),
        AccountTypeID=AccountType.query.filter_by(AccountTypeCode='SPONSOR').first().AccountTypeID,
        Username=f"sponsor_{uuid.uuid4().hex[:6]}",
        AccountType='SPONSOR',
        Email=f"sponsor_{uuid.uuid4().hex[:6]}@example.com",
        PasswordHash='hash',
        Status='A',
    )
    db.session.add(sponsor_account)
    db.session.flush()

    sponsor = Sponsor(
        SponsorID=str(uuid.uuid4()),
        AccountID=sponsor_account.AccountID,
        Company=sponsor_company.CompanyName,
        SponsorCompanyID=sponsor_company.SponsorCompanyID,
    )
    db.session.add(sponsor)
    db.session.flush()

    sponsor_link = DriverSponsor(
        DriverSponsorID=str(uuid.uuid4()),
        DriverID=driver.DriverID,
        SponsorID=sponsor.SponsorID,
        SponsorCompanyID=sponsor_company.SponsorCompanyID,
        PointsBalance=points,
        Status='ACTIVE',
    )
    db.session.add(sponsor_link)
    db.session.commit()
    return driver


def _create_achievement(code: str, threshold: int | None, is_points: bool) -> Achievement:
    achievement = Achievement(
        AchievementID=str(uuid.uuid4()),
        Code=code,
        Title=code.replace('_', ' ').title(),
        Description=f"Requirement for {code}",
        PointsThreshold=threshold,
        IsPointsBased=is_points,
        IsActive=True,
    )
    db.session.add(achievement)
    db.session.commit()
    return achievement


def test_points_based_achievement_is_awarded(app_context):
    driver = _create_driver(points=600)
    achv = _create_achievement("rookie_earner_1", 500, True)

    statuses = AchievementService.evaluate_driver_achievements(driver)
    db.session.commit()

    assert any(s.achievement.AchievementID == achv.AchievementID and s.is_earned for s in statuses)

    record = DriverAchievement.query.filter_by(DriverID=driver.DriverID, AchievementID=achv.AchievementID).first()
    assert record is not None
    assert record.IsEarned is True
    assert record.EarnedAt is not None


def test_non_points_achievement_remains_locked(app_context):
    driver = _create_driver(points=10000)
    achv = _create_achievement("future_goal", None, False)

    statuses = AchievementService.evaluate_driver_achievements(driver)
    db.session.commit()

    entry = next(s for s in statuses if s.achievement.AchievementID == achv.AchievementID)
    assert entry.is_earned is False
    assert entry.earned_at is None


def test_multiple_achievements_handles_mixed_thresholds(app_context):
    driver = _create_driver(points=12000)
    early = _create_achievement("early_goal", 1000, True)
    mid = _create_achievement("mid_goal", 5000, True)
    high = _create_achievement("high_goal", 20000, True)

    statuses = AchievementService.evaluate_driver_achievements(driver)
    db.session.commit()

    earned_ids = {s.achievement.AchievementID for s in statuses if s.is_earned}
    assert early.AchievementID in earned_ids
    assert mid.AchievementID in earned_ids
    assert high.AchievementID not in earned_ids
