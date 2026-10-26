# Eurelis — vérifie que l'image embarque les modèles spaCy EN + FR requis par le NER PII. Feature Eurelis.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Prérequis du NER du masquage PII (Presidio) : Presidio charge un modèle spaCy par langue AU
# DÉMARRAGE, depuis les packages installés dans l'image (aucun téléchargement runtime). Régression
# constatée en prod (v0.26.3-eurelis.2, Synerga francophone) : l'image ne contenait que
# en_core_web_sm → fr_core_news_lg introuvable → NER FR silencieusement désactivé
# (PII_MASKING_STARTUP_FAIL=false). Depuis v0.26.3-eurelis.3, l'image embarque fr_core_news_sm.
#
# On exécute spaCy DANS le conteneur sous test (docker exec), pas sur l'hôte : c'est l'artefact
# buildé qu'on valide. Skippé proprement si le conteneur est introuvable (stack de test non lancée,
# ou suite exécutée contre un hôte distant sans accès au démon Docker local).

import json

import pytest

from libs.container import docker_py as _docker_py
from libs.container import skip_reason

pytestmark = [pytest.mark.p1]


@pytest.fixture(autouse=True)
def _require_container():
    reason = skip_reason()
    if reason:
        pytest.skip(reason)


def test_spacy_models_installed():
    """L'image embarque en_core_web_sm ET fr_core_news_sm (NER PII EN + FR)."""
    models = json.loads(_docker_py("import spacy.util, json; print(json.dumps(spacy.util.get_installed_models()))"))
    assert "en_core_web_sm" in models, f"modèle EN manquant : {models}"
    assert "fr_core_news_sm" in models, f"modèle FR manquant (régression prod) : {models}"


def test_fr_ner_detects_person_and_location():
    """fr_core_news_sm détecte une PER (Jean Dupont) et une LOC (Paris) — sanity du NER FR."""
    code = (
        "import spacy, json; nlp = spacy.load('fr_core_news_sm'); "
        "print(json.dumps([[e.text, e.label_] for e in nlp('Contactez Jean Dupont à Paris').ents]))"
    )
    ents = json.loads(_docker_py(code))
    labels = {label for _, label in ents}
    texts = " ".join(text for text, _ in ents)
    assert "PER" in labels, f"aucune entité PER détectée : {ents}"
    assert "LOC" in labels, f"aucune entité LOC détectée : {ents}"
    assert "Jean Dupont" in texts, f"'Jean Dupont' non reconnu comme entité : {ents}"
    assert "Paris" in texts, f"'Paris' non reconnu comme entité : {ents}"
