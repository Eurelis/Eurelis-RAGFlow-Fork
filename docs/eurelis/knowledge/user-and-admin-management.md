---
title: "Gestion des utilisateurs et administration RAGFlow"
type: knowledge
status: reference
date: 2026-05-22
---

# Gestion des utilisateurs et administration RAGFlow

---

## Modèle conceptuel

Dans RAGFlow, chaque utilisateur **est son propre tenant** : `user.id == tenant_id`. Les "équipes" sont formées en invitant d'autres utilisateurs dans son tenant. Il n'y a pas de hiérarchie organisationnelle distincte.

**Rôles dans une équipe :**

| Rôle     | Description                                                         |
|----------|---------------------------------------------------------------------|
| `OWNER`  | Propriétaire du tenant — seul à pouvoir inviter/retirer des membres |
| `NORMAL` | Membre accepté                                                      |
| `INVITE` | Invitation en attente d'acceptation                                 |

**Rôle global :**

| Champ          | Description                     |
|----------------|---------------------------------|
| `is_superuser` | Accès au panel d'administration |

---

## API utilisateurs (accès authentifié standard)

Base : `/api/v1`

### Authentification

| Endpoint                           | Méthode | Description                              |
|------------------------------------|---------|------------------------------------------|
| `/auth/login`                      | POST    | Login email/password                     |
| `/auth/logout`                     | POST    | Logout                                   |
| `/auth/login/channels`             | GET     | Canaux OAuth disponibles (GitHub, OIDC…) |
| `/auth/login/{channel}`            | GET     | Redirection OAuth                        |
| `/auth/password/forgot/captcha`    | POST    | Captcha pour reset de mot de passe       |
| `/auth/password/forgot/otp`        | POST    | Envoi OTP par email                      |
| `/auth/password/forgot/otp/verify` | POST    | Vérification OTP                         |
| `/auth/password/reset`             | POST    | Réinitialisation du mot de passe         |

### Inscription

| Endpoint | Méthode | Description                        |
|----------|---------|------------------------------------|
| `/users` | POST    | Créer un compte (auto-inscription) |

> **Contrainte :** nécessite `REGISTER_ENABLED=true` dans la configuration du serveur. Il n'existe pas d'endpoint standard pour créer un utilisateur à la place d'un autre — c'est le rôle du panel admin.

**Body :**
```json
{ "nickname": "Alice", "email": "alice@example.com", "password": "<encrypted>" }
```

### Profil utilisateur courant

| Endpoint           | Méthode | Description                     |
|--------------------|---------|---------------------------------|
| `/users/me`        | GET     | Profil de l'utilisateur courant |
| `/users/me`        | PATCH   | Modifier son profil             |
| `/users/me/models` | GET     | Configuration LLM du tenant     |
| `/users/me/models` | PATCH   | Modifier la configuration LLM   |

---

## API équipes / tenants (accès authentifié standard)

Base : `/api/v1`

| Endpoint                     | Méthode | Restriction              | Description                                                     |
|------------------------------|---------|--------------------------|-----------------------------------------------------------------|
| `/tenants`                   | GET     | Authentifié              | Lister les équipes auxquelles l'utilisateur appartient          |
| `/tenants/{tenant_id}/users` | GET     | Owner uniquement         | Lister les membres de l'équipe                                  |
| `/tenants/{tenant_id}/users` | POST    | Owner uniquement         | Inviter un utilisateur par email → envoie un email d'invitation |
| `/tenants/{tenant_id}/users` | DELETE  | Owner ou membre lui-même | Retirer un membre                                               |
| `/tenants/{tenant_id}`       | PATCH   | Membre invité            | Accepter une invitation (passage de `INVITE` → `NORMAL`)        |

> **Contrainte :** l'invitation nécessite que l'invité possède déjà un compte RAGFlow (`POST /users` ou login OAuth préalable).

---

## Provisionnement automatique via SSO (OIDC / OAuth)

### Auto-création de compte

À la **première connexion** via un canal SSO (OIDC, OAuth2, GitHub), si l'email n'existe pas encore, RAGFlow **crée automatiquement le compte** (User + Tenant + relation `UserTenant` owner + dossier racine). Le point d'injection est le callback dans `api/apps/restful_apis/user_api.py` (`oauth_callback`).

> **⚠️ Non gardé par `REGISTER_ENABLED`.** Ce flag ne protège que l'inscription par mot de passe (`POST /users`). Le login SSO auto-provisionne toujours un compte si l'email est inconnu — le seul « contrôle » est la présence du canal dans `OAUTH_CONFIG`.

### Assignation aux équipes par défaut (`default_teams`) — *fork Eurelis*

À la création d'un compte SSO, l'utilisateur peut être **automatiquement ajouté comme membre (`NORMAL`)** à une liste d'équipes prédéfinies. Configuré par canal dans la section `oauth` du `service_conf.yaml` :

```yaml
oauth:
  keycloak:
    type: "oidc"
    issuer: "..."
    client_id: "..."
    client_secret: "..."
    redirect_uri: "..."
    default_teams:                 # ← clé propre au fork Eurelis
      - "team-owner-1@example.com" # email du propriétaire (owner) de l'équipe
      - "team-owner-2@example.com"
```

- Chaque entrée est l'**email de l'owner** d'une équipe (rappel : `tenant_id == user.id` de l'owner).
- L'assignation n'a lieu **qu'à la création** du compte ; les connexions suivantes ne modifient pas les appartenances (idempotent).
- Rôle assigné : `NORMAL` (jamais `OWNER`).
- Robuste : un email owner introuvable ou une erreur d'insertion est loggé mais **ne bloque jamais le login**.

Implémentation : `api/apps/auth/auto_team_provisioning.py` (fonction `assign_default_teams`). Conception et alternative envisagée (mapping groupes Keycloak) : voir [`features/done/keycloak-team-provisioning.md`](../features/done/keycloak-team-provisioning.md).

---

## Panel d'administration

### Architecture

Le panel admin est un **serveur Flask séparé** situé dans `admin/` à la racine du projet. Il tourne sur un port distinct et expose les routes `/api/v1/admin/...`. Il n'est pas intégré dans le serveur API principal (`api/`).

### Authentification admin

Login séparé via `POST /api/v1/admin/login`. Seuls les utilisateurs avec `is_superuser=True` peuvent s'authentifier.

**Compte superuser par défaut** (créé automatiquement si aucun superuser n'existe) :
```
email    : admin@ragflow.io
password : admin
```

> À changer impérativement en production.

### Endpoints d'administration

Base : `/api/v1/admin`

#### Utilisateurs

| Endpoint                             | Méthode | Description                                                   |
|--------------------------------------|---------|---------------------------------------------------------------|
| `/admin/login`                       | POST    | Login admin                                                   |
| `/admin/logout`                      | GET     | Logout admin                                                  |
| `/admin/users`                       | GET     | Lister tous les utilisateurs                                  |
| `/admin/users`                       | POST    | Créer un utilisateur                                          |
| `/admin/users/{username}`            | GET     | Détail d'un utilisateur                                       |
| `/admin/users/{username}`            | DELETE  | Supprimer un utilisateur                                      |
| `/admin/users/{username}/password`   | PUT     | Changer le mot de passe                                       |
| `/admin/users/{username}/activate`   | PUT     | Activer / désactiver (`{ "activate_status": "on" \| "off" }`) |
| `/admin/users/{username}/admin`      | PUT     | Accorder le rôle superuser                                    |
| `/admin/users/{username}/admin`      | DELETE  | Révoquer le rôle superuser                                    |
| `/admin/users/{username}/datasets`   | GET     | Datasets de l'utilisateur                                     |
| `/admin/users/{username}/agents`     | GET     | Agents de l'utilisateur                                       |
| `/admin/users/{username}/keys`       | POST    | Générer une API key                                           |
| `/admin/users/{username}/keys`       | GET     | Lister les API keys                                           |
| `/admin/users/{username}/keys/{key}` | DELETE  | Supprimer une API key                                         |
| `/admin/users/{username}/role`       | PUT     | Modifier le rôle                                              |
| `/admin/users/{username}/permission` | GET     | Permissions de l'utilisateur                                  |

#### Rôles et permissions

| Endpoint                         | Méthode | Description                       |
|----------------------------------|---------|-----------------------------------|
| `/admin/roles`                   | GET     | Lister les rôles                  |
| `/admin/roles`                   | POST    | Créer un rôle                     |
| `/admin/roles/{role}`            | PUT     | Modifier la description d'un rôle |
| `/admin/roles/{role}`            | DELETE  | Supprimer un rôle                 |
| `/admin/roles/{role}/permission` | GET     | Permissions d'un rôle             |
| `/admin/roles/{role}/permission` | POST    | Accorder des permissions          |
| `/admin/roles/{role}/permission` | DELETE  | Révoquer des permissions          |

#### Supervision et configuration

| Endpoint                   | Méthode    | Description                   |
|----------------------------|------------|-------------------------------|
| `/admin/services`          | GET        | Lister les services internes  |
| `/admin/services/{id}`     | GET        | Détail d'un service           |
| `/admin/services/{id}`     | DELETE     | Arrêter un service            |
| `/admin/services/{id}`     | PUT        | Redémarrer un service         |
| `/admin/sandbox/providers` | GET        | Providers sandbox disponibles |
| `/admin/sandbox/config`    | GET / POST | Configuration du sandbox code |
| `/admin/sandbox/test`      | POST       | Tester la connexion sandbox   |
| `/admin/log_levels`        | GET        | Niveaux de log actuels        |
| `/admin/log_levels`        | PUT        | Modifier un niveau de log     |
| `/admin/variables`         | GET / PUT  | Variables de configuration    |
| `/admin/configs`           | GET        | Configuration générale        |
| `/admin/environments`      | GET        | Variables d'environnement     |
| `/admin/version`           | GET        | Version RAGFlow               |
| `/admin/ping`              | GET        | Health check                  |

---

## Périmètre open-source vs Enterprise

La quasi-totalité des fonctionnalités ci-dessus est disponible en open-source. Le flag `IS_ENTERPRISE` (`VITE_RAGFLOW_ENTERPRISE=RAGFLOW_ENTERPRISE`) dans le frontend déverrouille uniquement des fonctionnalités UI secondaires (import Excel en masse, whitelist d'emails, affichages avancés de rôles) — le backend sous-jacent est entièrement open-source.
