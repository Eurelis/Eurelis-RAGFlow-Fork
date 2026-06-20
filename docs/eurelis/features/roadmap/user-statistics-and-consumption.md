# Statistiques de consommation par utilisateur

## Contexte

RAGFlow stocke dans la table `api_4_conversation` toutes les métriques de consommation par session (`tokens`, `duration`, `round`, `thumb_up`) avec un champ `user_id` indexé. Cependant :

- L'endpoint existant `GET /system/stats` n'agrège que par tenant, sans filtre par utilisateur
- Aucun endpoint ne permet à un utilisateur de consulter sa propre consommation
- L'interface admin ne propose pas de vue par utilisateur
- Le Shield ne peut pas afficher d'informations de consommation dans son interface

L'objectif est d'exploiter la donnée déjà présente en base pour exposer des statistiques à deux niveaux : **admin** (vue globale + deep dive) et **utilisateur** (consommation dans le Shield).

---

## État actuel

| Donnée                              | Stockée en DB | Exposée en API         | Filtrée par user |
|-------------------------------------|---------------|------------------------|------------------|
| Nombre de sessions                  | ✅             | ✅ `/system/stats` (pv) | ❌                |
| Utilisateurs uniques                | ✅             | ✅ `/system/stats` (uv) | ❌                |
| Tokens consommés                    | ✅             | ✅ `/system/stats`      | ❌                |
| Durée / vitesse                     | ✅             | ✅ `/system/stats`      | ❌                |
| Tours par session                   | ✅             | ✅ `/system/stats`      | ❌                |
| Feedback (thumb up)                 | ✅             | ✅ `/system/stats`      | ❌                |
| Stats par utilisateur               | ✅             | ❌                      | ❌                |
| Stats par chat                      | ✅             | ❌                      | ❌                |
| Consommation de la session courante | ✅             | ❌                      | ❌                |

---

## Modifications requises

### 1. Serveur admin — endpoint de stats par utilisateur

**Fichier :** `admin/server/routes.py` + `admin/server/services.py`

Nouvel endpoint agrégant les métriques par utilisateur, filtrable par période et par chat :

```
GET /api/v1/admin/stats/users
    ?from_date=2026-05-01
    ?to_date=2026-05-31
    ?chat_id=<dialog_id>       (optionnel)

→ liste d'utilisateurs avec leurs métriques agrégées sur la période
```

```json
[
  {
    "user_id": "550e8400e29b41d4a716446655440000",
    "sessions": 42,
    "tokens": 18500,
    "avg_duration": 3.2,
    "avg_round": 4.1,
    "thumb_up": 12
  },
  ...
]
```

```
GET /api/v1/admin/stats/users/{user_id}
    ?from_date=...&to_date=...

→ détail pour un utilisateur : métriques globales + breakdown par chat + évolution temporelle
```

```json
{
  "user_id": "...",
  "period": { "from": "2026-05-01", "to": "2026-05-31" },
  "totals": {
    "sessions": 42,
    "tokens": 18500,
    "avg_duration": 3.2,
    "avg_round": 4.1,
    "thumb_up": 12
  },
  "by_chat": [
    { "dialog_id": "...", "dialog_name": "...", "sessions": 20, "tokens": 9000 },
    ...
  ],
  "by_day": [
    { "date": "2026-05-01", "sessions": 3, "tokens": 1200 },
    ...
  ]
}
```

**Implémentation :** `API4ConversationService.get_list()` accepte déjà un filtre `user_id` — la logique d'agrégation est à ajouter dans `UserStatsMgr` (nouveau service dans `admin/server/services.py`).

---

### 2. API RAGFlow — endpoint de consommation utilisateur (pour le Shield)

**Fichier :** `api/apps/restful_apis/stats_api.py`

Endpoint authentifié par token utilisateur (API key ou JWT RAGFlow), retournant la consommation de l'utilisateur courant sur différentes fenêtres temporelles :

```
GET /api/v1/stats/me
    ?session_id=<id>   (optionnel — consommation d'une session spécifique)

→ consommation de l'utilisateur identifié par le token
```

```json
{
  "user_id": "550e8400e29b41d4a716446655440000",
  "today": {
    "sessions": 5,
    "tokens": 2100,
    "avg_duration": 2.8
  },
  "this_week": {
    "sessions": 18,
    "tokens": 7400,
    "avg_duration": 3.1
  },
  "this_month": {
    "sessions": 42,
    "tokens": 18500,
    "avg_duration": 3.2
  },
  "current_session": {           // présent uniquement si session_id fourni
    "session_id": "...",
    "tokens": 340,
    "round": 4,
    "duration": 8.5,
    "thumb_up": 0
  }
}
```

Le filtre par `user_id` s'applique automatiquement depuis le `current_user` authentifié — un utilisateur ne peut consulter que ses propres données.

---

### 3. Interface admin — vue d'ensemble des consommations

**Composant :** nouvelle page dans `web/src/pages/admin/` (ou section dans le dashboard existant)

#### Overview globale

Tableau de bord avec les métriques agrégées du tenant sur une période sélectionnable :

- Graphe d'activité journalière (sessions, tokens)
- Top utilisateurs par tokens consommés
- Top chats par nombre de sessions
- Répartition des feedbacks (thumb up / total)
- Métriques de performance (vitesse moyenne, tours moyens)

#### Deep dive par utilisateur

Accessible depuis l'overview ou via `GET /api/v1/admin/stats/users/{user_id}` :

- Identité de l'utilisateur (email, dernière activité)
- Courbe de consommation sur la période
- Breakdown par chat utilisé
- Sessions récentes avec détail (tokens, durée, feedback, extrait du dernier message)

---

### 4. Interface Shield — consommation dans l'UI utilisateur

Le Shield expose un endpoint proxy vers `GET /api/v1/stats/me` de RAGFlow, enrichi du contexte multi-serveurs :

```
GET /stats/me
    ?session_id=<namespaced_session_id>   (optionnel)

→ agrégation de la consommation sur tous les serveurs RAGFlow accessibles
```

Le Shield agrège les réponses de chaque serveur et consolide :

```json
{
  "today":      { "sessions": 7,  "tokens": 3200 },
  "this_week":  { "sessions": 22, "tokens": 9800 },
  "this_month": { "sessions": 51, "tokens": 24000 },
  "by_server": {
    "common":   { "today": { "sessions": 4, "tokens": 1800 }, ... },
    "dept-rh":  { "today": { "sessions": 3, "tokens": 1400 }, ... }
  },
  "current_session": { "tokens": 340, "round": 4, "duration": 8.5 }
}
```

#### Intégration dans l'UI Shield

**Page d'accueil :**
- Widgets "aujourd'hui / cette semaine / ce mois" avec tokens et sessions
- Indicateur de tendance (vs période précédente)

**Dans le fil de conversation :**
- Compteur de tokens de la session courante (mise à jour après chaque réponse)
- Durée de réponse du dernier tour

---

## Plan d'implémentation

| Étape | Périmètre                                                   | Priorité |
|-------|-------------------------------------------------------------|----------|
| 1     | Endpoint admin `GET /api/v1/admin/stats/users`              | Haute    |
| 2     | Endpoint admin `GET /api/v1/admin/stats/users/{user_id}`    | Haute    |
| 3     | Endpoint RAGFlow `GET /api/v1/stats/me`                     | Haute    |
| 4     | Endpoint Shield `GET /stats/me` (agrégation multi-serveurs) | Haute    |
| 5     | UI Shield — widgets page d'accueil                          | Moyenne  |
| 6     | UI Shield — compteur de tokens dans la conversation         | Moyenne  |
| 7     | UI Admin RAGFlow — overview globale                         | Basse    |
| 8     | UI Admin RAGFlow — deep dive par utilisateur                | Basse    |

Les étapes 1 à 4 sont des développements backend purs sur des données déjà disponibles en base. Les étapes 5 à 8 dépendent de l'existence d'une UI Shield et de l'UI admin RAGFlow Eurelis.

---

## Relation avec l'upstream

### Issues ouvertes

| Issue | Titre | État | Pertinence |
|---|---|---|---|
| [#9146](https://github.com/infiniflow/ragflow/issues/9146) | Usage object from RAG-enabled endpoint | OPEN, sans assigné | L'endpoint RAG ne retourne pas les tokens consommés dans la réponse API — exactement notre besoin pour la consommation de session |
| [#11576](https://github.com/infiniflow/ragflow/issues/11576) | Token usage and timing for agents | OPEN, assigné à Wang Qi | Métriques manquantes dans la réponse structurée des agents |
| [ROADMAP 2026 #12241](https://github.com/infiniflow/ragflow/issues/12241) | Admin dashboard | Backlog, non planifié | Mentionné vaguement dans les backlogs, sans scope per-user |

### Analyse de faisabilité

#### #9146 — Token usage dans la réponse RAG (complexité faible)

Les données sont déjà calculées dans `dialog_service.py:841-855` :
- `tk_num` — tokens générés
- `used_token_count` — tokens en entrée (prompt)
- `generate_result_time_cost` — durée de génération
- `total_time_cost` — durée totale

Elles sont aujourd'hui encodées en texte dans le champ `prompt` (le "## Token usage:" visible dans l'UI). Il suffit de les exposer comme champ structuré dans le dict de retour :

```python
# dialog_service.py — return à modifier
return {
    "answer": think + answer,
    "reference": refs,
    "prompt": ...,
    "created_at": time.time(),
    "usage": {                                                          # ← à ajouter
        "prompt_tokens": used_token_count,
        "completion_tokens": tk_num,
        "total_tokens": used_token_count + tk_num,
        "duration_ms": round(total_time_cost, 1),
        "tokens_per_second": int(tk_num / (generate_result_time_cost / 1000.0 + 0.001))
    }
}
```

`structure_answer()` propage le dict tel quel — le champ `usage` arriverait dans la réponse API sans autre modification. **1 fichier, ~10 lignes.**

Effet de bord utile : en passant `usage` à `API4ConversationService.append_message`, on corrige également le stockage des tokens en DB — actuellement `append_message` n'incrémente que `round`, les champs `tokens` et `duration` de `API4Conversation` restent à 0.

#### #11576 — Token usage pour les agents (complexité moyenne à haute)

Les agents s'exécutent via un canvas DSL (nœuds chaînés). Durée et tokens se répartissent sur plusieurs nœuds — il faudrait les accumuler nœud par nœud.

- **Total tokens + durée totale** à la fin d'exécution : faisable sur le même modèle que #9146, effort ~2j.
- **Breakdown par nœud** (durée Retrieval, durée LLM, etc.) : complexe, demande d'instrumenter chaque composant du canvas. À laisser à l'upstream.

### Stratégie

| Notre besoin | Position upstream | Action |
|---|---|---|
| Token usage dans la réponse API completion | #9146 ouvert, pas de solution | Implémenter dans le fork (~1j) |
| Token usage total pour les agents | #11576 assigné, en cours | Implémenter le total dans le fork ; attendre upstream pour le breakdown par nœud |
| Stats par `user_id` (endpoint dédié) | Aucune issue, hors radar | Développer dans le fork Eurelis |
| Admin dashboard per-user | Backlog vague, pas de per-user | Développer dans le fork Eurelis |

---

## Dépendances

- **Shield multi-serveurs** (`key_attr`, routing par `server_id`) — requis pour l'agrégation Shield (étape 4)
- **Propagation du `user_id` Keycloak `sub`** via le Shield — requis pour que les stats soient cohérentes entre les serveurs
- **`session_id` namespaced** (`server_id__original_id`) — requis pour que `current_session` soit resolvable par le Shield

Voir : `docs/integration/keycloak-authentication.md`
