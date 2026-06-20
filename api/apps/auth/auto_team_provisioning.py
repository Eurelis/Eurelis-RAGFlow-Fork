import logging

from admin.server.services import TenantMgr
from api.db.services import UserService

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
        TenantMgr.add_member(tenant_id, user_id, role="normal")
    except ValueError as exc:
        _logger.debug(
            "Skipping team assignment for user %s in tenant %s: %s",
            user_id, tenant_id, exc,
        )
    except Exception:
        _logger.warning(
            "Failed to assign user %s to tenant %s",
            user_id, tenant_id, exc_info=True,
        )
