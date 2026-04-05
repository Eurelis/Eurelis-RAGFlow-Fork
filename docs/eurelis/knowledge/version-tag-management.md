# Gestion des tags de version affichés dans RAGFlow

## Vue d'ensemble

La version affichée dans RAGFlow est générée **une seule fois, au moment du build Docker**, depuis l'historique git. Elle est figée dans un fichier `/ragflow/VERSION` embarqué dans l'image et propagée à tous les points d'affichage — logs, API, interface web — via une seule fonction Python.

```
git describe (build Docker)
        │
        ▼
/ragflow/VERSION             ← fichier texte dans l'image
        │
        ├─► entrypoint.sh     cat /ragflow/VERSION          (logs de démarrage)
        │
        ├─► ragflow_server.py  get_ragflow_version()         (log "RAGFlow version: …")
        │
        ├─► GET /v1/system/version                           (API REST principale)
        │
        └─► GET /api/v1/admin/version                        (API admin)
                │
                ▼
        web/src/hooks/use-user-setting-request.tsx           (affichage frontend)
```

---

## Étape 1 — Génération à la construction (`Dockerfile:162-165`)

```dockerfile
RUN version_info=$(git describe --tags --match=v* --first-parent --always); \
    echo "RAGFlow version: $version_info"; \
    echo $version_info > /ragflow/VERSION
```

La commande `git describe --tags --match=v* --first-parent --always` produit :

| Situation | Résultat |
|---|---|
| Commit pointé exactement par un tag `v*` | `v0.25.1` |
| N commits après le dernier tag trouvé | `v0.25.1-N-gSHA` |
| Aucun tag `v*` accessible | short SHA seul |

`--first-parent` ne remonte que la lignée principale (ignore les branches mergées). `--always` garantit un résultat même sans tag.

Le fichier `/ragflow/VERSION` est ensuite copié du stage `builder` vers l'image finale (`Dockerfile:207`) :

```dockerfile
COPY --from=builder /ragflow/VERSION /ragflow/VERSION
```

---

## Étape 2 — Lecture Python (`common/versions.py`)

```python
def get_ragflow_version() -> str:
    global RAGFLOW_VERSION_INFO
    if RAGFLOW_VERSION_INFO != "unknown":
        return RAGFLOW_VERSION_INFO          # ← mémoïsation, lu une seule fois

    version_path = os.path.join(..., "VERSION")
    if os.path.exists(version_path):
        with open(version_path) as f:
            RAGFLOW_VERSION_INFO = f.read().strip()
    else:
        RAGFLOW_VERSION_INFO = get_closest_tag_and_count()  # ← fallback git describe live
    return RAGFLOW_VERSION_INFO
```

Le fallback `get_closest_tag_and_count()` réexécute `git describe` à l'exécution — utile en développement local hors Docker, où `/ragflow/VERSION` n'existe pas.

---

## Étape 3 — Exposition via l'API (`api/apps/restful_apis/system_api.py:41`)

```python
@manager.route("/system/version", methods=["GET"])
@login_required
def version():
    return get_json_result(data=get_ragflow_version())
```

Endpoint : `GET /v1/system/version` — requiert une session authentifiée.

Le serveur admin expose également la version sur `GET /api/v1/admin/version` (consommé par `admin/client/ragflow_client.py`).

---

## Étape 4 — Affichage frontend (`web/src/hooks/use-user-setting-request.tsx:207`)

```typescript
const fetchSystemVersion = useCallback(async () => {
    const { data } = await userService.getSystemVersion();  // → /v1/system/version
    setVersion(data.data);
}, []);
```

La version est affichée dans les paramètres utilisateur (profil / à propos).

---

## Comportement spécifique au fork Eurelis

Sur `eurelis/main`, `git describe` retourne `v0.23.1-N-gSHA` au lieu du tag upstream courant (`v0.25.1`) pour la raison suivante :

- Le rebase réécrit les commits upstream avec de nouveaux SHAs
- Les tags upstream (`v0.24.0`, `v0.25.1`, etc.) pointent vers les SHAs **originaux**, absents du dépôt local
- `git describe` ne trouve donc que les tags importés dans le dépôt local — en l'occurrence le dernier tag présent depuis la création du fork : `v0.23.1`

```
upstream repo :   … ──[v0.23.1]── … ──[v0.24.0]── … ──[v0.25.1]── HEAD
                                              ↕ tags pointent vers ces SHAs

eurelis/main :    … ──[v0.23.1]── … ──(commits réécrits sans tag)── HEAD
                                              ↑
                                     git describe s'arrête ici
```

### Options pour afficher une version pertinente

| Option | Commande | Résultat affiché |
|---|---|---|
| Tag Eurelis local | `git tag eurelis/v0.25.1 HEAD` | `eurelis/v0.25.1` |
| Tag Eurelis avec distance | tag sur base + commits | `eurelis/v0.25.1-N-gSHA` |
| Version fixe dans le Dockerfile | `ARG RAGFLOW_VERSION=eurelis-v0.25.1` + `echo $RAGFLOW_VERSION > /ragflow/VERSION` | chaîne fixe |

La stratégie recommandée : poser un tag `eurelis/vX.Y.Z` à chaque sync upstream réussi — cela donne une version lisible sans modifier le Dockerfile.

```bash
git tag eurelis/v0.25.1
# puis au prochain build Docker : affichera "eurelis/v0.25.1" ou "eurelis/v0.25.1-N-gSHA"
```

---

## Fichiers clés

| Fichier | Rôle |
|---|---|
| `Dockerfile:162-165` | Génère `/ragflow/VERSION` via `git describe` au build |
| `/ragflow/VERSION` | Fichier texte embarqué dans l'image (non versionné) |
| `common/versions.py` | Lit `VERSION`, expose `get_ragflow_version()` |
| `api/apps/restful_apis/system_api.py:41` | Endpoint REST `GET /v1/system/version` |
| `web/src/hooks/use-user-setting-request.tsx:207` | Récupère et affiche la version dans le frontend |
| `docker/entrypoint.sh:6` | Affiche la version au démarrage du conteneur |
