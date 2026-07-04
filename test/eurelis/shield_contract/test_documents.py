# Eurelis — contrat P0 des endpoints documents (download / upload / images) proxyfiés par le Shield.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import pytest

from configs import REF_DATASET_NAME, VERSION
from libs.contract import assert_valid
from schemas.documents import UPLOAD_RECORD_SCHEMA


@pytest.fixture(scope="module")
def ref_dataset_and_doc(token):
    import httpx

    from configs import HOST_ADDRESS, HTTP_TIMEOUT

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=HOST_ADDRESS, headers=headers, timeout=HTTP_TIMEOUT) as c:
        ds = c.get(f"/api/{VERSION}/datasets", params={"name": REF_DATASET_NAME}).json()["data"]
        assert ds, "dataset de référence introuvable"
        dataset_id = ds[0]["id"]
        docs = (c.get(f"/api/{VERSION}/datasets/{dataset_id}/documents").json()["data"] or {}).get("docs") or []
        assert docs, "document de référence introuvable"
        return dataset_id, docs[0]["id"]


@pytest.mark.p0
def test_document_download(api, ref_dataset_and_doc):
    """GET /datasets/{ds}/documents/{doc} : blob téléchargeable (ouverture de source côté Shield)."""
    dataset_id, doc_id = ref_dataset_and_doc
    r = api.get(f"/api/{VERSION}/datasets/{dataset_id}/documents/{doc_id}")
    assert r.status_code == 200, r.text
    assert r.content, "corps de réponse vide"
    assert "content-disposition" in {k.lower() for k in r.headers}, "content-disposition absent"


@pytest.mark.p0
def test_chat_file_upload_contract(api):
    """POST /documents/upload : renvoie un DocumentRecord conforme (upload de pièce jointe chat)."""
    files = {"file": ("shield-upload.txt", b"contenu de test Shield", "text/plain")}
    r = api.post(f"/api/{VERSION}/documents/upload", files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("code") == 0, body
    assert_valid(body["data"], UPLOAD_RECORD_SCHEMA, label="upload record")
    assert body["data"]["mime_type"] == "text/plain"


@pytest.mark.p0
def test_document_image_endpoint(api, ref_dataset_and_doc):
    """
    GET /documents/images/{image_id} : image d'un chunk (rendu des citations illustrées).
    Skippé si la donnée de référence ne contient aucun chunk illustré (doc texte).
    """
    dataset_id, doc_id = ref_dataset_and_doc
    r = api.get(f"/api/{VERSION}/datasets/{dataset_id}/documents/{doc_id}/chunks")
    chunks = (r.json().get("data") or {}).get("chunks") or []
    image_id = next((c.get("image_id") for c in chunks if c.get("image_id")), None)
    if not image_id:
        pytest.skip("aucun chunk illustré dans la donnée de référence (doc texte) — endpoint image non couvert")
    img = api.get(f"/api/{VERSION}/documents/images/{image_id}")
    assert img.status_code == 200, img.text
    assert img.content, "image vide"
