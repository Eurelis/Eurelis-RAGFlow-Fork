# Eurelis — substitution ciblée des paramètres déclarés d'un prompt système (sans str.format).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# L'upstream rend le prompt système d'un assistant rattaché à une base de connaissances par
# `prompt_config["system"].format(**kwargs)`. Toute accolade littérale du prompt (CSS, JavaScript,
# JSON, `${…}`) est alors lue comme un champ de template : `KeyError(' font-family')` et
# l'assistant ne répond plus. Ici, seuls les paramètres déclarés (`prompt_config.parameters`,
# plus `knowledge`) sont substitués, par remplacement textuel de `{clé}` ; le reste du texte est
# transmis tel quel au modèle, exactement comme pour un assistant sans base (`async_chat_solo`).

from typing import Any, Iterable, Mapping

# Toujours substitué quand présent, même s'il manque dans `parameters` (l'upstream l'auto-ajoute).
ALWAYS_SUBSTITUTED = ("knowledge",)


def render_prompt_template(template: str, values: Mapping[str, Any], keys: Iterable[str] = ()) -> str:
    """Remplace `{clé}` par `values[clé]` pour chaque clé déclarée disponible ; le reste est intact.

    - `keys` : clés déclarées dans `prompt_config.parameters` (l'ordre est sans effet).
    - Une clé déclarée mais absente de `values` est laissée telle quelle (l'appelant a déjà
      vidé les paramètres optionnels manquants en amont).
    - Aucune accolade n'est interprétée : `{ color: red }`, `{{`, `${x}` passent inchangés.
    """
    if not template:
        return template or ""
    rendered = template
    for key in dict.fromkeys((*keys, *ALWAYS_SUBSTITUTED)):
        if key in values and values[key] is not None:
            rendered = rendered.replace("{%s}" % key, str(values[key]))
    return rendered
