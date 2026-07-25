---
title: "Exécution de code Python dans les agents (sandbox CodeExec)"
type: knowledge
status: reference
date: 2026-07-25
---

# Exécution de code Python dans les agents (sandbox CodeExec)

Les agents RAGFlow peuvent exécuter du code Python (ou JavaScript) via le composant **CodeExec**, disponible comme nœud de workflow ou comme outil d'un agent LLM. L'exécution est déléguée à un **provider sandbox** configurable. Ce document décrit les deux configurations validées — **Local** (développement) et **Self-Managed / self-hosted** (plateformes serveur) — ainsi que les workflows de test associés.

> Page Confluence associée : [RAGFlow — Exécution de code Python dans les agents (sandbox CodeExec)](https://eurelis.atlassian.net/wiki/spaces/AILAB/pages/1511194644) (espace AI Lab Initiative).

---

## Fonctionnement général

- Le provider sandbox se configure dans **Admin > Sandbox Settings** de RAGFlow.
- La configuration est stockée **en base de données** (`system_settings`, clés `sandbox.provider_type` et `sandbox.<provider>`), pas dans les fichiers de configuration : elle est rechargée à chaque exécution (`reload_provider()`), **aucun redémarrage n'est nécessaire** après modification.
- Le bouton *Test connection* de l'admin ne fait pas qu'un ping : il exécute un vrai script Python de bout en bout dans la sandbox (`admin/server/services.py:test_connection`).
- Le script utilisateur doit définir une fonction `main()` qui retourne un dictionnaire JSON-sérialisable.
- Code concerné : `agent/tools/code_exec.py` (composant), `agent/sandbox/client.py` + `agent/sandbox/providers/` (providers), `agent/sandbox/executor_manager/` (service self-hosted).

---

## Configuration 1 — Local (développement)

Le provider `local` exécute le code comme **sous-processus `python3` dans le conteneur RAGFlow** lui-même. Aucun service ni image supplémentaire n'est requis, ce qui en fait la configuration idéale pour le développement — notamment sur macOS, où le mode self-hosted n'est pas possible (voir prérequis).

> ⚠️ **Ce n'est pas une vraie sandbox.** Le code s'exécute dans le même environnement que le serveur RAGFlow, sans isolation renforcée ni analyse de sécurité du code. À réserver au développement local — ne jamais utiliser sur une plateforme partagée ou exposée.

| Champ | Valeur |
|---|---|
| Provider | `Local` |
| python_bin | `python3` (défaut) |
| timeout | 30 s (défaut) |
| max_memory_mb | 512 (défaut) |

---

## Configuration 2 — Self-Managed (self-hosted)

Le provider `self_managed` délègue l'exécution au service **`sandbox-executor-manager`** (conteneur dédié, port 9385). Au démarrage, ce service pré-crée un **pool de conteneurs d'exécution jetables** (3 Python + 3 Node.js par défaut, `SANDBOX_EXECUTOR_MANAGER_POOL_SIZE`) avec le runtime **gVisor (`runsc`)**, qui isole le code exécuté du noyau de l'hôte. Chaque exécution consomme un conteneur du pool, qui est ensuite recyclé.

| Champ | Valeur |
|---|---|
| Provider | `Self-Managed` |
| Executor Manager Endpoint | `http://sandbox-executor-manager:9385` |

> ⚠️ **Ne pas utiliser `http://localhost:9385`** comme endpoint : le health check est effectué depuis le conteneur RAGFlow (où tourne le serveur admin), pour lequel `localhost` ne pointe pas vers le manager. L'erreur résultante est opaque : « *Failed to initialize provider 'self_managed'* ».

### Analyse de sécurité du code (mode self-hosted uniquement)

Avant exécution, le manager analyse statiquement le code (AST, `agent/sandbox/executor_manager/services/security.py`) et **rejette** (« Code is unsafe ») tout script contenant :

- **Imports interdits** : `os`, `sys`, `subprocess`, `shutil`, `socket`, `ctypes`, `pickle`, `threading`, `multiprocessing`, `asyncio`, `builtins`…
- **Appels interdits** : `eval`, `exec`, `open`, `__import__`, `compile`, `getattr`/`setattr`, `globals`/`locals`…
- **Opérations binaires entre deux constantes littérales** (détection de concaténations suspectes type `"os." + "system"`) — écrire `x = 4` plutôt que `x = 2 + 2`.

Les modules `re`, `math`, `json`, ainsi que `pandas`, `numpy`, `matplotlib` et `requests` (préinstallés dans l'image Python) sont utilisables. Le provider `local` n'applique **pas** cette analyse — un script accepté en local peut donc être rejeté en self-hosted.

### Prérequis du mode self-hosted

Les commandes exactes dépendent de la cible (distribution, gestion de configuration). Sur les plateformes gérées par Ansible (dépôt `Eurelis-AnsiblePlaybooks/Eurelis-AWS`), l'ensemble est automatisé via `ragflow.sandbox.enabled: true` dans le `vars.yml` de l'hôte (tâches `roles/ragflow_install/tasks/gvisor.yml`).

1. **Hôte Linux** — gVisor est un logiciel exclusivement Linux. Le mode self-hosted est **impossible sous Docker Desktop macOS/Windows** (la VM gérée n'accepte pas de runtime supplémentaire) : le pool reste à 0/N avec l'erreur *unknown or invalid runtime name: runsc*.
2. **gVisor installé et enregistré comme runtime Docker** — le binaire `runsc` doit être présent sur l'hôte et déclaré dans `/etc/docker/daemon.json`. Le `--runtime=runsc` est codé en dur dans l'executor-manager (`executor_manager/core/container.py`) : sans lui, aucun conteneur d'exécution ne peut être créé. **L'enregistrement nécessite un redémarrage du démon Docker**, donc une brève interruption de toute la stack (une seule fois).
3. **Accès au socket Docker** — le service `sandbox-executor-manager` monte `/var/run/docker.sock` pour créer les conteneurs du pool sur l'hôte.
4. **Images de base pré-téléchargées** — `infiniflow/sandbox-base-python` et `infiniflow/sandbox-base-nodejs` doivent être présentes sur l'hôte **avant** le premier démarrage du service : la création des conteneurs du pool a un timeout de 10 s, insuffisant pour télécharger les images (symptôme : pool à 0/N avec *Command timed out* ; correctif : puller les images puis redémarrer le service).
5. **Profil compose `sandbox` activé** — le service est derrière un profil Docker Compose optionnel ; il faut l'ajouter à `COMPOSE_PROFILES`.
6. **Résolubilité réseau** — le conteneur RAGFlow doit joindre `sandbox-executor-manager:9385` (même réseau Docker Compose).

### Vérification du déploiement

- Logs du service : `Container pool initialization complete: 6/6 available` (et non 0/6).
- Les conteneurs `sandbox_python_*` / `sandbox_nodejs_*` tournent avec `runtime=runsc` (visible via `docker inspect`).
- Le *Test connection* de Admin > Sandbox Settings passe (il exécute un script de probe complet).

---

## Dépannage

| Symptôme | Cause | Correctif |
|---|---|---|
| Pool 0/N — *unknown or invalid runtime name: runsc* | gVisor absent ou non enregistré dans Docker | Installer/enregistrer gVisor, redémarrer le démon Docker |
| Pool 0/N — *Command timed out* | Images sandbox-base non présentes (téléchargement > 10 s) | Puller les images puis redémarrer le service |
| *Failed to initialize provider 'self_managed'* | Endpoint injoignable depuis le conteneur RAGFlow (souvent `localhost:9385`) | Utiliser `http://sandbox-executor-manager:9385` |
| *Execution timed out* au test alors que le health check passe | Pool vide : le service répond mais n'a aucun conteneur d'exécution | Voir les deux premières lignes |
| *Code is unsafe* | Script rejeté par l'analyseur AST (import/appel interdit) | Adapter le script (voir analyse de sécurité) |

---

## Workflows de test

Deux agents de test minimalistes (Begin → CodeExec → Message, **sans LLM**) permettent de valider la chaîne d'exécution de bout en bout. Le script extrait les nombres du message utilisateur et calcule des statistiques ; le nœud Message affiche le résultat ainsi que la variable `_ERROR` pour diagnostiquer directement un échec sandbox.

| Fichier | Mode | Particularité |
|---|---|---|
| [`code-exec-test-agent-unsafe.json`](./code-exec-test-agent-unsafe.json) | Local uniquement | Utilise `sys`/`platform` (rejeté par l'analyseur self-hosted) |
| [`code-exec-test-agent-safe.json`](./code-exec-test-agent-safe.json) | Local + Self-Managed | Imports limités à `re`/`math`, conforme à l'analyseur |

**Import** : page *Agents* → *Import JSON*. Le fichier doit contenir le DSL **à la racine** (`graph`, `components`, …) — le format template backend `{id, title, dsl: {...}}` donne un canvas vide sans erreur. Test : envoyer par exemple « `calcule 12 7 33.5` ».

---

## Validation

Validation effectuée le 2026-07-25 :

- Provider `local` en développement (macOS, stack `docker-compose-macos.yml`).
- Provider `self_managed` sur la plateforme AI Lab Sandbox (`aws-eur-integ-rgf01`) : gVisor déployé via Ansible, pool 6/6, test de connexion admin et workflow `safe` validés (exécution ~180 ms dans un conteneur `runsc`).
