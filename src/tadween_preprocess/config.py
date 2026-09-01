import os
import sys

from resource_semaphore.utils import get_memory, get_storage


def _get_int_env(name: str, default: int) -> int:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    val = os.environ.get(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def get_service_name() -> str:
    """Return the configured service name, defaulting to 'tadween_preprocess'."""
    return (os.environ.get("SERVICE_NAME") or "tadween_preprocess").strip()


def get_cpu_workers() -> int:
    return _get_int_env("PREPROCESS_CPU_WORKERS", os.cpu_count() or 4)


def get_download_workers() -> int:
    return _get_int_env("PREPROCESS_DOWNLOAD_WORKERS", 20)


def get_upload_workers() -> int:
    return _get_int_env("PREPROCESS_UPLOAD_WORKERS", 10)


def get_disk_budget_bytes(cache_dir: str | None = None) -> int:
    """
    Disk budget in bytes. Returns sys.maxsize if not configured and
    no cache_dir provided for auto-detection.
    Set 0 to explicitly disable (returns sys.maxsize).
    """
    configured = os.environ.get("PREPROCESS_DISK_BUDGET_BYTES")
    if configured is not None:
        try:
            val = int(configured)
            return val if val > 0 else sys.maxsize
        except ValueError:
            return sys.maxsize
    if cache_dir:
        try:
            free_bytes = get_storage(cache_dir)
            return int(free_bytes * 0.8)
        except Exception:
            return sys.maxsize
    return sys.maxsize


def get_ram_budget_bytes() -> int:
    """
    Total RAM budget in bytes. Returns sys.maxsize if not configured
    and auto-detection fails.
    Set 0 to explicitly disable (returns sys.maxsize).
    """
    configured = os.environ.get("PREPROCESS_RAM_BUDGET_MB")
    if configured is not None:
        try:
            val = int(configured)
            return val * 1024 * 1024 if val > 0 else sys.maxsize
        except ValueError:
            return sys.maxsize

    try:
        return int(get_memory() * 0.8)
    except Exception:
        return sys.maxsize


def get_ram_per_cpu_bytes() -> int:
    """RAM claimed per FFmpeg compression process."""
    mb = _get_int_env("PREPROCESS_RAM_PER_CPU_MB", 100)
    return mb * 1024 * 1024


def get_disk_multiplier() -> float:
    return _get_float_env("PREPROCESS_DISK_MULTIPLIER", 1.1)


def get_max_file_bytes() -> int:
    """Max file size per download in bytes. Default 2GB."""
    mb = _get_int_env("PREPROCESS_MAX_FILE_SIZE_MB", 2048)
    return mb * 1024 * 1024
