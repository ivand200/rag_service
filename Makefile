.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend
COMPOSE := docker compose

.PHONY: help \
	fix test check \
	check-frontend check-all \
	infra-up infra-down infra-logs infra-ps infra-config \
	migrate migrate-current migrate-history

help:
	@printf "\nAvailable targets:\n"
	@printf "  %-18s %s\n" "fix" "Run backend Ruff autofix and formatting"
	@printf "  %-18s %s\n" "test" "Run backend pytest suite"
	@printf "  %-18s %s\n" "check" "Run backend fix + tests"
	@printf "  %-18s %s\n" "check-frontend" "Run frontend typecheck and production build"
	@printf "  %-18s %s\n" "check-all" "Run backend and frontend checks"
	@printf "  %-18s %s\n" "infra-up" "Start local Docker Compose stack with rebuild"
	@printf "  %-18s %s\n" "infra-down" "Stop local Docker Compose stack"
	@printf "  %-18s %s\n" "infra-logs" "Tail Docker Compose logs"
	@printf "  %-18s %s\n" "infra-ps" "Show Docker Compose services"
	@printf "  %-18s %s\n" "infra-config" "Validate/render Docker Compose config"
	@printf "  %-18s %s\n" "migrate" "Run Alembic migrations to head"
	@printf "  %-18s %s\n" "migrate-current" "Show current Alembic revision"
	@printf "  %-18s %s\n" "migrate-history" "Show Alembic migration history"

fix:
	cd $(BACKEND_DIR) && uv run ruff check --fix .
	cd $(BACKEND_DIR) && uv run ruff format .

test:
	cd $(BACKEND_DIR) && uv run pytest tests -q

check: fix test

check-frontend:
	cd $(FRONTEND_DIR) && npm run typecheck
	cd $(FRONTEND_DIR) && npm run build

check-all: check check-frontend

infra-up:
	$(COMPOSE) up --build -d

infra-down:
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
