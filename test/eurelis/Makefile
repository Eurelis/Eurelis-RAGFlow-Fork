# Eurelis — orchestration des tests de non-régression (stack RAGFlow complète, sans bouchons).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Usage :  make -C test/eurelis <cible>   (ou depuis test/eurelis/ : make <cible>)
# Réf :    docs/eurelis/specs/tests-non-regression/strategy.md
#
# Cible tout-en-un :  make e2e            (up → models → seed → run)
# Rejeu rapide :      make e2e-run        (stack déjà up)
# Reset total :       make e2e-reset      (down -v)

# --- Chemins (calculés depuis l'emplacement de ce Makefile) ---------------------------------
MAKEFILE_DIR := $(patsubst %/,%,$(dir $(realpath $(lastword $(MAKEFILE_LIST)))))
REPO_ROOT    := $(realpath $(MAKEFILE_DIR)/../..)
COMPOSE_FILE := $(REPO_ROOT)/docker/docker-compose-test.yml

# --- Paramètres (surchargables : make e2e RAGFLOW_TEST_IMAGE=... ) ---------------------------
PROJECT              ?= ragflow-test
RAGFLOW_TEST_IMAGE   ?= eurelis/ragflow:v0.26.1-eurelis.3
RAGFLOW_TEST_PLATFORM?= linux/amd64
OLLAMA_CHAT_MODEL    ?= qwen2.5:0.5b
OLLAMA_EMBED_MODEL   ?= nomic-embed-text

# Endpoints exposés sur l'hôte
HOST_ADDRESS  ?= http://localhost:9380
ADMIN_ADDRESS ?= http://localhost:9381
OLLAMA_URL    ?= http://localhost:11434

RAGFLOW_CONTAINER := $(PROJECT)-ragflow-cpu-1
OLLAMA_CONTAINER  := $(PROJECT)-ollama-1

# docker compose préfixé des variables d'image/plateforme
COMPOSE := RAGFLOW_TEST_IMAGE=$(RAGFLOW_TEST_IMAGE) RAGFLOW_TEST_PLATFORM=$(RAGFLOW_TEST_PLATFORM) \
           docker compose -f $(COMPOSE_FILE)

# pytest depuis la racine du dépôt, ciblant la suite Eurelis.
# On préfère le .venv (rapide) et on retombe sur `uv run` s'il est absent.
# PYTEST_ARGS permet de filtrer :  make e2e-run PYTEST_ARGS="-m p0 -v"
PYTEST_ARGS ?=
PYBIN := $(if $(wildcard $(REPO_ROOT)/.venv/bin/python),$(REPO_ROOT)/.venv/bin/python,uv run python)
PYRUNNER := $(if $(wildcard $(REPO_ROOT)/.venv/bin/python),$(REPO_ROOT)/.venv/bin/python -m pytest,uv run pytest)
PYTEST := cd $(REPO_ROOT) && HOST_ADDRESS=$(HOST_ADDRESS) ADMIN_ADDRESS=$(ADMIN_ADDRESS) \
          OLLAMA_URL=$(OLLAMA_URL) $(PYRUNNER) test/eurelis $(PYTEST_ARGS)

.DEFAULT_GOAL := help
.PHONY: help e2e e2e-up e2e-wait e2e-models e2e-seed e2e-run e2e-health e2e-ps e2e-logs e2e-down e2e-reset e2e-pii-off

help: ## Affiche cette aide
	@echo "Tests de non-régression Eurelis — cibles disponibles :"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(firstword $(MAKEFILE_LIST)) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Image sous test : $(RAGFLOW_TEST_IMAGE)  (plateforme $(RAGFLOW_TEST_PLATFORM))"

e2e: e2e-up e2e-models e2e-seed e2e-run ## Cycle complet : up → models → seed → run

e2e-up: ## Démarre la stack de test et attend qu'elle soit healthy
	$(COMPOSE) up -d
	@$(MAKE) -s e2e-wait

e2e-wait: ## Attend que ragflow-cpu soit healthy (garde-fou anti-crashloop)
	@echo "Attente de $(RAGFLOW_CONTAINER) healthy…"
	@for i in $$(seq 1 80); do \
		h=$$(docker inspect -f '{{.State.Health.Status}}' $(RAGFLOW_CONTAINER) 2>/dev/null || echo missing); \
		r=$$(docker inspect -f '{{.RestartCount}}' $(RAGFLOW_CONTAINER) 2>/dev/null || echo 0); \
		if [ "$$h" = "healthy" ]; then echo "  → healthy (après ~$$((i*5))s)"; exit 0; fi; \
		if [ "$$r" -ge 5 ]; then echo "  → CRASHLOOP (restarts=$$r). Voir: make e2e-logs"; exit 1; fi; \
		sleep 5; \
	done; \
	echo "  → TIMEOUT (dernier statut=$$h). Voir: make e2e-logs"; exit 2

e2e-models: ## Précharge les modèles Ollama (chat + embedding)
	@echo "Pull des modèles Ollama dans $(OLLAMA_CONTAINER)…"
	docker exec $(OLLAMA_CONTAINER) ollama pull $(OLLAMA_CHAT_MODEL)
	docker exec $(OLLAMA_CONTAINER) ollama pull $(OLLAMA_EMBED_MODEL)
	@echo "Modèles présents :" && curl -s $(OLLAMA_URL)/api/tags | grep -o '"name":"[^"]*"' || true

e2e-seed: ## Injecte le jeu de données de référence (tenant, providers Ollama, docs, chat)
	cd $(REPO_ROOT) && HOST_ADDRESS=$(HOST_ADDRESS) ADMIN_ADDRESS=$(ADMIN_ADDRESS) \
		OLLAMA_URL=$(OLLAMA_URL) $(PYBIN) test/eurelis/seed.py

e2e-run: ## Lance pytest contre la stack déjà démarrée
	$(PYTEST)

e2e-health: ## Vérifie les endpoints de santé (ragflow + admin + ollama)
	@printf "healthz  : " && curl -s -o /dev/null -w "HTTP %{http_code}\n" $(HOST_ADDRESS)/api/v1/system/healthz
	@printf "admin    : " && curl -s -o /dev/null -w "HTTP %{http_code}\n" $(ADMIN_ADDRESS)/api/v1/admin/version
	@printf "ollama   : " && curl -s -o /dev/null -w "HTTP %{http_code}\n" $(OLLAMA_URL)/api/tags

e2e-ps: ## État des conteneurs de la stack de test
	$(COMPOSE) ps

e2e-logs: ## Suit les logs du conteneur ragflow (Ctrl-C pour quitter)
	docker logs -f --tail 100 $(RAGFLOW_CONTAINER)

e2e-pii-off: ## Recrée ragflow SANS masquage PII (boot plus rapide, sans Presidio)
	EURELIS_PII_ENABLED=false $(COMPOSE) up -d ragflow-cpu
	@$(MAKE) -s e2e-wait

e2e-down: ## Arrête la stack (volumes conservés → redémarrage rapide)
	$(COMPOSE) down

e2e-reset: ## Arrête la stack et supprime les volumes (état vierge)
	$(COMPOSE) down -v
