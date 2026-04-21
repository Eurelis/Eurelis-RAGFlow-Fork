---
description: Build et publie l'image Docker Eurelis sur Docker Hub depuis eurelis/main
allowed-tools: Bash(git log:*), Bash(git tag:*), Bash(git describe:*), Bash(git status:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(docker buildx:*), Bash(docker login:*), Bash(docker build:*), Bash(docker info:*), Bash(uv run:*), AskUserQuestion
---

# /build-and-publish — Build et publication de l'image Docker Eurelis

Tu es chargé de builder et publier l'image Docker du fork Eurelis de RAGFlow selon la stratégie de `docs/eurelis/guidelines/release-management.md`.

**Règle d'or** : on ne build que depuis `eurelis/main`, avec un tag `vX.Y.Z-eurelis.N` posé sur le commit courant. Jamais de build sans tag.

## Contexte courant (injecté au lancement)

- Branche active : !`git branch --show-current`
- Dernier tag Eurelis : !`git describe --tags --match="v*-eurelis.*" --abbrev=0 2>/dev/null || echo "AUCUN"`
- Tag sur HEAD : !`git tag --points-at HEAD --list "v*-eurelis.*" 2>/dev/null || echo "AUCUN"`
- Builder buildx : !`docker buildx ls 2>/dev/null | grep eurelis-builder || echo "ABSENT"`

---

## ÉTAPE 0 — Vérifications préliminaires (OBLIGATOIRE)

Avant toute action, vérifie :

1. **Branche correcte** : la branche active doit être `eurelis/main`. Si ce n'est pas le cas, **arrêter** et afficher :
   > ERREUR : vous devez être sur `eurelis/main` pour builder. Faites `git checkout eurelis/main`.

2. **Tag Eurelis sur HEAD** : `git tag --points-at HEAD --list "v*-eurelis.*"` doit retourner un tag. Si absent, **arrêter** et afficher :
   > ERREUR : aucun tag `vX.Y.Z-eurelis.N` sur le commit courant. Créez-le d'abord :
   > ```bash
   > git tag vX.Y.Z-eurelis.N eurelis/main
   > git push origin vX.Y.Z-eurelis.N
   > ```

3. **Docker opérationnel** : `docker info` doit répondre sans erreur. Si Docker n'est pas démarré, **arrêter**.

4. **Builder eurelis-builder présent** : `docker buildx ls` doit contenir `eurelis-builder`. Si absent, **arrêter** et afficher :
   > ERREUR : le builder multi-platform est absent. Créez-le avec :
   > ```bash
   > docker buildx create --name eurelis-builder --driver docker-container --bootstrap
   > docker buildx use eurelis-builder
   > ```

5. **Connexion Docker Hub** : `docker login` doit être actif (vérifiable via `docker info | grep Username`). Si absent, **arrêter** et afficher :
   > ERREUR : vous n'êtes pas connecté à Docker Hub. Lancez `docker login`.

Si une vérification échoue, **ne pas continuer**.

---

## ÉTAPE 1 — Confirmation du tag à builder

Récupérer le tag sur HEAD :

```bash
git tag --points-at HEAD --list "v*-eurelis.*"
```

Afficher clairement ce qui va être buildé :

```
Tag    : vX.Y.Z-eurelis.N
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
| Branche ≠ eurelis/main | Arrêt — demander checkout |
| Aucun tag eurelis sur HEAD | Arrêt — afficher la commande de tag |
| Docker non démarré | Arrêt — demander démarrage |
| Builder eurelis-builder absent | Arrêt — afficher la commande de création |
| Non connecté à Docker Hub | Arrêt — afficher `docker login` |
| Refus de confirmation | Arrêt propre |
| Erreur de build | Arrêt — afficher cause et solution |
