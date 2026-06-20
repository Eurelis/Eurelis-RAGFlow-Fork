# Feature : Gestion des équipes (group_work)

**Branche** : `eurelis/feature/group_work`  
**Date** : 2026-05-23  
**Statut** : Complet

---

## Objectif

Permettre aux key users de partager leurs agents et chats avec les membres de leur équipe (tenant), et fournir aux administrateurs une interface pour gérer les appartenances aux équipes directement, sans passer par le flow d'invitation email.

---

## Périmètre

| Bloc | Description | Statut |
|------|-------------|--------|
| Backend admin API | 6 nouveaux endpoints REST pour la gestion des équipes | ✅ |
| Frontend admin — onglet Teams | Onglet sur la page user-detail pour gérer les équipes d'un utilisateur | ✅ |
| Frontend admin — page /admin/teams | Page dédiée avec liste et détail des équipes | ✅ |
| Validation des invitations | Bouton pour promouvoir un utilisateur `invite` en `normal` depuis l'admin | ✅ |
| Chat permission | Champ `permission` (me/team) sur les chats, comme les Datasets et Agents | ✅ |
| Accès shared chat | Membres d'un tenant peuvent accéder aux chats `team` sans être l'owner | ✅ |
| Isolation des sessions | Sessions d'un chat `team` isolées par utilisateur (chaque membre ne voit que les siennes) | ✅ |

---

## Bloc 1 — Backend admin API

### Fichiers modifiés

- `admin/server/services.py` — classe `TenantMgr`
- `admin/server/routes.py` — 6 nouvelles routes

### Endpoints

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/api/v1/admin/tenants` | Liste tous les tenants (param `?with_members_only=true`) |
| `GET` | `/api/v1/admin/tenants/<tenant_id>/users` | Membres d'une équipe |
| `POST` | `/api/v1/admin/tenants/<tenant_id>/users` | Ajouter un membre (body : `{ user_id, role }`) |
| `DELETE` | `/api/v1/admin/tenants/<tenant_id>/users/<user_id>` | Retirer un membre |
| `PUT` | `/api/v1/admin/tenants/<tenant_id>/users/<user_id>/role` | Modifier le rôle (body : `{ role }`) |
| `GET` | `/api/v1/admin/users/<user_id>/tenants` | Équipes dont un utilisateur est membre |

### Points clés

- L'ajout se fait **sans email** — création directe d'un `UserTenant` avec `status=VALID`
- L'owner ne peut pas être retiré (`user_id == tenant_id` → erreur 400)
- Seuls les rôles `normal` et `admin` sont acceptables (pas `owner` ni `invite`)
- `get_all_users()` enrichi avec le champ `id` (UUID) pour les besoins de l'UI add-member
- Réutilise `UserTenantService`, `TenantService`, `UserService` existants

---

## Bloc 2 — Frontend admin

### Fichiers créés

| Fichier | Description |
|---------|-------------|
| `web/src/pages/admin/forms/add-to-team-form.tsx` | Formulaire react-hook-form + zod : sélecteur équipe + rôle |
| `web/src/pages/admin/teams.tsx` | Liste paginée de tous les tenants avec recherche par email |
| `web/src/pages/admin/team-detail.tsx` | Détail d'une équipe : membres, ajout, retrait |

### Fichiers modifiés

| Fichier | Modification |
|---------|-------------|
| `web/src/pages/admin/user-detail.tsx` | Onglet "Teams" ajouté (3e onglet après Datasets et Agents) |
| `web/src/pages/admin/layouts/navigation-layout.tsx` | Entrée "Team management" dans la sidebar |
| `web/src/routes.tsx` | Routes `/admin/teams` et `/admin/teams/:tenantId` |
| `web/src/utils/api.ts` | 6 nouvelles URL patterns (adminListTenants, etc.) |
| `web/src/services/admin-service.ts` | 6 nouvelles fonctions API exportées |
| `web/src/services/admin.service.d.ts` | Types `ListTenantsItem`, `TenantMember`, `UserTenantMembership` ; `id` sur `ListUsersItem` |
| `web/src/locales/en.ts` | Clés i18n : `teams`, `teamManagement`, `addToTeam`, etc. (namespace `admin` et `header`) |

### Navigation

```
/admin/teams              → AdminTeams (dans navigation-layout)
/admin/teams/:tenantId    → AdminTeamDetail (hors navigation-layout, comme user-detail)
```

### Onglet Teams (user-detail)

- Tableau : Owner (avatar + email + nickname), Rôle (badge), Date, Actions
- Actions :
  - **Icône check** (visible uniquement si `role='invite'`) : valide l'invitation → `PUT /admin/tenants/<tenant_id>/users/<user_id>/role` avec `role=normal`
  - **Icône corbeille** : retire l'utilisateur du tenant
- Bouton "Add to team" → Dialog avec sélecteur équipe + rôle
- Mutation sur `POST /admin/tenants/<tenant_id>/users` avec `user_id` de l'utilisateur courant
- Exclut du dropdown les équipes dont l'utilisateur est déjà membre

### Page team-detail (/admin/teams/:tenantId)

- Tableau : Email (avatar + nickname), Rôle (badge), Date de mise à jour, Actions
- Actions :
  - **Icône check** (visible uniquement si `role='invite'`) : valide l'invitation → `PUT /admin/tenants/<tenant_id>/users/<user_id>/role`
  - **Icône corbeille** : retire le membre

---

## Bloc 3 — Chat permission (me/team)

### Modèle DB

**Fichier** : `api/db/db_models.py`

```python
# Champ ajouté sur Dialog
permission = CharField(max_length=16, null=False, help_text="me|team", default="me", index=True)
```

Migration automatique via `migrate_db()` avec `alter_db_add_column`.

### Service — filtrage

**Fichier** : `api/db/services/dialog_service.py`

Pattern identique à `knowledgebase_service.py` :

```python
(
    (cls.model.tenant_id.in_(joined_tenant_ids) & (cls.model.permission == TenantPermission.TEAM.value))
    | (cls.model.tenant_id == user_id)
) & (cls.model.status == StatusEnum.VALID.value)
```

Les chats `permission="me"` d'un autre tenant ne remontent pas dans la liste, même si l'utilisateur est membre de ce tenant.

### API REST

**Fichier** : `api/apps/restful_apis/chat_api.py`

- `create_chat` : accepte `permission` (défaut `"me"`) ; valide `"me"|"team"`
- `update_chat` : `permission` dans les champs modifiables
- Champ inclus automatiquement via `_PERSISTED_FIELDS`
- `_ensure_owned_chat` : modifié pour autoriser les membres d'un tenant à accéder aux chats `permission="team"`
- `list_sessions` : si l'utilisateur n'est pas l'owner du chat, les sessions sont filtrées par `user_id=current_user.id` (isolation)

### Frontend

| Fichier | Modification |
|---------|-------------|
| `web/src/interfaces/database/chat.ts` | `permission?: 'me' \| 'team'` ajouté à `IDialog` |
| `web/src/pages/next-chats/chat/app-settings/use-chat-setting-schema.tsx` | `permission: z.enum(['me', 'team']).optional()` |
| `web/src/pages/next-chats/chat/app-settings/chat-settings.tsx` | `defaultValues.permission = 'me'` |
| `web/src/pages/next-chats/chat/app-settings/chat-basic-settings.tsx` | `<PermissionFormField />` réutilisé depuis `dataset-setting` |

---

## Comportement attendu

| Scénario | Résultat |
|----------|---------|
| Chat `permission="me"` créé par l'owner | Visible uniquement par l'owner |
| Chat `permission="team"` créé par l'owner | Visible par tous les membres du tenant |
| Admin ajoute user B dans le tenant de user A | user B voit les chats `team` de user A |
| Admin retire user B du tenant | user B ne voit plus les chats `team` (filtre `status=VALID`) |
| Admin tente de retirer l'owner | Erreur 400 |
| Membre du tenant accède à un chat `team` | Autorisé — `_ensure_owned_chat` vérifie l'appartenance au tenant |
| Membre du tenant liste ses sessions sur un chat `team` | Uniquement ses propres sessions (isolation par `user_id`) |
| Admin valide une invitation (`role=invite`) | Rôle mis à jour en `normal` via `PUT /role`, accès effectif au tenant |

---

## Types TypeScript clés

```ts
// Tenant dans la liste admin
type ListTenantsItem = { tenant_id, owner_email, owner_nickname, member_count }

// Membre d'un tenant (GET /admin/tenants/<id>/users)
type TenantMember = {
  id, user_id,
  role: 'owner' | 'admin' | 'normal' | 'invite',
  status, nickname, email, avatar?, update_date, is_superuser?
}

// Appartenance d'un user à un tenant (GET /admin/users/<id>/tenants)
type UserTenantMembership = {
  tenant_id,
  role: 'owner' | 'admin' | 'normal' | 'invite',
  nickname, email, avatar?, update_date
}
```

> Le rôle `invite` est retourné tel quel par le backend. L'UI affiche un bouton "Valider" (icône check) pour ces entrées.

---

## Scénarios de tests fonctionnels

### Prérequis

- Instance RAGFlow avec le panel admin accessible
- Accès à 4 navigateurs/profils distincts : admin, user_a, user_b, user_c

---

### Scénario 1 — Partage d'un chat via invitation + validation admin

#### Mise en place (admin)

1. Créer trois utilisateurs : `user_a@test.com`, `user_b@test.com`, `user_c@test.com`
2. S'assurer que user_a a un modèle LLM configuré dans son tenant (nécessaire pour le chat)
3. user_b et user_c **n'ont pas besoin** de modèle LLM configuré

#### Configuration (user_a)

4. Se connecter en tant que user_a
5. Créer un dataset, lui donner la permission **"Team"**
6. Créer un chat, lui donner la permission **"Team"**
7. Vérifier que le dataset et le chat sont bien visibles pour user_a

#### Vérification isolation initiale (user_b, user_c)

8. Se connecter en tant que user_b → le dataset et le chat de user_a **ne doivent pas apparaître**
9. Se connecter en tant que user_c → même vérification

#### Invitation (user_a)

10. Depuis l'interface de user_a, inviter user_b dans son équipe (flow d'invitation standard RAGFlow)
11. Le statut de user_b dans l'équipe de user_a est alors `invite`

#### Ajout direct et validation (admin)

12. Se connecter en tant qu'admin
13. Aller dans **Admin → Users → user_b → onglet Teams**
    - Vérifier que user_b apparaît avec le rôle `Invited` dans le tenant de user_a
    - Cliquer sur l'icône **check** pour valider l'invitation → rôle passe à `normal`
14. Aller dans **Admin → Users → user_c → onglet Teams**
    - Cliquer sur **Add to team**, sélectionner le tenant de user_a, rôle `normal`
    - Confirmer
15. Alternativement via **Admin → Teams → tenant de user_a** :
    - Vérifier que user_b et user_c apparaissent dans la liste des membres
    - Le rôle de user_b doit être `normal` (validé), celui de user_c `normal` (ajout direct)

#### Vérification accès (user_b, user_c)

16. Se connecter en tant que user_b → le dataset et le chat de user_a **doivent maintenant apparaître**
17. Envoyer un message dans le chat → la réponse utilise le modèle LLM de user_a
18. Se connecter en tant que user_c → même vérification
19. Vérifier que les **sessions sont isolées** : user_b et user_c ne voient pas les sessions l'un de l'autre dans ce chat

#### Vérification retrait (admin)

20. Aller dans **Admin → Teams → tenant de user_a**, retirer user_b
21. Se reconnecter en tant que user_b → le chat de user_a **ne doit plus apparaître**

---

### Scénario 2 — Chat avec permission "Me" (non partagé)

1. user_a crée un second chat avec la permission **"Me"**
2. L'admin ajoute user_b dans le tenant de user_a
3. user_b se connecte → le chat `permission="Me"` de user_a **ne doit pas apparaître**, seul le chat `permission="Team"` est visible

---

### Scénario 3 — Protection de l'owner

1. L'admin va dans **Admin → Teams → tenant de user_a**
2. Tenter de retirer user_a (l'owner) de son propre tenant
3. L'API doit retourner une erreur 400 — user_a ne peut pas être retiré de son propre tenant

---

### Matrice de visibilité attendue

| Ressource | user_a | user_b (membre) | user_c (membre) | user_d (hors équipe) |
|-----------|--------|-----------------|-----------------|----------------------|
| Dataset `permission="team"` | ✅ | ✅ | ✅ | ❌ |
| Dataset `permission="me"` | ✅ | ❌ | ❌ | ❌ |
| Chat `permission="team"` | ✅ | ✅ | ✅ | ❌ |
| Chat `permission="me"` | ✅ | ❌ | ❌ | ❌ |
| Sessions dans un chat `team` | Toutes | Ses propres | Ses propres | — |
| Modèle LLM utilisé | Le sien | Celui de user_a | Celui de user_a | — |

---

## Services réutilisés

| Service | Méthode | Usage |
|---------|---------|-------|
| `UserTenantService` | `get_by_tenant_id()` | Lister les membres d'un tenant |
| `UserTenantService` | `get_tenants_by_user_id()` | Lister les équipes d'un user |
| `UserTenantService` | `get_num_members()` | Comptage dans `list_tenants` |
| `UserTenantService` | `filter_update()` | Remove + update role |
| `UserTenantService` | `save()` | Add member |
| `UserService` | `get_all_users()` | Liste users pour l'UI |
| `PermissionFormField` | composant React | Réutilisé tel quel depuis `dataset-setting` |
