# Gestion du fork — Fork Eurelis de RAGFlow

La meilleure approche est le **fork Git avec synchronisation upstream**, combinée à une discipline de branches rigoureuse. Voici la stratégie complète :

## Initialisation du fork

**Sur GitHub**, forker le dépôt `infiniflow/ragflow` vers ton organisation (ex: `eurelis/ragflow`).

Puis en local :

```bash
git clone https://github.com/eurelis/ragflow.git
cd ragflow

# Ajouter le dépôt officiel comme remote "upstream"
git remote add upstream https://github.com/infiniflow/ragflow.git

# Vérification
git remote -v
# origin    https://github.com/eurelis/ragflow.git (fetch/push)
# upstream  https://github.com/infiniflow/ragflow.git (fetch/push)
```

## Structure de branches recommandée

```
upstream/main  (ragflow officiel)
      │
      ▼
    main                ← miroir propre de l'upstream (jamais de commits ici)
      │
      ├── eurelis/main  ← modifications transversales stables
      │
      └── feature/xxx ← fonctionnalités spécifiques
```

La règle d'or : **`main` ne contient que du code upstream**. Tes modifications vivent exclusivement dans des branches dédiées.

## Workflow de synchronisation avec l'upstream

À faire régulièrement (idéalement à chaque release RAGFlow) :

```bash
# 1. Récupérer les nouveautés upstream
git fetch upstream

# 2. Mettre à jour ton main local
git checkout main
git merge upstream/main   # fast-forward uniquement
git push origin main

# 3. Rebaser tes branches perso sur le nouveau main
git checkout eurelis/main
git rebase main

# Résoudre les conflits éventuels, puis :
git push origin core --force-with-lease
```

Préfère **`rebase`** à `merge` pour tes branches perso : l'historique reste linéaire et les conflits sont plus faciles à identifier.

## Minimiser les conflits futurs — bonnes pratiques

**Isoler tes modifications** est la clé pour une vie sereine :

- **Ne jamais modifier** les fichiers core de RAGFlow directement si tu peux les *étendre* (héritage, hooks, plugins, surcharge de configuration).
- **Préférer la configuration** à la modification de code : variables d'environnement, fichiers de config séparés, feature flags.
- **Créer tes propres modules** dans des répertoires dédiés (`eurelis/`, `kuhn/`) plutôt que d'insérer du code dans les modules existants.
- **Documenter chaque modification** avec un commentaire `# EURELIS: raison du changement` pour les retrouver facilement lors des rebase.

## Gérer les conflits lors du rebase

```bash
git rebase main
# Conflit détecté...

# Voir les fichiers en conflit
git status

# Résoudre manuellement, puis :
git add fichier_resolu.py
git rebase --continue

# En cas de blocage total :
git rebase --abort
```

Pour les conflits complexes, `git rerere` (Reuse Recorded Resolution) peut automatiser la résolution de conflits récurrents :

```bash
git config rerere.enabled true
```

## Suivi des releases upstream

Pour ne pas rater les nouvelles versions de RAGFlow :

- **Activer les "Watch > Releases only"** sur le dépôt GitHub upstream.
- Consulter le `CHANGELOG.md` avant chaque synchronisation pour anticiper les breaking changes.
- Maintenir un fichier `EURELIS_CHANGES.md` listant toutes tes modifications avec leur justification — indispensable pour auditer rapidement l'impact d'une nouvelle version.

## Résumé

| Branche        | Rôle                       | Modifiable ?            |
|----------------|----------------------------|-------------------------|
| `main`         | Miroir exact de l'upstream | ❌ Jamais                |
| `eurelis/main` | Version modifiée           | ✅                       |
| `feature/*`    | Développements spécifiques | ✅                       |
| `release/*`    | Livraisons clients         | ✅ (depuis core/feature) |

Cette stratégie te permet de **livrer tes modifications Kuhn-RAGFlow** à tout moment sur tes branches, tout en absorbant les mises à jour de RAGFlow avec un effort minimal. Le point de vigilance principal sera les rebase après les grosses releases upstream — d'où l'importance de garder tes changements bien isolés dès le départ.
