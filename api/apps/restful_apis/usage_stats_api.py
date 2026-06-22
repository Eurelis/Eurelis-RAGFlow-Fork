# Eurelis — Endpoint de statistiques de consommation pour l'utilisateur courant.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

from datetime import date, timedelta

from quart import request

from api.apps import current_user, login_required
from api.db.services.usage_log_service import UsageLogService
from api.utils.api_utils import get_data_error_result, get_json_result, server_error_response


def _today() -> str:
    return date.today().isoformat()


def _month_start() -> str:
    return date.today().replace(day=1).isoformat()


def _week_start() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def _year_ago() -> str:
    today = date.today()
    return today.replace(year=today.year - 1).isoformat()


def _parse_source(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    parts = [s.strip() for s in raw.split(",") if s.strip()]
    return parts or None


@manager.route('/usage-stats/me/sources', methods=['GET'])  # noqa: F821
@login_required
async def usage_stats_me_sources():
    try:
        sources = UsageLogService.available_sources()
        types = UsageLogService.available_types()
        return get_json_result(data={"sources": sources, "types": types})
    except Exception as e:
        return server_error_response(e)


@manager.route('/usage-stats/me/timeseries', methods=['GET'])  # noqa: F821
@login_required
async def usage_stats_me_timeseries():
    try:
        from_date = request.args.get("from_date", _month_start())
        to_date = request.args.get("to_date", _today())
        granularity = request.args.get("granularity") or None
        source = _parse_source(request.args.get("source"))
        token_type = _parse_source(request.args.get("type"))
        by_source = request.args.get("by_source", "false").lower() == "true"
        by_type = request.args.get("by_type", "false").lower() == "true"
        user_id = current_user.id

        if by_type:
            result = UsageLogService.stats_timeseries_by_token_type(from_date, to_date, granularity, user_id, source)
        elif by_source:
            result = UsageLogService.stats_timeseries_by_source(from_date, to_date, granularity, user_id, source, token_type)
        else:
            result = UsageLogService.stats_timeseries(from_date, to_date, granularity, user_id, source, token_type)
        return get_json_result(data=result)
    except Exception as e:
        return server_error_response(e)


@manager.route('/usage-stats/me/session/<session_id>', methods=['GET'])  # noqa: F821
@login_required
async def usage_stats_me_session(session_id: str):
    try:
        result = UsageLogService.stats_for_session(current_user.id, session_id)
        if result is None:
            return get_data_error_result(message="Session not found or access denied")
        return get_json_result(data=result)
    except Exception as e:
        return server_error_response(e)


@manager.route('/usage-stats/me/ingestion', methods=['GET'])  # noqa: F821
@login_required
async def usage_stats_me_ingestion():
    try:
        from_date = request.args.get("from_date", _month_start())
        to_date = request.args.get("to_date", _today())
        user_id = current_user.id
        totals = UsageLogService.stats_ingestion_for_user(user_id, from_date, to_date)
        by_kb = UsageLogService.stats_ingestion_by_kb(user_id, from_date, to_date)
        return get_json_result(data={
            "period": {"from": from_date, "to": to_date},
            "totals": totals,
            "by_kb": by_kb,
        })
    except Exception as e:
        return server_error_response(e)


@manager.route('/usage-stats/me/breakdown', methods=['GET'])  # noqa: F821
@login_required
async def usage_stats_me_breakdown():
    try:
        from_date = request.args.get("from_date", _month_start())
        to_date = request.args.get("to_date", _today())
        group_by = request.args.get("group_by", "model")
        source = _parse_source(request.args.get("source"))
        token_type = _parse_source(request.args.get("type"))
        user_id = current_user.id

        if group_by in ("model", "provider"):
            items = UsageLogService.stats_by_model(from_date, to_date, user_id, source, token_type)
        elif group_by == "dialog":
            items = UsageLogService.stats_by_dialog(from_date, to_date, user_id, source, token_type)
        elif group_by == "type":
            items = UsageLogService.stats_by_token_type(from_date, to_date, user_id, source)
        else:
            items = UsageLogService.stats_by_source(from_date, to_date, user_id, token_type)

        return get_json_result(data={"group_by": group_by, "items": items})
    except Exception as e:
        return server_error_response(e)


@manager.route('/usage-stats/me', methods=['GET'])  # noqa: F821
@login_required
async def usage_stats_me():
    try:
        today = _today()
        from_date = request.args.get("from_date", _month_start())
        to_date = request.args.get("to_date", today)
        source = _parse_source(request.args.get("source"))
        token_type = _parse_source(request.args.get("type"))
        user_id = current_user.id

        totals = UsageLogService.stats_for_user(user_id, from_date, to_date, source=source, token_type=token_type)
        by_day = UsageLogService.stats_by_day(user_id, from_date, to_date, source=source, token_type=token_type)
        by_usage = UsageLogService.stats_by_usage(user_id, from_date, to_date, source=source, token_type=token_type)

        return get_json_result(data={
            "user_id": user_id,
            "email": current_user.email,
            "period": {"from": from_date, "to": to_date},
            "totals": totals,
            "by_day": by_day,
            "by_usage": by_usage,
        })
    except Exception as e:
        return server_error_response(e)
