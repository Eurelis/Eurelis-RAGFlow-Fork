# Eurelis — non-régression : accolades littérales dans le prompt système d'un assistant avec base.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Contexte (Synerga, prompt « Office » / artefacts HTML) : un prompt système contenant du CSS ou
# du JavaScript (`body { font-family: … }`) plantait tout assistant rattaché à une base de
# connaissances avec `KeyError(' font-family')`, car `async_chat` rendait le prompt par
# `str.format(**kwargs)`. Les assistants sans base (prompt brut) n'étaient pas touchés, d'où deux
# variantes de prompt à maintenir. `render_prompt_template` ne substitue que les paramètres
# déclarés : un seul prompt fonctionne désormais dans les deux cas.

import pytest

from api.db.services.eurelis_prompt_template import render_prompt_template

CSS = "body { font-family: system-ui, Arial; color: #3C3939; } th { background: #E1E1EA; }"
JS = 'const THEME = { text: "3C3939" }; const rule = (s, y) => s.addShape({ fill: { color: THEME.accent } });'
TEMPLATE_LITERAL = 'return `<p:cNvPr id="${next++}"`;'


def test_css_and_js_braces_are_left_intact():
    template = f"Voici la base : {{knowledge}}\n```css\n{CSS}\n```\n```js\n{JS}\n{TEMPLATE_LITERAL}\n```"
    out = render_prompt_template(template, {"knowledge": "CHUNKS"}, ["knowledge"])
    assert out.startswith("Voici la base : CHUNKS")
    assert CSS in out and JS in out and TEMPLATE_LITERAL in out


def test_str_format_would_have_failed_on_the_same_template():
    """Garde le sens du correctif : l'ancien rendu lève bien sur ce prompt."""
    template = "{knowledge}\n" + CSS
    with pytest.raises(KeyError):
        template.format(knowledge="x")
    assert render_prompt_template(template, {"knowledge": "x"}, ["knowledge"]) == "x\n" + CSS


def test_declared_parameters_are_substituted_in_any_order():
    template = "Client : {client}. Base : {knowledge}. Encore {client}."
    out = render_prompt_template(template, {"client": "WeMa", "knowledge": "K"}, ["knowledge", "client"])
    assert out == "Client : WeMa. Base : K. Encore WeMa."


def test_knowledge_is_substituted_even_if_not_declared():
    out = render_prompt_template("Base : {knowledge}", {"knowledge": "K"}, [])
    assert out == "Base : K"


def test_undeclared_placeholder_is_not_touched():
    """Une clé présente dans kwargs mais non déclarée (ex. doc_ids, quote) n'est plus substituée."""
    out = render_prompt_template("Docs {doc_ids} / {knowledge}", {"doc_ids": "a,b", "knowledge": "K"}, ["knowledge"])
    assert out == "Docs {doc_ids} / K"


def test_declared_but_missing_value_is_left_as_is():
    out = render_prompt_template("Bonjour {name}", {}, ["name"])
    assert out == "Bonjour {name}"


def test_non_string_values_are_stringified_and_none_is_skipped():
    out = render_prompt_template("{n} / {maybe}", {"n": 3, "maybe": None}, ["n", "maybe"])
    assert out == "3 / {maybe}"


def test_doubled_braces_are_no_longer_an_escape():
    """Changement assumé : `{{` n'est plus un échappement, il est transmis tel quel au modèle."""
    assert render_prompt_template("x {{ y }} {knowledge}", {"knowledge": "K"}, ["knowledge"]) == "x {{ y }} K"


def test_empty_template():
    assert render_prompt_template("", {"knowledge": "K"}, ["knowledge"]) == ""
