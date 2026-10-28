.PHONY: help up down logs sh test test-fast test-all seed reset build-prod build-dev

help:
	@echo "SYNORA — common commands"
	@echo ""
	@echo "  build          Build backend with current INSTALL_DEV (.env)"
	@echo "  build-dev      Rebuild with INSTALL_DEV=true (includes pytest)"
	@echo "  build-prod     Rebuild with INSTALL_DEV=false (production image)"
	@echo "  up             Start all services"
	@echo "  down           Stop all services"
	@echo "  logs           Tail backend logs"
	@echo "  sh             Shell into backend"
	@echo "  test-fast      Fast tests (no LLM, ~15s)"
	@echo "  test-all       All tests including LLM E2E (~11 min)"
	@echo "  seed           Seed agents + scenarios"
	@echo "  reset          Drop DB + rebuild + seed"

build:
	docker compose build backend

build-dev:
	docker compose build --build-arg INSTALL_DEV=true backend

build-prod:
	docker compose build --build-arg INSTALL_DEV=false backend

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f backend

sh:
	docker compose exec backend bash

test-fast:
	docker compose exec -T backend pytest -v -m "not slow"

test-all:
	docker compose exec -T backend sh -c "RUN_SLOW=1 pytest -v"

test: test-fast

seed:
	docker compose exec -T backend python -m synora.cli.seed_agents
	docker compose exec -T backend python -m synora.cli.seed_scenarios

reset:
	docker compose down -v
	docker compose up -d postgres ollama
	docker compose up ollama-init
	docker compose up -d backend
	@echo "Waiting for backend..."
	@sleep 8
	docker compose exec -T backend python -m synora.cli.seed_agents
	docker compose exec -T backend python -m synora.cli.seed_scenarios
