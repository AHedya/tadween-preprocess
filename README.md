# Tadween Preprocess

![License](https://img.shields.io/badge/License-AGPLv3-blue.svg)
![Python](https://img.shields.io/badge/Python-3.14-blue.svg)

A resilient, high-concurrency microservice and client package for media inspection, FFmpeg Opus transcoding, and storage lifecycle orchestration.

Designed for serverless container environments (e.g. [RunPod](https://runpod.io), Modal, AWS ECS/Fargate, GCP Cloud Run) and local batch workflows.

---

## Installation

Install only what you need depending on your deployment target:

```bash
# 1. Monolith / Dispatcher (Client schemas & validation only, zero heavy dependencies)
pip install tadween-preprocess

# 2. Worker Runtime / Container (Full pipeline engine, FFmpeg, HTTP streaming, telemetry). Sufficient for local uses.
pip install "tadween-preprocess[worker]"

# 3. Worker Runtime + supported serverless handler (runpod for example)
pip install "tadween-preprocess[worker,runpod]"

# 4. Worker + all non-confecting serverless handlers
pip install "tadween-preprocess[all]"
```

---

## 3-Minute Quickstart

### Mode 1: Dispatcher / Monolith (Dispatching S3 Presigned URLs)

If you are calling the worker from your backend:

```python
import uuid
from tadween_preprocess.models import (
    HttpLocation,
    ItemContext,
    ItemOptions,
    PreprocessBatch,
    PreprocessItem,
    PreprocessJobRequest,
    WebhookConfig,
)

file_id = uuid.uuid4()
batch_id = uuid.uuid4()

# 1. Build the Job Request
request = PreprocessJobRequest(
    webhook=WebhookConfig(
        url="https://api.yourdomain.com/webhooks/preprocess", token="jwt-secret"
    ),
    batch=PreprocessBatch(
        id=batch_id,
        files={
            file_id: PreprocessItem(
                context=ItemContext(file_id=file_id, filename="user_audio.mp3"),
                source=HttpLocation(
                    url="https://s3.amazonaws.com/bucket/raw.mp3?AWSAccessKeyId=..."
                ),
                sink=HttpLocation(
                    url="https://s3.amazonaws.com/bucket/processed.opus?AWSAccessKeyId=...",
                    method="PUT",
                ),
                options=ItemOptions(
                    require_compression=True,
                    require_duration=True,
                    require_size=True,
                ),
            )
        },
    ),
    telemetry_context={
        "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    },
)

# Send request.model_dump(mode="json") to your worker queue / RunPod endpoint!
```

---

### Mode 2: Serverless Worker Runtime (Executing Jobs)

Inside the worker container receiving jobs:

```python
from tadween_preprocess import run
from tadween_preprocess.models import PreprocessJobRequest


# Inside your queue/RunPod handler:
def handler(job_input: dict):
    request = PreprocessJobRequest.model_validate(job_input)

    # Executes the pipeline, sends the webhook, and cleans up scratchpad
    results = run(request)
    return {"status": "success", "processed_files": len(results)}
```

---

### Mode 3: Local Developer / CLI (Scraping Local Folders)

Process a local directory of audio files directly into Opus format:

```python
from pathlib import Path
from tadween_preprocess import create_batch_from_directory, run
from tadween_preprocess.core.models import ItemOptions
from tadween_preprocess.models import PreprocessJobRequest

# 1. Automatically discover all .mp3, .wav, .m4a, .flac files in a directory
batch = create_batch_from_directory(
    directory=Path("/data/raw_audio"),
    output_dir=Path("/data/compressed_opus"),
    recursive=True,
    options=ItemOptions(require_compression=True),
)

# 2. Execute local batch
request = PreprocessJobRequest(batch=batch)
results = run(request)

print(f"Processed {len(results)} files to /data/compressed_opus")
```

---

## Execution Pipeline Overview

Each item moves linearly through 4 decoupled hexagonal adapter stages:

| Stage | Adapter | Role | Resource Claimed |
| :--- | :--- | :--- | :--- |
| **1. Source** | `HTTPSource` / `LocalSource` | Streams remote file to `temp_dir/http` or symlinks local file to `temp_dir/local`. | `download_slots: 1` |
| **2. Budget** | `Orchestrator` | Measures raw file size and claims dynamic ephemeral disk budget ticket. | `disk_bytes: size * 1.1` |
| **3. Process** | `MediaProcessor` | Offloads FFprobe inspection & FFmpeg Opus transcode (`temp_dir/opus`) to worker threads. | `cpu_cores: 1, ram_bytes: 100MB` |
| **4. Sink** | `HTTPSink` / `LocalSink` | Streams output to remote HTTP PUT/POST URL or copies/moves to destination file path. | `upload_slots: 1` |
| **5. Cleanup** | `cleanup_envelope` | **Active working-set compaction**: Unlinks temp files and releases disk ticket immediately. | Releases `disk_bytes` |

---

## Configuration (Environment Variables)

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `production` | Set to `test` to disable real OTLP exports (uses in-memory telemetry). |
| `TELEMETRY_ENABLED` | `false` | Set to `1` or `true` to enable OpenTelemetry instrumentation. |
| `SERVICE_NAME` | `tadween_preprocess` | Microservice name in tracing dashboards. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (empty) | Your OTLP collector endpoint. |
| `PREPROCESS_CPU_WORKERS` | CPU Cores | Max concurrent FFmpeg compression processes (defaults to `os.cpu_count()`). |
| `PREPROCESS_DOWNLOAD_WORKERS` | `20` | Max concurrent download I/O slots. |
| `PREPROCESS_UPLOAD_WORKERS` | `10` | Max concurrent upload I/O slots. |
| `PREPROCESS_MAX_FILE_SIZE_MB` | `2048` (2 GB) | Hard download limit per file in MB. |
| `PREPROCESS_DISK_BUDGET_BYTES` | Auto-detect (80%) | Ephemeral disk budget. `0` = unlimited / auto-detect. |
| `PREPROCESS_DISK_MULTIPLIER` | `1.1` | Multiplier for dynamic disk claims to reserve space for converted output. |
| `PREPROCESS_RAM_BUDGET_MB` | Auto-detect (80%) | Total RAM budget in MB. `0` = unlimited / auto-detect. |
| `PREPROCESS_RAM_PER_CPU_MB` | `100` | RAM claim per concurrent FFmpeg process in MB. |

---

## Documentation & Deep Dives

* [**Production Guide & Architecture Deep Dive (`docs/PRODUCTION.md`)**](docs/PRODUCTION.md): Step-by-step execution lifecycle ("What Happens When"), two-tier cleanup architecture, failure modes matrix, RunPod deployment tips, and OpenTelemetry setup.
* [**Future Roadmap (`docs/TODO.md`)**](docs/TODO.md): Native S3 adapter roadmap, streaming multipart uploads, VAD pre-filtering, and per-item webhook events.

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPLv3)**. See the `LICENSE` file for details.
