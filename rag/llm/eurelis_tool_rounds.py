# Eurelis — dernier tour d'une boucle d'outils LLM après dépassement de max_rounds (AILAB-46).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Au-delà de max_rounds, les boucles d'outils de chat_model.py font un dernier appel pour obtenir une
# réponse texte. Cet appel doit toujours déclarer les outils : l'historique contient des blocs
# tool_use/tool_result, et Bedrock Converse refuse sinon la requête (« Bedrock doesn't support tool
# calling without `tools=` param specified »). `tool_choice="none"` n'est pas une option (non pris en
# charge par Converse, retiré sans bruit par drop_params) : on garde "auto", on demande explicitement de
# ne plus appeler d'outil, et les tool_calls éventuels de ce dernier tour ne sont jamais exécutés.


def max_rounds_prompt(max_rounds: int) -> str:
    """Consigne ajoutée à l'historique avant le dernier appel."""
    return f"Exceed max rounds: {max_rounds}. Do not call any tool anymore: answer now with the information already gathered."


def max_rounds_empty_answer(max_rounds: int) -> str:
    """Réponse renvoyée si le dernier appel ne produit aucun texte (p.ex. un nouvel appel d'outil)."""
    return f"L'agent a dépassé {max_rounds} tours d'outils sans produire de réponse."


def final_round_answer(message, max_rounds: int) -> str:
    """Texte du dernier tour ; ses tool_calls sont ignorés, jamais exécutés."""
    content = (getattr(message, "content", None) or "").strip() if message else ""
    return content or max_rounds_empty_answer(max_rounds)
