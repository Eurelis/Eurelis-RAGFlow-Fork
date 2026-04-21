---
description: Build et publie l'image Docker Eurelis sur Docker Hub depuis eurelis/main
allowed-tools: Bash(git log:*), Bash(git tag:*), Bash(git describe:*), Bash(git status:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git fetch:*), Bash(git checkout:*), Bash(docker buildx:*), Bash(docker login:*), Bash(docker build:*), Bash(docker info:*), Bash(uv run:*), AskUserQuestion
---

# /build-and-publish — Build et publication de l'image Docker Eurelis

Tu es chargé de builder et publier l'image Docker du fork Eurelis de RAGFlow selon la stratégie de `docs/eurelis/guidelines/release-management.md`.

**Règle d'or** : on ne build que depuis `eurelis/main`, avec un tag `vX.Y.Z-eurelis.N`. Jamais de build sans tag.

**Usage** :
- `/build-and-publish` — utilise le tag `vX.Y.Z-eurelis.N` présent sur HEAD
- `/build-and-publish v0.25.0-eurelis.1` — utilise le tag passé en paramètre (`$ARGUMENTS`)

## Contexte courant (injecté au lancement)

- Branche active : !`git branch --show-current`
- Paramètre reçu : $ARGUMENTS
- Dernier tag Eurelis : !`git describe --tags --match="v*-eurelis.*" --abbrev=0 2>/dev/null || echo "AUCUN"`
- Tag sur HEAD : !`git tag --points-at HEAD --list "v*-eurelis.*" 2>/dev/null || echo "AUCUN"`
- Builder buildx : !`docker buildx ls 2>/dev/null | grep eurelis-builder || echo "ABSENT"`

---

## ÉTAPE 0 — Vérifications préliminaires (OBLIGATOIRE)

### Résolution du tag à utiliser

**Si `$ARGUMENTS` est fourni** (ex: `/build-and-publish v0.25.0-eurelis.1`) :

1. Vérifier que le tag existe : `git tag --list "$ARGUMENTS"`. Si absent, **arrêter** :
   > ERREUR : le tag `$ARGUMENTS` n'existe pas. Vérifiez avec `git tag --list "v*-eurelis.*"`.

2. Récupérer le commit pointé par le tag : `git rev-parse $ARGUMENTS`

3. Si ce commit **n'est pas** le HEAD actuel :
   - Afficher un avertissement : le tag `$ARGUMENTS` pointe sur `<sha>`, mais HEAD est sur `<sha-head>`.
   - Proposer : **voulez-vous checkout le commit du tag avant de builder ?**
     - Si oui : `git checkout $ARGUMENTS` (mode detached HEAD). Informer l'utilisateur.
     - Si non : **arrêter** — on ne builde pas depuis un état incohérent.

**Si `$ARGUMENTS` est absent** :

1. Vérifier qu'un tag Eurelis est posé sur HEAD : `git tag --points-at HEAD --list "v*-eurelis.*"`. Si absent, **arrêter** :
   > ERREUR : aucun tag `vX.Y.Z-eurelis.N` sur le commit courant. Créez-le ou passez-le en paramètre :
   > ```bash
   > git tag vX.Y.Z-eurelis.N HEAD
   > git push origin vX.Y.Z-eurelis.N
   > # ou : /build-and-publish vX.Y.Z-eurelis.N
   > ```

### Vérifications communes

Après avoir résolu le tag, vérifier :

1. **Branche correcte** : la branche active (ou le commit checké) doit appartenir à `eurelis/main`. Si ce n'est pas le cas, **arrêter** :
   > ERREUR : vous devez builder depuis `eurelis/main`. Faites `git checkout eurelis/main`.

2. **Docker opérationnel** : `docker info` doit répondre sans erreur. Si Docker n'est pas démarré, **arrêter**.

3. **Builder eurelis-builder présent** : `docker buildx ls` doit contenir `eurelis-builder`. Si absent, **arrêter** :
   > ERREUR : le builder multi-platform est absent. Créez-le avec :
   > ```bash
   > docker buildx create --name eurelis-builder --driver docker-container --bootstrap
   > docker buildx use eurelis-builder
   > ```

4. **Connexion Docker Hub** : vérifiable via `cat ~/.docker/config.json | grep index.docker.io`. Si absent, **arrêter** :
   > ERREUR : vous n'êtes pas connecté à Docker Hub. Lancez `docker login`.

Si une vérification échoue, **ne pas continuer**.

---

## ÉTAPE 1 — Confirmation du tag à builder

Afficher clairement ce qui va être buildé :

```
Tag    : vX.Y.Z-eurelis.N
Commit : <sha>
Images : eurelis/ragflow:vX.Y.Z-eurelis.N
         eurelis/ragflow:latest
Plateforme : linux/amd64
```

Demander confirmation à l'utilisateur avant de continuer : **voulez-vous lancer le build ?**

Si l'utilisateur refuse, arrêter proprement.

---

## ÉTAPE 2 — Build et push de l'image

```bash
docker buildx build \
  --builder eurelis-builder \
  --platform linux/amd64 \
  -t eurelis/ragflow:TAG \
  -t eurelis/ragflow:latest \
  --push \
  .
```

Remplacer `TAG` par le tag réel récupéré à l'étape précédente.

Cette commande est longue (10-30 min). Informer l'utilisateur que le build est en cours.

**En cas d'erreur**, afficher le message d'erreur et la solution correspondante du tableau suivant :

| Erreur | Cause | Solution |
|---|---|---|
| `No space left on device` | Cache BuildKit plein | `docker buildx prune --builder eurelis-builder -f` |
| `cannot allocate memory` | RAM insuffisante | Augmenter la RAM Docker Desktop à 16 GB |
| `The service was stopped` | Builder instable | `docker buildx stop eurelis-builder` puis relancer |
| `GPG error ports.ubuntu.com` | Clés ARM64 obsolètes | Construire en `linux/amd64` uniquement (déjà le cas) |

---

## RAPPORT FINAL

À la fin d'un build réussi, afficher :

```
Image publiée avec succès :
  docker pull eurelis/ragflow:TAG
  docker pull eurelis/ragflow:latest
```

Et rappeler la procédure de mise à jour d'une instance existante :

```bash
# Dans le dossier docker de l'instance cible
# 1. Modifier RAGFLOW_IMAGE=eurelis/ragflow:TAG dans .env
# 2. docker pull eurelis/ragflow:TAG
# 3. docker compose up -d --no-deps <nom-du-service-ragflow>
```

---

## RÉSUMÉ DES CAS D'ARRÊT AUTOMATIQUE

| Situation | Action |
|---|---|
| Tag paramètre inexistant | Arrêt — afficher les tags disponibles |
| Tag paramètre ≠ HEAD, refus de checkout | Arrêt propre |
| Aucun tag eurelis sur HEAD (sans paramètre) | Arrêt — afficher la commande de tag ou l'usage avec paramètre |
| Commit non issu de eurelis/main | Arrêt — demander checkout |
| Docker non démarré | Arrêt — demander démarrage |
| Builder eurelis-builder absent | Arrêt — afficher la commande de création |
| Non connecté à Docker Hub | Arrêt — afficher `docker login` |
| Refus de confirmation | Arrêt propre |
| Erreur de build | Arrêt — afficher cause et solution |
