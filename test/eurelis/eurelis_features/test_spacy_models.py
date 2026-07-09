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
import os
import shutil
import subprocess

import pytest

pytestmark = [pytest.mark.p1]


def _resolve_container() -> str | None:
    """Nom du conteneur ragflow sous test : override explicite, sinon découverte par labels compose."""
    override = os.getenv("RAGFLOW_TEST_CONTAINER")
    if override:
        return override
    if shutil.which("docker") is None:
        return None
    proc = subprocess.run(
        [
            "docker", "ps",
            "--filter", "label=com.docker.compose.project=ragflow-test",
            "--filter", "label=com.docker.compose.service=ragflow-cpu",
            "--format", "{{.Names}}",
        ],
        capture_output=True, text=True,
    )
    names = [n for n in proc.stdout.split() if n]
    return names[0] if names else None


def _docker_py(code: str) -> str:
    """Exécute un snippet Python dans le conteneur RAGFlow sous test et renvoie stdout (strip)."""
    container = _resolve_container()
    proc = subprocess.run(
        ["docker", "exec", container, "python", "-c", code],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, f"docker exec a échoué (rc={proc.returncode}) : {proc.stderr.strip()}"
    return proc.stdout.strip()


@pytest.fixture(autouse=True)
def _require_container():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI indisponible sur l'hôte de test")
    if _resolve_container() is None:
        pytest.skip("conteneur ragflow sous test introuvable (stack de test non lancée ?)")


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
