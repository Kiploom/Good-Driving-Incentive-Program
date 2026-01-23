from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from sqlalchemy import or_, case
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import (
    ChallengeTemplate,
    Driver,
    DriverChallengeSubscription,
    DriverSponsor,
    Sponsor,
    SponsorChallenge,
)


ACTIVE_SUBSCRIPTION_STATUSES = {"subscribed"}
TERMINAL_STATUSES = {"completed", "expired", "removed"}


@dataclass
class SponsorChallengeDTO:
    challenge: SponsorChallenge
    availability: str


class ChallengeService:
    """Domain logic for sponsor challenges."""

    @staticmethod
    def list_templates(active_only: bool = True) -> List[ChallengeTemplate]:
        query = ChallengeTemplate.query
        if active_only:
            query = query.filter(ChallengeTemplate.IsActive.is_(True))
        return query.order_by(ChallengeTemplate.Title.asc()).all()

    @staticmethod
    def list_sponsor_challenges(sponsor: Sponsor) -> List[SponsorChallengeDTO]:
        ChallengeService.expire_outdated_challenges()
        now = datetime.utcnow()
        challenges = (
            SponsorChallenge.query
            .filter(SponsorChallenge.SponsorID == sponsor.SponsorID)
            .order_by(SponsorChallenge.CreatedAt.desc())
            .all()
        )

        dtos: List[SponsorChallengeDTO] = []
        for challenge in challenges:
            if not challenge.IsActive:
                availability = "deactivated"
            elif challenge.StartsAt and challenge.StartsAt > now:
                availability = "upcoming"
            elif challenge.ExpiresAt and challenge.ExpiresAt < now:
                availability = "expired"
            else:
                availability = "active"
            dtos.append(SponsorChallengeDTO(challenge=challenge, availability=availability))

        return dtos

    @staticmethod
    def get_challenge_for_sponsor(sponsor: Sponsor, challenge_id: str) -> Optional[SponsorChallenge]:
        return (
            SponsorChallenge.query
            .filter_by(SponsorID=sponsor.SponsorID, SponsorChallengeID=challenge_id)
            .first()
        )

    @staticmethod
    def create_sponsor_challenge(sponsor: Sponsor, payload: Dict) -> SponsorChallenge:
        template = None
        template_id = payload.get("template_id")
        if template_id:
            template = ChallengeTemplate.query.filter_by(ChallengeTemplateID=template_id, IsActive=True).first()
            if not template:
                raise ValueError("Template not found or inactive.")

        title = payload.get("title") or (template.Title if template else None)
        if not title:
            raise ValueError("Title is required (either provide or inherit from template).")

        description = payload.get("description") or (template.Description if template else None)
        reward_points = payload.get("reward_points")
        if reward_points is None:
            reward_points = template.DefaultRewardPoints if template else None
        if reward_points is not None:
            try:
                reward_points = int(reward_points)
            except (TypeError, ValueError):
                raise ValueError("Reward points must be an integer.")
        if reward_points is None:
            raise ValueError("Reward points are required.")

        is_optional_raw = payload.get("is_optional", True)
        if isinstance(is_optional_raw, str):
            is_optional = is_optional_raw.lower() in {"1", "true", "yes", "on"}
        else:
            is_optional = bool(is_optional_raw)
        starts_at = payload.get("starts_at")
        expires_at = payload.get("expires_at")

        challenge = SponsorChallenge(
            SponsorID=sponsor.SponsorID,
            ChallengeTemplateID=template.ChallengeTemplateID if template else None,
            Title=title,
            Description=description,
            RewardPoints=reward_points,
            IsOptional=is_optional,
            StartsAt=starts_at,
            ExpiresAt=expires_at,
        )

        db.session.add(challenge)
        db.session.flush()
        return challenge

    @staticmethod
    def update_sponsor_challenge(challenge: SponsorChallenge, updates: Dict) -> SponsorChallenge:
        allowed_fields = {
            "title": "Title",
            "description": "Description",
            "reward_points": "RewardPoints",
            "is_optional": "IsOptional",
            "starts_at": "StartsAt",
            "expires_at": "ExpiresAt",
        }

        for incoming_key, model_attr in allowed_fields.items():
            if incoming_key in updates:
                value = updates[incoming_key]
                if incoming_key == "reward_points" and value is not None:
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        raise ValueError("Reward points must be an integer.")
                if incoming_key == "is_optional" and value is not None:
                    if isinstance(value, str):
                        value = value.lower() in {"1", "true", "yes", "on"}
                    else:
                        value = bool(value)
                setattr(challenge, model_attr, value)

        db.session.flush()
        return challenge

    @staticmethod
    def deactivate_challenge(challenge: SponsorChallenge) -> SponsorChallenge:
        now = datetime.utcnow()
        challenge.IsActive = False
        if challenge.ExpiresAt is None:
            challenge.ExpiresAt = now
        ChallengeService._update_subscriptions_for_challenge(challenge, "removed")
        db.session.flush()
        return challenge

    @staticmethod
    def _update_subscriptions_for_challenge(challenge: SponsorChallenge, status: str) -> None:
        now = datetime.utcnow()
        subs = (
            challenge.subscriptions
            .filter(DriverChallengeSubscription.Status.in_(ACTIVE_SUBSCRIPTION_STATUSES))
            .all()
        )
        for sub in subs:
            sub.Status = status
            sub.UpdatedAt = now

    @staticmethod
    def expire_outdated_challenges() -> None:
        now = datetime.utcnow()
        expired = (
            SponsorChallenge.query
            .filter(
                SponsorChallenge.IsActive.is_(True),
                SponsorChallenge.ExpiresAt.isnot(None),
                SponsorChallenge.ExpiresAt < now,
            )
            .all()
        )
        for challenge in expired:
            ChallengeService._update_subscriptions_for_challenge(challenge, "expired")
            challenge.UpdatedAt = now
        if expired:
            db.session.flush()

    @staticmethod
    def get_driver_active_challenges(driver: Driver) -> List[Dict]:
        ChallengeService.expire_outdated_challenges()

        sponsor_links = DriverSponsor.query.filter_by(DriverID=driver.DriverID).all()
        sponsor_ids = [
            link.SponsorID
            for link in sponsor_links
            if (link.Status or "").upper() == "ACTIVE"
        ]
        if not sponsor_ids:
            return []

        now = datetime.utcnow()
        challenges = (
            SponsorChallenge.query
            .filter(
                SponsorChallenge.SponsorID.in_(sponsor_ids),
                SponsorChallenge.IsActive.is_(True),
                or_(SponsorChallenge.StartsAt.is_(None), SponsorChallenge.StartsAt <= now),
                or_(SponsorChallenge.ExpiresAt.is_(None), SponsorChallenge.ExpiresAt >= now),
            )
            .options(joinedload(SponsorChallenge.sponsor))
            .order_by(
                case(
                    (SponsorChallenge.ExpiresAt.is_(None), 1),
                    else_=0
                ),
                SponsorChallenge.ExpiresAt.asc(),
                SponsorChallenge.Title.asc()
            )
            .all()
        )

        challenge_ids = [ch.SponsorChallengeID for ch in challenges]
        subs = (
            DriverChallengeSubscription.query
            .filter(
                DriverChallengeSubscription.DriverID == driver.DriverID,
                DriverChallengeSubscription.SponsorChallengeID.in_(challenge_ids),
            )
            .all()
        )
        subs_by_challenge = {sub.SponsorChallengeID: sub for sub in subs}

        results: List[Dict] = []
        for challenge in challenges:
            sub = subs_by_challenge.get(challenge.SponsorChallengeID)
            results.append(
                {
                    "challenge_id": challenge.SponsorChallengeID,
                    "sponsor_id": challenge.SponsorID,
                    "sponsor_name": challenge.sponsor.Company if challenge.sponsor else None,
                    "title": challenge.Title,
                    "description": challenge.Description,
                    "reward_points": challenge.RewardPoints,
                    "is_optional": challenge.IsOptional,
                    "starts_at": challenge.StartsAt,
                    "expires_at": challenge.ExpiresAt,
                    "status": sub.Status if sub else None,
                }
            )
        return results

    @staticmethod
    def subscribe_driver_to_challenge(driver: Driver, challenge: SponsorChallenge) -> DriverChallengeSubscription:
        if not challenge.is_available:
            raise ValueError("Challenge is not available.")
        if not challenge.IsOptional:
            raise ValueError("Challenge is not optional.")

        sponsor_link = DriverSponsor.query.filter_by(
            DriverID=driver.DriverID,
            SponsorID=challenge.SponsorID,
        ).first()
        if not sponsor_link or (sponsor_link.Status or "").upper() != "ACTIVE":
            raise ValueError("Driver cannot join this challenge.")

        existing = DriverChallengeSubscription.query.filter_by(
            DriverID=driver.DriverID,
            SponsorChallengeID=challenge.SponsorChallengeID,
        ).first()

        now = datetime.utcnow()
        if existing:
            if existing.Status in TERMINAL_STATUSES:
                existing.Status = "subscribed"
            else:
                existing.Status = "subscribed"
            existing.SubscribedAt = existing.SubscribedAt or now
            existing.UpdatedAt = now
            db.session.flush()
            return existing

        subscription = DriverChallengeSubscription(
            DriverID=driver.DriverID,
            SponsorChallengeID=challenge.SponsorChallengeID,
            Status="subscribed",
            SubscribedAt=now,
            UpdatedAt=now,
        )
        db.session.add(subscription)
        db.session.flush()
        return subscription


