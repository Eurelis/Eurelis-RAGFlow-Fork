---
title: "PDF scannés joints au chat ou à un agent : pages transmises en images"
type: knowledge
status: reference
date: 2026-11-16
---

# PDF scannés joints au chat ou à un agent : pages transmises en images

Depuis `v0.26.3-eurelis.17` (AILAB-52, SM-298), les pages **sans texte** d'un PDF joint à un
assistant ou à un agent sont rendues en JPEG et envoyées au LLM comme des images jointes. Avant,
un scan arrivait vide : le modèle ne recevait que `File: x.pdf Content as following:`.

> **En bref.** PDF texte : lecture inchangée, au caractère près (AILAB-26, AILAB-45). Page de
> moins de 50 caractères visibles : image. 20 pages en images au plus par requête
> (`EURELIS_ATTACHMENT_SCAN_MAX_PAGES`), et le prompt le dit quand on coupe. Modèle sans vision :
> lecture texte comme avant, avec une phrase qui signale les pages non lues.

---

## 1. Chemin des pièces jointes

Une seule fonction pour les deux chemins : `FileService.read_attachments`
(`api/db/services/eurelis_scanned_pdf.py`). Elle renvoie, dans l'ordre des fichiers, une liste plate
d'entrées : texte, puis les images (data URI, ou octets bruts en mode `raw`).

| Chemin | Appel | Images vers le LLM |
| --- | --- | --- |
| Assistant, modèle `chat` | `split_file_attachments` → `FileService.get_files` | `convert_last_user_msg_to_multimodal` (`image_url`, ou blocs Anthropic / Gemini) |
| Assistant, modèle `image2text` (mode raw) | `FileService.get_files(raw=True)` | `images=` du modèle CV (octets JPEG) |
| Agent | `Canvas.get_files_async` → `sys.files` | composant LLM / Agent (`_collect_sys_files` sépare les `data:image/`) |

L'ingestion des bases de connaissances (DeepDOC, VisionParser…) n'est pas concernée.

## 2. Détection, page par page

Analyse pdfium (`pypdfium2`, déjà dans l'image) sous le verrou partagé de deepdoc.

- **Page scannée** : moins de `MIN_TEXT_CHARS` = 50 caractères **visibles** (blancs exclus), et la
  page contient une image ou un tracé (une page vierge n'est pas envoyée).
- **Texte invisible** : couche OCR de copieur en mode de rendu 3 → non compté.
- **Texte sous l'image** : texte peint avant une image qui le recouvre (page couverte à plus de
  50 % par des images) → non compté.
- **Surface d'image** : union des rectangles d'image sur une grille 100 × 100 : un scan livré en
  101 bandes de 2480 × 35 px couvre bien toute la page.
- Une image de fond avec du vrai texte peint par-dessus (papier à en-tête) reste une page texte.

## 3. Ce que reçoit le modèle

| Cas | Texte | Images |
| --- | --- | --- |
| Aucune page scannée | lecture actuelle (`FileService.parse`), inchangée | aucune |
| Scan complet | `x.pdf : document scanné, N pages transmises en images (une image par page, dans l'ordre : pages 1 à N).` | N JPEG |
| PDF mixte | phrase d'en-tête, puis les pages texte lues comme avant, balisées `[x.pdf, pages 1 et 2]`, et `[x.pdf, page 3 : page scannée, transmise en image]` à la place des pages scannées | une par page scannée |
| Plafond atteint | en plus : `ATTENTION : plafond de 20 pages en images par message atteint : les pages … de x.pdf n'ont pas été lues. Préviens l'utilisateur…` | premières pages seulement |
| Modèle sans vision | lecture actuelle + `x.pdf : N pages scannées sans texte (pages …) non lues : le modèle utilisé ne lit pas les images. Préviens l'utilisateur.` | aucune |

La couche OCR d'un scan (souvent fausse sur les montants) n'est jamais transmise avec l'image.

**Rendu** : JPEG qualité 85, 150 dpi, grand côté ramené à 1568 px (A4 → 1109 × 1568). Environ
2,3 k tokens par page chez Claude ; 180 à 390 Ko par page, soit 1,5 à 2,5 Mo de base64 pour 4 à
6 pages.

## 4. Plafond par requête

`EURELIS_ATTACHMENT_SCAN_MAX_PAGES` (défaut `20`) compte les pages en images sur **toute la
requête**, toutes pièces jointes confondues : le Shield renvoie toutes les PJ de la session à
chaque tour. Le budget est réservé dans l'ordre des pièces jointes : les premières pages passent.
`0` désactive la fonction (lecture texte seule, comme avant).

## 5. Le modèle lit-il les images ?

`model_reads_images(tenant_id, llm_id)` : vrai si le modèle est enregistré avec le type
`image2text`, sinon d'après son nom (familles multimodales : `claude-`, `gpt-4o`, `gpt-4.1`,
`gpt-5`, `gemini`, `pixtral`, `qwen…-vl`, `llama-3.2…vision`, `nova-lite|pro`…). Les modèles
Bedrock ajoutés à la main (type `chat` seul) passent par le nom : `eu.anthropic.claude-opus-4-8`
est reconnu.

Pour un agent, il suffit qu'un composant LLM ou Agent du canvas utilise un modèle multimodal.
`sys.files` est calculé une fois par exécution, avant les composants.

## 6. Journaux

- `scanned_pdf name=… pages=… scanned=… images=… image_bytes=… mixed=…` (INFO) par PDF traité.
- `[HISTORY]` / `[HISTORY STREAMLY]` (`Base`, `LiteLLMBase`) : chaque image base64 est remplacée par
  `data:image/jpeg;base64,/9j/…[base64 tronqué, N caractères]` (`rag/llm/eurelis_history_log.py`).
  L'historique envoyé au modèle n'est pas modifié.
- Toute erreur d'analyse ou de rendu est journalisée (WARNING) et retombe sur la lecture texte.

## 7. Limites connues

- Composant `UserFillUp` (fichiers saisis en cours d'exécution d'un agent) : pages en images
  quel que soit le modèle (pas de repli « sans vision »), comme les images jointes.
- Webhook d'agent (`multipart/form-data`) : plafond compté par fichier, l'API traitant les
  fichiers un par un.
- Les images ne sont pas comptées par `message_fit_in` (comme les images jointes) : c'est le
  plafond de pages qui borne le coût.
