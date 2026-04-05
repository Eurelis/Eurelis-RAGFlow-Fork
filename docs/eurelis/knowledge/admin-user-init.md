# Initialisation de l'utilisateur admin par défaut

## Vue d'ensemble

L'utilisateur admin (`admin@ragflow.io`) n'est **pas créé automatiquement** au démarrage. Il existe deux mécanismes distincts selon le contexte d'usage, et une subtilité importante entre login UI et authentification HTTP Basic.

---

## Credentials par défaut

Définis dans `api/db/init_data.py:47-49`, surchargeables par variables d'environnement :

| Variable d'env | Valeur par défaut |
|---|---|
| `DEFAULT_SUPERUSER_EMAIL` | `admin@ragflow.io` |
| `DEFAULT_SUPERUSER_PASSWORD` | `admin` |
| `DEFAULT_SUPERUSER_NICKNAME` | `admin` |

---

## Mécanisme 1 — Initialisation explicite (`--init-superuser`)

### Déclenchement

```bash
# Local
python api/ragflow_server.py --init-superuser

# Docker (flag entrypoint)
./entrypoint.sh --init-superuser
```

`--init-superuser` appelle `init_superuser()` puis **le serveur continue de démarrer normalement** — ce n'est pas un `sys.exit()`, une seule commande suffit.

### Ce que fait `init_superuser()` (`api/db/init_data.py:50`)

1. Vérifie si un user avec cet email existe déjà → **idempotent**, skip si oui
2. Crée le user avec `is_superuser=True`, mot de passe encodé en base64
3. Crée le **tenant** associé (nom : `"admin's Kingdom"`)
4. Crée la liaison `UserTenant` avec le rôle `OWNER`
5. Crée les `TenantLLM` depuis la config par défaut

C'est le **seul mécanisme qui crée un user complet avec tenant**. Sans tenant, les fonctionnalités RAG (bases de connaissances, modèles, dialogues) ne sont pas accessibles.

> `init_web_data()` contenait un appel commenté à `init_superuser()` (`init_data.py:194`) — il n'est donc pas exécuté au démarrage normal.

---

## Mécanisme 2 — Auto-création dans `check_admin()` (`admin/server/auth.py:190`)

Utilisé uniquement pour l'**authentification HTTP Basic** sur les routes admin (CLI, SDK) :

```python
def check_admin(username, password):
    users = UserService.query(email=username)
    if not users:
        # auto-crée l'user si absent
        UserService.save(email="admin@ragflow.io", is_superuser=True, ...)
```

⚠️ Ce mécanisme crée le user **sans tenant** — il débloque l'accès CLI/API mais pas le login UI.

---

## Flux du login UI (`POST /api/v1/admin/login`)

Implémenté dans `admin/server/auth.py:login_admin()` :

```
email + password (formulaire)
        │
        ▼
UserService.query(email=email)
        │── absent → UserNotFoundError → HTTP 500
        ▼
UserService.query_user(email, password_décrypté)
        │── mauvais mot de passe → AdminException → HTTP 500
        ▼
user.is_superuser == True ?
        │── False → AdminException 403
        ▼
user.is_active == ACTIVE ?
        │── False → AdminException 403
        ▼
Génère access_token, sauvegarde last_login_time
→ Retourne session + token
```

Le login UI **refuse** les users sans `is_superuser=True` — un user créé via `check_admin()` (sans tenant) peut se connecter à l'UI admin, mais rencontrera des erreurs sur les opérations qui nécessitent un tenant.

---

## Récapitulatif par contexte

| Contexte | Commande | User créé | Tenant créé |
|---|---|---|---|
| Premier démarrage local | `python api/ragflow_server.py --init-superuser` | ✓ | ✓ |
| Conteneur Docker | `./entrypoint.sh --init-superuser` | ✓ | ✓ |
| Appel CLI/SDK sans user en DB | automatique via `check_admin()` | ✓ | ✗ |

---

## Fichiers clés

| Fichier | Rôle |
|---|---|
| `api/db/init_data.py:50` | `init_superuser()` — création complète user + tenant |
| `api/ragflow_server.py:120` | Traitement du flag `--init-superuser` |
| `docker/entrypoint.sh:92` | Propagation du flag `--init-superuser` au serveur |
| `admin/server/auth.py:162` | `login_admin()` — login UI, vérifie `is_superuser` |
| `admin/server/auth.py:190` | `check_admin()` — auth HTTP Basic, auto-création sans tenant |
