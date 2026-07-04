# Eurelis — P1 (palier lourd, opt-in) : extraction de CONTENU par LLM de vision à l'ingestion.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Quand un modèle image2text (vision) est le défaut du tenant, le parser PICTURE / VisionFigureParser
# appelle LLMBundle.describe() pour extraire le contenu des images → add_ingestion_llm_tokens →
# bucket `source=ingestion, token_type=llm` (même bucket que mots-clés/questions).
# (DeepDoc, le défaut, fait de l'OCR/layout avec des modèles EMBARQUÉS → pas d'appel LLM, pas de tokens.)
#
# GATÉ par EURELIS_RUN_VISION=1 (skippé sinon). Deux providers possibles :
#
#   • OpenAI cloud (RECOMMANDÉ, VALIDÉ) — si OPENAI_API_KEY est défini : inférence distante
#     (gpt-5.4-mini), ES n'est pas sollicité → **fiable**. Le test passe (~15 s).
#         OPENAI_API_KEY=sk-... EURELIS_RUN_VISION=1 make -C test/eurelis e2e-run PYTEST_ARGS="-m vision"
#     (L'instance OpenAI, qui porte la clé, est supprimée en teardown.)
#
#   • Ollama local (moondream) — sinon : inférence LOCALE qui, sous émulation amd64 (Apple Silicon),
#     **déstabilise Elasticsearch** (crashes/restarts observés — VM 15,6 Go, ES 8 Go + modèle vision +
#     ragflow). Non fiable ici ; réserver à un hôte capable. Prérequis : `ollama pull moondream`.
#
# (DeepDoc, le parser par défaut, fait l'OCR/layout avec des modèles EMBARQUÉS → aucun appel LLM.)

import io
import time
import uuid

import pytest

from configs import (
    HOST_ADDRESS,
    OLLAMA_INSTANCE,
    OLLAMA_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_INSTANCE,
    OPENAI_PROVIDER,
    OPENAI_VISION_MODEL,
    PARSE_TIMEOUT,
    VERSION,
    VISION_MODEL,
)

pytestmark = [
    pytest.mark.p1,
    pytest.mark.vision,
    pytest.mark.skipif(
        not __import__("os").getenv("EURELIS_RUN_VISION"),
        reason="palier vision gaté (EURELIS_RUN_VISION=1) — instable sous émulation (ES crashe).",
    ),
]


def _ingestion_by_model(api) -> dict:
    data = api.get(f"/api/{VERSION}/usage-stats/me/breakdown", params={"source": "ingestion"}).json()["data"]
    return {(it["label"], it["token_type"]): it["tokens"] for it in data.get("items", [])}


def _unique_png() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (384, 160), (250, 250, 250))
    ImageDraw.Draw(img).text((12, 60), f"Eurelis RAGFlow vision {uuid.uuid4().hex[:8]}", fill=(10, 10, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _ok(body: dict) -> bool:
    msg = (body.get("message") or "").lower()
    return body.get("code") == 0 or "already exist" in msg or "duplicated" in msg


@pytest.fixture
def vision_default(api):
    """
    Enregistre un modèle image2text et le fixe comme défaut `vision` du tenant, puis nettoie.

    Provider choisi selon l'environnement :
      - **OpenAI cloud** (`gpt-5.4-mini`) si `OPENAI_API_KEY` est défini → inférence distante, ES
        n'est pas sollicité (chemin fiable) ;
      - sinon **Ollama** (`moondream`) local → instable sous émulation (cf. docstring du module).
    Renvoie le nom du modèle vision (pour cibler le bucket `ingestion/llm`).
    """
    if OPENAI_API_KEY:
        provider, instance, model = OPENAI_PROVIDER, OPENAI_INSTANCE, OPENAI_VISION_MODEL
        api.put(f"/api/{VERSION}/providers", json={"provider_name": provider})
        r = api.post(
            f"/api/{VERSION}/providers/{provider}/instances",
            json={
                "instance_name": instance,
                "api_key": OPENAI_API_KEY,
                "model_info": [{"model_type": ["image2text"], "model_name": model, "max_tokens": 4096}],
            },
        )
        assert _ok(r.json()), f"création instance OpenAI : {r.text}"
    else:
        provider, instance, model = OLLAMA_PROVIDER, OLLAMA_INSTANCE, VISION_MODEL
        api.post(
            f"/api/{VERSION}/providers/{provider}/instances/{instance}/models",
            json={"model_name": model, "model_type": "image2text", "max_tokens": 4096},
        )

    r = api.patch(
        f"/api/{VERSION}/models/default",
        json={"model_provider": provider, "model_instance": instance, "model_type": "vision", "model_name": model},
    )
    assert r.json().get("code") == 0, r.text
    yield model
    # Nettoyage : clear le défaut vision, et supprime l'instance OpenAI (qui porte la clé API).
    api.patch(f"/api/{VERSION}/models/default", json={"model_type": "vision"})
    if OPENAI_API_KEY:
        api.request("DELETE", f"/api/{VERSION}/providers/{OPENAI_PROVIDER}/instances", json={"instances": [OPENAI_INSTANCE]})


def test_vision_content_extraction_logs_llm(api, vision_default):
    """Ingérer une image (chunk_method=picture) fait décrire l'image par le modèle vision → ingestion/llm."""
    vision_model = vision_default
    name = "eurelis-vision"
    for ds in api.get(f"/api/{VERSION}/datasets", params={"name": name}).json().get("data") or []:
        api.request("DELETE", f"/api/{VERSION}/datasets", json={"ids": [ds["id"]]})
    dsid = api.post(f"/api/{VERSION}/datasets", json={"name": name, "chunk_method": "picture"}).json()["data"]["id"]
    try:
        doc = api.post(
            f"/api/{VERSION}/datasets/{dsid}/documents",
            files={"file": ("vision.png", _unique_png(), "image/png")},
        ).json()["data"][0]["id"]
        before = _ingestion_by_model(api)
        api.post(f"/api/{VERSION}/datasets/{dsid}/chunks", json={"document_ids": [doc]})

        deadline = time.monotonic() + PARSE_TIMEOUT
        run = None
        while time.monotonic() < deadline:
            docs = (api.get(f"/api/{VERSION}/datasets/{dsid}/documents").json()["data"] or {}).get("docs") or []
            run = docs[0]["run"] if docs else None
            if run == "DONE":
                break
            assert run != "FAIL", f"parse en échec : {docs[0].get('progress_msg', '') if docs else ''}"
            time.sleep(4)
        assert run == "DONE", f"parse non terminé (run={run})"
        time.sleep(3)

        after = _ingestion_by_model(api)
        vision_llm = after.get((vision_model, "llm"), 0) - before.get((vision_model, "llm"), 0)
        assert vision_llm > 0, f"aucun token llm du modèle vision {vision_model} : {before} -> {after}"
    finally:
        api.request("DELETE", f"/api/{VERSION}/datasets", json={"ids": [dsid]})
