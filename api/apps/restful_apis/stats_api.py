#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
from datetime import date, timedelta

from quart import request

from api.apps import current_user, login_required
from api.db.services.api_service import API4ConversationService
from api.db.services.usage_log_service import UsageLogService
from api.utils.api_utils import get_json_result, server_error_response


def _today() -> str:
    return date.today().isoformat()


def _month_start() -> str:
    return date.today().replace(day=1).isoformat()


def _week_start() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


# ---------------------------------------------------------------------------
# Upstream legacy endpoint — kept as-is
# ---------------------------------------------------------------------------


@manager.route("/system/stats", methods=["GET"])  # noqa: F821
@login_required
def stats():
    try:
        objs = API4ConversationService.stats(
            current_user.id,
            request.args.get(
                "from_date",
                (date.today() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")),
            request.args.get(
                "to_date",
                date.today().strftime("%Y-%m-%d %H:%M:%S")),
            "agent" if "canvas_id" in request.args else None)

        res = {"pv": [], "uv": [], "speed": [], "tokens": [], "round": [], "thumb_up": []}
        for obj in objs:
            dt = obj["dt"]
            res["pv"].append((dt, obj["pv"]))
            res["uv"].append((dt, obj["uv"]))
            res["speed"].append((dt, float(obj["tokens"]) / (float(obj["duration"]) + 0.1)))  # +0.1 to avoid division by zero
            res["tokens"].append((dt, float(obj["tokens"]) / 1000.0))  # convert to thousands
            res["round"].append((dt, obj["round"]))
            res["thumb_up"].append((dt, obj["thumb_up"]))
        return get_json_result(data=res)
    except Exception as e:
        return server_error_response(e)


# ---------------------------------------------------------------------------
# Étape 4 — user self-service stats
# ---------------------------------------------------------------------------

@manager.route('/stats/me', methods=['GET'])  # noqa: F821
@login_required
def stats_me():
    try:
        today = _today()
        from_date = request.args.get("from_date", _month_start())
        to_date = request.args.get("to_date", today)
        session_id = request.args.get("session_id")
        user_id = current_user.id

        period = UsageLogService.stats_for_user(user_id, from_date, to_date)
        today_stats = UsageLogService.stats_for_user(user_id, today, today)
        week_stats = UsageLogService.stats_for_user(user_id, _week_start(), today)

        result = {
            "user_id": user_id,
            "period": {"from": from_date, "to": to_date, **period},
            "today": today_stats,
            "this_week": week_stats,
        }
        if session_id:
            session_stats = UsageLogService.stats_for_user(
                user_id, "2000-01-01", today, object_id=session_id
            )
            result["current_session"] = {"session_id": session_id, **session_stats}

        return get_json_result(data=result)
    except Exception as e:
        return server_error_response(e)


