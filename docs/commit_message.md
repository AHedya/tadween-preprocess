test(ci): update test suite structure, add pre-commit hook, and simplify CI

Split and organize test suite, move quality checks
to a local pre-commit hook running `nox -t quality`, and
simplify the CI workflow for GitHub Actions and local `act` testing.

### Key Changes
- **Test Suite Organization**: Split mixed test files into focused modules across `unit/` and `integration/`layers, standardizing test names and adding an FFmpeg check to skip missing binary errors.
- **Dropped E2E**.
- **Pre-Commit Hook**: Added `pre-commit` to run `uv run nox -t quality` (Ruff linter/formatter and Pyrefly type checking) locally before commits.
- **CI Workflow**: Removed quality and release jobs from GitHub Actions to run pytest only, and updated `.actrc` for local testing with `act`.
- **Cleanup & Docs**: Removed old `dist/` files, cleaned up unused sessions in `noxfile.py`, and updated `docs/CMDs.md`.
