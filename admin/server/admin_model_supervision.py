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
from api.db.services.tenant_model_service import TenantModelService
from api.apps.services.models_api_service import (
    list_tenant_added_models,
    list_tenant_default_models,
    MODEL_TYPE_TO_FIELD,
    MODEL_TAG_TO_TYPE,
)

# Reverse map: resolved default model_type (e.g. "speech2text") -> tenant field key ("asr").
_RESOLVED_TYPE_TO_KEY = {v: k for k, v in MODEL_TAG_TO_TYPE.items()}

admin_model_supervision_bp = Blueprint(
    "admin_model_supervision", __name__, url_prefix="/api/v1/admin"
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

    @staticmethod
    def _ensure_provider(target_id: str, provider_name: str):
        """Return the target provider, creating it if missing (insert() returns a
        row count, not the object → re-fetch)."""
        tp = TenantModelProviderService.get_by_tenant_id_and_provider_name(target_id, provider_name)
        if not tp:
            TenantModelProviderService.insert(tenant_id=target_id, provider_name=provider_name)
            tp = TenantModelProviderService.get_by_tenant_id_and_provider_name(target_id, provider_name)
        return tp

    @staticmethod
    def _copy_instance_to(source_instance, provider_name: str, target_id: str) -> str:
        """Upsert one provider/instance (api_key + tenant_model) onto a target.
        Returns 'added' or 'overwritten'."""
        tp = TenantModelMgr._ensure_provider(target_id, provider_name)
        existing = TenantModelInstanceService.get_by_provider_id_and_instance_name(
            tp.id, source_instance.instance_name
        )
        if existing:
            TenantModelInstanceService.update_by_id(
                existing.id,
                {"api_key": source_instance.api_key, "extra": source_instance.extra, "status": source_instance.status},
            )
            target_instance_id = existing.id
            outcome = "overwritten"
        else:
            TenantModelInstanceService.create_instance(
                tp.id, source_instance.instance_name, source_instance.api_key, source_instance.extra
            )
            created = TenantModelInstanceService.get_by_provider_id_and_instance_name(
                tp.id, source_instance.instance_name
            )
            target_instance_id = created.id if created else None
            outcome = "added"

        # tenant_model rows (usually none — overwrite if present)
        if target_instance_id:
            for sm in TenantModelService.get_models_by_instance_id(source_instance.id):
                existing_models = TenantModelService.get_by_provider_id_and_instance_id_and_model_type_and_model_name(
                    tp.id, target_instance_id, sm.model_type, sm.model_name
                )
                if existing_models:
                    TenantModelService.update_by_id(existing_models[0].id, {"status": sm.status, "extra": sm.extra})
                else:
                    TenantModelService.insert(
                        provider_id=tp.id, instance_id=target_instance_id,
                        model_name=sm.model_name, model_type=sm.model_type,
                        status=sm.status, extra=sm.extra,
                    )
        return outcome

    @staticmethod
    def _resolve_source_instance(source_tenant_id: str, provider_name: str, instance_name: str):
        sp = TenantModelProviderService.get_by_tenant_id_and_provider_name(source_tenant_id, provider_name)
        if not sp:
            raise ValueError(f"Provider '{provider_name}' not found for source tenant")
        si = TenantModelInstanceService.get_by_provider_id_and_instance_name(sp.id, instance_name)
        if not si:
            raise ValueError(f"Instance '{instance_name}' not found for source tenant")
        return si

    @staticmethod
    def copy_instance(source_tenant_id: str, provider_name: str, instance_name: str, target_tenant_ids: list[str]) -> dict:
        """Copy one provider/instance (api_key incl.) from a source tenant to targets (overwrite)."""
        si = TenantModelMgr._resolve_source_instance(source_tenant_id, provider_name, instance_name)
        summary = {"added": 0, "overwritten": 0, "skipped": 0}
        for tid in target_tenant_ids:
            if tid == source_tenant_id:
                summary["skipped"] += 1
                continue
            te, _ = TenantService.get_by_id(tid)
            if not te:
                summary["skipped"] += 1
                continue
            outcome = TenantModelMgr._copy_instance_to(si, provider_name, tid)
            summary[outcome] += 1
        return summary

    @staticmethod
    def delete_instance(provider_name: str, instance_name: str, target_tenant_ids: list[str]) -> dict:
        """Delete one provider/instance from each target tenant (and its tenant_model
        rows; the provider is removed too if it has no instance left)."""
        summary = {"deleted": 0, "not_found": 0}
        for tid in target_tenant_ids:
            tp = TenantModelProviderService.get_by_tenant_id_and_provider_name(tid, provider_name)
            if not tp:
                summary["not_found"] += 1
                continue
            inst = TenantModelInstanceService.get_by_provider_id_and_instance_name(tp.id, instance_name)
            if not inst:
                summary["not_found"] += 1
                continue
            for m in TenantModelService.get_models_by_instance_id(inst.id):
                TenantModelService.delete_by_id(m.id)
            TenantModelInstanceService.delete_by_provider_id_and_instance_name(tp.id, instance_name)
            summary["deleted"] += 1
            if not TenantModelInstanceService.get_all_by_provider_id(tp.id):
                TenantModelProviderService.delete_by_tenant_id_and_provider_name(tid, provider_name)
        return summary

    @staticmethod
    def copy_defaults(source_tenant_id: str, target_tenant_ids: list[str]) -> dict:
        """Copy the Tenant default model strings (llm_id, embd_id, …) to targets (overwrite)."""
        se, source_tenant = TenantService.get_by_id(source_tenant_id)
        if not se:
            raise ValueError(f"Source tenant not found: {source_tenant_id}")
        updates = {}
        copied = []
        for mtype, field in MODEL_TYPE_TO_FIELD.items():
            value = getattr(source_tenant, field, None)
            if value:
                updates[field] = value
                copied.append({"model_type": mtype, "value": value})
        applied = 0
        for tid in target_tenant_ids:
            if tid == source_tenant_id or not updates:
                continue
            te, _ = TenantService.get_by_id(tid)
            if not te:
                continue
            TenantService.update_by_id(tid, dict(updates))
            applied += 1
        return {"targets": applied, "defaults_copied": copied}


@admin_model_supervision_bp.route("/tenants/<tenant_id>/models", methods=["GET"])
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


@admin_model_supervision_bp.route("/tenants/models/compare", methods=["GET"])
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


def _targets(data: dict) -> list[str]:
    raw = data.get("target_tenant_ids") or []
    return [t.strip() for t in raw if isinstance(t, str) and t.strip()]


@admin_model_supervision_bp.route("/tenants/models/instances/copy", methods=["POST"])
@login_required
@check_admin_auth
def copy_instance():
    """Copy one provider/instance to targets.
    Body: {source_tenant_id, provider_name, instance_name, target_tenant_ids[]}."""
    try:
        data = request.get_json(silent=True) or {}
        source_id = (data.get("source_tenant_id") or "").strip()
        provider_name = (data.get("provider_name") or "").strip()
        instance_name = (data.get("instance_name") or "").strip()
        targets = _targets(data)
        if not (source_id and provider_name and instance_name and targets):
            return error_response(
                "source_tenant_id, provider_name, instance_name and target_tenant_ids are required", 400
            )
        return success_response(
            TenantModelMgr.copy_instance(source_id, provider_name, instance_name, targets)
        )
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@admin_model_supervision_bp.route("/tenants/models/instances/delete", methods=["POST"])
@login_required
@check_admin_auth
def delete_instance():
    """Delete one provider/instance from targets.
    Body: {provider_name, instance_name, target_tenant_ids[]}."""
    try:
        data = request.get_json(silent=True) or {}
        provider_name = (data.get("provider_name") or "").strip()
        instance_name = (data.get("instance_name") or "").strip()
        targets = _targets(data)
        if not (provider_name and instance_name and targets):
            return error_response(
                "provider_name, instance_name and target_tenant_ids are required", 400
            )
        return success_response(
            TenantModelMgr.delete_instance(provider_name, instance_name, targets)
        )
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)


@admin_model_supervision_bp.route("/tenants/models/defaults/copy", methods=["POST"])
@login_required
@check_admin_auth
def copy_defaults():
    """Copy the default models of a source tenant to targets.
    Body: {source_tenant_id, target_tenant_ids[]}."""
    try:
        data = request.get_json(silent=True) or {}
        source_id = (data.get("source_tenant_id") or "").strip()
        targets = _targets(data)
        if not (source_id and targets):
            return error_response("source_tenant_id and target_tenant_ids are required", 400)
        return success_response(TenantModelMgr.copy_defaults(source_id, targets))
    except ValueError as e:
        return error_response(str(e), 400)
    except Exception as e:
        return error_response(str(e), 500)
