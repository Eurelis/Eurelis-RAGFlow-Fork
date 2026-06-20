# Analyse : Partage des Modèles LLM dans RAGFlow

## Contexte

RAGFlow permet le partage des datasets entre utilisateurs. Les configurations de modèles LLM (clés API, paramètres) sont actuellement strictement privées par tenant. Ce document analyse les modifications nécessaires pour permettre leur partage.

---

## Architecture actuelle des modèles

### Modèles de base de données (`api/db/db_models.py`)

Trois tables coexistent :

| Modèle                      | Table           | Rôle                                                 |
|-----------------------------|-----------------|------------------------------------------------------|
| `LLMFactories` (~ligne 784) | `llm_factories` | Catalogue des fournisseurs (OpenAI, Claude, etc.)    |
| `LLM` (~ligne 798)          | `llm`           | Catalogue global des modèles disponibles             |
| `TenantLLM` (~ligne 817)    | `tenant_llm`    | **Configurations par tenant (clés API, paramètres)** |

### Modèle `TenantLLM` — champs clés

```python
tenant_id    # Tenant propriétaire (indexé)
llm_factory  # Fournisseur (OpenAI, Anthropic, etc.)
model_type   # chat, embedding, image2text, rerank, tts...
llm_name     # Nom du modèle spécifique
api_key      # SENSIBLE : clé API du fournisseur
api_base     # URL de base personnalisée
max_tokens   # Limite de tokens
used_tokens  # Suivi d'utilisation
status       # État de validation
```

**Contrainte unique actuelle :** `(tenant_id, llm_factory, llm_name)`

### Accès actuel

Tous les endpoints utilisent `current_user.id` comme `tenant_id` sans aucune logique de partage :

- `GET /my_llms` → `TenantLLM.where(tenant_id == current_user.id)`
- `POST /set_api_key` → `TenantLLMService.save(tenant_id=current_user.id, ...)`
- `POST /add_llm` → `TenantLLMService.save(tenant_id=current_user.id, ...)`
- `POST /delete_llm` → `TenantLLM.where(tenant_id=current_user.id, ...)`

---

## Pourquoi les modèles ne sont pas partageables

Comparaison avec le modèle `Knowledgebase` :

| Aspect                 | Dataset | TenantLLM      |
|------------------------|---------|----------------|
| Champ `permission`     | ✓       | ✗ Manquant     |
| Champ `created_by`     | ✓       | ✗ Manquant     |
| Requêtes multi-tenant  | ✓       | ✗ Absent       |
| Méthode `accessible()` | ✓       | ✗ Manquante    |
| Filtrage par équipe    | ✓       | ✗ Non supporté |

---

## Enjeu spécifique : sécurité des clés API

Le partage de modèles LLM diffère du partage de datasets car `TenantLLM` contient des **clés API sensibles**. Deux approches sont possibles :

### Option A — Partage des credentials (déconseillé)

Permettre à d'autres tenants de lire directement les enregistrements `TenantLLM` d'un autre utilisateur.

**Risque :** Exposition des clés API en cas de compromission d'un compte membre.

### Option B — Partage de configuration sans exposition des credentials (recommandé)

Les membres de l'équipe utilisent la configuration du créateur **sans jamais voir la clé API**. Le backend résout la clé API de façon transparente lors des appels LLM.

**Avantage :** Cohérent avec l'architecture actuelle de résolution via `tenant_id`.

---

## Modifications à apporter

### 1. Schéma de base de données

**Fichier :** `api/db/db_models.py` (~ligne 817, modèle `TenantLLM`)

Ajouter deux champs :

```python
permission = CharField(max_length=16, default="me")  # "me" ou "team"
created_by = CharField(max_length=32)                # utilisateur créateur
```

**Migration pour les données existantes :**

- `created_by = tenant_id`
- `permission = "me"` pour tous les enregistrements existants

> La contrainte unique `(tenant_id, llm_factory, llm_name)` reste inchangée — elle garantit qu'un tenant ne configure pas deux fois le même modèle.

---

### 2. Service

**Fichier :** `api/db/services/tenant_llm_service.py`

#### Modifier `get_my_llms(tenant_id)` (ligne ~67)

```python
# AVANT — retourne uniquement les LLMs du tenant
TenantLLM.select().where(
    TenantLLM.tenant_id == tenant_id,
    TenantLLM.api_key.is_null(False)
)

# APRÈS — inclut les LLMs d'équipe partagés (pattern datasets)
WHERE ((tenant_llm.tenant_id IN joined_tenant_ids AND tenant_llm.permission == 'team')
    OR tenant_llm.tenant_id == user_id)
  AND tenant_llm.api_key IS NOT NULL
```

#### Modifier `get_api_key(tenant_id, model_name, model_type)` (ligne ~38)

Lors de la résolution d'un modèle pour un utilisateur, chercher également dans les LLMs partagés par son équipe si aucun résultat n'est trouvé dans son propre tenant.

#### Modifier `get_model_config(tenant_id, llm_type, llm_name)` (ligne ~94)

Même logique de fallback : si le modèle n'est pas trouvé dans le tenant de l'utilisateur, chercher dans les LLMs d'équipe partagés.

#### Ajouter `accessible(user_id, tenant_llm_id)`

Vérification d'accès via `UserTenant` (même pattern que `KnowledgebaseService.accessible()`).

#### Ajouter `accessible4deletion(user_id, tenant_llm_id)`

Vérification que seul `created_by == user_id` peut supprimer ou modifier la permission.

**Référence :** `api/db/services/knowledgebase_service.py` (lignes 53–83 et 481–494).

---

### 3. API

**Fichier :** `api/apps/llm_app.py`

| Endpoint            | Modification                                                  |
|---------------------|---------------------------------------------------------------|
| `GET /my_llms`      | Inclure les LLMs d'équipe (permission = "team")               |
| `POST /set_api_key` | Accepter `permission` ("me"/"team"), enregistrer `created_by` |
| `POST /add_llm`     | Accepter `permission`, enregistrer `created_by`               |
| `POST /delete_llm`  | Vérifier `created_by` via `accessible4deletion()`             |

**Règle importante :** La clé API ne doit **jamais** être retournée dans les réponses pour les LLMs partagés dont l'utilisateur n'est pas le créateur (masquer ou omettre le champ `api_key`).

---

### 4. Résolution des modèles dans le pipeline RAG

**Fichier :** `api/db/services/llm_service.py` et usages dans `rag/`

La résolution actuelle se fait via `tenant_id = current_user.id`. Avec le partage, la logique doit :

1. Chercher d'abord dans les modèles du tenant courant
2. En cas d'absence, chercher dans les modèles partagés (`permission = "team"`) des tenants rejoints
3. Résoudre la clé API à partir du `tenant_id` du **créateur** (pas de l'utilisateur courant)

---

### 5. Frontend

**Répertoire :** `web/src/` (pages de configuration des modèles)

- Ajouter un sélecteur "Me / Team" lors de la configuration d'un modèle
- Afficher les modèles partagés par l'équipe avec un indicateur visuel distinct
- Masquer le champ de clé API pour les modèles partagés dont l'utilisateur n'est pas propriétaire
- Empêcher la suppression/modification des modèles partagés non-créés par l'utilisateur courant

---

## Fichiers clés de référence

| Rôle                                            | Fichier                                    |
|-------------------------------------------------|--------------------------------------------|
| Modèles DB (TenantLLM ~817, Knowledgebase ~852) | `api/db/db_models.py`                      |
| Service LLM à modifier                          | `api/db/services/tenant_llm_service.py`    |
| Wrapper LLM bundle                              | `api/db/services/llm_service.py`           |
| Endpoints modèles à modifier                    | `api/apps/llm_app.py`                      |
| Pattern de partage à reproduire                 | `api/db/services/knowledgebase_service.py` |
| Enum TenantPermission                           | `api/db/__init__.py`                       |

---

## Résumé de l'effort

| Priorité | Tâche                                               | Effort       |
|----------|-----------------------------------------------------|--------------|
| Haute    | Migration DB : ajouter `permission` et `created_by` | Faible       |
| Haute    | Mettre à jour `TenantLLMService` (listing + accès)  | Moyen        |
| Haute    | Mettre à jour les endpoints `llm_app.py`            | Moyen        |
| Haute    | Sécuriser : masquer les clés API dans les réponses  | Faible       |
| Haute    | Pipeline RAG : résolution de clé API via créateur   | Moyen–Élevé  |
| Moyenne  | Contrôles d'accès et suppression                    | Faible–Moyen |
| Basse    | Interface frontend (sélecteur, masquage clé API)    | Moyen–Élevé  |

Le portage est plus complexe que pour les Chats en raison de la **sensibilité des clés API** et de la résolution des modèles dans le pipeline RAG. La logique d'accès aux credentials doit rester côté serveur en toutes circonstances.
