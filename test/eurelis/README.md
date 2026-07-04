<!-- Eurelis — guide de lancement de la suite de tests de non-régression.
     Fichier propre au fork Eurelis, absent de l'upstream RAGFlow. -->

# Tests de non-régression Eurelis

Suite de tests d'intégration **sans bouchons** contre une stack RAGFlow complète (image du fork).
Elle protège trois périmètres : le **contrat des endpoints consommés par le Shield**, les **correctifs**
Eurelis et les **évolutions** Eurelis.

> Stratégie & décisions : [`docs/eurelis/specs/tests-non-regression/strategy.md`](../../docs/eurelis/specs/tests-non-regression/strategy.md)

---

## Prérequis

- **Docker Desktop** (≈ 20 Go d'espace libre côté VM : l'image du fork pèse ~8,5 Go).
- **Image Eurelis** du fork, p.ex. `eurelis/ragflow:v0.26.1-eurelis.3`. L'image du Docker Hub est
  **amd64-only** → sur Apple Silicon elle tourne en émulation (`platform: linux/amd64`, déjà configuré).
- **Environnement Python** : `uv sync --python 3.13 --all-extras` (crée `.venv/`, utilisé par le Makefile).
- Aucune clé LLM cloud : les modèles tournent **en local via Ollama**.

---

## Démarrage rapide

Depuis la racine du dépôt :

```bash
make -C test/eurelis e2e          # up stack + Ollama, pull modèles, seed, pytest
```

Ou, en pilotant l'image sous test :

```bash
RAGFLOW_TEST_IMAGE=eurelis/ragflow:v0.26.1-eurelis.3 make -C test/eurelis e2e
```

Le premier lancement est long (pull image + boot RAGFlow ~1-2 min en émulation + init PII/Presidio ~30 s).
Ensuite, **rejeu rapide** sur la stack déjà démarrée :

```bash
make -C test/eurelis e2e-run                       # toute la suite
make -C test/eurelis e2e-run PYTEST_ARGS="-m p0"   # contrat Shield seulement
```

---

## Cibles Make

| Cible | Rôle |
|---|---|
| `e2e` | Cycle complet : up → models → seed → run |
| `e2e-up` | Démarre la stack et attend qu'elle soit *healthy* |
| `e2e-models` | Précharge les modèles Ollama (chat + embedding) |
| `e2e-seed` | Injecte le jeu de référence (tenant, providers Ollama, dataset+doc parsé, 2 chats) |
| `e2e-run` | Lance pytest (accepte `PYTEST_ARGS="…"`) |
| `e2e-health` | Vérifie les endpoints de santé (RAGFlow + admin + Ollama) |
| `e2e-ps` / `e2e-logs` | État des conteneurs / logs de ragflow |
| `e2e-down` | Arrête la stack (volumes conservés → redémarrage rapide) |
| `e2e-reset` | Arrête et **supprime les volumes** (état vierge) |
| `e2e-pii-off` | Recrée ragflow **sans** masquage PII (boot plus rapide, sans Presidio) |

`make -C test/eurelis help` liste tout.

---

## Sélection des tests (markers)

| Marker | Portée | Exemple |
|---|---|---|
| `p0` | Contrat Shield (structure des flux JSON, cœur SSE) | `PYTEST_ARGS="-m p0"` |
| `p1` | Correctifs + évolutions Eurelis | `PYTEST_ARGS="-m p1"` |
| `pii` | Masquage PII (nécessite la stack PII, active par défaut) | `PYTEST_ARGS="-m pii"` |
| `vision` | Extraction de contenu par LLM de vision (image2text) — **opt-in** | `EURELIS_RUN_VISION=1 … PYTEST_ARGS="-m vision"` |

Les tests `pii` se **skippent automatiquement** si la stack tourne sans PII (`e2e-pii-off`).
Les tests `vision` sont **gatés par `EURELIS_RUN_VISION=1`** (skippés sinon) et choisissent le provider :
- **OpenAI cloud** (`gpt-5.4-mini`) si `OPENAI_API_KEY` est défini → **fiable** (inférence distante) :
  ```bash
  OPENAI_API_KEY=sk-... EURELIS_RUN_VISION=1 make -C test/eurelis e2e-run PYTEST_ARGS="-m vision"
  ```
  (l'instance OpenAI, qui porte la clé, est supprimée en teardown) ;
- **Ollama local** (`moondream`) sinon → déstabilise ES sous émulation (voir Dépannage) ; prérequis
  `docker exec ragflow-test-ollama-1 ollama pull moondream`.

---

## Comment ça marche

- **Projet Compose isolé** `ragflow-test` (`docker/docker-compose-test.yml`) : volumes/conteneurs séparés
  du stack de dev, réinitialisables sans toucher aux données de développement.
- **LLM local Ollama** : `qwen2.5:0.5b` (chat) + `nomic-embed-text` (embedding, dim 768). On valide la
  **structure** des réponses (contrat de schéma), jamais le contenu généré — robuste au non-déterminisme.
- **PII toujours activé mais scopé** au suffixe `::pii` (`PII_MASKING_PROVIDERS=.*::pii@.*`). Deux modèles
  chat coexistent : `qwen2.5:0.5b` (sans masquage) et `qwen2.5:0.5b::pii` (avec). Observabilité via le
  journal d'audit monté sur l'hôte : `docker/ragflow-logs/pii_audit.log`.
- **Deux chats de référence** (seed) : `eurelis-ref-chat` (sans PII) et `eurelis-ref-chat-pii` (avec PII).
- **Auth** : utilisateur `qa@eurelis.test` (register → login → token Bearer, comme le Shield) ;
  admin `admin@ragflow.io` sur `:9381` (login RSA → JWT en en-tête).
- **Idempotence** : `seed.py` et les fixtures retrouvent l'existant avant de créer ; la suite se relance
  sans nettoyage manuel.

---

## Structure

```
test/eurelis/
├── Makefile              # orchestration e2e-*
├── configs.py            # endpoints, credentials, modèles, données de référence
├── conftest.py           # fixtures : auth, token, api, admin, ref_chat_id(_pii), seed auto
├── seed.py               # amorçage idempotent (standalone)
├── test_smoke.py         # p0 — socle (healthz, auth, défauts Ollama)
├── libs/                 # ragflow_api (auth/ollama/admin), sse (parseur), contract (jsonschema)
├── schemas/              # contrats JSON Schema par domaine
├── shield_contract/      # p0 — endpoints consommés par le Shield (SSE, sessions, chats, documents)
├── eurelis_fixes/        # p1 — correctifs (chats équipe, retrieval)
└── eurelis_features/     # p1 — évolutions (usage-stats, supervision, PII)
```

---

## Périmètre couvert

- **Contrat Shield (p0)** : flux SSE des complétions (enveloppe, streaming/finale, sentinelle, `reference`,
  `usage`), chats/agents, cycle de vie session, download & upload de fichier chat, `system/version`.
- **Correctifs (p1)** : visibilité des chats partagés en équipe, chemin de retrieval.
- **Évolutions (p1)** : stats de conso user + admin (schéma, cohérence des agrégats, **delta llm/embedding**),
  supervision des modèles (lecture, **mutations copy/defaults/delete**, **masquage des clés API**),
  **masquage PII** (opt-in `::pii`, via journal d'audit), **merge `llm_factories.patch.json`** (patch synthétique
  monté dans la stack → catalogue fusionné vérifié via l'API).

### Reliquats connus (voir la stratégie)

- Endpoint image de chunk (`/documents/images/{id}`) — skippé (donnée de référence sans image).
- Cascade delete des fichiers chat (nettoyage MinIO) — introspection stockage à ajouter.
- Correctifs provider-cloud (Bedrock, IMAGE2TEXT→CHAT) — non testables sans credentials cloud
  (tests unitaires / palier `@pytest.mark.cloud`).

---

## Dépannage

| Symptôme | Cause / solution |
|---|---|
| `no matching manifest for linux/arm64` | Image amd64-only sur Apple Silicon → `platform: linux/amd64` (déjà en place). |
| mysql `out of disk space` au boot | VM Docker pleine → `docker system prune` / supprimer d'anciennes images. |
| `uv run` réinstalle tout à chaque appel | Le Makefile utilise directement `.venv/bin/python` — faire `uv sync` une fois. |
| Tests `pii` tous *skipped* | Stack lancée sans PII (`e2e-pii-off`) → relancer `e2e-up`. |
| `pii_audit.log` reste vide | Ne pas `rm` le fichier après le boot (descripteur ouvert → inode orphelin) ; le handler le (re)crée au démarrage de ragflow. |
| Boot lent (~30 s) avec PII | Presidio télécharge le modèle spaCy par défaut à chaque boot ; à pré-embarquer dans l'image pour la CI. |
| `EURELIS_RUN_VISION=1` fait crasher ES | L'inférence du modèle de vision + ES (8 Go) sature la VM (15,6 Go) → ES redémarre en boucle. Réserver ce palier à un hôte capable (amd64 natif / plus de RAM) ou un modèle vision plus léger. |
