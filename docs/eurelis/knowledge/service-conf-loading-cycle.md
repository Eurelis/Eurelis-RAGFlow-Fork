# Cycle de chargement et mise à jour de `service_conf.yaml`

## Vue d'ensemble

`service_conf.yaml.template` est le fichier source versionné qui définit la configuration de tous les services RAGFlow. Il n'est jamais lu directement par Python — il est d'abord transformé en `conf/service_conf.yaml` par le script de démarrage du conteneur.

```
docker/.env
    │
    ▼ (démarrage conteneur)
entrypoint.sh  ──substitution vars──►  conf/service_conf.yaml
                                               │
                                               │ (import Python — une fois)
                                               ▼
                                   CONFIGS = read_config()  ◄── conf/local.service_conf.yaml
                                               │                 (surcharge optionnelle)
                                               │ (démarrage Flask)
                                               ▼
                                   init_settings() → connexions DB, LLM, stockage…
                                               │
                                               │ (runtime)
                                               ▼
                                   update_config() → réécrit le fichier disque
                                   ⚠️  CONFIGS en mémoire non mis à jour
```

---

## Étape 1 — Génération du fichier de configuration (`entrypoint.sh:155-176`)

Au démarrage du conteneur, `entrypoint.sh` lit le template ligne par ligne et substitue les variables d'environnement selon la syntaxe `${VAR:-default}` :

- Si `$VAR` est défini dans l'environnement Docker → utilise sa valeur
- Sinon → utilise la valeur par défaut déclarée dans le template

```bash
TEMPLATE_FILE="/ragflow/conf/service_conf.yaml.template"
CONF_FILE="/ragflow/conf/service_conf.yaml"

rm -f "${CONF_FILE}"
while IFS= read -r line; do
    # substitue ${VAR:-default} et écrit dans CONF_FILE
    ...
done < "${TEMPLATE_FILE}"
```

Les valeurs de `docker/.env` sont injectées dans l'environnement du conteneur par Docker Compose, ce qui permet de surcharger n'importe quel paramètre sans modifier le template.

Cette étape est **exécutée une seule fois** par démarrage de conteneur, avant tout processus Python.

---

## Étape 2 — Chargement en mémoire à l'import (`common/config_utils.py:55-75`)

Dès qu'un module Python importe `common.config_utils`, la ligne suivante s'exécute **au niveau module** :

```python
CONFIGS = read_config()  # exécuté une seule fois, à l'import
```

`read_config()` applique une logique de fusion en deux couches :

1. Charge `conf/service_conf.yaml` (le fichier généré) comme config globale
2. Charge `conf/local.service_conf.yaml` si le fichier existe (non versionné, pour surcharges locales)
3. La config locale écrase la config globale clé par clé (`global_config.update(local_config)`)

Le résultat est stocké dans le dict module-level `CONFIGS`, utilisé par toute l'application via `get_base_config()`.

---

## Étape 3 — Initialisation des services (`common/settings.py:init_settings()`)

Appelée au démarrage du serveur Flask (`api/ragflow_server.py`), `init_settings()` lit `CONFIGS` pour instancier toutes les connexions :

| Variable globale    | Clé dans `service_conf.yaml` | Service                          |
|---------------------|------------------------------|----------------------------------|
| `DATABASE`          | `mysql` / `oceanbase`        | Base de données principale       |
| `LLM_FACTORY`       | `user_default_llm.factory`   | Fournisseur LLM par défaut       |
| `STORAGE_IMPL`      | env `STORAGE_IMPL`           | MinIO, S3, Azure, GCS…           |
| `AUTHENTICATION_CONF` | `authentication`           | Auth client / site               |
| `OAUTH_CONFIG`      | `oauth`                      | OAuth2 / OIDC / GitHub           |
| `SMTP_CONF`         | `smtp`                       | Envoi d'emails                   |

Le moteur de documents (`DOC_ENGINE`) est lu depuis la variable d'environnement `DOC_ENGINE` et non depuis `service_conf.yaml` — il doit donc être défini dans `docker/.env`.

---

## Étape 4 — Mise à jour à l'exécution (`common/config_utils.py:update_config()`)

```python
def update_config(key, value, conf_name=SERVICE_CONF):
    conf_path = conf_realpath(conf_name=conf_name)
    with FileLock(os.path.join(os.path.dirname(conf_path), ".lock")):
        config = load_yaml_conf(conf_path=conf_path)
        config[key] = value
        rewrite_yaml_conf(conf_path=conf_path, config=config)
```

- Utilise un **verrou fichier** pour éviter les écritures concurrentes entre workers
- Réécrit `conf/service_conf.yaml` sur disque
- **Ne met pas à jour `CONFIGS` en mémoire** — les processus en cours continuent d'utiliser l'ancienne valeur

Usages dans le code : persistance de la clé secrète JWT générée automatiquement au premier démarrage (`settings._get_or_create_secret_key()`).

---

## Surcharge locale sans redémarrage

Pour modifier la configuration sans rebuilder l'image, créer `conf/local.service_conf.yaml` avec uniquement les clés à surcharger :

```yaml
# conf/local.service_conf.yaml — non versionné
mysql:
  host: 'localhost'
  port: 3307
```

Ce fichier est fusionné au-dessus de `service_conf.yaml` à chaque démarrage du processus Python.

---

## Appliquer un changement de configuration

| Contexte                  | Action                                                              |
|---------------------------|---------------------------------------------------------------------|
| Variable Docker (`.env`)  | Modifier `docker/.env` puis `docker compose restart`               |
| Surcharge locale          | Créer/modifier `conf/local.service_conf.yaml` puis redémarrer Flask|
| Nouveau moteur de docs    | Modifier `DOC_ENGINE` dans `.env` puis `docker compose down -v && docker compose up -d` |
| Valeur runtime persistée  | `update_config()` écrit sur disque — effet au prochain démarrage   |

> **Important** : il n'existe pas de mécanisme de rechargement à chaud (`hot-reload`) de la configuration. Tout changement nécessite un redémarrage du processus Python concerné.

---

## Fichiers clés

| Fichier                                    | Rôle                                                      |
|--------------------------------------------|-----------------------------------------------------------|
| `docker/service_conf.yaml.template`        | Template source versionné avec variables `${VAR:-default}`|
| `conf/service_conf.yaml`                   | Fichier généré au démarrage (non versionné)               |
| `conf/local.service_conf.yaml`             | Surcharges locales optionnelles (non versionné)           |
| `docker/entrypoint.sh`                     | Génère `service_conf.yaml` depuis le template             |
| `common/config_utils.py`                   | Charge, expose et met à jour la configuration             |
| `common/settings.py`                       | Instancie les connexions aux services au démarrage        |
