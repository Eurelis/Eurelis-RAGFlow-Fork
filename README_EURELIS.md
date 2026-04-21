# README Eurelis — Fork RAGFlow

Ce fichier documente les outils et conventions spécifiques au fork Eurelis de RAGFlow.

---

## Slash command `/sync-upstream`

**Fichier** : `.claude/commands/sync-upstream.md`  
**Usage** : taper `/sync-upstream` depuis Claude Code dans ce projet

Ce command agentic synchronise le miroir `main` depuis l'upstream RAGFlow et rebase `eurelis/main` sur le nouveau `main`.

### Processus en 6 étapes

1. **Vérifications** — working directory propre, remote `upstream` présent, branches existantes
2. **Sauvegardes** — tags `backup/main-before-sync` et `backup/eurelis-main-before-sync` créés avant toute modification
3. **Fetch upstream** — avec affichage des nouveaux commits, arrêt si déjà à jour
4. **Merge main** — `--ff-only` strict, arrêt si `main` contient des commits non-upstream
5. **Rebase eurelis/main** — arrêt immédiat en cas de conflits (jamais de résolution automatique)
6. **Push** — `--force-with-lease` obligatoire pour `eurelis/main`

### Réversibilité

- Les tags de sauvegarde permettent un `git reset --hard` sur les deux branches
- Les commandes de rollback complètes sont affichées à la fin de chaque exécution, même en cas de succès
- Chaque étape à risque déclenche un arrêt plutôt qu'une action forcée

### Rollback manuel

```bash
git rebase --abort  # si un rebase est en cours

git checkout main
git reset --hard backup/main-before-sync
git push origin main --force-with-lease

git checkout eurelis/main
git reset --hard backup/eurelis-main-before-sync
git push origin eurelis/main --force-with-lease
```

---

## Références

- Guidelines fork : `docs/eurelis/guidelines/fork-management.md`
- Définition du command : `.claude/commands/sync-upstream.md`
