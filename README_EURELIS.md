# README Eurelis — Fork RAGFlow

Ce fichier documente les outils et conventions spécifiques au fork Eurelis de RAGFlow.

---

## Slash command `/sync-upstream`

**Fichier** : `.claude/commands/sync-upstream.md`  
**Usage** : taper `/sync-upstream` depuis Claude Code dans ce projet

Ce command agentic synchronise le miroir `main` depuis l'upstream RAGFlow et rebase `eurelis/main` sur le nouveau `main`.

### Processus en 7 étapes

1. **Vérifications** — working directory propre, remote `upstream` présent, branches existantes
2. **Sauvegardes** — tags `backup/main-before-sync` et `backup/eurelis-main-before-sync-YYYY-MM-DD` créés avant toute modification
3. **Fetch upstream** — avec affichage des nouveaux commits, arrêt si déjà à jour
4. **Merge main** — `--ff-only` strict, arrêt si `main` contient des commits non-upstream
5. **Rebase eurelis/main** — arrêt immédiat en cas de conflits (jamais de résolution automatique)
6. **Push** — `--force-with-lease` obligatoire pour `eurelis/main`
7. **Rapport** — fichier `docs/eurelis/sync-upstream/YYYY-MM-DD.md` créé automatiquement avec SHAs, commits intégrés et conflits résolus

### Réversibilité

- Le tag `backup/eurelis-main-before-sync-YYYY-MM-DD` est daté pour conserver l'historique des syncs précédentes
- Les commandes de rollback complètes sont affichées à la fin de chaque exécution, même en cas de succès
- Chaque étape à risque déclenche un arrêt plutôt qu'une action forcée

### Rollback manuel

```bash
git rebase --abort  # si un rebase est en cours

git checkout main
git reset --hard backup/main-before-sync
git push origin main --force-with-lease

git checkout eurelis/main
git reset --hard backup/eurelis-main-before-sync-YYYY-MM-DD  # remplacer par la date du sync
git push origin eurelis/main --force-with-lease
```

---

## Slash command `/build-and-publish`

**Fichier** : `.claude/commands/build-and-publish.md`  
**Usage** :
- `/build-and-publish` — utilise le tag `vX.Y.Z-eurelis.N` posé sur HEAD
- `/build-and-publish v0.25.0-eurelis.1` — utilise le tag passé en paramètre

Ce command agentic build et publie l'image Docker du fork Eurelis sur Docker Hub.

### Prérequis

- Être sur la branche `eurelis/main` (ou avoir un commit de `eurelis/main` checké)
- Un tag `vX.Y.Z-eurelis.N` existant — sur HEAD ou passé en paramètre (voir `docs/eurelis/guidelines/release-management.md`)
- Docker Desktop démarré avec 16 GB de RAM alloués minimum
- Être connecté à Docker Hub (`docker login`)
- Builder multi-platform `eurelis-builder` créé (une seule fois) :
  ```bash
  docker buildx create --name eurelis-builder --driver docker-container --bootstrap
  ```

### Processus en 2 étapes

1. **Vérifications** — résolution du tag (paramètre ou HEAD), branche, Docker, builder, connexion Hub
2. **Build et push** — `docker buildx build --platform linux/amd64 --push` vers `eurelis/ragflow:TAG` et `eurelis/ragflow:latest`

### Passage du tag en paramètre

Si le tag ne pointe pas sur HEAD, la commande propose un `git checkout` du commit correspondant avant de lancer le build. Cela permet de builder une release antérieure sans avoir à manipuler les branches manuellement.

### Versioning

Format : `vX.Y.Z-eurelis.N` — `X.Y.Z` est la version RAGFlow upstream, `N` est le numéro de release Eurelis sur cette base.

---

## Références

- Guidelines fork : `docs/eurelis/guidelines/fork-management.md`
- Guidelines release : `docs/eurelis/guidelines/release-management.md`
- Commande sync : `.claude/commands/sync-upstream.md`
- Commande build : `.claude/commands/build-and-publish.md`
