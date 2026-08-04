.PHONY: install install-frontend dev dev-backend dev-frontend lint format typecheck security test run build clean

# ─── Installation ────────────────────────────────────────────────────────────

install: ## Install all Python dependencies
	pip install -r requirements.txt

install-dev: ## Install development dependencies
	pip install -r requirements.txt ruff mypy pre-commit

install-frontend: ## Install frontend dependencies
	cd frontend && npm install

install-all: install install-dev install-frontend ## Install everything

# ─── Development ──────────────────────────────────────────────────────────────

dev: ## Start both backend and frontend
	python scripts/run.sh

dev-backend: ## Start backend server only
	python -m uvicorn app.web.api:app --host 0.0.0.0 --port 8000 --reload

dev-frontend: ## Start frontend dev server only
	cd frontend && npm run dev

# ─── Code Quality ────────────────────────────────────────────────────────────

lint: ## Lint Python code with ruff
	ruff check app/

lint-fix: ## Fix lint issues automatically
	ruff check --fix app/

format: ## Format Python code with ruff
	ruff format app/

format-check: ## Check formatting without changes
	ruff format --check app/

typecheck: ## Run mypy type checking
	mypy app/

typecheck-strict: ## Run mypy with strict settings
	mypy --strict app/

security: ## Run security scanners
	bandit -r app/ -x app/tests/

security-verbose: ## Run all security scanners with detailed output
	bandit -r app/ -x app/tests/ -f json

lint-all: lint format-check typecheck security ## Run all linting and checks

# ─── Testing ─────────────────────────────────────────────────────────────────

test: ## Run functional test
	python scripts/test_run.py

smoke-test: ## Run smoke test
	@echo "Checking Python version..."
	python --version
	@echo "Checking lint..."
	ruff check app/ --statistics

# ─── Pre-commit ──────────────────────────────────────────────────────────────

pre-commit-install: ## Install pre-commit hooks
	pre-commit install

pre-commit-run: ## Run pre-commit on all files
	pre-commit run --all-files

# ─── Build ────────────────────────────────────────────────────────────────────

build: ## Build Windows executable
	python scripts/build_exe.py

build-frontend: ## Build frontend for production
	cd frontend && npm run build

clean: ## Clean build artifacts and caches
	rm -rf build/ dist/ *.spec __pycache__/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .mypy_cache/ .ruff_cache/ .pytest_cache/

# ─── Help ─────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
