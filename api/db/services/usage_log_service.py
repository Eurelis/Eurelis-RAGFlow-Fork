# Eurelis — Service d'analytics sur la table usage_log (append-only).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import datetime
import logging
from decimal import Decimal

import peewee

from api.db.db_models import DB, UsageLog
from api.db.services.common_service import CommonService

logger = logging.getLogger(__name__)


def _int(v) -> int:
    """MySQL SUM/COUNT return Decimal or int — cast to plain int for JSON safety."""
    return int(v) if v is not None else 0


def _float(v) -> float:
    """MySQL AVG returns Decimal — cast to float for JSON safety."""
    return float(v) if v is not None else 0.0


def _filter_source(q, source, field):
    """Apply source filter accepting a single str or a list[str]."""
    if not source:
        return q
    if isinstance(source, list):
        return q.where(field.in_(source))
    return q.where(field == source)


def _filter_type(q, token_type, field):
    """Apply token_type filter accepting a single str or a list[str]."""
    if not token_type:
        return q
    if isinstance(token_type, list):
        return q.where(field.in_(token_type))
    return q.where(field == token_type)


def _period(v) -> str:
    """MySQL DATE() returns datetime.date — convert to ISO string."""
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return str(v) if v is not None else ""

# Granularity expressions for GROUP BY time period.
# Each lambda receives the create_date field and returns a Peewee SQL expression.
_GRANULARITY_FN = {
    "day":   lambda f: peewee.fn.DATE(f),                        # YYYY-MM-DD
    "week":  lambda f: peewee.fn.DATE_FORMAT(f, "%Y-%u"),        # YYYY-WW
    "month": lambda f: peewee.fn.DATE_FORMAT(f, "%Y-%m"),        # YYYY-MM
}

_VALID_SORT = {"tokens", "sessions", "avg_duration_ms"}


def _auto_granularity(from_date: str, to_date: str) -> str:
    """Pick day/week/month based on the width of the requested window."""
    from datetime import date
    try:
        delta = (date.fromisoformat(to_date) - date.fromisoformat(from_date)).days
    except ValueError:
        return "day"
    if delta <= 31:
        return "day"
    if delta <= 365:
        return "week"
    return "month"


class UsageLogService(CommonService):
    model = UsageLog

    @classmethod
    @DB.connection_context()
    def log(cls, *, user_id: str, resource_id: str, object_id: str,
            source: str = "chat", token_type: str = "llm", tokens: int = 0, duration: float = 0.0,
            model: str = "", provider: str = "") -> None:
        if not tokens and not duration:
            return
        try:
            cls.insert(
                user_id=user_id,
                resource_id=resource_id,
                object_id=object_id,
                source=source,
                token_type=token_type,
                tokens=tokens,
                duration=duration,
                model=model,
                provider=provider,
            )
        except Exception:
            logger.exception(
                "Failed to write usage_log: user_id=%s resource_id=%s object_id=%s source=%s token_type=%s tokens=%d model=%s",
                user_id, resource_id, object_id, source, token_type, tokens, model,
            )

    # ------------------------------------------------------------------
    # Single-user aggregates
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def stats_for_user(
        cls,
        user_id: str,
        from_date: str,
        to_date: str,
        resource_id: str | None = None,
        object_id: str | None = None,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> dict:
        """Aggregate tokens/duration/sessions for a single user over a period."""
        q = (
            cls.model
            .select(
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
                peewee.fn.COALESCE(
                    peewee.fn.AVG(peewee.fn.NULLIF(cls.model.duration, 0)), 0.0
                ).alias("avg_duration_ms"),
            )
            .where(
                cls.model.user_id == user_id,
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
        )
        if resource_id:
            q = q.where(cls.model.resource_id == resource_id)
        if object_id:
            q = q.where(cls.model.object_id == object_id)
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        row = q.dicts().first() or {}
        return {
            "sessions": _int(row.get("sessions")),
            "tokens": _int(row.get("tokens")),
            "avg_duration_ms": round(_float(row.get("avg_duration_ms")), 1),
        }

    @classmethod
    @DB.connection_context()
    def stats_by_day(
        cls,
        user_id: str,
        from_date: str,
        to_date: str,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> list[dict]:
        """Daily breakdown for a single user."""
        q = (
            cls.model
            .select(
                peewee.fn.DATE(cls.model.create_date).alias("date"),
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                cls.model.user_id == user_id,
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(peewee.SQL("date"))
            .order_by(peewee.SQL("date"))
        )
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())
        for row in rows:
            row["date"] = _period(row.get("date"))
            row["tokens"] = _int(row.get("tokens"))
        return rows

    # ------------------------------------------------------------------
    # Admin aggregates — all users
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def stats_all_users(
        cls,
        from_date: str,
        to_date: str,
        resource_id: str | None = None,
        sort_by: str = "tokens",
        limit: int = 50,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> list[dict]:
        """Aggregate per user_id over a period, enriched with active_users count and sources list."""
        if sort_by not in _VALID_SORT:
            sort_by = "tokens"
        q = (
            cls.model
            .select(
                cls.model.user_id,
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
                peewee.fn.COALESCE(
                    peewee.fn.AVG(peewee.fn.NULLIF(cls.model.duration, 0)), 0.0
                ).alias("avg_duration_ms"),
                peewee.fn.GROUP_CONCAT(cls.model.source.distinct()).alias("sources_raw"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(cls.model.user_id)
            .order_by(peewee.SQL(sort_by).desc())
            .limit(limit)
        )
        if resource_id:
            q = q.where(cls.model.resource_id == resource_id)
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())
        for row in rows:
            raw = row.pop("sources_raw", "") or ""
            row["sources"] = [s for s in raw.split(",") if s]
            row["tokens"] = _int(row.get("tokens"))
            row["avg_duration_ms"] = round(_float(row.get("avg_duration_ms")), 1)
        return rows

    @classmethod
    @DB.connection_context()
    def active_users_count(
        cls,
        from_date: str,
        to_date: str,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> int:
        """Count distinct users active over the period."""
        q = (
            cls.model
            .select(peewee.fn.COUNT(cls.model.user_id.distinct()))
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
        )
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        return q.scalar() or 0

    # ------------------------------------------------------------------
    # Time series — dashboard main chart
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def stats_timeseries(
        cls,
        from_date: str,
        to_date: str,
        granularity: str | None = None,
        user_id: str | None = None,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> dict:
        """Time series of sessions and tokens grouped by day/week/month.

        Returns {"granularity": str, "series": [{"period": str, "sessions": int, "tokens": int}]}.
        granularity defaults to auto-detection based on the date window.
        """
        gran = granularity if granularity in _GRANULARITY_FN else _auto_granularity(from_date, to_date)
        period_expr = _GRANULARITY_FN[gran](cls.model.create_date)
        q = (
            cls.model
            .select(
                period_expr.alias("period"),
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(peewee.SQL("period"))
            .order_by(peewee.SQL("period"))
        )
        if user_id:
            q = q.where(cls.model.user_id == user_id)
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())
        for row in rows:
            row["period"] = _period(row.get("period"))
            row["sessions"] = _int(row.get("sessions"))
            row["tokens"] = _int(row.get("tokens"))
        return {"granularity": gran, "series": rows}

    @classmethod
    @DB.connection_context()
    def stats_timeseries_by_source(
        cls,
        from_date: str,
        to_date: str,
        granularity: str | None = None,
        user_id: str | None = None,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> dict:
        """Time series of tokens grouped by (period, source).

        Returns {"granularity": str, "series": [{"period": str, "source": str, "tokens": int}]}.
        """
        gran = granularity if granularity in _GRANULARITY_FN else _auto_granularity(from_date, to_date)
        period_expr = _GRANULARITY_FN[gran](cls.model.create_date)
        q = (
            cls.model
            .select(
                period_expr.alias("period"),
                cls.model.source,
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(peewee.SQL("period"), cls.model.source)
            .order_by(peewee.SQL("period"), cls.model.source)
        )
        if user_id:
            q = q.where(cls.model.user_id == user_id)
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())
        for row in rows:
            row["period"] = _period(row.get("period"))
            row["tokens"] = _int(row.get("tokens"))
        return {"granularity": gran, "series": rows}

    # ------------------------------------------------------------------
    # Breakdowns — source and model
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def stats_by_source(
        cls,
        from_date: str,
        to_date: str,
        user_id: str | None = None,
        token_type: str | list[str] | None = None,
    ) -> list[dict]:
        """Breakdown by source flow (chat/search/agent/ingestion) with pct_tokens."""
        q = (
            cls.model
            .select(
                cls.model.source.alias("label"),
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(cls.model.source)
            .order_by(peewee.SQL("tokens").desc())
        )
        if user_id:
            q = q.where(cls.model.user_id == user_id)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())
        for r in rows:
            r["tokens"] = _int(r.get("tokens"))
        total = sum(r["tokens"] for r in rows) or 1
        for r in rows:
            r["pct_tokens"] = round(r["tokens"] / total * 100, 1)
        return rows

    @classmethod
    @DB.connection_context()
    def stats_by_token_type(
        cls,
        from_date: str,
        to_date: str,
        user_id: str | None = None,
        source: str | list[str] | None = None,
    ) -> list[dict]:
        """Breakdown by token_type (llm/embedding) with pct_tokens."""
        q = (
            cls.model
            .select(
                cls.model.token_type.alias("label"),
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(cls.model.token_type)
            .order_by(peewee.SQL("tokens").desc())
        )
        if user_id:
            q = q.where(cls.model.user_id == user_id)
        q = _filter_source(q, source, cls.model.source)
        rows = list(q.dicts())
        for r in rows:
            r["tokens"] = _int(r.get("tokens"))
        total = sum(r["tokens"] for r in rows) or 1
        for r in rows:
            r["pct_tokens"] = round(r["tokens"] / total * 100, 1)
        return rows

    @classmethod
    @DB.connection_context()
    def stats_timeseries_by_token_type(
        cls,
        from_date: str,
        to_date: str,
        granularity: str | None = None,
        user_id: str | None = None,
        source: str | list[str] | None = None,
    ) -> dict:
        """Time series of tokens grouped by (period, token_type).

        Returns {"granularity": str, "series": [{"period": str, "token_type": str, "tokens": int}]}.
        """
        gran = granularity if granularity in _GRANULARITY_FN else _auto_granularity(from_date, to_date)
        period_expr = _GRANULARITY_FN[gran](cls.model.create_date)
        q = (
            cls.model
            .select(
                period_expr.alias("period"),
                cls.model.token_type,
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(peewee.SQL("period"), cls.model.token_type)
            .order_by(peewee.SQL("period"), cls.model.token_type)
        )
        if user_id:
            q = q.where(cls.model.user_id == user_id)
        q = _filter_source(q, source, cls.model.source)
        rows = list(q.dicts())
        for row in rows:
            row["period"] = _period(row.get("period"))
            row["tokens"] = _int(row.get("tokens"))
        return {"granularity": gran, "series": rows}

    @classmethod
    @DB.connection_context()
    def stats_by_model(
        cls,
        from_date: str,
        to_date: str,
        user_id: str | None = None,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> list[dict]:
        """Breakdown by model + provider with pct_tokens."""
        q = (
            cls.model
            .select(
                cls.model.model.alias("label"),
                cls.model.provider,
                cls.model.token_type,
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
                cls.model.model != "",
            )
            .group_by(cls.model.model, cls.model.provider, cls.model.token_type)
            .order_by(peewee.SQL("tokens").desc())
        )
        if user_id:
            q = q.where(cls.model.user_id == user_id)
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())
        for r in rows:
            r["tokens"] = _int(r.get("tokens"))
        total = sum(r["tokens"] for r in rows) or 1
        for r in rows:
            r["pct_tokens"] = round(r["tokens"] / total * 100, 1)
        return rows

    # ------------------------------------------------------------------
    # Per-dialog breakdown — admin overview (all users)
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def stats_by_dialog(
        cls,
        from_date: str,
        to_date: str,
        user_id: str | None = None,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Breakdown by resource_id across all users, enriched with dialog/canvas name."""
        from api.db.db_models import Dialog

        q = (
            cls.model
            .select(
                cls.model.resource_id,
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(cls.model.resource_id)
            .order_by(peewee.SQL("sessions").desc())
            .limit(limit)
        )
        if user_id:
            q = q.where(cls.model.user_id == user_id)
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())

        from api.db.db_models import Knowledgebase, UserCanvas

        resource_ids = [r["resource_id"] for r in rows]
        name_map = {}
        if resource_ids:
            for d in Dialog.select(Dialog.id, Dialog.name).where(Dialog.id.in_(resource_ids)).tuples():
                name_map[d[0]] = d[1]
            missing = [rid for rid in resource_ids if rid not in name_map]
            if missing:
                for c in UserCanvas.select(UserCanvas.id, UserCanvas.title).where(UserCanvas.id.in_(missing)).tuples():
                    if c[1]:
                        name_map[c[0]] = c[1]
            missing = [rid for rid in resource_ids if rid not in name_map]
            if missing:
                for kb in Knowledgebase.select(Knowledgebase.id, Knowledgebase.name).where(Knowledgebase.id.in_(missing)).tuples():
                    if kb[1]:
                        name_map[kb[0]] = kb[1]

        for r in rows:
            r["tokens"] = _int(r.get("tokens"))
        total_sessions = sum(r["sessions"] for r in rows) or 1
        for r in rows:
            rid = r["resource_id"]
            name = name_map.get(rid)
            r["label"] = f"{name} ({rid[:8]})" if name else "Autre ressource"
            r["pct_sessions"] = round(r["sessions"] / total_sessions * 100, 1)

        return rows

    # ------------------------------------------------------------------
    # Per-dialog breakdown (for user detail page)
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def stats_by_usage(
        cls,
        user_id: str,
        from_date: str,
        to_date: str,
        source: str | list[str] | None = None,
        token_type: str | list[str] | None = None,
    ) -> list[dict]:
        """Breakdown by resource_id for a single user, enriched with dialog/canvas/kb name and pct fields."""
        from api.db.db_models import Dialog, Knowledgebase, UserCanvas

        q = (
            cls.model
            .select(
                cls.model.resource_id,
                peewee.fn.COUNT(cls.model.id).alias("sessions"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
                peewee.fn.COALESCE(peewee.fn.AVG(peewee.fn.NULLIF(cls.model.duration, 0)), 0.0).alias("avg_duration_ms"),
            )
            .where(
                cls.model.user_id == user_id,
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(cls.model.resource_id)
            .order_by(peewee.SQL("tokens").desc())
        )
        q = _filter_source(q, source, cls.model.source)
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.dicts())

        resource_ids = [r["resource_id"] for r in rows]
        name_map = {}
        if resource_ids:
            for d in Dialog.select(Dialog.id, Dialog.name).where(Dialog.id.in_(resource_ids)).tuples():
                name_map[d[0]] = d[1]
            missing = [rid for rid in resource_ids if rid not in name_map]
            if missing:
                for c in UserCanvas.select(UserCanvas.id, UserCanvas.title).where(UserCanvas.id.in_(missing)).tuples():
                    if c[1]:
                        name_map[c[0]] = c[1]
            missing = [rid for rid in resource_ids if rid not in name_map]
            if missing:
                for kb in Knowledgebase.select(Knowledgebase.id, Knowledgebase.name).where(Knowledgebase.id.in_(missing)).tuples():
                    if kb[1]:
                        name_map[kb[0]] = kb[1]

        for r in rows:
            r["tokens"] = _int(r.get("tokens"))
            r["avg_duration_ms"] = round(_float(r.get("avg_duration_ms")), 1)
        total_tokens = sum(r["tokens"] for r in rows) or 1
        total_sessions = sum(r["sessions"] for r in rows) or 1
        for r in rows:
            rid = r["resource_id"]
            name = name_map.get(rid)
            r["label"] = f"{name} ({rid[:8]})" if name else "Autre ressource"
            r["pct_tokens"] = round(r["tokens"] / total_tokens * 100, 1)
            r["pct_sessions"] = round(r["sessions"] / total_sessions * 100, 1)

        return rows

    # ------------------------------------------------------------------
    # Ingestion — embedding token consumption
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def log_ingestion(
        cls,
        *,
        user_id: str,
        kb_id: str,
        doc_id: str,
        tokens: int,
        duration_ms: float = 0.0,
        model: str = "",
        provider: str = "",
        token_type: str = "embedding",
    ) -> None:
        """Log token consumption from a document ingestion task.

        Stores source='ingestion', resource_id=kb_id, object_id=doc_id.
        token_type='embedding' for embedding tokens, 'llm' for LLM tokens
        (graphrag/raptor/extraction). Never join resource_id/object_id without
        filtering by source/token_type.
        """
        if not tokens:
            return
        try:
            cls.insert(
                user_id=user_id,
                resource_id=kb_id,
                object_id=doc_id,
                source="ingestion",
                token_type=token_type,
                tokens=tokens,
                duration=duration_ms,
                model=model,
                provider=provider,
            )
        except Exception:
            logger.exception(
                "Failed to write ingestion usage_log: user_id=%s kb_id=%s doc_id=%s token_type=%s tokens=%d",
                user_id, kb_id, doc_id, token_type, tokens,
            )

    @classmethod
    @DB.connection_context()
    def stats_ingestion_for_user(
        cls,
        user_id: str,
        from_date: str,
        to_date: str,
    ) -> dict:
        """Aggregate embedding token consumption from ingestion tasks for a single user."""
        q = (
            cls.model
            .select(
                peewee.fn.COUNT(cls.model.id).alias("tasks"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.duration), 0.0).alias("total_duration_ms"),
            )
            .where(
                cls.model.user_id == user_id,
                cls.model.source == "ingestion",
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
        )
        row = q.dicts().first() or {}
        return {
            "tasks": _int(row.get("tasks")),
            "tokens": _int(row.get("tokens")),
            "total_duration_ms": round(_float(row.get("total_duration_ms")), 1),
        }

    @classmethod
    @DB.connection_context()
    def stats_ingestion_by_kb(
        cls,
        user_id: str,
        from_date: str,
        to_date: str,
    ) -> list[dict]:
        """Ingestion token consumption broken down by knowledgebase (resource_id=kb_id)."""
        from api.db.db_models import Knowledgebase

        rows = list(
            cls.model
            .select(
                cls.model.resource_id.alias("kb_id"),
                peewee.fn.COUNT(cls.model.id).alias("tasks"),
                peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            )
            .where(
                cls.model.user_id == user_id,
                cls.model.source == "ingestion",
                peewee.fn.DATE(cls.model.create_date) >= from_date,
                peewee.fn.DATE(cls.model.create_date) <= to_date,
            )
            .group_by(cls.model.resource_id)
            .order_by(peewee.SQL("tokens").desc())
            .dicts()
        )

        kb_ids = [r["kb_id"] for r in rows]
        name_map = {}
        if kb_ids:
            for kb in Knowledgebase.select(Knowledgebase.id, Knowledgebase.name).where(Knowledgebase.id.in_(kb_ids)).tuples():
                name_map[kb[0]] = kb[1]

        for r in rows:
            r["tokens"] = _int(r.get("tokens"))
        total = sum(r["tokens"] for r in rows) or 1
        for r in rows:
            r["kb_name"] = name_map.get(r["kb_id"], r["kb_id"])
            r["pct_tokens"] = round(r["tokens"] / total * 100, 1)

        return rows

    # ------------------------------------------------------------------
    # Available sources
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def available_sources(cls) -> list[str]:
        """Return the distinct source values present in the table, sorted."""
        rows = (
            cls.model
            .select(cls.model.source)
            .distinct()
            .order_by(cls.model.source)
            .tuples()
        )
        return [r[0] for r in rows if r[0]]

    @classmethod
    @DB.connection_context()
    def available_types(cls) -> list[str]:
        """Return the distinct token_type values present in the table, sorted."""
        rows = (
            cls.model
            .select(cls.model.token_type)
            .distinct()
            .order_by(cls.model.token_type)
            .tuples()
        )
        return [r[0] for r in rows if r[0]]

    # ------------------------------------------------------------------
    # Per-session breakdown
    # ------------------------------------------------------------------

    @classmethod
    @DB.connection_context()
    def stats_for_session(
        cls,
        user_id: str,
        session_id: str,
        token_type: str | list[str] | None = "llm",
    ) -> dict | None:
        """Per-turn breakdown for a single session, scoped to user_id for security.

        Restricted to ``token_type`` consumption (default ``"llm"``) so the
        per-turn totals/histogram reflect LLM usage only and exclude embedding
        (and other non-LLM) token consumption. Pass ``None`` to include all types.

        Returns None if the session doesn't exist or doesn't belong to user_id.
        """
        from api.db.db_models import Dialog, UserCanvas

        q = (
            cls.model
            .select()
            .where(
                cls.model.user_id == user_id,
                cls.model.object_id == session_id,
            )
        )
        q = _filter_type(q, token_type, cls.model.token_type)
        rows = list(q.order_by(cls.model.create_date).dicts())

        if not rows:
            return None

        resource_id = rows[0]["resource_id"]
        dialog_name = None
        for d in Dialog.select(Dialog.id, Dialog.name).where(Dialog.id == resource_id).tuples():
            dialog_name = d[1]
        if not dialog_name:
            for c in UserCanvas.select(UserCanvas.id, UserCanvas.title).where(UserCanvas.id == resource_id).tuples():
                dialog_name = c[1]

        by_turn = []
        for i, r in enumerate(rows):
            at = r["create_date"]
            by_turn.append({
                "turn": i + 1,
                "tokens": r["tokens"],
                "duration_ms": round(r["duration"], 1),
                "model": r["model"],
                "provider": r["provider"],
                "at": at.isoformat() if hasattr(at, "isoformat") else str(at),
            })

        total_tokens = sum(r["tokens"] for r in rows)
        total_duration = sum(r["duration"] for r in rows)
        turn_count = len(rows)

        return {
            "object_id": session_id,
            "resource_id": resource_id,
            "dialog_name": dialog_name or resource_id,
            "source": rows[0]["source"],
            "first_turn_at": by_turn[0]["at"],
            "last_turn_at": by_turn[-1]["at"],
            "totals": {
                "turns": turn_count,
                "tokens": total_tokens,
                "total_duration_ms": round(total_duration, 1),
                "avg_duration_ms": round(total_duration / max(turn_count, 1), 1),
            },
            "by_turn": by_turn,
        }
