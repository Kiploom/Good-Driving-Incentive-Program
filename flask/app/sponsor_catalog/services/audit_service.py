# app/sponsor_catalog/services/audit_service.py
from app.extensions import db
from app.models import SponsorAuditLog
from flask import current_app

def log(sponsor_id: str, action: str, actor_user_id: str | None, details: dict | None = None) -> None:
    try:
        row = SponsorAuditLog(
            SponsorID=sponsor_id,          # <-- use actual column name
            Action=action,                 # <-- actual column name
            ActorUserID=actor_user_id,     # <-- actual column name
            DetailsJSON=(details or {}),   # <-- actual column name
        )
        db.session.add(row)
        db.session.commit()
    except Exception as e:
        # Rollback on error and re-raise so caller can handle it
        db.session.rollback()
        current_app.logger.error(f"Failed to write audit log: {e}", exc_info=True)
        raise