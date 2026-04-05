---
description: Build et publie l'image Docker Eurelis sur Docker Hub depuis eurelis/main
allowed-tools: Bash(git log:*), Bash(git tag:*), Bash(git describe:*), Bash(git status:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git fetch:*), Bash(git checkout:*), Bash(git push:*), Bash(git commit:*), Bash(git add:*), Bash(git diff:*), Bash(git merge-base:*), Bash(docker buildx:*), Bash(docker login:*), Bash(docker build:*), Bash(docker info:*), Bash(docker manifest:*), Bash(cat:*), Bash(grep:*), Read, Edit, AskUserQuestion
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

### 0a — Résolution du tag (sans créer le tag git encore)

**Si `$ARGUMENTS` est fourni** (ex: `/build-and-publish v0.25.0-eurelis.1`) :

1. Vérifier si le tag git existe : `git tag --list "$ARGUMENTS"`.
   - Si **présent** : récupérer le commit pointé : `git rev-parse $ARGUMENTS`
     - Si ce commit **n'est pas** HEAD :
       - Afficher un avertissement : le tag `$ARGUMENTS` pointe sur `<sha>`, mais HEAD est sur `<sha-head>`.
       - Proposer : **voulez-vous checkout le commit du tag avant de builder ?**
         - Si oui : `git checkout $ARGUMENTS` (mode detached HEAD). Informer l'utilisateur.
         - Si non : **arrêter** — on ne builde pas depuis un état incohérent.
   - Si **absent** : noter que le tag sera créé après la mise à jour du changelog (étape 0c).

**Si `$ARGUMENTS` est absent** :

1. Vérifier qu'un tag Eurelis est posé sur HEAD : `git tag --points-at HEAD --list "v*-eurelis.*"`. Si absent, **arrêter** :
   > ERREUR : aucun tag `vX.Y.Z-eurelis.N` sur le commit courant. Créez-le ou passez-le en paramètre :
   > ```bash
   > git tag vX.Y.Z-eurelis.N HEAD
   > git push origin vX.Y.Z-eurelis.N
   > # ou : /build-and-publish vX.Y.Z-eurelis.N
   > ```

### 0b — Vérifications communes

Après avoir résolu le tag, vérifier :

1. **Image Docker Hub inexistante** : `docker manifest inspect eurelis/ragflow:TAG 2>/dev/null`. Si la commande **réussit** (image déjà publiée), **arrêter** :
   > ERREUR : l'image `eurelis/ragflow:TAG` existe déjà sur Docker Hub. Incrémentez le numéro de version ou utilisez un tag différent.

2. **Branche correcte** : la branche active (ou le commit checké) doit appartenir à `eurelis/main`. Si ce n'est pas le cas, **arrêter** :
   > ERREUR : vous devez builder depuis `eurelis/main`. Faites `git checkout eurelis/main`.

3. **Docker opérationnel** : `docker info` doit répondre sans erreur. Si Docker n'est pas démarré, **arrêter**.

4. **Builder eurelis-builder présent** : `docker buildx ls` doit contenir `eurelis-builder`. Si absent, **arrêter** :
   > ERREUR : le builder multi-platform est absent. Créez-le avec :
   > ```bash
   > docker buildx create --name eurelis-builder --driver docker-container --bootstrap
   > docker buildx use eurelis-builder
   > ```

5. **Connexion Docker Hub** : vérifiable via `cat ~/.docker/config.json | grep index.docker.io`. Si absent, **arrêter** :
   > ERREUR : vous n'êtes pas connecté à Docker Hub. Lancez `docker login`.

Si une vérification échoue, **ne pas continuer**.

### 0c — Mise à jour du CHANGELOG_EURELIS.md

> **Cette étape est obligatoire.** Le tag git est créé (ou confirmé) après le commit du changelog, afin que le tag pointe sur un commit incluant les notes de release.

#### Si le tag n'existait pas encore (cas "absent" de l'étape 0a)

1. Lire `CHANGELOG_EURELIS.md` et vérifier si une entrée `## [TAG]` existe déjà.

2. **Si l'entrée est absente** : générer l'entrée à partir des commits Eurelis-spécifiques.
   - Lister les commits depuis le dernier tag Eurelis :
     ```bash
     git log --oneline HEAD --not $(git merge-base HEAD main)
     ```
   - Pour chaque commit, identifier la catégorie (`Added`, `Changed`, `Fixed`, `Removed`) selon le préfixe conventionnel (`feat`, `fix`, `docs`, `chore`, etc.).
   - Rédiger l'entrée en français selon le format :
     ```markdown
     ## [TAG] - YYYY-MM-DD

     Basé sur RAGFlow `vX.Y.Z`.

     ### Added
     - ...

     ### Changed
     - ...

     ### Fixed
     - ...
     ```
   - Insérer l'entrée **en tête** du fichier, juste après le premier `---`.
   - Afficher à l'utilisateur l'entrée générée et demander confirmation : **l'entrée du changelog est-elle correcte ?**
     - Si non : demander les corrections à apporter, les appliquer, puis confirmer à nouveau.

3. **Si l'entrée existe déjà** : afficher son contenu et demander : **souhaitez-vous la modifier avant de continuer ?**
   - Si oui : demander les modifications, les appliquer.
   - Si non : continuer.

4. Committer la mise à jour :
   ```bash
   git add CHANGELOG_EURELIS.md
   git commit -m "chore(eurelis): update CHANGELOG_EURELIS.md for TAG"
   ```

5. Créer le tag sur le nouveau HEAD et le pousser :
   ```bash
   git tag TAG HEAD
   git push origin TAG
   git push origin eurelis/main
   ```
   Informer l'utilisateur que le tag a été créé sur le commit incluant le changelog.

#### Si le tag existait déjà et pointait sur HEAD

1. Vérifier si `CHANGELOG_EURELIS.md` contient une entrée `## [TAG]`.
   - Si **absente** : afficher un avertissement et proposer de l'ajouter :
     > AVERTISSEMENT : le tag TAG existe mais aucune entrée correspondante n'est présente dans CHANGELOG_EURELIS.md.
     > Voulez-vous créer l'entrée maintenant ? (elle sera committée et le tag sera déplacé sur ce nouveau commit)
     - Si oui : générer, committer, puis recréer le tag : `git tag -f TAG HEAD && git push origin TAG --force`
     - Si non : continuer sans changelog (déconseillé).
   - Si **présente** : continuer.

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

## ÉTAPE 2 — Commande de build

Afficher la commande sur **une seule ligne** (remplacer `TAG` par le tag réel) :

```
docker buildx build --builder eurelis-builder --platform linux/amd64 -t eurelis/ragflow:TAG -t eurelis/ragflow:latest --push .
```

Rappeler à l'utilisateur de lancer cette commande depuis la **racine du dépôt** et que le build prend 10 à 30 minutes.

**En cas d'erreur**, voici les solutions :

| Erreur | Cause | Solution |
|---|---|---|
| `No space left on device` | Cache BuildKit plein | `docker buildx prune --builder eurelis-builder -f` |
| `cannot allocate memory` | RAM insuffisante | Augmenter la RAM Docker Desktop à 16 GB |
| `The service was stopped` | Builder instable | `docker buildx stop eurelis-builder` puis relancer |
| `GPG error ports.ubuntu.com` | Clés ARM64 obsolètes | Construire en `linux/amd64` uniquement (déjà le cas) |

---

## RAPPORT FINAL

Une fois le build terminé avec succès, les images sont disponibles sur Docker Hub :

```
docker pull eurelis/ragflow:TAG
docker pull eurelis/ragflow:latest
```

Procédure de mise à jour d'une instance existante :

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
| Image Docker Hub déjà publiée | Arrêt — demander un tag différent |
| Tag paramètre absent en git | Mise à jour changelog → commit → création tag + push |
| Tag paramètre ≠ HEAD, refus de checkout | Arrêt propre |
| Aucun tag eurelis sur HEAD (sans paramètre) | Arrêt — afficher la commande de tag ou l'usage avec paramètre |
| Commit non issu de eurelis/main | Arrêt — demander checkout |
| Docker non démarré | Arrêt — demander démarrage |
| Builder eurelis-builder absent | Arrêt — afficher la commande de création |
| Non connecté à Docker Hub | Arrêt — afficher `docker login` |
| Changelog absent pour un tag existant | Avertissement — proposer création + déplacement du tag |
| Entrée changelog incorrecte | Demander corrections avant de continuer |
| Refus de confirmation | Arrêt propre |
| Erreur de build | Arrêt — afficher cause et solution |
