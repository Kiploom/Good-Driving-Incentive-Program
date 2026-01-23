from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List

from sqlalchemy import func

from app.extensions import db
from app.models import Achievement, Driver, DriverAchievement, DriverSponsor


@dataclass
class AchievementStatus:
    achievement: Achievement
    is_earned: bool
    earned_at: datetime | None


class AchievementService:
    """Encapsulate driver achievement evaluation logic."""

    @staticmethod
    def get_driver_total_points(driver: Driver) -> int:
        total = (
            db.session.query(func.coalesce(func.sum(DriverSponsor.PointsBalance), 0))
            .filter(DriverSponsor.DriverID == driver.DriverID)
            .scalar()
        )
        return int(total or 0)

    @staticmethod
    def evaluate_driver_achievements(driver: Driver) -> List[AchievementStatus]:
        total_points = AchievementService.get_driver_total_points(driver)
        achievements = Achievement.query.filter_by(IsActive=True).order_by(Achievement.Title.asc()).all()

        statuses: List[AchievementStatus] = []

        for achievement in achievements:
            driver_record = DriverAchievement.query.filter_by(
                DriverID=driver.DriverID,
                AchievementID=achievement.AchievementID,
            ).first()

            earned = False
            earned_at = None

            if achievement.IsPointsBased and achievement.PointsThreshold is not None:
                if total_points >= (achievement.PointsThreshold or 0):
                    earned = True
                    earned_at = driver_record.EarnedAt if driver_record and driver_record.IsEarned else datetime.utcnow()
                    if driver_record:
                        if not driver_record.IsEarned:
                            driver_record.IsEarned = True
                            driver_record.EarnedAt = earned_at
                            driver_record.UpdatedAt = datetime.utcnow()
                    else:
                        driver_record = DriverAchievement(
                            DriverID=driver.DriverID,
                            AchievementID=achievement.AchievementID,
                            IsEarned=True,
                            EarnedAt=earned_at,
                        )
                        db.session.add(driver_record)
                else:
                    earned = driver_record.IsEarned if driver_record else False
                    earned_at = driver_record.EarnedAt if driver_record else None
            else:
                # Non points achievements remain locked until future logic is implemented.
                earned = driver_record.IsEarned if driver_record else False
                earned_at = driver_record.EarnedAt if driver_record else None

            if not driver_record:
                # Ensure a placeholder exists for non-earned achievements to maintain history.
                driver_record = DriverAchievement(
                    DriverID=driver.DriverID,
                    AchievementID=achievement.AchievementID,
                    IsEarned=earned,
                    EarnedAt=earned_at,
                )
                db.session.add(driver_record)

            statuses.append(AchievementStatus(achievement=achievement, is_earned=earned, earned_at=earned_at))

        db.session.flush()
        return statuses


