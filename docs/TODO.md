# Tadween Preprocess - Roadmap & Future Plans

This document outlines prioritized future enhancements for `tadween_preprocess`.

---

## 1. Multi-Source & Multi-Sink Storage (ETL Model)
* [ ] **Direct S3 Source & Sink Adapters**: Native S3 SDK (`boto3` / `aioboto3`) support for bucket/key ingestion and direct egress alongside presigned HTTP URLs.
* [ ] **Streaming Multipart POST Uploads**: True streaming multipart generator for POST form-data to further minimize memory footprint for arbitrary large payloads (currently postponed as converted Opus files are small, typically <5 MB).

## 2. Notification & Webhook Enhancements
* [ ] **Per-Item Webhook Notifications**: Optional per-item progress / completion notifications configurable alongside the standard post-batch notification.

## 3. Observability & Operational Tooling
* [ ] **Structured JSON Logging**: Centralized structured JSON logger attaching `trace_id`, `job_id`, and `file_id`.