# Feature : Provisionnement automatique des équipes via Keycloak

**Branche** : à définir (`eurelis/feature/keycloak-team-provisioning`)  
**Date** : 2026-06-17  
**Statut** : Spécification — non implémenté

---

## Objectif

Lors de la première connexion d'un utilisateur via le connecteur Keycloak (OIDC), l'assigner automatiquement à une ou plusieurs équipes RAGFlow sans passer par le flux d'invitation/approbation manuel.

Deux options sont envisagées selon le niveau de granularité souhaité.

---

## Contexte

Le mécanisme d'auto-provisionnement de comptes existe déjà : à la première connexion OIDC, RAGFlow crée automatiquement un compte utilisateur (User + Tenant + UserTenant owner + dossier racine). Le point d'injection est le callback OIDC dans `api/apps/restful_apis/user_api.py`.

L'appartenance aux équipes est gérée par le modèle `UserGroup` (feature `group_work`). L'assignation à une équipe nécessite actuellement une invitation manuelle par un admin.

---

## Option A — Équipes par défaut (config statique)

### Principe

Tous les utilisateurs créés via Keycloak sont automatiquement assignés à une liste fixe d'équipes, définie dans la configuration du connecteur.

### Configuration

Dans `conf/service_conf.yaml` (et `docker/service_conf.yaml.template`) :

```yaml
oauth:
  keycloak:
    type: "oidc"
    issuer: "http://host.docker.internal:8180/realms/ragflow"
    client_id: "ragflow-client"
    client_secret: "<secret>"
    redirect_uri: "http://localhost/api/v1/auth/oauth/keycloak/callback"
    default_teams:
      - "team-owner-1@example.com"
      - "team-owner-2@example.com"
```

> **Note** : les équipes sont identifiées par l'email de leur propriétaire (owner). En RAGFlow, le `tenant_id` d'une équipe est égal au `user_id` de son owner. L'implémentation résoudra l'email en `tenant_id` via `UserService.query(email=...)`.

### Flux

```
Connexion Keycloak
    → Callback OIDC
    → [nouveau compte] Création User + Tenant + UserTenant + dossier
    → Lecture oauth.keycloak.default_teams depuis la config
    → Pour chaque email : UserService.query(email) → tenant_id
    → TenantMgr.add_member(tenant_id, user_id, role="normal")
    → Connexion établie
```

### Fichiers impactés

| Fichier | Nature | Modification |
|---|---|---|
| `api/apps/restful_apis/user_api.py` | upstream | +5 lignes : appel hook post-création |
| `api/apps/auth/auto_team_provisioning.py` | **nouveau Eurelis** | logique d'assignation |
| `conf/service_conf.yaml` | upstream | champ `default_teams` |
| `docker/service_conf.yaml.template` | upstream | même champ |

### Avantages

- Empreinte minimale sur les fichiers upstream
- Simple à implémenter et à maintenir
- Logique isolée dans un fichier Eurelis pur

### Limites

- Granularité nulle : tous les utilisateurs Keycloak reçoivent les mêmes équipes
- Changement d'équipes → modification de config + redéploiement

---

## Option B — Mapping Keycloak groups → équipes RAGFlow

### Principe

Keycloak expose les groupes de l'utilisateur dans le `userinfo` endpoint (claim `groups`). Au callback, RAGFlow lit ce claim et assigne l'utilisateur aux équipes RAGFlow correspondantes selon un mapping configuré.

### Configuration

```yaml
oauth:
  keycloak:
    type: "oidc"
    issuer: "http://host.docker.internal:8180/realms/ragflow"
    client_id: "ragflow-client"
    client_secret: "<secret>"
    redirect_uri: "http://localhost/api/v1/auth/oauth/keycloak/callback"
    group_team_mapping:
      "/analysts":    "uuid-team-analysts"
      "/developers":  "uuid-team-dev"
      "/all-users":   "uuid-team-general"
```

### Prérequis Keycloak

1. Activer le mapper **Group Membership** sur le client Keycloak (`ragflow-client`)
2. Configurer le claim name `groups` (full path : `/analysts`, `/developers`, etc.)
3. Ajouter les utilisateurs aux groupes Keycloak correspondants

### Flux

```
Connexion Keycloak
    → Callback OIDC
    → Appel userinfo → { email, name, ..., groups: ["/analysts", "/all-users"] }
    → [nouveau compte] Création User + Tenant + UserTenant + dossier
    → Lecture oauth.keycloak.group_team_mapping depuis la config
    → Intersection(groupes utilisateur, mapping)
    → Pour chaque match : UserGroup.create(user_id, team_id, role="member")
    → Connexion établie
```

### Fichiers impactés

| Fichier | Nature | Modification |
|---|---|---|
| `api/apps/restful_apis/user_api.py` | upstream | +5 lignes : appel hook post-création |
| `api/apps/auth/auto_team_provisioning.py` | **nouveau Eurelis** | logique de mapping |
| `conf/service_conf.yaml` | upstream | champ `group_team_mapping` |
| `docker/service_conf.yaml.template` | upstream | même champ |

> **Note** : le claim `groups` est déjà disponible dans la réponse `userinfo` sans modifier `api/apps/auth/oidc.py`. Cela évite de toucher au parsing JWT.

### Avantages

- Granularité par utilisateur : chaque compte reçoit ses équipes selon son profil Keycloak
- Keycloak est la source de vérité pour les appartenances
- Changement d'équipes → modification dans Keycloak uniquement (sans redéploiement RAGFlow)

### Limites

- Nécessite une configuration Keycloak supplémentaire (mapper Group Membership)
- Mapping à maintenir en cohérence entre Keycloak et RAGFlow
- Empreinte légèrement plus large (parsing du claim `groups`)

---

## Comparaison

| Critère | Option A | Option B |
|---|---|---|
| Granularité | Identique pour tous | Par utilisateur |
| Source de vérité | Config RAGFlow | Keycloak |
| Changement sans redéploiement | Non | Oui |
| Empreinte upstream | Minimale | Minimale (via userinfo) |
| Complexité d'implémentation | Faible | Moyenne |
| Prérequis Keycloak | Aucun | Mapper Group Membership |

---

## Comportement commun aux deux options

- L'assignation n'a lieu **qu'à la création du compte** (première connexion)
- Les connexions suivantes ne modifient pas les appartenances (idempotence)
- Si une `team_id` référencée n'existe pas en base, l'erreur est loggée mais n'interrompt pas la connexion
- Le rôle assigné est `member` (non `owner`)
- Compatible avec les deux implémentations existantes (Python `user_api.py` et Go `internal/service/oauth_login.go`)

---

## Point d'implémentation

```python
# api/apps/auth/auto_team_provisioning.py (nouveau fichier)

import logging
from api.db.services import UserService
from admin.server.services import TenantMgr

def assign_default_teams(user_id: str, oauth_config: dict) -> None:
    """Assigne automatiquement l'utilisateur aux équipes configurées (Option A)."""
    for owner_email in oauth_config.get("default_teams", []):
        owners = UserService.query(email=owner_email)
        if not owners:
            logging.getLogger(__name__).warning(
                "default_teams: no user found for email %s, skipping", owner_email
            )
            continue
        tenant_id = owners[0].id
        _safe_assign(tenant_id, user_id)

def _safe_assign(tenant_id: str, user_id: str) -> None:
    try:
        TenantMgr.add_member(tenant_id, user_id, role="normal")
    except ValueError as e:
        # Déjà membre — silencieux
        logging.getLogger(__name__).debug(
            "Skipping team assignment for user %s in tenant %s: %s", user_id, tenant_id, e
        )
    except Exception:
        logging.getLogger(__name__).warning(
            "Failed to assign user %s to tenant %s", user_id, tenant_id, exc_info=True
        )
```

**Point d'injection dans `api/apps/restful_apis/user_api.py`** (ligne ~246, après `user_register`) :

```python
users = user_register(user_id, {...})
if not users:
    raise Exception(f"Failed to register {user_info.email}")

from api.apps.auth.eurelis_provisioning import assign_default_teams
assign_default_teams(user_id, channel_config)

user = users[0]
login_user(user)
```

Les deux options (A et B) peuvent coexister dans la même implémentation en étendant `assign_default_teams`.
