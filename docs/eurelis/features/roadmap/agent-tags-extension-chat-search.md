# Feature : Extension du système de tags aux Discussions et Recherches

**Date** : 2026-06-20  
**Statut** : Piste d'implémentation — non implémenté  
**Origine** : Feature upstream [#14774](https://github.com/infiniflow/ragflow/pull/14774) (tags agents, mai 2026) — extension Eurelis envisagée

---

## Suivi d'implémentation

- [ ] **Dialog** (chatbots) — tags organisationnels sur les assistants
- [ ] **Search** (recherches) — tags organisationnels sur les interfaces de recherche

---

## Contexte

Le système de tags pour les agents (`UserCanvas`) a été introduit par l'upstream RAGFlow en mai 2026 (PR #14774, auteur `plind`). Il permet d'étiqueter librement les agents et de les filtrer par tag.

Ce système n'est pas étendu aux objets `Dialog` (chatbots) ni `Search` (interfaces de recherche) côté upstream, et aucune issue ou PR communautaire n'en discute à ce jour.

---

## Architecture du système existant (référence)

**Stockage** : `UserCanvas.tags` — `VARCHAR(512)`, comma-separated, indexé, migration automatique au démarrage.

**Service** (`canvas_service.py`) :
- `list_tags(joined_tenant_ids, user_id)` — agrège `{tag: count}` sur le périmètre tenant
- `update_tags(canvas_id, tags)` — normalise (virgules → espaces, dédup case-insensitive, max 64 chars/tag)
- `get_by_tenant_ids(..., tags=None)` — filtre avec `CONCAT(",", tags, ",")` contient `,tag,` (évite les faux positifs partiels)

**API** : `GET /agents/tags`, `PUT /agents/<id>/tags`

**Frontend** : `AgentTagEditor` (dialog avec autocomplete), badges sur les cartes, facette de filtre avec counts.

---

## Piste d'implémentation

Le pattern est identique pour `Dialog` et `Search` — les deux partagent la même structure que `UserCanvas` : UUID, `tenant_id`, isolation multi-tenant.

### 1. Base de données

Ajouter le champ `tags` aux deux modèles dans `api/db/db_models.py` :

```python
# Dans class Dialog(DataBaseModel) :
tags = CharField(max_length=512, null=False, default="", index=True)

# Dans class Search(DataBaseModel) :
tags = CharField(max_length=512, null=False, default="", index=True)
```

La migration est automatique : RAGFlow détecte et applique les nouvelles colonnes au démarrage (voir pattern ligne ~1777 dans `db_models.py`).

### 2. Services

Copier le pattern de `UserCanvasService` dans `DialogService` et `SearchService` :

```python
@classmethod
def list_tags(cls, joined_tenant_ids, user_id):
    # Agréger tous les tags sur le périmètre tenant
    # Retourner {tag: count}

@classmethod
def update_tags(cls, object_id, tags: list[str]) -> str:
    # Normaliser : virgules → espaces, dédup case-insensitive, tronquer à 64 chars
    # Persister et retourner la valeur stockée

# Dans get_by_tenant_ids() : ajouter paramètre tags=None et le filtre CONCAT
```

Fichiers : `api/db/services/dialog_service.py`, `api/db/services/search_service.py`

### 3. API

Deux endpoints par objet, en suivant le pattern de `agent_api.py` :

**Dialog** (dans `api/apps/restful_apis/chat_api.py`) :
- `GET /api/v1/chats/tags` — liste les tags avec leur count
- `PUT /api/v1/chats/<chat_id>/tags` — met à jour les tags

**Search** (dans `api/apps/restful_apis/search_app.py` ou équivalent) :
- `GET /api/v1/searches/tags`
- `PUT /api/v1/searches/<search_id>/tags`

### 4. Frontend

**Interfaces TypeScript** :
```typescript
// src/interfaces/database/chat.ts
interface IDialog { tags?: string; ... }

// src/interfaces/database/search.ts
interface ISearchAppProps { tags?: string; ... }
```

**Composants** : `AgentTagEditor` est générique — le réutiliser directement en passant les hooks appropriés, ou l'extraire en `TagEditor` partagé dans `src/components/`.

**Hooks** (copier le pattern de `use-agent-request.ts`) :
- `useFetchChatTags()` — `GET /api/v1/chats/tags`
- `useUpdateChatTags()` — `PUT /api/v1/chats/<id>/tags`
- `useFetchSearchTags()` / `useUpdateSearchTags()`

**Intégration** :
- Ajouter le bouton "Edit tags" dans le menu d'actions des cartes Chat et Search
- Ajouter la facette "Tags" dans la barre de filtres des pages `/chats` et `/searches`

---

## Points d'attention

| Point | Dialog | Search |
|---|---|---|
| Isolation tenant | `tenant_id` direct ✓ | `tenant_id` direct ✓ |
| Permission field | `permission` (me/team) ✓ | Absent — accès par `tenant_id` uniquement |
| Volume d'objets | Modéré | Modéré |
| Risque de conflit upstream | Faible (zones distinctes) | Faible |

**`Search` n'a pas de champ `permission`** : le filtrage des tags devra s'appuyer uniquement sur `tenant_id` et `created_by`, comme le fait déjà `SearchService.get_by_tenant_ids()`.

---

## Effort estimé

| Objet | Backend | Frontend | Total |
|---|---|---|---|
| Dialog | ~2h | ~2–3h | ~4–5h |
| Search | ~2h | ~2–3h | ~4–5h |
| **Total** | | | **~8–10h** |

---

## Relation avec l'upstream

Aucune issue ni PR upstream ne traite de cette extension à ce jour (vérifié juin 2026). L'implémentation peut être :
- **Eurelis-only** : ajout dans `eurelis/main`, faible empreinte (fichiers distincts de l'upstream)
- **Contribution upstream** : proposition de PR sur `infiniflow/ragflow` après validation interne
