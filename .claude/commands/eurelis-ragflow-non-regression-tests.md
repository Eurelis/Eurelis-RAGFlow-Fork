---
description: Lance les tests de non-régression Eurelis contre une image Docker donnée (paramètre = tag ou image complète)
allowed-tools: Bash(make:*), Bash(docker compose:*), Bash(docker inspect:*), Bash(docker image inspect:*), Bash(docker images:*), Bash(docker pull:*), Bash(docker logs:*), Bash(curl:*), Bash(ls:*), Bash(uv sync:*), Read, AskUserQuestion
---

# /eurelis-ragflow-non-regression-tests — Tests de non-régression sur une image

Tu lances la suite de tests d'intégration **sans bouchons** (`test/eurelis/`) contre l'image passée en
paramètre : stack RAGFlow complète isolée + Ollama local, contrat Shield (P0), correctifs et évolutions
Eurelis (P1). Références : `docs/eurelis/specs/tests-non-regression/strategy.md` et `test/eurelis/README.md`.

**Usage** :
- `/eurelis-ragflow-non-regression-tests v0.26.1-eurelis.3` — teste `eurelis/ragflow:v0.26.1-eurelis.3`
- `/eurelis-ragflow-non-regression-tests eurelis/ragflow:latest` — image complète (contient `/` ou `:`)
- `/eurelis-ragflow-non-regression-tests` — sans paramètre : demander le tag

## Contexte (injecté au lancement)

- Paramètre reçu : $ARGUMENTS
- venv Python : !`ls .venv/bin/python 2>/dev/null || echo "ABSENT (uv sync requis)"`
- Docker : !`docker info >/dev/null 2>&1 && echo OK || echo "KO (Docker non démarré)"`

---

## ÉTAPE 0 — Résolution de l'image

1. **Si `$ARGUMENTS` est vide** : demander le tag à tester (ou afficher l'usage et s'arrêter).
2. **Si `$ARGUMENTS` contient `/` ou `:`** : c'est une référence d'image complète → l'utiliser telle quelle.
3. **Sinon** : construire `eurelis/ragflow:$ARGUMENTS`.

Noter la référence résolue sous `IMAGE` pour la suite.

Vérifier la présence locale : `docker image inspect IMAGE`.
- Si **absente** : prévenir que `docker compose` tentera de la puller (l'image doit exister sur le registre).
  L'image Eurelis est **amd64-only** → sur Apple Silicon elle tourne en émulation (déjà géré par le compose,
  `platform: linux/amd64`).

---

## ÉTAPE 1 — Préconditions

- **Docker démarré** (contexte ci-dessus = OK). Sinon **arrêter**.
- **venv présent**. Si absent : `uv sync --python 3.13 --all-extras`.
- **~20 Go d'espace disque** côté VM Docker (l'image pèse ~8,5 Go). En cas de `No space left`, voir le
  tableau de dépannage de `test/eurelis/README.md`.

---

## ÉTAPE 2 — Lancer la suite

Exécuter (remplacer `IMAGE` par la référence résolue) :

```bash
RAGFLOW_TEST_IMAGE=IMAGE make -C test/eurelis e2e
```

Cette cible enchaîne : montée de la stack + Ollama → pull des modèles → seed idempotent → `pytest`.
Le **premier** lancement est long (boot RAGFlow ~2 min sous émulation + init PII/Presidio ~30 s).

Variantes utiles :
- **Smoke rapide** (contrat P0 seulement) :
  ```bash
  RAGFLOW_TEST_IMAGE=IMAGE make -C test/eurelis e2e-up && \
    make -C test/eurelis e2e-seed && make -C test/eurelis e2e-run PYTEST_ARGS="-m p0"
  ```
- **Rejeu** (stack déjà démarrée, même image) : `make -C test/eurelis e2e-run`
- **Palier vision** (opt-in, recommandé via OpenAI) :
  `OPENAI_API_KEY=… EURELIS_RUN_VISION=1 make -C test/eurelis e2e-run PYTEST_ARGS="-m vision"`

---

## ÉTAPE 3 — Verdict

Le code retour de `make e2e` reflète celui de `pytest` :
- **exit 0 → SUCCÈS** : afficher le résumé (`N passed, M skipped`). Les `skipped` attendus : endpoint
  image de chunk, et palier `vision` (gaté par `EURELIS_RUN_VISION`).
- **exit ≠ 0 → ÉCHEC** : afficher les tests en échec **sans les masquer**. Ce statut est **exploitable
  comme gate** par `/eurelis-ragflow-build-and-publish` (ne pas publier une image dont les tests échouent).

En cas d'échec, aider au diagnostic : `make -C test/eurelis e2e-logs`, et le tableau de dépannage du README.

---

## ÉTAPE 4 — Nettoyage (optionnel)

- Laisser la stack **up** pour un rejeu rapide (`make -C test/eurelis e2e-run`), ou :
  - `make -C test/eurelis e2e-down` — arrêt, volumes conservés (redémarrage rapide) ;
  - `make -C test/eurelis e2e-reset` — arrêt + suppression des volumes (état vierge).

---

## RÉSUMÉ DES CAS D'ARRÊT

| Situation | Action |
|---|---|
| Paramètre absent | Demander le tag / afficher l'usage |
| Docker non démarré | Arrêter |
| venv absent | `uv sync --python 3.13 --all-extras` puis continuer |
| Image absente en local ET impossible à puller | Arrêter — image introuvable sur le registre |
| Tests en échec (exit ≠ 0) | **ÉCHEC** — remonter les tests rouges, ne pas déclarer succès |
