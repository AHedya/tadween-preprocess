import re
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

from pytest_httpserver import HTTPServer
from resource_semaphore import AsyncResourceSemaphore

from tadween_preprocess.core.models import (
    HttpLocation,
    ItemContext,
    ItemOptions,
)
from tadween_preprocess.models import (
    PreprocessBatch,
    PreprocessItem,
    PreprocessJobRequest,
    WebhookConfig,
)
from tadween_preprocess.orchestrator import Orchestrator


def _create_item(name: str, base_url: str) -> PreprocessItem:
    return PreprocessItem(
        context=ItemContext(file_id=uuid.uuid4(), filename=f"{name}.mp3"),
        source=HttpLocation(url=f"{base_url}/{name}"),
        sink=HttpLocation(url=f"{base_url}/put_{name}", method="PUT"),
        options=ItemOptions(
            require_duration=True,
            require_size=True,
            require_compression=True,
            declared_duration_seconds=600.0,
            declared_size_bytes=1024,
            tolerance_rate=0.1,
        ),
    )


async def test_orchestrator_resource_concurrency_tracks_and_releases_all_allocations(
    httpserver: HTTPServer,
    mock_convert_to_opus: MagicMock,
    mock_get_media_metadata: MagicMock,
    tmp_path: Path,
):
    httpserver.expect_request(re.compile(r"^/.*"), method="GET").respond_with_data(
        b"x" * 1024
    )
    httpserver.expect_request(re.compile(r"^/put_.*"), method="PUT").respond_with_data(
        "OK", status=200
    )
    httpserver.expect_request("/webhook", method="POST").respond_with_json(
        {"status": "ok"}
    )
    base_url = httpserver.url_for("").rstrip("/")

    rm = AsyncResourceSemaphore(
        {
            "download_slots": 20,
            "cpu_cores": 4,
            "upload_slots": 10,
            "disk_bytes": 100 * 1024 * 1024,  # 100 MB
            "ram_bytes": 500 * 1024 * 1024,  # 500 MB
        }
    )

    orchestrator = Orchestrator(rm=rm)

    items = [_create_item(f"item_{i}", base_url) for i in range(5)]
    batch_id = uuid.uuid4()
    req = PreprocessJobRequest(
        webhook=WebhookConfig(url=f"{base_url}/webhook", token="secret"),
        batch=PreprocessBatch(
            id=batch_id,
            files={item.context.file_id: item for item in items},
        ),
    )

    results = await orchestrator.execute_async(req, temp_dir=tmp_path)

    assert len(results) == 5
    for res in results.values():
        assert res.status == "completed"

    assert rm.available["download_slots"] == 20
    assert rm.available["cpu_cores"] == 4
    assert rm.available["upload_slots"] == 10
    assert rm.available["disk_bytes"] == 100 * 1024 * 1024
    assert rm.available["ram_bytes"] == 500 * 1024 * 1024


async def test_orchestrator_resource_backpressure_serializes_execution_under_constrained_disk(
    httpserver: HTTPServer,
    mock_convert_to_opus: MagicMock,
    mock_get_media_metadata: MagicMock,
    tmp_path: Path,
):
    httpserver.expect_request(re.compile(r"^/.*"), method="GET").respond_with_data(
        b"x" * 1024
    )
    httpserver.expect_request(re.compile(r"^/put_.*"), method="PUT").respond_with_data(
        "OK", status=200
    )
    httpserver.expect_request("/webhook", method="POST").respond_with_json(
        {"status": "ok"}
    )
    base_url = httpserver.url_for("").rstrip("/")

    rm = AsyncResourceSemaphore(
        {
            "download_slots": 20,
            "cpu_cores": 4,
            "upload_slots": 10,
            "disk_bytes": 1500,
            "ram_bytes": sys.maxsize,
        }
    )

    orchestrator = Orchestrator(rm=rm)

    items = [_create_item(f"item_{i}", base_url) for i in range(3)]
    batch_id = uuid.uuid4()
    req = PreprocessJobRequest(
        webhook=WebhookConfig(url=f"{base_url}/webhook", token="secret"),
        batch=PreprocessBatch(
            id=batch_id,
            files={item.context.file_id: item for item in items},
        ),
    )

    results = await orchestrator.execute_async(req, temp_dir=tmp_path)

    assert len(results) == 3
    for res in results.values():
        assert res.status == "completed"

    # All resources must be safely released
    assert rm.available["download_slots"] == 20
    assert rm.available["cpu_cores"] == 4
    assert rm.available["upload_slots"] == 10
    assert rm.available["disk_bytes"] == 1500
