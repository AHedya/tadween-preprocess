import uuid
from unittest.mock import MagicMock

import httpx

from tadween_preprocess.adapters.runner import run_adapter
from tadween_preprocess.core.models import (
    Envelope,
    HttpLocation,
    ItemArtifacts,
    ItemContext,
    ItemInspection,
    ItemOptions,
    ItemState,
)


def _make_dummy_envelope(payload) -> Envelope:
    file_id = uuid.uuid4()
    return Envelope(
        context=ItemContext(file_id=file_id),
        dist=HttpLocation(url="http://example.com/put", method="PUT"),
        options=ItemOptions(),
        insp=ItemInspection(),
        state=ItemState(),
        artifacts=ItemArtifacts(),
        payload=payload,
    )


async def test_adapter_runner_skips_terminal_failed_items():
    env = _make_dummy_envelope(payload="data")
    env.state.status = "failed"

    mock_func = MagicMock()
    result = await run_adapter("test_adapter", mock_func, env)
    assert result.state.status == "failed"
    mock_func.assert_not_called()


async def test_adapter_runner_retries_transient_errors_until_success():
    env = _make_dummy_envelope(payload="data")

    attempts = 0

    async def flaky_func(envelope):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("Connection timed out")
        return envelope

    result = await run_adapter(
        "test_flaky",
        flaky_func,
        env,
        retries=2,
        retry_delay=0.01,
        retry_exceptions=(httpx.ConnectTimeout,),
    )
    assert result.state.status == "pending"
    assert attempts == 2
