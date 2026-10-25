from __future__ import annotations

import io
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from tools import model_panel


def test_json_and_stream_report_actual_model_and_completion() -> None:
    value = {
        "model": "kimi-k3",
        "choices": [{"message": {"content": "ação"}, "finish_reason": "stop"}],
    }
    plain = model_panel.parse_response([json.dumps(value).encode()], "kimi/kimi-k3")
    lines = [
        b": heartbeat\n",
        b'data: {"model":"kimi-k3","choices":[]}\n',
        b'data: {"choices":[{"delta":{"content":"a\\u00e7\\u00e3o"},"finish_reason":null}]}\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
        b"data: [DONE]\n",
    ]
    streamed = model_panel.parse_response(lines, "kimi/kimi-k3")
    assert plain == streamed
    assert streamed.status == "completed" and streamed.model == "kimi-k3"
    assert streamed.content == "ação"


def test_header_and_done_are_not_completion() -> None:
    reply = model_panel.parse_response(
        [b'data: {"model":"grok-4.5","choices":[]}\n', b"data: [DONE]\n"], "xai/grok-4.5"
    )
    assert reply.status == "incomplete" and reply.model == "grok-4.5"


def test_deadline_is_total_not_reset_by_worker_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def stalled(*args: Any) -> model_panel.Reply:
        release.wait(2)
        return model_panel.Reply("model", "completed")

    monkeypatch.setattr(model_panel, "request", stalled)
    start = time.monotonic()
    try:
        reply = model_panel.bounded_request("base", "secret", "model", "prompt", 0.03)
        assert reply.status == "deadline_exceeded"
        assert time.monotonic() - start < 1
    finally:
        release.set()


@pytest.mark.parametrize("failure", [False, True])
def test_request_does_not_leak_credentials_or_retry(
    monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    calls = []

    def upstream(request: Any, timeout: float) -> io.BytesIO:
        calls.append(request)
        if failure:
            raise urllib.error.HTTPError(request.full_url, 503, "secret-value", {}, None)  # type: ignore[arg-type]
        return io.BytesIO(
            json.dumps(
                {
                    "model": "actual",
                    "choices": [{"message": {"content": "secret-value"}, "finish_reason": "stop"}],
                }
            ).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", upstream)
    reply = model_panel.request("http://localhost/v1", "secret-value", "model", "prompt", 1)
    assert "secret-value" not in repr(reply)
    assert len(calls) == 1
    assert calls[0].full_url == "http://localhost/v1/chat/completions"
    assert reply.status == ("http_error" if failure else "completed")
    if failure:
        assert reply.http_status == 503
