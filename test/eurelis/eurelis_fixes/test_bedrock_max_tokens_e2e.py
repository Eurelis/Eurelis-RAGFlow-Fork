# Eurelis — e2e opt-in AILAB-22 : les réponses longues Bedrock ne sont plus tronquées à ~4 096 tokens.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Palier OPT-IN avec appel cloud réel (contrairement au reste de la suite, déterministe et locale) :
# skippé sauf si EURELIS_BEDROCK_TEST_AK / EURELIS_BEDROCK_TEST_SK sont fournis. Coût : une réponse
# longue (~8-10k tokens de sortie) du modèle EURELIS_BEDROCK_TEST_CHAT_MODEL (défaut
# eu.anthropic.claude-opus-4-8) par exécution, soit 1 à 3 minutes de génération.
#
# Régression gardée : sans injection de max_tokens (branche Bedrock de
# _construct_completion_args), Converse applique son défaut service (~4 096 tokens pour Claude),
# coupe en plein milieu de la liste et RAGFlow ajoute le suffixe LENGTH_NOTIFICATION
# ("The answer is truncated…"). Avec le correctif, la liste va jusqu'au dernier item, sans suffixe.
#
# Lancement :
#   EURELIS_BEDROCK_TEST_AK=... EURELIS_BEDROCK_TEST_SK=... \
#     make -C test/eurelis e2e-run PYTEST_ARGS="-k bedrock_max_tokens"

import json
import re

import httpx
import pytest

from configs import (
    BEDROCK_INSTANCE,
    BEDROCK_PROVIDER,
    BEDROCK_TEST_AK,
    BEDROCK_TEST_CHAT_MODEL,
    BEDROCK_TEST_REGION,
    BEDROCK_TEST_SK,
    HOST_ADDRESS,
    HTTP_TIMEOUT,
    VERSION,
    bedrock_ref,
)

pytestmark = [
    pytest.mark.p3,
    pytest.mark.skipif(
        not (BEDROCK_TEST_AK and BEDROCK_TEST_SK),
        reason="palier Bedrock réel : EURELIS_BEDROCK_TEST_AK / EURELIS_BEDROCK_TEST_SK non fournis",
    ),
]

# La génération longue (~8-10k tokens) prend 1 à 3 minutes : client dédié à timeout large.
COMPLETION_TIMEOUT = 600

TRUNCATION_SUFFIXES = (
    "The answer is truncated by your chosen LLM",
    "回答已经被大模型截断",
)

# 200 items numérotés × 2 phrases ≈ 8-10k tokens de sortie, largement au-delà du défaut
# service (~4 096). Le marqueur "200." en fin de liste prouve que la réponse est complète.
N_ITEMS = 200
QUESTION = (
    f"Rédige une liste numérotée de 1 à {N_ITEMS} de conseils de révision comptable. "
    "Chaque item doit contenir exactement deux phrases complètes. "
    f"Numérote strictement chaque item « 1. », « 2. », …, « {N_ITEMS}. », sans t'arrêter avant {N_ITEMS}."
)


def _ensure_bedrock_instance(auth: str) -> None:
    """Amorçage idempotent du provider Bedrock sur le tenant de test (clé JSON access_key_secret)."""
    headers = {"Authorization": auth, "Content-Type": "application/json"}

    def _ok(body: dict) -> bool:
        msg = (body.get("message") or "").lower()
        return body.get("code") == 0 or "already exist" in msg or "duplicated" in msg

    r = httpx.put(
        f"{HOST_ADDRESS}/api/{VERSION}/providers",
        headers=headers,
        json={"provider_name": BEDROCK_PROVIDER},
        timeout=HTTP_TIMEOUT,
    )
    assert _ok(r.json()), f"add provider Bedrock : {r.json().get('message')!r}"

    r = httpx.post(
        f"{HOST_ADDRESS}/api/{VERSION}/providers/{BEDROCK_PROVIDER}/instances",
        headers=headers,
        json={
            "instance_name": BEDROCK_INSTANCE,
            "api_key": json.dumps(
                {
                    "auth_mode": "access_key_secret",
                    "bedrock_ak": BEDROCK_TEST_AK,
                    "bedrock_sk": BEDROCK_TEST_SK,
                    "bedrock_region": BEDROCK_TEST_REGION,
                    "aws_role_arn": "",
                }
            ),
            "base_url": "",
            "region": BEDROCK_TEST_REGION,
            "model_info": [
                {"model_type": ["chat"], "model_name": BEDROCK_TEST_CHAT_MODEL, "max_tokens": 200000},
            ],
        },
        timeout=HTTP_TIMEOUT,
    )
    assert _ok(r.json()), f"create instance Bedrock : {r.json().get('message')!r}"


def test_bedrock_long_answer_not_truncated(auth, token):
    _ensure_bedrock_instance(auth)

    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=COMPLETION_TIMEOUT,
    ) as api:
        body = api.post(
            f"/api/{VERSION}/chats",
            json={
                "name": "eurelis-bedrock-max-tokens",
                "llm_id": bedrock_ref(),
                # Chat sans dataset : prompt système direct, sans placeholder {knowledge}
                # ni réponse en conserve, sinon le défaut oriente le modèle vers le refus RAG.
                "prompt_config": {
                    "system": "Tu es un assistant de rédaction. Réponds directement et complètement à la demande.",
                    "prologue": "Bonjour.",
                    "parameters": [],
                    "empty_response": "",
                },
            },
        ).json()
        assert body.get("code") == 0, f"création du chat en échec : {body.get('message')!r}"
        assert body["data"]["llm_id"] == bedrock_ref(), f"le chat n'utilise pas le modèle Bedrock : {body['data'].get('llm_id')!r}"
        chat_id = body["data"]["id"]
        try:
            sid = api.post(f"/api/{VERSION}/chats/{chat_id}/sessions", json={"name": "x"}).json()["data"]["id"]
            body = api.post(
                f"/api/{VERSION}/chats/{chat_id}/completions",
                json={"question": QUESTION, "stream": False, "session_id": sid},
            ).json()
            assert body.get("code") == 0, f"completion en échec : {body.get('message')!r}"
            answer = body["data"]["answer"]

            # 1) Le symptôme exact du bug : le suffixe de troncature ajouté sur finish_reason "length".
            for suffix in TRUNCATION_SUFFIXES:
                assert suffix not in answer, f"réponse tronquée (suffixe présent) — {len(answer)} caractères"

            # 2) La réponse est complète : le dernier item numéroté est présent
            #    (une coupure au défaut service ~4 096 tokens s'arrête vers l'item ~80-120).
            assert re.search(rf"\b{N_ITEMS}\s*\.", answer), (
                f"liste incomplète : item {N_ITEMS} absent — {len(answer)} caractères, fin : …{answer[-200:]!r}"
            )
        finally:
            api.request("DELETE", f"/api/{VERSION}/chats", json={"ids": [chat_id]})
