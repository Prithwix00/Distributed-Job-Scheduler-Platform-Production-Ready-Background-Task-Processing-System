# Convenience targets. Run `make help` for the list.

.PHONY: help up down logs seed test backend-dev worker-dev scheduler-dev frontend-dev install

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Build and start the whole stack (postgres, api, scheduler, 2 workers, frontend)
	docker compose up --build

down: ## Stop the stack and remove volumes
	docker compose down -v

logs: ## Tail all service logs
	docker compose logs -f

seed: ## Populate a demo workspace (API must be running)
	cd backend && python -m app.runtime.seed --base-url http://localhost:8000

test: ## Run the backend test suite
	cd backend && python -m pytest

install: ## Install backend deps into a local venv
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

backend-dev: ## Run the API locally against SQLite
	cd backend && DATABASE_URL=sqlite:///./dev.db uvicorn app.main:app --reload

scheduler-dev: ## Run the scheduler locally against SQLite
	cd backend && DATABASE_URL=sqlite:///./dev.db python -m app.runtime.scheduler

worker-dev: ## Run a worker locally against the local API
	cd backend && DATABASE_URL=sqlite:///./dev.db python -m app.runtime.worker --base-url http://localhost:8000

frontend-dev: ## Run the Vite dev server
	cd frontend && npm install && npm run dev
