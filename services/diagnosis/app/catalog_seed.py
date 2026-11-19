"""No reviewed agronomic package has been supplied for increment 4.

Use the existing reviewed administrative API when real approval is available.
The previous generated reviewer names and recommendations were not evidence.
"""
from sqlalchemy.orm import Session
from app.domain.models import Recommendation

REVIEWED_RECOMMENDATIONS: list[dict] = []


def seed_reviewed_recommendations(db: Session) -> list[Recommendation]:
    """Preserve existing data; never invent review or populate recommendations."""
    return []
