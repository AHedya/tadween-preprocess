from unittest.mock import patch

from tadween_preprocess.config import (
    get_cpu_workers,
    get_disk_budget_bytes,
    get_disk_multiplier,
    get_download_workers,
    get_max_file_bytes,
    get_ram_budget_bytes,
    get_ram_per_cpu_bytes,
    get_upload_workers,
)


def test_config_env_worker_and_multiplier_parsing(monkeypatch):
    monkeypatch.setenv("PREPROCESS_CPU_WORKERS", "invalid")
    assert isinstance(get_cpu_workers(), int)

    monkeypatch.setenv("PREPROCESS_DOWNLOAD_WORKERS", "bad_int")
    assert get_download_workers() == 20

    monkeypatch.setenv("PREPROCESS_UPLOAD_WORKERS", "15")
    assert get_upload_workers() == 15

    monkeypatch.setenv("PREPROCESS_DISK_MULTIPLIER", "not_a_float")
    assert get_disk_multiplier() == 1.1

    monkeypatch.setenv("PREPROCESS_MAX_FILE_SIZE_MB", "invalid")
    assert get_max_file_bytes() == 2048 * 1024 * 1024

    monkeypatch.setenv("PREPROCESS_RAM_PER_CPU_MB", "invalid")
    assert get_ram_per_cpu_bytes() == 100 * 1024 * 1024

    monkeypatch.setenv("PREPROCESS_DISK_BUDGET_BYTES", "invalid")
    assert get_disk_budget_bytes() > 0

    monkeypatch.setenv("PREPROCESS_RAM_BUDGET_MB", "invalid")
    assert get_ram_budget_bytes() > 0


def test_config_disk_and_ram_budget_fallbacks(monkeypatch):
    monkeypatch.setenv("PREPROCESS_DISK_BUDGET_BYTES", "not_a_number")
    assert get_disk_budget_bytes() > 0

    monkeypatch.setenv("PREPROCESS_DISK_BUDGET_BYTES", "-100")
    assert get_disk_budget_bytes() > 0

    monkeypatch.delenv("PREPROCESS_DISK_BUDGET_BYTES", raising=False)
    with patch(
        "tadween_preprocess.config.get_storage", side_effect=Exception("Storage error")
    ):
        assert get_disk_budget_bytes(cache_dir="/dummy") > 0

    monkeypatch.setenv("PREPROCESS_RAM_BUDGET_MB", "not_a_number")
    assert get_ram_budget_bytes() > 0

    monkeypatch.delenv("PREPROCESS_RAM_BUDGET_MB", raising=False)
    with patch(
        "tadween_preprocess.config.get_memory", side_effect=Exception("RAM error")
    ):
        assert get_ram_budget_bytes() > 0
