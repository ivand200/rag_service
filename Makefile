.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend
COMPOSE := docker compose
PROJECT_DIR := $(CURDIR)
E2E_COMPOSE := $(COMPOSE) -f $(PROJECT_DIR)/docker-compose.yml -f $(PROJECT_DIR)/docker-compose.e2e.yml --project-directory $(PROJECT_DIR)

.PHONY: help \
	fix lint test e2e e2e-up e2e-down check check-frontend check-all qa \
	infra-up infra-down infra-down-v infra-logs infra-ps infra-config \
	migrate migrate-current migrate-history

help:
	@printf "\nAvailable targets:\n"
	@printf "  %-18s %s\n" "fix" "Run backend Ruff autofix and formatting"
	@printf "  %-18s %s\n" "lint" "Run backend Ruff checks without modifying files"
	@printf "  %-18s %s\n" "test" "Run backend pytest suite"
	@printf "  %-18s %s\n" "e2e" "Run Playwright E2E smoke suite against Docker Compose"
	@printf "  %-18s %s\n" "e2e-up" "Start deterministic E2E Docker Compose stack"
	@printf "  %-18s %s\n" "e2e-down" "Stop E2E stack and remove named volumes"
	@printf "  %-18s %s\n" "check" "Run backend lint + tests"
	@printf "  %-18s %s\n" "check-frontend" "Run frontend typecheck and production build"
	@printf "  %-18s %s\n" "check-all" "Run backend and frontend checks"
	@printf "  %-18s %s\n" "qa" "Run backend fix first, then tests"
	@printf "  %-18s %s\n" "infra-up" "Start local Docker Compose stack with rebuild"
	@printf "  %-18s %s\n" "infra-down" "Stop local Docker Compose stack"
	@printf "  %-18s %s\n" "infra-down-v" "Stop stack and remove named volumes"
	@printf "  %-18s %s\n" "infra-logs" "Tail Docker Compose logs"
	@printf "  %-18s %s\n" "infra-ps" "Show Docker Compose services"
	@printf "  %-18s %s\n" "infra-config" "Validate/render Docker Compose config"
	@printf "  %-18s %s\n" "migrate" "Run Alembic migrations to head"
	@printf "  %-18s %s\n" "migrate-current" "Show current Alembic revision"
	@printf "  %-18s %s\n" "migrate-history" "Show Alembic migration history"

fix:
	cd $(BACKEND_DIR) && uv run ruff check --fix .
	cd $(BACKEND_DIR) && uv run ruff format .

lint:
	cd $(BACKEND_DIR) && uv run ruff check .
	cd $(BACKEND_DIR) && uv run ruff format --check .

test:
	cd $(BACKEND_DIR) && uv run pytest tests -q

e2e:
	set -e; \
	$(E2E_COMPOSE) up --build -d; \
	trap '$(E2E_COMPOSE) down -v' EXIT; \
	cd $(FRONTEND_DIR) && PLAYWRIGHT_BASE_URL="$${PLAYWRIGHT_BASE_URL:-http://localhost:$${E2E_FRONTEND_PORT:-5173}}" npm run e2e

e2e-up:
	$(E2E_COMPOSE) up --build -d

e2e-down:
	$(E2E_COMPOSE) down -v

check: lint test

check-frontend:
	cd $(FRONTEND_DIR) && npm run typecheck
	cd $(FRONTEND_DIR) && npm run build

check-all: check check-frontend

qa: fix test

infra-up:
	$(COMPOSE) up --build -d

infra-down:
	$(COMPOSE) down

infra-down-v:
	$(COMPOSE) down -v

infra-logs:
	$(COMPOSE) logs -f

infra-ps:
	$(COMPOSE) ps

infra-config:
	$(COMPOSE) config

migrate:
	cd $(BACKEND_DIR) && uv run alembic upgrade head

migrate-current:
	cd $(BACKEND_DIR) && uv run alembic current

migrate-history:
	cd $(BACKEND_DIR) && uv run alembic history
