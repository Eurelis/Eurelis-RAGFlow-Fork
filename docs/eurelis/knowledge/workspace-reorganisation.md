---
title: "Réorganisation du workspace Eurelis RAGFlow"
type: knowledge
status: reference
---

# Réorganisation du workspace Eurelis RAGFlow

**Objectif :** regrouper `Eurelis-RAGFlow-Fork` et `Eurelis-RAGFlow-Shield` sous un dossier parent commun pour partager le contexte Claude Code en une seule session.

---

## Structure cible

```
1-Interne/
└── Eurelis-RAGFlow/
    ├── CLAUDE.md          ← contexte global (architecture, relation Fork↔Shield)
    ├── Fork/              ← ancien Eurelis-RAGFlow-Fork
    │   └── CLAUDE.md
    └── Shield/            ← ancien Eurelis-RAGFlow-Shield
        └── CLAUDE.md
```

Claude Code charge les CLAUDE.md en cascade : le parent au démarrage, puis ceux des sous-dossiers au fur et à mesure que Claude les explore.

---

## Procédure de migration

### 1. Créer le dossier parent et déplacer les projets

```bash
mkdir /Users/vincentlambert/Projects/1-Interne/Eurelis-RAGFlow

mv /Users/vincentlambert/Projects/1-Interne/Eurelis-RAGFlow-Fork \
   /Users/vincentlambert/Projects/1-Interne/Eurelis-RAGFlow/Fork

mv /Users/vincentlambert/Projects/1-Interne/Eurelis-RAGFlow-Shield \
   /Users/vincentlambert/Projects/1-Interne/Eurelis-RAGFlow/Shield
```

### 2. Migrer la mémoire Claude Code

La mémoire est stockée dans des dossiers nommés d'après le chemin absolu du projet.

```bash
# Fork
mv ~/.claude/projects/-Users-vincentlambert-Projects-1-Interne-Eurelis-RAGFlow-Fork \
   ~/.claude/projects/-Users-vincentlambert-Projects-1-Interne-Eurelis-RAGFlow-Fork-

# Shield (si existant)
mv ~/.claude/projects/-Users-vincentlambert-Projects-1-Interne-Eurelis-RAGFlow-Shield \
   ~/.claude/projects/-Users-vincentlambert-Projects-1-Interne-Eurelis-RAGFlow-Shield-
```

> **Note :** vérifier les noms exacts des dossiers mémoire avant de renommer :
> ```bash
> ls ~/.claude/projects/ | grep RAGFlow
> ```

### 3. Créer le CLAUDE.md parent

```bash
touch /Users/vincentlambert/Projects/1-Interne/Eurelis-RAGFlow/CLAUDE.md
```

Contenu minimal :

```markdown
# Eurelis — Plateforme RAGFlow

Deux projets fortement couplés, à travailler depuis ce dossier racine.

## Fork/
Fork d'infiniflow/ragflow — backend Python (Flask), frontend React/TypeScript.
Admin API sur :9381, RAGFlow API sur :9380.

## Shield/
Proxy FastAPI devant RAGFlow — authentification Keycloak, stratégies token.
Specs d'intégration dans Shield/docs/specs/.

## Relation
Les specs Shield décrivent les modifications à apporter au Fork.
Les routes admin du Fork (Fork/admin/server/routes.py) sont consommées par Shield.
```

### 4. Mettre à jour les références aux chemins absolus

Fichiers à vérifier après déplacement :

| Fichier | Référence à mettre à jour |
|---|---|
| `Shield/CLAUDE.md` | Chemins vers `Eurelis-RAGFlow-Fork/...` |
| `Shield/backend/.env` | `RAGFLOW_URL`, `RAGFLOW_ADMIN_URL` (généralement localhost — OK) |
| Aliases shell / bookmarks IDE | Selon l'environnement |

### 5. Lancer Claude depuis le dossier parent

```bash
cd /Users/vincentlambert/Projects/1-Interne/Eurelis-RAGFlow
claude
```

---

## Points sans impact

- **Git** : repos auto-contenus, remotes = URLs — aucun changement
- **npm / Vite** : chemins relatifs — aucun changement
- **Docker** : volumes et ports — aucun changement
- **Configs projet** (`.env`, `.claude/settings.json`) : se déplacent avec le dossier
