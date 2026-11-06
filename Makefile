.PHONY: help up down logs sh test test-fast test-all seed seed-kb refresh-kb eval-kb export-kb reset build-prod build-dev

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
	@echo "  seed-kb        Ingest data/knowledge_base/raw into the vector store"
	@echo "  refresh-kb     Update an existing knowledge base, embedding only changed text"
	@echo "  eval-kb        Measure retrieval against data/kb_eval_questions.json (no LLM)"
	@echo "  export-kb      Export the knowledge base in the ITU reference layout to kb_export/"
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
	docker compose exec -T backend python -m synora.cli.seed_agents --force
	docker compose exec -T backend python -m synora.cli.seed_scenarios --force

seed-kb:
	docker compose exec -T backend python -m synora.cli.seed_knowledge_base

refresh-kb:
	docker compose exec -T backend python -m synora.cli.seed_knowledge_base --refresh

eval-kb:
	docker compose exec -T backend python -m synora.cli.eval_kb > docs/kb-evaluation.md
	@cat docs/kb-evaluation.md

export-kb:
	docker compose exec -T backend python -m synora.cli.export_kb --out /tmp/kb_export
	rm -rf kb_export
	docker compose cp backend:/tmp/kb_export ./kb_export

reset:
	docker compose down -v
	docker compose up -d postgres ollama
	docker compose up ollama-init
	docker compose up -d backend
	@echo "Waiting for backend..."
	@sleep 8
	docker compose exec -T backend python -m synora.cli.seed_agents --force
	docker compose exec -T backend python -m synora.cli.seed_scenarios --force
	docker compose exec -T backend python -m synora.cli.seed_knowledge_base
