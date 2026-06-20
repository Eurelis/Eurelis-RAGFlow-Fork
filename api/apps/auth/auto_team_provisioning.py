import logging
from datetime import datetime

from api.db import UserTenantRole
from api.db.services.user_service import UserService, UserTenantService
from common.constants import StatusEnum
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format

_logger = logging.getLogger(__name__)


def assign_default_teams(user_id: str, oauth_config: dict) -> None:
    """Assign the newly created user to teams listed in oauth_config['default_teams'].

    Each entry is the email address of the team owner. Errors are logged but
    never propagate — a misconfigured team must not block the login flow.
    """
    for owner_email in oauth_config.get("default_teams", []):
        owners = UserService.query(email=owner_email)
        if not owners:
            _logger.warning(
                "default_teams: no user found for email %r, skipping", owner_email
            )
            continue
        _safe_assign(tenant_id=owners[0].id, user_id=user_id)


def _safe_assign(tenant_id: str, user_id: str) -> None:
    try:
        existing = UserTenantService.filter_by_tenant_and_user_id(tenant_id, user_id)
        if existing and existing.status == StatusEnum.VALID.value:
            _logger.debug(
                "User %s is already a member of tenant %s, skipping", user_id, tenant_id
            )
            return
        now = current_timestamp()
        UserTenantService.save(
            id=get_uuid(),
            user_id=user_id,
            tenant_id=tenant_id,
            role=UserTenantRole.NORMAL.value,
            invited_by=tenant_id,
            status=StatusEnum.VALID.value,
            create_time=now,
            create_date=datetime_format(datetime.now()),
            update_time=now,
            update_date=datetime_format(datetime.now()),
        )
        _logger.info("Assigned user %s to tenant %s", user_id, tenant_id)
    except Exception:
        _logger.warning(
            "Failed to assign user %s to tenant %s", user_id, tenant_id, exc_info=True
        )
