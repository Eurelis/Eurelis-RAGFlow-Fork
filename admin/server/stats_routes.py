# Eurelis — Routes Flask du tableau de bord admin stats (/api/v1/admin/stats/*).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

from flask import Blueprint, request
from flask_login import login_required

from auth import check_admin_auth
from responses import error_response, success_response
from api.db.services.usage_log_service import UsageLogService
from api.db.db_models import User

eurelis_stats_bp = Blueprint(
    "eurelis_stats", __name__, url_prefix="/api/v1/admin/stats"
)


def _resolve_emails(user_ids: list[str]) -> dict[str, str]:
    if not user_ids:
        return {}
    rows = User.select(User.id, User.email).where(User.id.in_(user_ids)).tuples()
    return {uid: email for uid, email in rows}


@eurelis_stats_bp.route("/sources", methods=["GET"])
@login_required
@check_admin_auth
def admin_stats_sources():
    try:
        sources = UsageLogService.available_sources()
        types = UsageLogService.available_types()
        return success_response({"sources": sources, "types": types})
    except Exception as e:
        return error_response(str(e), 500)


@eurelis_stats_bp.route("/users", methods=["GET"])
@login_required
@check_admin_auth
def admin_stats_users():
    try:
        from datetime import date, timedelta

        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()

        from_date = request.args.get("from_date", month_start)
        to_date = request.args.get("to_date", today)
        resource_id = request.args.get("resource_id") or None
        sort_by = request.args.get("sort_by", "tokens")
        limit = min(int(request.args.get("limit", 50)), 500)
        raw_source = request.args.get("source") or ""
        source = [s.strip() for s in raw_source.split(",") if s.strip()] or None
        raw_type = request.args.get("type") or ""
        token_type = [s.strip() for s in raw_type.split(",") if s.strip()] or None

        rows = UsageLogService.stats_all_users(
            from_date, to_date, resource_id, sort_by, limit, source, token_type
        )
        active = UsageLogService.active_users_count(from_date, to_date, source, token_type)

        email_map = _resolve_emails([r["user_id"] for r in rows])
        for row in rows:
            row["email"] = email_map.get(row["user_id"], row["user_id"])

        return success_response({"active_users": active, "users": rows})
    except Exception as e:
        return error_response(str(e), 500)


@eurelis_stats_bp.route("/users/<path:user_email>", methods=["GET"])
@login_required
@check_admin_auth
def admin_stats_user_detail(user_email):
    try:
        from datetime import date

        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()

        from_date = request.args.get("from_date", month_start)
        to_date = request.args.get("to_date", today)
        raw_source = request.args.get("source") or ""
        source = [s.strip() for s in raw_source.split(",") if s.strip()] or None
        raw_type = request.args.get("type") or ""
        token_type = [s.strip() for s in raw_type.split(",") if s.strip()] or None

        user = User.select(User.id, User.email).where(User.email == user_email).first()
        if not user:
            return error_response(f"User not found: {user_email}", 404)
        user_id = str(user.id)

        totals = UsageLogService.stats_for_user(user_id, from_date, to_date, source=source, token_type=token_type)
        by_day = UsageLogService.stats_by_day(user_id, from_date, to_date, source=source, token_type=token_type)
        by_usage = UsageLogService.stats_by_usage(user_id, from_date, to_date, source=source, token_type=token_type)

        return success_response({
            "user_id": user_id,
            "email": user.email,
            "period": {"from": from_date, "to": to_date},
            "totals": totals,
            "by_day": by_day,
            "by_usage": by_usage,
        })
    except Exception as e:
        return error_response(str(e), 500)


@eurelis_stats_bp.route("/timeseries", methods=["GET"])
@login_required
@check_admin_auth
def admin_stats_timeseries():
    try:
        from datetime import date

        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()

        from_date = request.args.get("from_date", month_start)
        to_date = request.args.get("to_date", today)
        granularity = request.args.get("granularity") or None
        user_id = request.args.get("user_id") or None
        raw_source = request.args.get("source") or ""
        source = [s.strip() for s in raw_source.split(",") if s.strip()] or None
        raw_type = request.args.get("type") or ""
        token_type = [s.strip() for s in raw_type.split(",") if s.strip()] or None
        by_source = request.args.get("by_source", "false").lower() == "true"
        by_type = request.args.get("by_type", "false").lower() == "true"

        if by_type:
            result = UsageLogService.stats_timeseries_by_token_type(
                from_date, to_date, granularity, user_id, source
            )
        elif by_source:
            result = UsageLogService.stats_timeseries_by_source(
                from_date, to_date, granularity, user_id, source, token_type
            )
        else:
            result = UsageLogService.stats_timeseries(
                from_date, to_date, granularity, user_id, source, token_type
            )
        return success_response(result)
    except Exception as e:
        return error_response(str(e), 500)


@eurelis_stats_bp.route("/breakdown", methods=["GET"])
@login_required
@check_admin_auth
def admin_stats_breakdown():
    try:
        from datetime import date

        today = date.today().isoformat()
        month_start = date.today().replace(day=1).isoformat()

        from_date = request.args.get("from_date", month_start)
        to_date = request.args.get("to_date", today)
        group_by = request.args.get("group_by", "source")
        user_id = request.args.get("user_id") or None
        raw_source = request.args.get("source") or ""
        source = [s.strip() for s in raw_source.split(",") if s.strip()] or None
        raw_type = request.args.get("type") or ""
        token_type = [s.strip() for s in raw_type.split(",") if s.strip()] or None

        if group_by in ("model", "provider"):
            items = UsageLogService.stats_by_model(from_date, to_date, user_id, source, token_type)
        elif group_by == "dialog":
            items = UsageLogService.stats_by_dialog(from_date, to_date, user_id, source, token_type)
        elif group_by == "type":
            items = UsageLogService.stats_by_token_type(from_date, to_date, user_id, source)
        else:
            items = UsageLogService.stats_by_source(from_date, to_date, user_id, token_type)

        return success_response({"group_by": group_by, "items": items})
    except Exception as e:
        return error_response(str(e), 500)
