.PHONY: dev dev-backend dev-frontend docker docker-down test test-backend test-frontend build clean help

# Default target
help:
	@echo "Work-Flow Platform"
	@echo ""
	@echo "Development:"
	@echo "  make dev            - Start all services locally (Temporal + Backend + Frontend)"
	@echo "  make dev-backend    - Start backend only (Temporal + Worker + FastAPI)"
	@echo "  make dev-frontend   - Start frontend dev server only"
	@echo ""
	@echo "Docker:"
	@echo "  make docker         - Build and start all services via Docker Compose"
	@echo "  make docker-down    - Stop and remove Docker Compose services"
	@echo ""
	@echo "Testing:"
	@echo "  make test           - Run all tests (backend + frontend)"
	@echo "  make test-backend   - Run backend tests (pytest)"
	@echo "  make test-frontend  - Run frontend tests (vitest)"
	@echo ""
	@echo "Build:"
	@echo "  make build          - Build frontend for production"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          - Remove build artifacts and logs"

# ---- Development ----

dev:
	@echo "Starting all services..."
	@$(MAKE) -C backend dev &
	@sleep 5
	@cd frontend && npm run dev

dev-backend:
	@$(MAKE) -C backend dev

dev-frontend:
	@cd frontend && npm run dev

# ---- Docker ----

docker:
	docker compose up --build

docker-down:
	docker compose down

# ---- Testing ----

test: test-backend test-frontend

test-backend:
	@cd backend && python -m pytest

test-frontend:
	@cd frontend && npm test -- --run

# ---- Build ----

build:
	@cd frontend && npm run build

# ---- Cleanup ----

clean:
	@$(MAKE) -C backend clean
	@rm -rf frontend/.next frontend/node_modules/.cache
	@echo "Cleaned build artifacts and logs."
