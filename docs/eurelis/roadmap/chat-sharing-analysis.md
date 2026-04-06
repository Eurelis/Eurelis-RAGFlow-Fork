# Analyse : Partage des Chats dans RAGFlow

## Contexte

RAGFlow permet le partage des datasets (knowledge bases) entre utilisateurs via un système de permissions. Les Chats (dialogs) ne bénéficient pas de cette fonctionnalité. Ce document analyse les modifications nécessaires pour l'implémenter.

---

## Infrastructure existante (datasets)

Le système de partage repose sur :

- Un champ `permission` (`"me"` ou `"team"`) sur le modèle `Knowledgebase`
- Un champ `created_by` pour suivre le créateur
- L'enum `TenantPermission` dans `api/db/__init__.py`
- Des méthodes `accessible()` et `accessible4deletion()` dans le service
- La relation `UserTenant` pour déterminer l'appartenance à une équipe

### Fonctionnement

- Chaque utilisateur est un **Tenant** (son `user_id` sert de `tenant_id`)
- Les équipes sont représentées par des enregistrements `UserTenant`
- Un dataset partagé a `permission = "team"` et reste rattaché au `tenant_id` du créateur
- Les membres d'équipe y accèdent via la jointure `UserTenant`

---

## Pourquoi les Chats ne sont pas partageables

Le modèle `Dialog` est incomplet par rapport au modèle `Knowledgebase` :

| Aspect                  | Dataset | Dialog         |
|-------------------------|---------|----------------|
| Champ `permission`      | ✓       | ✗ Manquant     |
| Champ `created_by`      | ✓       | ✗ Manquant     |
| Méthode `accessible()`  | ✓       | ✗ Manquante    |
| Contrôle de suppression | ✓       | ✗ Absent       |
| Filtrage par équipe     | ✓       | ✗ Non supporté |

Le `DialogService.get_by_tenant_ids()` retourne tous les dialogs d'un tenant sans vérification de permission, ce qui est incorrect.

---

## Modifications à apporter

### 1. Schéma de base de données

**Fichier :** `api/db/db_models.py` (~ligne 970, modèle `Dialog`)

Ajouter deux champs :

```python
permission = CharField(max_length=16, default="me")  # "me" ou "team"
created_by = CharField(max_length=32)                # utilisateur créateur
```

**Migration pour les données existantes :**

- `created_by = tenant_id` (le propriétaire du tenant est le créateur)
- `permission = "me"` pour tous les dialogs existants (préserve le comportement actuel)

---

### 2. Service

**Fichier :** `api/db/services/dialog_service.py`

#### Modifier `get_by_tenant_ids()` (ligne ~108)

```python
# AVANT — retourne tout le tenant sans contrôle
WHERE (dialog.tenant_id IN joined_tenant_ids OR dialog.tenant_id == user_id)
  AND dialog.status == VALID

# APRÈS — respecte la permission (pattern identique aux datasets)
WHERE ((dialog.tenant_id IN joined_tenant_ids AND dialog.permission == 'team')
    OR dialog.tenant_id == user_id)
  AND dialog.status == VALID
```

#### Ajouter `accessible()`

Vérification qu'un utilisateur peut accéder à un dialog donné, via la relation `UserTenant`.

Référence : `KnowledgebaseService.accessible()` dans `api/db/services/knowledgebase_service.py` (lignes 481–494).

#### Ajouter `accessible4deletion()`

Vérification que seul le créateur (`created_by == user_id`) peut supprimer.

Référence : `KnowledgebaseService.accessible4deletion()` (lignes 53–83).

**Autre référence complète :** `api/db/services/canvas_service.py` (lignes 142–206) — implémentation identique pour les canvases.

---

### 3. API

**Fichier :** `api/apps/dialog_app.py`

| Endpoint                  | Modification                                                                                 |
|---------------------------|----------------------------------------------------------------------------------------------|
| `POST /set` (création)    | Accepter le paramètre `permission` ("me"/"team"), enregistrer `created_by = current_user.id` |
| `POST /set` (mise à jour) | Permettre de modifier `permission` uniquement si `created_by == current_user.id`             |
| `POST /rm`                | Vérifier `created_by` avant suppression via `accessible4deletion()`                          |
| `GET /get`                | Ajouter contrôle d'accès via `accessible()`                                                  |
| `GET /list`, `POST /next` | Déjà correct si `get_by_tenant_ids()` est mis à jour                                         |

**Référence API RESTful :** `api/apps/restful_apis/dataset_api.py` (lignes 72–75 pour le champ `permission` en création, lignes 210–213 pour la mise à jour).

---

### 4. Frontend

**Répertoire :** `web/src/`

- Ajouter un sélecteur "Me / Team" lors de la création et modification d'un chat
- Afficher un indicateur visuel de partage sur les cartes de chat
- Masquer les actions "modifier" et "supprimer" si l'utilisateur n'est pas le créateur
- Cohérence visuelle avec l'interface de partage des datasets

---

## Fichiers clés de référence

| Rôle                                         | Fichier                                    |
|----------------------------------------------|--------------------------------------------|
| Modèles DB (Dialog ~962, Knowledgebase ~852) | `api/db/db_models.py`                      |
| Pattern de partage à reproduire              | `api/db/services/knowledgebase_service.py` |
| Autre référence (canvas)                     | `api/db/services/canvas_service.py`        |
| Service dialog à modifier                    | `api/db/services/dialog_service.py`        |
| Endpoints dialog à modifier                  | `api/apps/dialog_app.py`                   |
| Enum TenantPermission                        | `api/db/__init__.py`                       |
| Pattern API RESTful de référence             | `api/apps/restful_apis/dataset_api.py`     |

---

## Résumé de l'effort

| Priorité | Tâche                                                  | Effort       |
|----------|--------------------------------------------------------|--------------|
| Haute    | Migration DB : ajouter `permission` et `created_by`    | Faible       |
| Haute    | Mettre à jour `DialogService`                          | Faible–Moyen |
| Haute    | Mettre à jour les endpoints `dialog_app.py`            | Moyen        |
| Moyenne  | Contrôles d'accès dans tous les endpoints              | Faible–Moyen |
| Basse    | Interface frontend (sélecteur permission, indicateurs) | Moyen–Élevé  |

Le travail est essentiellement un **portage** du système déjà en place pour les datasets/canvases vers les dialogs. L'architecture est prouvée et les patterns sont cohérents dans le code existant.
