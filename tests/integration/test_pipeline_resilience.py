import json
import re
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from pytest_httpserver import HTTPServer

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
from tadween_preprocess.runner import notify_webhook, run


def _create_item(name: str, base_url: str) -> PreprocessItem:
    return PreprocessItem(
        context=ItemContext(file_id=uuid.uuid4(), filename=f"{name}.mp3"),
        source=HttpLocation(url=f"{base_url}/{name}"),
        sink=HttpLocation(url=f"{base_url}/put_{name}", method="PUT"),
        options=ItemOptions(
            require_duration=True,
            require_size=True,
            require_compression=True,
            declared_duration_seconds=10.0,
            declared_size_bytes=1024,
            tolerance_rate=0.1,
        ),
    )


def test_pipeline_honeycomb_error_matrix_and_webhook_reporting(
    httpserver: HTTPServer,
    mock_convert_to_opus: MagicMock,
    mock_get_media_metadata: MagicMock,
    tmp_path: Path,
):
    # 1. Setup mock server endpoints
    httpserver.expect_request("/dl_fail").respond_with_data("Not Found", status=404)
    httpserver.expect_request("/put_upload_fail", method="PUT").respond_with_data(
        "Forbidden", status=403
    )

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

    # 2. Define all items that represent edge cases
    item_happy = _create_item("happy", base_url)
    item_dl_fail = _create_item("dl_fail", base_url)
    item_meta_fail = _create_item("meta_fail", base_url)
    item_size_fail = _create_item("size_fail", base_url)
    item_duration_fail = _create_item("duration_fail", base_url)
    item_compress_fail = _create_item("compress_fail", base_url)
    item_upload_fail = _create_item("upload_fail", base_url)
    item_unexpected = _create_item("unexpected", base_url)
    item_no_audio = _create_item("no_audio", base_url)

    items_list = [
        item_happy,
        item_dl_fail,
        item_meta_fail,
        item_size_fail,
        item_duration_fail,
        item_compress_fail,
        item_upload_fail,
        item_unexpected,
        item_no_audio,
    ]

    orig_meta = mock_get_media_metadata.side_effect

    def meta_effect(file_path, *args, **kwargs):
        path_str = str(file_path)
        if str(item_meta_fail.context.file_id) in path_str:
            raise ValueError("FFprobe failed: Metadata extraction failed")
        if str(item_no_audio.context.file_id) in path_str:
            meta = orig_meta(file_path, *args, **kwargs)
            meta.audio_streams = []
            meta.format_name = "mp4"
            meta.duration = 10.0
            return meta
        if str(item_duration_fail.context.file_id) in path_str:
            meta = orig_meta(file_path, *args, **kwargs)
            meta.duration = 100.0  # Force duration drift violation
            return meta
        if str(item_unexpected.context.file_id) in path_str:
            raise RuntimeError("Something completely unexpected")
        meta = orig_meta(file_path, *args, **kwargs)
        meta.duration = 10.0
        return meta

    mock_get_media_metadata.side_effect = meta_effect

    orig_compress = mock_convert_to_opus.side_effect

    def compress_effect(input_file, *args, **kwargs):
        if str(item_compress_fail.context.file_id) in str(input_file):
            raise ValueError("Compression failed")
        return orig_compress(input_file, *args, **kwargs)

    mock_convert_to_opus.side_effect = compress_effect

    # 3. Execution
    orchestrator = Orchestrator()
    batch_id = uuid.uuid4()
    req = PreprocessJobRequest(
        webhook=WebhookConfig(url=f"{base_url}/webhook", token="secret"),
        batch=PreprocessBatch(
            id=batch_id,
            files={item.context.file_id: item for item in items_list},
        ),
    )

    # For size drift test, adjust item_size_fail's declared size
    item_size_fail.options.declared_size_bytes = (
        100  # 1024 downloaded vs 100 declared is >10% drift
    )

    run(req, cache_dir=tmp_path, orchestrator=orchestrator)

    # 4. Assertions on the side effects
    webhook_calls = [req for req, res in httpserver.log if req.path == "/webhook"]
    assert len(webhook_calls) == 1
    payload = json.loads(webhook_calls[0].data)

    assert payload["job_id"] == str(batch_id)
    results = payload["files"]
    assert len(results) == len(items_list)

    res_happy = results[str(item_happy.context.file_id)]
    assert res_happy["status"] == "completed"

    res_dl = results[str(item_dl_fail.context.file_id)]
    assert res_dl["status"] == "failed"
    assert res_dl["failed_step"] == "source"
    assert "404" in res_dl["error"] or "Not Found" in res_dl["error"]

    res_meta = results[str(item_meta_fail.context.file_id)]
    assert res_meta["status"] == "flagged"
    assert res_meta["failed_step"] == "metadata"
    assert res_meta["error"] == "invalid_media_type"

    res_no_audio = results[str(item_no_audio.context.file_id)]
    assert res_no_audio["status"] == "flagged"
    assert res_no_audio["failed_step"] == "metadata"
    assert res_no_audio["error"] == "no_audio_stream"

    res_size = results[str(item_size_fail.context.file_id)]
    assert res_size["status"] == "flagged"
    assert res_size["error"] == "size_drift_exceeded"

    res_duration = results[str(item_duration_fail.context.file_id)]
    assert res_duration["status"] == "flagged"
    assert res_duration["error"] == "duration_drift_exceeded"

    res_comp = results[str(item_compress_fail.context.file_id)]
    assert res_comp["status"] == "failed"
    assert res_comp["failed_step"] == "compress"
    assert "Compression failed" in res_comp["error"]

    res_ul = results[str(item_upload_fail.context.file_id)]
    assert res_ul["status"] == "failed"
    assert res_ul["failed_step"] == "sink"
    assert "403" in res_ul["error"] or "Forbidden" in res_ul["error"]

    res_unexp = results[str(item_unexpected.context.file_id)]
    assert res_unexp["status"] == "failed"
    assert "Something completely unexpected" in res_unexp["error"]


@patch("tadween_preprocess.runner.time.sleep")
def test_webhook_delivery_retries_transient_failures_until_exhausted(
    mock_sleep: MagicMock, httpserver: HTTPServer
):
    httpserver.expect_request("/webhook_fail").respond_with_data(
        "Server Error", status=500
    )
    base_url = httpserver.url_for("")

    webhook = WebhookConfig(
        url=f"{base_url}/webhook_fail",
        token="secret",
        max_retries=3,
        retry_delay_seconds=1,
    )

    notify_webhook(webhook=webhook, payload={"job_id": str(uuid.uuid4()), "files": {}})

    assert mock_sleep.call_count == 2
    requests = [r for r, _ in httpserver.log if r.path == "/webhook_fail"]
    assert len(requests) == 3
