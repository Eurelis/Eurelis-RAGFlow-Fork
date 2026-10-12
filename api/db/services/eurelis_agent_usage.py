# Eurelis — comptabilisation de l'usage d'une exécution d'agent canvas (api_4_conversation + usage_log).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Une « exécution » = un appel de complétion d'agent : un départ, ou une reprise après une pause
# UserFillUp. Chaque exécution :
#   - incrémente `api_4_conversation.tokens` / `duration` via `append_message` (comme le chat) ;
#   - écrit UNE ligne `usage_log` (source="agent", token_type="llm"), pauses, erreurs et annulations
#     comprises.
# Tokens = total du collecteur par exécution de `Canvas.run` (`token_usage_sink`, alimenté par les
# appels de CHAT de LLMBundle uniquement : l'embedding de `Retrieval` est journalisé à part par
# `eurelis_usage_log`, sans double comptage). Durée = temps réel de l'exécution, en millisecondes
# (même unité que `duration_ms` côté chat). `model` / `provider` restent vides : le collecteur
# n'agrège qu'un total, une exécution peut appeler plusieurs modèles.

import logging
import time

from api.db.services.usage_log_service import UsageLogService

logger = logging.getLogger(__name__)


class AgentRunMeter:
    """Mesure une exécution de canvas. Créé juste avant `canvas.run`, arrêté une seule fois."""

    def __init__(self, canvas):
        self._canvas = canvas
        self._start = time.perf_counter()
        self._stopped = False
        self.tokens = 0
        self.duration_ms = 0.0

    def restart(self) -> None:
        """Repart de maintenant : un flux SSE n'exécute le canvas qu'à sa consommation."""
        self._start = time.perf_counter()

    def stop(self) -> "AgentRunMeter":
        """Fige durée et tokens au premier appel (idempotent). Lit le collecteur, pas `workflow_finished`."""
        if self._stopped:
            return self
        self._stopped = True
        self.duration_ms = round((time.perf_counter() - self._start) * 1000, 1)
        try:
            self.tokens = int(self._canvas._run_usage_payload().get("total_tokens", 0) or 0)
        except Exception:
            logger.warning("Agent run usage unavailable", exc_info=True)
        return self


def log_agent_run(meter: AgentRunMeter, *, user_id, agent_id, session_id) -> None:
    """Écrit la ligne usage_log de l'exécution. Synchrone (appelable dans un `finally`), ne lève jamais."""
    meter.stop()
    try:
        UsageLogService.log(
            user_id=user_id or "",
            resource_id=agent_id or "",
            object_id=session_id or "",
            source="agent",
            token_type="llm",
            tokens=meter.tokens,
            duration=meter.duration_ms,
        )
    except Exception:
        logger.exception("Failed to write agent usage_log: agent_id=%s session_id=%s", agent_id, session_id)
