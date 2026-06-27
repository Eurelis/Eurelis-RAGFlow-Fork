# Eurelis — Supervision admin des modèles configurés par tenant (/api/v1/admin/tenants/.../models).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import json

from flask import Blueprint, request
from flask_login import login_required

from auth import check_admin_auth
from responses import error_response, success_response

from api.db.db_models import User
from api.db.services.user_service import TenantService
from api.db.services.tenant_model_provider_service import TenantModelProviderService
from api.db.services.tenant_model_instance_service import TenantModelInstanceService
from api.apps.services.models_api_service import (
    list_tenant_added_models,
    list_tenant_default_models,
    MODEL_TYPE_TO_FIELD,
    MODEL_TAG_TO_TYPE,
)

# Reverse map: resolved default model_type (e.g. "speech2text") -> tenant field key ("asr").
_RESOLVED_TYPE_TO_KEY = {v: k for k, v in MODEL_TAG_TO_TYPE.items()}

eurelis_model_supervision_bp = Blueprint(
    "eurelis_model_supervision", __name__, url_prefix="/api/v1/admin"
)


def _mask_secret(raw: str) -> str | None:
    """Return a non-reversible hint of an api_key, never the secret itself."""
    if not raw:
        return None
    if len(raw) <= 10:
        return "***"
    return f"{raw[:4]}…{raw[-4:]}"


def _instance_base_url(extra: str) -> str:
    try:
        return (json.loads(extra) or {}).get("base_url", "") if extra else ""
    except (ValueError, TypeError):
        return ""


def _resolve_owner_email(tenant_id: str) -> str:
    row = User.select(User.email).where(User.id == tenant_id).first()
    return row.email if row else tenant_id


class TenantModelMgr:
    """Admin service: read & compare per-tenant model configuration (system `tenant_model_*`).

    `tenant_llm` (legacy) and the routing groups are out of scope. Secrets
    (`TenantModelInstance.api_key`) are never returned in clear — only a masked
    hint / presence flag.
    """

    @staticmethod
    def _list_instances(tenant_id: str) -> list[dict]:
        """Providers + instances of a tenant, api_key masked."""
        providers = TenantModelProviderService.get_by_tenant_id(tenant_id)
        if not providers:
            return []
        provider_name_by_id = {p.id: p.provider_name for p in providers}
        instances = TenantModelInstanceService.get_by_provider_ids([p.id for p in providers])
        result = []
        for inst in instances or []:
            api_key = inst.api_key or ""
            has_key = bool(api_key) and api_key not in ("{}", "xxx")
            result.append({
                "provider_name": provider_name_by_id.get(inst.provider_id, ""),
                "instance_name": inst.instance_name,
                "status": inst.status,
                "has_api_key": has_key,
                "api_key_hint": _mask_secret(api_key) if has_key else None,
                "base_url": _instance_base_url(inst.extra),
            })
        result.sort(key=lambda x: (x["provider_name"], x["instance_name"]))
        return result

    @staticmethod
    def _raw_defaults(tenant, resolved_models: list[dict]) -> list[dict]:
        """Default model strings straight from the Tenant record, with a
        `resolvable` flag (False = dangling pointer, e.g. provider not configured)."""
        resolved_keys = {
            _RESOLVED_TYPE_TO_KEY.get(d["model_type"], d["model_type"]) for d in resolved_models
        }
        raw = []
        for mtype, field in MODEL_TYPE_TO_FIELD.items():
            value = getattr(tenant, field, None)
            if value:
                raw.append({"model_type": mtype, "value": value, "resolvable": mtype in resolved_keys})
        return raw

    @staticmethod
    def list_tenant_models(tenant_id: str) -> dict:
        """Full model configuration of a single tenant (no secrets)."""
        exist, tenant = TenantService.get_by_id(tenant_id)
        if not exist:
            raise ValueError(f"Tenant not found: {tenant_id}")

        ok_added, added = list_tenant_added_models(tenant_id)
        ok_default, default = list_tenant_default_models(tenant_id)
        resolved = (default or {}).get("models", []) if ok_default else []

        return {
            "tenant_id": tenant_id,
            "owner_email": _resolve_owner_email(tenant_id),
            "instances": TenantModelMgr._list_instances(tenant_id),
            "added_models": added if ok_added else [],
            "default_models": resolved,
            "raw_defaults": TenantModelMgr._raw_defaults(tenant, resolved),
        }

    @staticmethod
    def compare_tenants(tenant_ids: list[str]) -> dict:
        """Side-by-side configuration matrix across several tenants.

        Rows are keyed by identity (instance, or provider@instance@model, or
        model_type for defaults); columns are tenants.
        """
        per_tenant = {tid: TenantModelMgr.list_tenant_models(tid) for tid in tenant_ids}

        # --- instances matrix : key = (provider_name, instance_name) ---
        instances: dict[tuple, dict] = {}
        for tid, data in per_tenant.items():
            for inst in data["instances"]:
                key = (inst["provider_name"], inst["instance_name"])
                row = instances.setdefault(key, {
                    "provider_name": inst["provider_name"],
                    "instance_name": inst["instance_name"],
                    "by_tenant": {},
                })
                row["by_tenant"][tid] = {
                    "present": True,
                    "has_api_key": inst["has_api_key"],
                    "api_key_hint": inst["api_key_hint"],
                    "base_url": inst["base_url"],
                    "status": inst["status"],
                }

        # --- models matrix : key = (provider_name, instance_name, model_name) ---
        models: dict[tuple, dict] = {}
        for tid, data in per_tenant.items():
            for m in data["added_models"]:
                key = (m["provider_name"], m["instance_name"], m["name"])
                row = models.setdefault(key, {
                    "provider_name": m["provider_name"],
                    "instance_name": m["instance_name"],
                    "model_name": m["name"],
                    "by_tenant": {},
                })
                row["by_tenant"][tid] = {"present": True, "model_type": m["model_type"]}

        # --- defaults matrix : key = model_type (raw values, dangling included) ---
        defaults: dict[str, dict] = {}
        for tid, data in per_tenant.items():
            for d in data["raw_defaults"]:
                mtype = d["model_type"]
                row = defaults.setdefault(mtype, {"model_type": mtype, "by_tenant": {}})
                row["by_tenant"][tid] = {
                    "value": d["value"],
                    "resolvable": d["resolvable"],
                }

        return {
            "tenants": [
                {"tenant_id": tid, "owner_email": per_tenant[tid]["owner_email"]}
                for tid in tenant_ids
            ],
            "instances": sorted(instances.values(), key=lambda r: (r["provider_name"], r["instance_name"])),
            "models": sorted(models.values(), key=lambda r: (r["provider_name"], r["instance_name"], r["model_name"])),
            "defaults": sorted(defaults.values(), key=lambda r: r["model_type"]),
        }


@eurelis_model_supervision_bp.route("/tenants/<tenant_id>/models", methods=["GET"])
@login_required
@check_admin_auth
def list_tenant_models(tenant_id: str):
    """List the full model configuration of a tenant (cross-tenant, admin only)."""
    try:
        return success_response(TenantModelMgr.list_tenant_models(tenant_id))
    except ValueError as e:
        return error_response(str(e), 404)
    except Exception as e:
        return error_response(str(e), 500)


@eurelis_model_supervision_bp.route("/tenants/models/compare", methods=["GET"])
@login_required
@check_admin_auth
def compare_tenant_models():
    """Compare the model configuration of several tenants (?tenant_ids=a,b,c)."""
    try:
        raw = request.args.get("tenant_ids", "") or ""
        tenant_ids = [t.strip() for t in raw.split(",") if t.strip()]
        if not tenant_ids:
            return error_response("tenant_ids is required (comma-separated)", 400)
        return success_response(TenantModelMgr.compare_tenants(tenant_ids))
    except ValueError as e:
        return error_response(str(e), 404)
    except Exception as e:
        return error_response(str(e), 500)
