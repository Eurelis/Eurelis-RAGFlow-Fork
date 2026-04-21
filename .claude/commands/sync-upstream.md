---
description: Synchronise le miroir main depuis upstream et rebase eurelis/main — avec rollback automatique en cas d'échec
allowed-tools: Bash(git fetch:*), Bash(git checkout:*), Bash(git merge:*), Bash(git push:*), Bash(git rebase:*), Bash(git tag:*), Bash(git reset:*), Bash(git status:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git remote:*), Bash(git diff:*), Bash(git add:*)
---

# /sync-upstream — Synchronisation fork Eurelis ↔ upstream RAGFlow

Tu es chargé de synchroniser le fork Eurelis de RAGFlow avec l'upstream selon la stratégie de `docs/eurelis/guidelines/fork-management.md`.

**Règle d'or** : `main` est un miroir exact de l'upstream — aucun commit Eurelis n'y vit jamais. Les modifications Eurelis vivent exclusivement dans `eurelis/main`.

## Contexte courant (injecté au lancement)

- Branche active : !`git branch --show-current`
- État du working directory : !`git status --short`
- Remotes configurés : !`git remote -v`
- SHA de main : !`git rev-parse main 2>/dev/null || echo "INTROUVABLE"`
- SHA de eurelis/main : !`git rev-parse eurelis/main 2>/dev/null || echo "INTROUVABLE"`
- Derniers commits main : !`git log main --oneline -5`
- Derniers commits eurelis/main : !`git log eurelis/main --oneline -5`

---

## ÉTAPE 0 — Vérifications préliminaires (OBLIGATOIRE)

Avant toute action, vérifie :

1. **Working directory propre** : `git status --short` ne doit rien afficher. Si des modifications non commitées existent, **arrêter immédiatement** et demander à l'utilisateur de les commiter ou stasher.

2. **Remote upstream configuré** : `git remote get-url upstream` doit retourner une URL valide. Si absent, **arrêter** et afficher : `git remote add upstream https://github.com/infiniflow/ragflow.git`

3. **Branches requises existantes** : `main` et `eurelis/main` doivent exister localement.

Si une vérification échoue, **ne pas continuer**. Afficher le problème clairement et les commandes correctrices.

---

## ÉTAPE 1 — Sauvegardes pour rollback

Créer des tags de sauvegarde horodatés **avant toute modification** :

```bash
git tag -f backup/main-before-sync main
git tag -f backup/eurelis-main-before-sync eurelis/main
```

Afficher et noter les SHAs :
- `SHA_MAIN_AVANT` = résultat de `git rev-parse main`
- `SHA_EURELIS_AVANT` = résultat de `git rev-parse eurelis/main`

Ces tags permettront un rollback complet. Les communiquer à l'utilisateur.

---

## ÉTAPE 2 — Récupération upstream

```bash
git fetch upstream
```

Puis afficher un résumé des nouveaux commits :
```bash
git log main..upstream/main --oneline
```

Si `upstream/main` est identique à `main` (aucun nouveau commit), informer l'utilisateur que tout est déjà à jour et **terminer ici** (ne pas continuer les étapes suivantes inutilement).

---

## ÉTAPE 3 — Mise à jour de main (fast-forward uniquement)

```bash
git checkout main
git merge --ff-only upstream/main
```

**Si le merge échoue** (non fast-forward) : c'est une violation de la règle d'or — `main` contient des commits non-upstream. **Arrêter immédiatement**, ne pas forcer, afficher :
> ERREUR : main contient des commits locaux qui ne viennent pas de l'upstream. Résolution manuelle requise.

Si succès, afficher le nombre de commits intégrés.

---

## ÉTAPE 4 — Push de main vers origin

```bash
git push origin main
```

En cas d'erreur, **arrêter**. Ne pas utiliser `--force`.

---

## ÉTAPE 5 — Rebase de eurelis/main sur le nouveau main

```bash
git checkout eurelis/main
git rebase main
```

**En cas de conflits** :
- Lister immédiatement les fichiers en conflit : `git status --short`
- **Arrêter le processus automatique**
- Afficher les instructions de résolution manuelle
- Ne jamais résoudre des conflits automatiquement
- Rappeler la commande d'abandon : `git rebase --abort`

Si le rebase réussit sans conflits, passer à l'étape 6.

---

## ÉTAPE 6 — Push de eurelis/main vers origin

```bash
git push origin eurelis/main --force-with-lease
```

`--force-with-lease` est obligatoire (sécurité contre les écrasements involontaires). Ne jamais utiliser `--force` seul.

---

## RAPPORT FINAL

À la fin d'une synchronisation réussie, afficher un tableau récapitulatif :

| Branche | SHA avant | SHA après | Commits intégrés |
|---|---|---|---|
| main | SHA_MAIN_AVANT | SHA_MAIN_APRÈS | N |
| eurelis/main | SHA_EURELIS_AVANT | SHA_EURELIS_APRÈS | N (rebasés) |

Puis afficher les commandes de rollback (toujours, même en cas de succès) :

```
--- ROLLBACK (si nécessaire) ---
git rebase --abort  # si un rebase est en cours

git checkout main
git reset --hard backup/main-before-sync
git push origin main --force-with-lease

git checkout eurelis/main
git reset --hard backup/eurelis-main-before-sync
git push origin eurelis/main --force-with-lease
```

---

## RÉSUMÉ DES CAS D'ARRÊT AUTOMATIQUE

| Situation | Action |
|---|---|
| Working directory sale | Arrêt — demander commit/stash |
| Remote upstream absent | Arrêt — afficher la commande d'ajout |
| main non fast-forwardable | Arrêt — intervention manuelle requise |
| Conflits de rebase | Arrêt — lister les conflits, attendre l'utilisateur |
| Push échoue | Arrêt — ne jamais forcer sans confirmation |
