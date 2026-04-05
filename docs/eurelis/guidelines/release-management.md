# Release et build des images — Fork Eurelis de RAGFlow

## Gestion des releases

### Branches

| Branche               | Rôle                             |
|-----------------------|----------------------------------|
| `main`                | Upstream RAGFlow (lecture seule) |
| `eurelis/main`        | Branche principale Eurelis       |
| `eurelis/feature/xxx` | Développements en cours          |

### Workflow

```
eurelis/feature/xxx
        │
        │  PR + merge (--no-ff)
        ▼
  eurelis/main  ──────────────────► tag vX.Y.Z-eurelis.N
```

#### Merger une feature

```bash
git checkout eurelis/main
git merge eurelis/feature/xxx --no-ff
git push origin eurelis/main
```

### Versioning

Format : **`vX.Y.Z-eurelis.N`**

- `X.Y.Z` — version RAGFlow upstream de base
- `N` — numéro de release Eurelis sur cette base (commence à 1)

Exemples :
- `v0.24.0-eurelis.1` — première release Eurelis sur RAGFlow v0.24.0
- `v0.24.0-eurelis.2` — patch Eurelis sur la même base upstream
- `v0.25.0-eurelis.1` — après sync avec RAGFlow v0.25.0

> Le tag doit commencer par `v` pour être reconnu par le `Dockerfile`
> (`git describe --tags --match=v*`) et affiché correctement dans le frontend.

### Créer une release

```bash
# 1. S'assurer que eurelis/main est à jour et poussé
git checkout eurelis/main
git push origin eurelis/main

# 2. Mettre à jour CHANGELOG-EURELIS.md et commiter
git add CHANGELOG-EURELIS.md
git commit -m "docs: changelog vX.Y.Z-eurelis.N"
git push origin eurelis/main

# 3. Créer et pousser le tag
git tag vX.Y.Z-eurelis.N eurelis/main
git push origin vX.Y.Z-eurelis.N
```

> Si le tag doit être déplacé (ex. commit ajouté après la pose du tag) :
> ```bash
> git tag -d vX.Y.Z-eurelis.N
> git tag vX.Y.Z-eurelis.N eurelis/main
> git push origin :refs/tags/vX.Y.Z-eurelis.N
> git push origin vX.Y.Z-eurelis.N
> ```

### Synchronisation avec l'upstream

Régulièrement, intégrer les évolutions de RAGFlow dans `eurelis/main` :

```bash
git fetch origin
git checkout eurelis/main
git merge main
git push origin eurelis/main
```

Après une sync avec une nouvelle version upstream, incrémenter `X.Y.Z` et remettre `N` à 1.

### CHANGELOG

Le fichier `CHANGELOG-EURELIS.md` à la racine du projet documente uniquement les modifications Eurelis (hors commits upstream).

Structure d'une entrée :

```markdown
## [vX.Y.Z-eurelis.N] - YYYY-MM-DD

Basé sur RAGFlow `vX.Y.Z`.

### Added
### Changed
### Fixed
### Removed
```

## Build et publication de l'image Docker

### Prérequis

- Docker Desktop ≥ 24.0.0 avec **16 GB de RAM** alloués minimum
- Être connecté à Docker Hub : `docker login`
- Tag git posé sur `eurelis/main` (voir section *Créer une release*)

### Première fois : créer le builder multi-platform

```bash
docker buildx create --name eurelis-builder --driver docker-container --bootstrap
docker buildx use eurelis-builder
```

> Ce builder est à créer une seule fois. Vérifier qu'il existe : `docker buildx ls`

### Télécharger les dépendances

À faire une fois, ou si `pyproject.toml` ou `download_deps.py` ont changé :

```bash
uv run download_deps.py
docker build -f Dockerfile.deps -t infiniflow/ragflow_deps .
```

### Build et push

```bash
docker buildx build \
  --builder eurelis-builder \
  --platform linux/amd64 \
  -t eurelis/ragflow:vX.Y.Z-eurelis.N \
  -t eurelis/ragflow:latest \
  --push \
  .
```

> Le flag `--push` envoie directement sur Docker Hub sans stocker l'image en local.
> Le flag `--no-cache` peut être ajouté pour forcer un build complet (plus long).

### Support ARM64

Le build `linux/arm64` est bloqué par un bug de signature GPG sur `ports.ubuntu.com`
lors d'un build cross-platform depuis Mac Apple Silicon. En attendant un fix upstream :
- Construire `linux/amd64` depuis Mac
- Construire `linux/arm64` depuis un serveur ARM natif, puis merger les manifests

### Problèmes courants

| Erreur                              | Cause                                             | Solution                                           |
|-------------------------------------|---------------------------------------------------|----------------------------------------------------|
| `No space left on device`           | Cache BuildKit ou disque virtuel Docker plein     | `docker buildx prune --builder eurelis-builder -f` |
| `cannot allocate memory`            | RAM insuffisante pour `npm run build`             | Augmenter la RAM Docker Desktop à 16 GB            |
| `The service was stopped` (esbuild) | Build concurrent ou builder dans un état instable | `docker buildx stop eurelis-builder` puis relancer |
| GPG error `ports.ubuntu.com`        | Clés Ubuntu ARM64 obsolètes                       | Construire en `linux/amd64` uniquement             |

## Mise à jour de l'image Docker d'une instance RAGFlow

Pour mettre à jour une instance existante (sans réinstallation complète) :

```bash
# 1. Se placer dans le dossier docker
cd docker

# 2. Modifier RAGFLOW_IMAGE dans .env
# RAGFLOW_IMAGE=eurelis/ragflow:vX.Y.Z-eurelis.N

# 3. Tirer la nouvelle image
docker pull eurelis/ragflow:vX.Y.Z-eurelis.N

# 4. Identifier le nom du service ragflow
docker compose ps

# 5. Recréer uniquement le conteneur ragflow (sans toucher aux données)
docker compose up -d --no-deps <nom-du-service-ragflow>
# Nom du service par défaut : ragflow-cpu
```

> `--no-deps` est important : il évite de redémarrer les services dépendants (MySQL, Elasticsearch, Redis, MinIO).

Le nom du service ragflow peut varier selon l'installation. Exemples observés :
- `ragflow-server`
- `ragflow-cpu`

Le nom du conteneur Docker (ex. `devai-labeurelisinfo-ragflow-cpu-1`) permet de déduire le nom du service (`ragflow-cpu`).

## Où est affichée la version ?

La version est générée à la build Docker via `git describe` (`Dockerfile:173`) et stockée dans `/ragflow/VERSION`. Elle est ensuite lue au démarrage (`docker/entrypoint.sh`) et exposée au frontend.
