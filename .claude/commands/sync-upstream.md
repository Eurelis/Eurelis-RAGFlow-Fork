---
description: Synchronise le miroir main depuis upstream et rebase eurelis/main — avec rollback automatique en cas d'échec
allowed-tools: Bash(git fetch:*), Bash(git checkout:*), Bash(git merge:*), Bash(git push:*), Bash(git rebase:*), Bash(git tag:*), Bash(git reset:*), Bash(git status:*), Bash(git log:*), Bash(git rev-parse:*), Bash(git remote:*), Bash(git diff:*), Bash(git add:*), Bash(date:*), Write
---

# /sync-upstream — Synchronisation fork Eurelis ↔ upstream RAGFlow

Tu es chargé de synchroniser le fork Eurelis de RAGFlow avec l'upstream selon la stratégie de `docs/eurelis/guidelines/fork-management.md`.

**Règle d'or** : `main` est un miroir exact de l'upstream — aucun commit Eurelis n'y vit jamais. Les modifications Eurelis vivent exclusivement dans `eurelis/main`.

## Paramètre

La commande accepte un argument optionnel `$ARGUMENTS` :

| Valeur | Comportement |
|---|---|
| _(vide)_ ou `HEAD` | Synchronise avec le dernier commit de `upstream/main` |
| `v0.25.0` (tag upstream) | Réintègre `eurelis/main` sur ce tag précis de l'upstream |

En début de traitement, résoudre la cible :
```
SYNC_TARGET="${ARGUMENTS:-HEAD}"
if [ "$SYNC_TARGET" = "HEAD" ]; then
  TARGET_REF="upstream/main"
else
  TARGET_REF="$SYNC_TARGET"
fi
```

Afficher clairement : `Cible de synchronisation : $TARGET_REF`

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

Obtenir la date du jour puis créer les tags de sauvegarde **avant toute modification** :

```bash
DATE=$(date +%Y-%m-%d)
git tag -f backup/main-before-sync main
git tag -f backup/eurelis-main-before-sync-$DATE-$SYNC_TARGET eurelis/main
```

Afficher et noter les SHAs :
- `SHA_MAIN_AVANT` = résultat de `git rev-parse main`
- `SHA_EURELIS_AVANT` = résultat de `git rev-parse eurelis/main`

Ces tags permettront un rollback complet. Les communiquer à l'utilisateur, en précisant le nom exact du tag daté (ex. `backup/eurelis-main-before-sync-2026-04-21-v0.25.1`).

---

## ÉTAPE 2 — Récupération upstream

```bash
git fetch upstream --tags
```

Vérifier que `TARGET_REF` est accessible après le fetch :
- Si `TARGET_REF` est un tag : `git rev-parse "$TARGET_REF"` doit retourner un SHA. Si introuvable, **arrêter** : `ERREUR : tag "$TARGET_REF" introuvable dans upstream.`
- Si `TARGET_REF` est `upstream/main` : vérification implicite.

Afficher un résumé des commits entre `main` et `TARGET_REF` :
```bash
git log main..$TARGET_REF --oneline
```

Si `TARGET_REF` est identique à `main` (aucun écart), informer l'utilisateur que tout est déjà à jour et **terminer ici**.

Si `TARGET_REF` est **en arrière** de `main` (downgrade de version), afficher un avertissement explicite :
> ⚠ ATTENTION : $TARGET_REF est antérieur à l'état actuel de main. Cette opération fait reculer main vers une version plus ancienne. Continuer ?

Attendre confirmation explicite avant de continuer.

---

## ÉTAPE 3 — Mise à jour de main vers TARGET_REF

```bash
git checkout main
```

**Cas A — TARGET_REF = `upstream/main`** (avancement vers le dernier commit) :
```bash
git merge --ff-only upstream/main
```
Si le merge échoue (non fast-forward) : violation de la règle d'or — `main` contient des commits non-upstream. **Arrêter immédiatement** :
> ERREUR : main contient des commits locaux qui ne viennent pas de l'upstream. Résolution manuelle requise.

**Cas B — TARGET_REF = tag spécifique** :
```bash
git reset --hard "$TARGET_REF"
```
Un `reset --hard` est utilisé ici car un tag peut être antérieur ou postérieur à l'état actuel de `main`.

Si succès (dans les deux cas), afficher le nombre de commits d'écart avec l'état précédent.

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

## ÉTAPE 7 — Enregistrement du rapport

Obtenir la date du jour :
```bash
date +%Y-%m-%d
```

Créer le fichier `docs/eurelis/sync-upstream/YYYY-MM-DD.md` (remplacer la date réelle) avec le contenu suivant, en remplaçant toutes les variables par leurs valeurs réelles :

```markdown
# Sync upstream — YYYY-MM-DD

## Rapport final

| Branche | SHA avant | SHA après | Commits intégrés |
|---|---|---|---|
| `main` | `SHA_MAIN_AVANT` | `SHA_MAIN_APRÈS` | N commits upstream |
| `eurelis/main` | `SHA_EURELIS_AVANT` | `SHA_EURELIS_APRÈS` | N commits Eurelis rebasés |

## Conflits résolus

<!-- Lister ici les conflits rencontrés et leur résolution, ou supprimer cette section si aucun conflit -->
```

Si aucun conflit n'a eu lieu, supprimer la section `## Conflits résolus` du fichier généré.

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
git reset --hard backup/eurelis-main-before-sync-YYYY-MM-DD-TARGET_REF  # remplacer par le tag affiché à l'étape 1
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
