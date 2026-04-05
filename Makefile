# RAGFlow Makefile

# Default values
HOST ?= localhost
PORT ?= 9381
USERNAME ?= admin@ragflow.io

# Set PYTHONPATH to project root for proper imports
PYTHONPATH := $(shell pwd)

.PHONY: ragflow_cli help

# Launch RAGFlow CLI with proper environment
ragflow_cli:
	@echo "Launching RAGFlow CLI..."
	@echo "Host: $(HOST), Port: $(PORT), Username: $(USERNAME)"
	@cd admin/client && PYTHONPATH=$(PYTHONPATH) uv run ragflow_cli.py --host $(HOST) --port $(PORT) --username $(USERNAME)

# Launch RAGFlow CLI with custom parameters
# Usage: make ragflow_cli_custom HOST=dev.ai-lab.eurelis.info PORT=9381 USERNAME=admin@ragflow.io
ragflow_cli_custom:
	@echo "Launching RAGFlow CLI with custom parameters..."
	@echo "Host: $(HOST), Port: $(PORT), Username: $(USERNAME)"
	@cd admin/client && PYTHONPATH=$(PYTHONPATH) uv run ragflow_cli.py --host $(HOST) --port $(PORT) --username $(USERNAME)

# Launch RAGFlow CLI for Eurelis dev environment
ragflow_cli_dev:
	@echo "Launching RAGFlow CLI for Eurelis dev environment..."
	@cd admin/client && PYTHONPATH=$(PYTHONPATH) uv run ragflow_cli.py --host dev.ai-lab.eurelis.info --port 9381 --username admin@ragflow.io

# Setup dependencies for RAGFlow CLI
setup_cli:
	@echo "Setting up RAGFlow CLI dependencies..."
	@cd admin/client && uv sync

# Test CLI dependencies
test_cli:
	@echo "Testing RAGFlow CLI dependencies..."
	@cd admin/client && uv run python -c "from Cryptodome.Cipher import PKCS1_v1_5; print('✓ pycryptodomex OK')"
	@cd admin/client && uv run python -c "import requests; print('✓ requests OK')"
	@cd admin/client && uv run python -c "import lark; print('✓ lark OK')"

# Show help
help:
	@echo "Available commands:"
	@echo "  ragflow_cli      - Launch RAGFlow CLI with default settings"
	@echo "  ragflow_cli_dev  - Launch RAGFlow CLI for Eurelis dev environment"
	@echo "  ragflow_cli_custom HOST=<host> PORT=<port> USERNAME=<user> - Launch with custom parameters"
	@echo "  setup_cli        - Install CLI dependencies"
	@echo "  test_cli         - Test CLI dependencies"
	@echo "  help             - Show this help"
	@echo ""
	@echo "Examples:"
	@echo "  make ragflow_cli"
	@echo "  make ragflow_cli_dev" 
	@echo "  make ragflow_cli_custom HOST=myhost.com PORT=9381 USERNAME=user@example.com"