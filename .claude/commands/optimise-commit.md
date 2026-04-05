---
description: Commit et squashe automatiquement dans le bon groupe de eurelis/main pour des rebases propres avec l'upstream
allowed-tools: Bash(git add:*), Bash(git commit:*), Bash(git log:*), Bash(git status:*), Bash(git diff:*), Bash(git rebase:*), Bash(git push:*), Bash(git rev-parse:*), Bash(git branch:*), Write
---

# /optimise-commit — Commit optimisé pour eurelis/main

Tu es chargé de commiter les modifications courantes puis de les squasher dans le bon groupe de commits sur `eurelis/main`, afin de maintenir les commits atomiques qui minimisent les conflits lors des rebases upstream.

**Règle fondamentale** : les `fix` et les `feat` sont des groupes distincts et ne doivent jamais être mélangés dans un même commit. Cette séparation est indispensable pour la traçabilité des corrections et des évolutions.

## Paramètre

`$ARGUMENTS` = message de commit au format conventionnel (obligatoire).

Le message **doit** commencer par un préfixe conventionnel : `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `perf`.

Exemples :
- `/optimise-commit fix timeout in retrieval pipeline`
- `/optimise-commit feat add hybrid search support`
- `/optimise-commit docs update release guidelines`

## Contexte courant (injecté au lancement)

- Branche active : !`git branch --show-current`
- Modifications en attente : !`git status --short`
- Fichiers stagés : !`git diff --cached --name-only`
- Commits Eurelis actuels (du plus ancien au plus récent) : !`git log main..eurelis/main --oneline --reverse`

---

## ÉTAPE 0 — Vérifications préliminaires

1. **Branche** : la branche courante doit être `eurelis/main`. Sinon, **arrêter** :
   > ERREUR : Cette commande doit être exécutée sur eurelis/main.

2. **Message** : `$ARGUMENTS` ne doit pas être vide. Sinon, **arrêter** :
   > ERREUR : Un message de commit est requis. Usage : /optimise-commit \<message\>

3. **Préfixe conventionnel** : `$ARGUMENTS` doit commencer par `feat`, `fix`, `docs`, `chore`, `refactor`, `test` ou `perf`. Sinon, **avertir** :
   > ⚠ ATTENTION : Le message ne commence pas par un préfixe conventionnel reconnu.
   > Préfixes valides : feat, fix, docs, chore, refactor, test, perf.
   > Voulez-vous continuer avec ce message ?

   Attendre confirmation explicite avant de continuer.

4. **Modifications** : `git status --short` doit afficher des fichiers. Sinon, **arrêter** :
   > Rien à commiter.

---

## ÉTAPE 1 — Stager et commiter

Si des fichiers sont déjà stagés (`git diff --cached --name-only` non vide), utiliser uniquement les fichiers stagés. Sinon, stager tout :

```bash
git add -A
```

Récupérer la liste des fichiers dans le commit :

```bash
git diff --cached --name-only
```

Créer le commit :

```bash
git commit -m "$ARGUMENTS"
```

Noter le SHA du nouveau commit : `NEW_SHA=$(git rev-parse HEAD)`

---

## ÉTAPE 2 — Détection du groupe cible

Le groupe est déterminé en combinant les **fichiers modifiés** et le **préfixe du message** (`$ARGUMENTS`).

### Règles de routage (par ordre de priorité)

| Priorité | Groupe | Condition | Préfixe du commit cible |
|---|---|---|---|
| 1 | **deps** | Fichiers : `pyproject.toml`, `uv.lock`, `Makefile` | `feat(eurelis/deps):` |
| 2 | **fix** | Fichiers code Python (`rag/`, `api/`, `agent/`, `deepdoc/`) **et** message préfixé par `fix` ou `refactor` ou `perf` | `fix(eurelis):` |
| 3 | **feat** | Fichiers code Python (`rag/`, `api/`, `agent/`, `deepdoc/`) **et** message préfixé par `feat` ou `test` | `feat(eurelis):` |
| 4 | **tooling** | `.markdownlint*`, `.pre-commit*`, fichiers de config à la racine (`.json`, `.yaml`, `.toml`) hors `pyproject.toml` | `chore(eurelis):` |
| 5 | **docs** | `docs/`, `.claude/`, `README_EURELIS*`, `CHANGELOG*EURELIS*`, tout `.md` Eurelis-only | `docs(eurelis):` |

### Cas de mélange interdits

**fix + feat dans le même commit** : si les fichiers stagés contiennent des modifications qui relèvent à la fois d'un fix et d'une évolution (ex: message `fix` mais avec de nouveaux fichiers ou fonctionnalités), **arrêter** :
> ERREUR : Ce commit mélange une correction et une évolution. Séparez-les en deux commits distincts pour garantir la traçabilité :
> - Un commit `fix(eurelis): ...` pour la correction
> - Un commit `feat(eurelis): ...` pour l'évolution

**code + deps dans le même commit** : si les fichiers couvrent à la fois du code Python et des dépendances, **avertir** :
> ⚠ ATTENTION : Ce commit touche à la fois du code Python et des dépendances. Recommandation : séparer en deux commits distincts. Continuer en groupe 'deps' ?

Attendre confirmation explicite avant de continuer.

Afficher : `Groupe détecté : <groupe> → squash dans "<préfixe de commit cible>"`

---

## ÉTAPE 3 — Identifier le commit cible

Dans la liste `git log main..eurelis/main --oneline --reverse` (sans HEAD), trouver le commit dont le message **commence par** le préfixe du groupe.

Si aucun commit correspondant n'existe, **arrêter** :
> ERREUR : Aucun commit de groupe "<préfixe>" trouvé sur eurelis/main.
> Conseil : La structure de groupes n'est peut-être pas encore initialisée. Faites un premier commit manuel pour chaque groupe.

Noter son SHA : `TARGET_SHA`

---

## ÉTAPE 4 — Construire et exécuter le rebase

Construire le fichier todo `/tmp/eurelis-optimise-commit-todo` en reprenant **tous** les commits de `git log main..eurelis/main --oneline --reverse` (du plus ancien au plus récent), **en excluant** `NEW_SHA`, et en insérant `fixup NEW_SHA <message>` immédiatement après la ligne de `TARGET_SHA`.

Exemple (groupe fix, NEW_SHA = `abc1234`) :

```
pick 8cceaea85 feat(eurelis): improve tree-structured query decomposition retrieval
pick 388c823e0 feat(eurelis/deps): add Eurelis dependencies (zhipuai) and build tooling
pick f1a2b3c4d fix(eurelis): handle missing parent chunk in retrieval_by_children
fixup abc1234 fix timeout in retrieval pipeline
pick 6310984ab docs(eurelis): Eurelis documentation, guidelines, and Claude commands
```

Exemple (groupe feat, NEW_SHA = `abc1234`) :

```
pick 8cceaea85 feat(eurelis): improve tree-structured query decomposition retrieval
fixup abc1234 feat add hybrid search support
pick 388c823e0 feat(eurelis/deps): add Eurelis dependencies (zhipuai) and build tooling
pick f1a2b3c4d fix(eurelis): handle missing parent chunk in retrieval_by_children
pick 6310984ab docs(eurelis): Eurelis documentation, guidelines, and Claude commands
```

Exécuter :

```bash
GIT_SEQUENCE_EDITOR="cp /tmp/eurelis-optimise-commit-todo" git rebase -i main
```

En cas d'erreur de rebase, **arrêter** et afficher :
```
git rebase --abort   # pour annuler
git reset --hard HEAD~1  # pour défaire le commit créé à l'étape 1
```

---

## ÉTAPE 5 — Push

```bash
git push origin eurelis/main --force-with-lease
```

---

## RAPPORT FINAL

```
✓ Commit squashé dans le groupe <groupe>
✓ eurelis/main poussé sur origin

État actuel :
<git log main..eurelis/main --oneline>
```

---

## RÉSUMÉ DES CAS D'ARRÊT

| Situation | Action |
|---|---|
| Branche ≠ eurelis/main | Arrêt immédiat |
| Message vide | Arrêt immédiat |
| Préfixe non conventionnel | Avertissement + confirmation |
| Mélange fix + feat | Arrêt — demander séparation en deux commits |
| Fichiers code + deps mélangés | Avertissement + confirmation |
| Aucune modification | Arrêt immédiat |
| Groupe cible introuvable | Arrêt — conseil de structure |
| Erreur de rebase | Arrêt + commandes d'annulation |
| Push échoue | Arrêt — ne jamais forcer sans confirmation |
