# Configuration LLM et gestion des tenants

## Modèle de données

Dans RAGFlow, chaque utilisateur possède son propre **tenant** (`tenant_id = user_id`). Les connexions LLM sont toujours scopées à un tenant via la table `TenantLLM` — il n'existe pas de LLM "global" partagé entre tenants.

```
User ──── UserTenant ──── Tenant ──── TenantLLM (api_key, factory, model_type)
 id            │            id              │
  └── tenant_id (= user_id du créateur)     └── tenant_id
```

---

## Rôles dans un tenant

Définis dans `api/db/__init__.py` :

| Rôle | Description |
|---|---|
| `owner` | Créateur du tenant — seul à pouvoir gérer les membres et configurer les LLMs |
| `admin` | Existe dans l'enum mais **non implémenté** — mêmes droits qu'un `normal` |
| `normal` | Membre actif, peut utiliser les LLMs et KBs du tenant |
| `invite` | En attente d'acceptation |

> Le contrôle d'accès dans `tenant_app.py` vérifie uniquement `current_user.id == tenant_id`, ce qui n'est vrai que pour l'owner. Le rôle `admin` ne confère aucun privilège supplémentaire dans l'état actuel du code.

---

## L'utilisateur `admin@ragflow.io`

Créé au premier démarrage si le flag `--init-superuser` est passé (`entrypoint.sh`).

```python
# api/db/init_data.py:46-48
DEFAULT_SUPERUSER_EMAIL    = os.getenv("DEFAULT_SUPERUSER_EMAIL",    "admin@ragflow.io")
DEFAULT_SUPERUSER_PASSWORD = os.getenv("DEFAULT_SUPERUSER_PASSWORD", "admin")
DEFAULT_SUPERUSER_NICKNAME = os.getenv("DEFAULT_SUPERUSER_NICKNAME", "admin")
```

Ces valeurs sont surchargeables via `docker/.env`.

Propriétés particulières :
- `is_superuser = True` — protège contre la suppression, aucun autre privilège
- `role = OWNER` de son propre tenant
- Ne peut **pas** administrer les tenants des autres utilisateurs

---

## Partage de configuration LLM

### Ce qui est partagé au sein d'un tenant

Tous les membres d'un tenant utilisent les mêmes connexions LLM (`TenantLLM`), la même clé API et le même pool de tokens (`Tenant.credit`). La configuration est faite une fois par l'owner via Settings → Model providers.

### Partage entre tenants : `user_default_llm`

Le seul mécanisme cross-tenant est `user_default_llm` dans `service_conf.yaml`. Il est appliqué **à la création de chaque nouvel utilisateur** via `get_init_tenant_llm()` (`api/db/services/llm_service.py:36`) :

```python
# Pour chaque nouvel utilisateur, copie la config dans son tenant
tenant_llm.append({
    "tenant_id": user_id,
    "llm_factory": factory_config["factory"],
    "api_key":     factory_config["api_key"],   # copié depuis service_conf.yaml
    "api_base":    factory_config["base_url"],
    ...
})
```

C'est une **copie au moment de l'inscription**, pas un partage en temps réel. Les utilisateurs existants ne sont pas affectés par un changement ultérieur de `service_conf.yaml`.

---

## Tableau récapitulatif

| Besoin | Possible | Méthode |
|---|---|---|
| Partager une clé LLM entre membres d'un même tenant | ✅ | Natif — l'owner configure une fois |
| Appliquer une clé LLM à tous les **nouveaux** utilisateurs | ✅ | `user_default_llm` dans `service_conf.yaml` |
| Mettre à jour la clé sur tous les tenants **existants** | ⚠️ | Requête SQL directe sur `tenant_llm` |
| Partager un LLM entre tenants en temps réel | ❌ | Non supporté nativement |

### Mise à jour en masse des tenants existants (SQL)

```sql
UPDATE tenant_llm
SET api_key = 'nouvelle-clé'
WHERE llm_factory = 'OpenAI';
```

> Nécessite un accès direct à la base MySQL. Aucun rechargement de processus n'est nécessaire — la clé est lue à chaque requête LLM.

---

## Knowledge Bases : partage intra-tenant

Le champ `permission` de la table `knowledgebase` contrôle la visibilité :

| Valeur | Accès |
|---|---|
| `me` | Créateur uniquement |
| `team` | Tous les membres du tenant |

---

## Fichiers clés

| Fichier | Contenu |
|---|---|
| `api/db/init_data.py:46-109` | Création de l'utilisateur superuser et de son tenant |
| `api/db/services/llm_service.py:36-82` | `get_init_tenant_llm()` — config LLM appliquée aux nouveaux utilisateurs |
| `api/db/joint_services/user_account_service.py:143-152` | Blocage de suppression du superuser |
| `api/apps/tenant_app.py:34,53` | Contrôle d'accès owner-only |
| `api/db/__init__.py:21-24` | Enum `UserTenantRole` |
| `docker/service_conf.yaml.template` | Section `user_default_llm` |
