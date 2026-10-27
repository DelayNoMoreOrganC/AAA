"""Single case-visibility policy shared by HTTP, WebSocket and background jobs."""
from sqlalchemy import and_

from .models import Case, Role


def case_access_filter(user):
    within_org = Case.org_id == user.org_id
    return within_org if user.role == Role.admin else and_(within_org, Case.created_by == user.id)


def can_access_case(user, case):
    return bool(user and case and user.is_active and user.org_id == case.org_id
                and (user.role == Role.admin or case.created_by == user.id))
