import os
import sys

import nox

sys.path.insert(0, os.path.dirname(__file__))

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True
PY_VERSION = "3.14"


@nox.session(tags=["lint"], python=PY_VERSION)
def lint(session: nox.Session):
    session.run_install("uv", "pip", "install", "ruff")
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")


@nox.session(tags=["style"], python=PY_VERSION)
def apply_style(session: nox.Session):
    session.run_install("uv", "pip", "install", "ruff")
    session.run("ruff", "check", "--fix", ".")
    session.run("ruff", "format", ".")


@nox.session(tags=["type"], python=PY_VERSION)
def type_check(session: nox.Session):
    session.run("uv", "sync", "--active", "--all-extras", "--all-groups")
    session.run("pyrefly", "check")


@nox.session(tags=["quality", "static_analysis"], python=PY_VERSION)
def quality(
    session: nox.Session,
):
    """Run linting, formatting check, and type check."""
    session.run("uv", "sync", "--active", "--all-extras", "--all-groups")
    session.run("ruff", "check", ".")
    session.run("ruff", "format", "--check", ".")
    session.run("pyrefly", "check")
