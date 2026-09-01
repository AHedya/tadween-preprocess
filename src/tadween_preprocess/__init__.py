"""
Tadween Preprocess: Media Preprocessing Microservice & Client Package.

Client Usage (Monolith / Dispatcher):
    from tadween_preprocess.models import PreprocessJobRequest, PreprocessItem, ...

Worker Execution Engine:
    from tadween_preprocess import Orchestrator, run
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .orchestrator import Orchestrator
    from .runner import notify_webhook, run

__all__ = [
    "Orchestrator",
    "create_batch_from_directory",
    "notify_webhook",
    "run",
    "scan_directory_for_media",
]


def __getattr__(name: str) -> Any:
    if name == "Orchestrator":
        try:
            from .orchestrator import Orchestrator

            return Orchestrator
        except ImportError as e:
            raise ImportError(
                f"'{name}' requires worker dependencies. "
                "Install with: pip install 'tadween-preprocess[worker]'"
            ) from e

    if name in ("create_batch_from_directory", "scan_directory_for_media"):
        try:
            from .adapters import discovery

            return getattr(discovery, name)
        except ImportError as e:
            raise ImportError(
                f"'{name}' requires worker dependencies. "
                "Install with: pip install 'tadween-preprocess[worker]'"
            ) from e

    if name in ("notify_webhook", "run"):
        try:
            from . import runner

            return getattr(runner, name)
        except ImportError as e:
            raise ImportError(
                f"'{name}' requires worker dependencies. "
                "Install with: pip install 'tadween-preprocess[worker]'"
            ) from e

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
