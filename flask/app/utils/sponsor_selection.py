from __future__ import annotations

from typing import Optional

from app.models import Sponsor


def select_primary_sponsor_for_company(sponsor_company_id: str) -> Optional[Sponsor]:
    """
    Select the best Sponsor record to represent a SponsorCompany.

    Preference order:
    1. Sponsor users marked as admin
    2. Oldest sponsor account for the company
    """
    if not sponsor_company_id:
        return None

    return (
        Sponsor.query.filter_by(SponsorCompanyID=sponsor_company_id)
        .order_by(Sponsor.IsAdmin.desc(), Sponsor.CreatedAt.asc())
        .first()
    )

