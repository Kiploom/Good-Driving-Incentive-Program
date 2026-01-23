from __future__ import annotations

from typing import Any, Dict, Optional

from flask import session
from app.models import Account

ROLE_LABELS = {
    "DRIVER": "Driver",
    "SPONSOR": "Sponsor",
    "ADMIN": "Admin",
    "SYSTEM": "System",
    "UNKNOWN": "Unknown",
}


def _role_label(code: Optional[str]) -> str:
    if not code:
        return ROLE_LABELS["UNKNOWN"]
    upper = code.upper()
    return ROLE_LABELS.get(upper, upper.title())


def _resolve_account_role(account_id: Optional[str]) -> Optional[str]:
    if not account_id:
        return None
    account = Account.query.get(account_id)
    if not account:
        return None
    return (account.AccountType or "UNKNOWN").upper()


def derive_point_change_actor_metadata(initiator_account: Optional[Account]) -> Dict[str, Any]:
    """
    Produce metadata for a PointChange record based on the current initiator and any
    active impersonation context stored in the session.
    """
    actor_role_code = "SYSTEM"
    actor_label = ROLE_LABELS["SYSTEM"]

    if initiator_account:
        actor_role_code = (initiator_account.AccountType or "UNKNOWN").upper()
        actor_label = _role_label(actor_role_code)

    impersonator_account_id: Optional[str] = None
    impersonator_role_code: Optional[str] = None

    if session.get("impersonating"):
        # Admin impersonation takes precedence over sponsor impersonation markers
        impersonator_account_id = (
            session.get("original_admin_account_id")
            or session.get("original_sponsor_account_id")
        )

        impersonator_role_code = _resolve_account_role(impersonator_account_id)

        # If lookup failed but we know which marker was present, infer the role code
        if not impersonator_role_code and impersonator_account_id:
            if session.get("original_admin_account_id"):
                impersonator_role_code = "ADMIN"
            elif session.get("original_sponsor_account_id"):
                impersonator_role_code = "SPONSOR"

    if impersonator_role_code:
        impersonator_label = _role_label(impersonator_role_code)
        actor_label = f"{impersonator_label} → {actor_label} (Impersonation)"

    return {
        "actor_role_code": actor_role_code,
        "actor_label": actor_label,
        "impersonator_account_id": impersonator_account_id,
        "impersonator_role_code": impersonator_role_code,
    }


__all__ = ["derive_point_change_actor_metadata"]


