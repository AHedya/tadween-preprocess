# Developer Command Reference

This document provides a fast, copy-pasteable reference of all commands used for local development, code quality verification, testing, coverage analysis, pre-commit hooks, and Docker workflows.

---

## 1. Quality Gates & Static Analysis

```bash
# Run complete quality suite via Nox (Ruff lint + format check + Pyrefly type check)
uv run nox -t quality

# Run Ruff linter
uv run ruff check .

# Automatically fix fixable lint errors
uv run ruff check --fix .

# Check code formatting
uv run ruff format --check .

# Automatically apply formatting
uv run ruff format .

# Run Pyrefly static type checking
uv run pyrefly check
```

---

## 2. Pre-Commit Hooks & Local CI Testing

```bash
# Install pre-commit git hook (runs nox -t quality on commit)
uv run pre-commit install

# Manually trigger pre-commit hooks across all files
uv run pre-commit run --all-files

# Test GitHub Actions CI workflow locally using act
act push
```

---

## 3. Testing & Code Coverage

```bash
# Run all unit and integration tests
uv run pytest

# Run tests with terminal missing-lines coverage report
uv run pytest --cov=src/tadween_preprocess --cov-report=term-missing

# Generate HTML coverage report (opens in htmlcov/index.html)
uv run pytest --cov=src/tadween_preprocess --cov-report=html
```

---

## 4. Docker Image Multi-Stage Builds

```bash
# Build production RunPod serverless worker image
docker build --target runpod -t tadween-preprocess:latest .

# Build test runner container image
docker build --target test -t tadween-preprocess:test .

# Build full dev image with all tooling
docker build --target dev -t tadween-preprocess:dev .
```

---

## 5. Dependency Management

```bash
# Sync all dependencies including dev, test, and worker extras
uv sync --all-groups --all-extras

# Lock dependencies without modifying virtualenv
uv lock

# Add a new runtime dependency to worker extra
uv add <package_name> --extra worker

# Add a new development dependency
uv add <package_name> --group dev
```