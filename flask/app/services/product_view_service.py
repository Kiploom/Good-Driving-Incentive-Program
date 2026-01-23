from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List

from sqlalchemy import func, and_

import uuid

from app.extensions import db
from app.models import DriverProductView, Products, Sponsor


@dataclass
class RecentProduct:
    external_item_id: str
    provider: str | None
    title: str | None
    image_url: str | None
    points: int | None
    price: float | None
    currency: str | None
    sponsor_id: str | None
    sponsor_name: str | None
    last_viewed: datetime
    product_id: str | None


class ProductViewService:
    """Service to record and fetch driver product views."""

    @staticmethod
    def record_view(
        *,
        driver_id: str,
        sponsor_id: str | None,
        external_item_id: str,
        provider: str | None,
        title: str | None,
        image_url: str | None,
        points: int | None,
        price: float | str | None,
        currency: str | None,
    ) -> None:
        if not driver_id or not external_item_id:
            return

        now = datetime.utcnow()

        points_value = None
        if points is not None:
            try:
                points_value = int(points)
            except (ValueError, TypeError):
                points_value = None

        price_decimal = None
        if price is not None:
            try:
                price_decimal = Decimal(str(price))
            except Exception:
                price_decimal = None

        product = None
        if external_item_id:
            product = Products.query.filter_by(ExternalItemID=external_item_id).first()
            if not product:
                product = Products(
                    ProductID=str(uuid.uuid4()),
                    ExternalItemID=external_item_id,
                    Title=title or f"Product {external_item_id}",
                    PointsPrice=points_value or 0,
                    PriceAmount=price_decimal,
                    Currency=currency,
                )
                db.session.add(product)
                db.session.flush()
            else:
                updated = False
                if title and product.Title != title:
                    product.Title = title
                    updated = True
                if points_value is not None and product.PointsPrice != points_value:
                    product.PointsPrice = points_value
                    updated = True
                if price_decimal is not None:
                    product.PriceAmount = price_decimal
                    updated = True
                    if currency:
                        product.Currency = currency
                if updated:
                    product.LastSyncedAt = now

        view = DriverProductView(
            DriverID=driver_id,
            ProductID=product.ProductID if product else None,
            SponsorID=sponsor_id,
            Provider=provider,
            ExternalItemID=external_item_id,
            ProductTitle=title,
            ImageURL=image_url,
            PointsSnapshot=points_value,
            PriceSnapshot=price_decimal,
            Currency=currency,
            ViewedAt=now,
            CreatedAt=now,
            UpdatedAt=now,
        )
        db.session.add(view)
        db.session.flush()

    @staticmethod
    def get_recent_products(driver_id: str, *, limit: int = 12, window_minutes: int = 30) -> List[RecentProduct]:
        if not driver_id:
            return []

        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)

        db.session.query(DriverProductView).filter(
            DriverProductView.DriverID == driver_id,
            DriverProductView.ViewedAt < cutoff,
        ).delete(synchronize_session=False)
        db.session.flush()

        subquery = (
            db.session.query(
                DriverProductView.ExternalItemID.label("external_item_id"),
                func.max(DriverProductView.ViewedAt).label("last_viewed")
            )
            .filter(
                DriverProductView.DriverID == driver_id,
                DriverProductView.ViewedAt >= cutoff,
            )
            .group_by(DriverProductView.ExternalItemID)
            .subquery()
        )

        if subquery is None:
            return []

        rows = (
            db.session.query(DriverProductView, subquery.c.last_viewed)
            .join(
                subquery,
                and_(
                    DriverProductView.ExternalItemID == subquery.c.external_item_id,
                    DriverProductView.ViewedAt == subquery.c.last_viewed,
                    DriverProductView.DriverID == driver_id,
                ),
            )
            .order_by(subquery.c.last_viewed.desc())
            .limit(limit)
            .all()
        )

        results: List[RecentProduct] = []
        sponsor_map: dict[str, str] = {}

        for view, last_viewed in rows:
            sponsor_name = None
            if view.SponsorID:
                sponsor_name = sponsor_map.get(view.SponsorID)
                if sponsor_name is None:
                    sponsor = Sponsor.query.filter_by(SponsorID=view.SponsorID).first()
                    sponsor_name = sponsor.Company if sponsor else None
                    if view.SponsorID and sponsor_name:
                        sponsor_map[view.SponsorID] = sponsor_name

            price_value = float(view.PriceSnapshot) if view.PriceSnapshot is not None else None

            results.append(
                RecentProduct(
                    external_item_id=view.ExternalItemID,
                    provider=view.Provider,
                    title=view.ProductTitle,
                    image_url=view.ImageURL,
                    points=view.PointsSnapshot,
                    price=price_value,
                    currency=view.Currency,
                    sponsor_id=view.SponsorID,
                    sponsor_name=sponsor_name,
                    last_viewed=last_viewed,
                    product_id=view.ProductID,
                )
            )

        return results


