# Eurelis — résolution du tenant dont les modèles servent à exécuter un agent canvas (AILAB-43).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
"""Model tenant of an agent canvas.

Upstream resolves every model of an agent (chat, image2text, TTS, tool
LLMs) on the *caller's* tenant, so a team member without any model provider
cannot run an agent shared with the team. Chat assistants, on the other hand,
resolve their models on the assistant owner's tenant. This module aligns
agents on assistants: models come from the canvas owner (``user_canvas.user_id``).

Storage, sessions and usage attribution (``sys.user_id``) stay on the caller.

Set ``EURELIS_AGENT_MODELS_FROM_OWNER=false`` to restore upstream behaviour.
"""

import logging
import os

ENV_SWITCH = "EURELIS_AGENT_MODELS_FROM_OWNER"


def models_from_owner_enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "true").strip().lower() not in ("0", "false", "no", "off")


def resolve_model_tenant_id(canvas_id, caller_tenant_id):
    """Return the tenant whose models run the canvas, falling back to the caller."""
    if not canvas_id or not models_from_owner_enabled():
        return caller_tenant_id
    try:
        # Lazy import: canvas_service imports agent.canvas.
        from api.db.services.canvas_service import UserCanvasService

        exists, cvs = UserCanvasService.get_by_id(canvas_id)
    except Exception:
        logging.exception("Eurelis: failed to resolve owner of canvas %s, using caller tenant", canvas_id)
        return caller_tenant_id
    if not exists or not getattr(cvs, "user_id", None):
        return caller_tenant_id
    return cvs.user_id
