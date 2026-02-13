# app/sponsor_catalog/services/cache_service.py
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import SponsorCatalogResultCache

TTL_SECONDS = 60 * 15  # 15 minutes


def _canonical_json(data: dict) -> str:
    """Stable JSON string for hashing (sort keys, no whitespace)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def fingerprint(payload: dict) -> str:
    """
    Create a stable hash for a cache key based on payload.
    Example payload in preview: {"merged": <rules>, "page": int, "sort": str}
    """
    s = _canonical_json(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def get_cached(sponsor_id: str, fingerprint: str, page: int, sort: str) -> dict | None:
    row = (
        SponsorCatalogResultCache.query
        .filter_by(sponsor_id=sponsor_id, filter_fingerprint=fingerprint, page=page, sort=sort)
        .first()
    )
    if not row:
        return None

    now = datetime.now(timezone.utc)
    # If DB stored naive timestamps, coerce to aware for comparison
    expires = row.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires and expires < now:
        try:
            db.session.delete(row)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return None

    return row.results_json


def set_cached(sponsor_id: str, fingerprint: str, page: int, sort: str, payload: dict) -> None:
    expires = datetime.now(timezone.utc) + timedelta(seconds=TTL_SECONDS)

    row = (
        SponsorCatalogResultCache.query
        .filter_by(sponsor_id=sponsor_id, filter_fingerprint=fingerprint, page=page, sort=sort)
        .first()
    )
    if row:
        row.results_json = payload
        row.expires_at = expires
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
    else:
        row = SponsorCatalogResultCache(
            sponsor_id=sponsor_id,
            filter_fingerprint=fingerprint,
            page=page,
            sort=sort,
            results_json=payload,
            expires_at=expires,
        )
        db.session.add(row)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            # Handle race condition: if another request inserted the same cache entry,
            # try to update the existing row instead
            existing_row = (
                SponsorCatalogResultCache.query
                .filter_by(sponsor_id=sponsor_id, filter_fingerprint=fingerprint, page=page, sort=sort)
                .first()
            )
            if existing_row:
                existing_row.results_json = payload
                existing_row.expires_at = expires
                db.session.commit()
            else:
                raise
        except Exception:
            db.session.rollback()
            raise


def purge_cache_for_sponsor(sponsor_id: str) -> int:
    q = SponsorCatalogResultCache.query.filter_by(sponsor_id=sponsor_id)
    count = q.count()
    if count:
        q.delete(synchronize_session=False)
        db.session.commit()
    return count
