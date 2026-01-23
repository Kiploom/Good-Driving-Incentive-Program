import uuid
from datetime import datetime, timedelta

import os
import sys

import pytest
from flask import Flask

# Ensure app package importable when running tests directly from this directory
TESTS_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.abspath(os.path.join(TESTS_DIR, ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.extensions import db
from app.models import (
    Account,
    AccountType,
    Driver,
    DriverChallengeSubscription,
    DriverSponsor,
    Sponsor,
    SponsorChallenge,
    SponsorCompany,
)
from app.services.challenge_service import ChallengeService


ACCOUNT_TYPE_IDS = {}


@pytest.fixture
def app_context():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Seed required account types for foreign keys
        for code in ('DRIVER', 'SPONSOR'):
            acct_type = AccountType(
                AccountTypeID=str(uuid.uuid4()),
                AccountTypeCode=code,
            )
            db.session.add(acct_type)
            ACCOUNT_TYPE_IDS[code] = acct_type.AccountTypeID
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def _create_account(account_type: str) -> Account:
    account = Account(
        AccountID=str(uuid.uuid4()),
        AccountTypeID=ACCOUNT_TYPE_IDS[account_type],
        Username=f"user_{uuid.uuid4().hex[:8]}",
        AccountType=account_type,
        Email=f"{uuid.uuid4().hex[:8]}@example.com",
        PasswordHash="hash",
        Status='A',
    )
    db.session.add(account)
    return account


def _create_sponsor(company: str) -> Sponsor:
    account = _create_account('SPONSOR')
    sponsor_company = SponsorCompany(
        SponsorCompanyID=str(uuid.uuid4()),
        CompanyName=company,
    )
    db.session.add(sponsor_company)
    db.session.flush()
    sponsor = Sponsor(
        SponsorID=str(uuid.uuid4()),
        AccountID=account.AccountID,
        Company=company,
        SponsorCompanyID=sponsor_company.SponsorCompanyID,
    )
    db.session.add(sponsor)
    return sponsor


def _create_driver() -> Driver:
    account = _create_account('DRIVER')
    driver = Driver(
        DriverID=str(uuid.uuid4()),
        AccountID=account.AccountID,
        Status='ACTIVE',
    )
    db.session.add(driver)
    return driver


def _link_driver_sponsor(driver: Driver, sponsor: Sponsor) -> DriverSponsor:
    if not driver.SponsorCompanyID:
        driver.SponsorCompanyID = sponsor.SponsorCompanyID

    link = DriverSponsor(
        DriverSponsorID=str(uuid.uuid4()),
        DriverID=driver.DriverID,
        SponsorID=sponsor.SponsorID,
        SponsorCompanyID=sponsor.SponsorCompanyID,
        Status='ACTIVE',
    )
    db.session.add(link)
    return link


def test_driver_sees_challenges_from_all_sponsors(app_context):
    with app_context.app_context():
        driver = _create_driver()
        sponsor_a = _create_sponsor('Alpha Logistics')
        sponsor_b = _create_sponsor('Bravo Freight')
        _link_driver_sponsor(driver, sponsor_a)
        _link_driver_sponsor(driver, sponsor_b)

        challenge_a = SponsorChallenge(
            SponsorChallengeID=str(uuid.uuid4()),
            SponsorID=sponsor_a.SponsorID,
            Title='Alpha Bonus',
            RewardPoints=500,
            IsOptional=True,
            IsActive=True,
        )
        challenge_b = SponsorChallenge(
            SponsorChallengeID=str(uuid.uuid4()),
            SponsorID=sponsor_b.SponsorID,
            Title='Bravo Mileage',
            RewardPoints=750,
            IsOptional=True,
            IsActive=True,
        )
        db.session.add_all([challenge_a, challenge_b])
        db.session.commit()

        results = ChallengeService.get_driver_active_challenges(driver)
        assert len(results) == 2
        sponsors = {row['sponsor_name'] for row in results}
        assert sponsors == {'Alpha Logistics', 'Bravo Freight'}


def test_deactivate_challenge_updates_subscriptions(app_context):
    with app_context.app_context():
        driver = _create_driver()
        sponsor = _create_sponsor('Sunrise Carriers')
        _link_driver_sponsor(driver, sponsor)

        challenge = SponsorChallenge(
            SponsorChallengeID=str(uuid.uuid4()),
            SponsorID=sponsor.SponsorID,
            Title='On-Time Week',
            RewardPoints=300,
            IsOptional=True,
            IsActive=True,
        )
        db.session.add(challenge)
        db.session.commit()

        subscription = ChallengeService.subscribe_driver_to_challenge(driver, challenge)
        db.session.commit()
        assert subscription.Status == 'subscribed'

        ChallengeService.deactivate_challenge(challenge)
        db.session.commit()

        refreshed = DriverChallengeSubscription.query.get(subscription.DriverChallengeSubscriptionID)
        assert refreshed.Status == 'removed'
        assert not challenge.IsActive


def test_expired_challenge_marks_subscription(app_context):
    with app_context.app_context():
        driver = _create_driver()
        sponsor = _create_sponsor('Horizon Logistics')
        _link_driver_sponsor(driver, sponsor)

        future_expiration = datetime.utcnow() + timedelta(days=1)
        challenge = SponsorChallenge(
            SponsorChallengeID=str(uuid.uuid4()),
            SponsorID=sponsor.SponsorID,
            Title='Fuel Smart',
            RewardPoints=400,
            IsOptional=True,
            IsActive=True,
            ExpiresAt=future_expiration,
        )
        db.session.add(challenge)
        db.session.commit()

        subscription = ChallengeService.subscribe_driver_to_challenge(driver, challenge)
        db.session.commit()
        assert subscription.Status == 'subscribed'

        # Simulate expiration
        challenge.ExpiresAt = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        results = ChallengeService.get_driver_active_challenges(driver)
        db.session.commit()

        assert results == []
        refreshed = DriverChallengeSubscription.query.get(subscription.DriverChallengeSubscriptionID)
        assert refreshed.Status == 'expired'

