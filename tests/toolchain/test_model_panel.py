from __future__ import annotations

import io
import json
import queue
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
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


@pytest.mark.parametrize("finish", ["stop", "length", None])
def test_done_ends_stream_without_waiting_for_connection_close(finish: str | None) -> None:
    def lines() -> Iterator[bytes]:
        value = {
            "model": "actual",
            "choices": [{"delta": {"content": "review"}, "finish_reason": finish}],
        }
        yield b"data: " + json.dumps(value).encode() + b"\n"
        yield b"data: [DONE]\n"
        raise AssertionError("parser read past the terminal SSE event")

    reply = model_panel.parse_response(lines(), "requested")
    assert reply.status == ("completed" if finish == "stop" else "incomplete")
    assert reply.model == "actual" and reply.content == "review"
    assert reply.finish_reason == finish


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


@pytest.mark.parametrize(
    "scenario", ["before_headers", "headers", "heartbeats", "finish_without_done"]
)
def test_timeout_preserves_only_safe_progress(
    monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    reached = threading.Event()
    release = threading.Event()
    ended = threading.Event()
    calls = []
    lines = (
        [b": private heartbeat\n", b": secret-key\n"]
        if scenario == "heartbeats"
        else [
            b'data: {"model":"secret-key","choices":[{"delta":{"content":"private prompt"},'
            b'"finish_reason":"stop"}]}\n'
        ]
        if scenario == "finish_without_done"
        else []
    )

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: Any) -> None:
            ended.set()

        def __iter__(self) -> Iterator[bytes]:
            yield from lines
            reached.set()
            release.wait(1)

    def upstream(request: Any, timeout: float) -> Response:
        calls.append(request)
        if scenario == "before_headers":
            reached.set()
            release.wait(1)
            ended.set()
            raise OSError("secret-key private transport error")
        return Response()

    class DeadlineQueue(queue.Queue[model_panel.Reply]):
        def get(self, block: bool = True, timeout: float | None = None) -> model_panel.Reply:
            # Synchronize an authored deadline to the requested stream state, without sleeping.
            assert reached.wait(1)
            raise queue.Empty

    monkeypatch.setattr(urllib.request, "urlopen", upstream)
    monkeypatch.setattr(queue, "Queue", DeadlineQueue)
    try:
        reply = model_panel.bounded_request(
            "http://private-host/v1", "secret-key", "requested", "private prompt", 180
        )
        assert reply.status == "deadline_exceeded"
        assert reply.content == "" and reply.model is None and reply.finish_reason is None
        progress = reply.progress
        assert progress is not None
        assert set(progress) == {
            "phase",
            "http_status",
            "headers_s",
            "first_data_s",
            "last_data_s",
            "bytes_read",
            "data_events",
            "last_finish_reason",
            "elapsed_s",
        }
        assert progress["phase"] == (
            "before_request" if scenario == "before_headers" else "stream" if lines else "headers"
        )
        assert progress["http_status"] == (None if scenario == "before_headers" else 200)
        assert (progress["headers_s"] is None) is (scenario == "before_headers")
        assert (progress["first_data_s"] is None) is (not lines)
        assert (progress["last_data_s"] is None) is (not lines)
        assert progress["bytes_read"] == sum(map(len, lines))
        assert progress["data_events"] == int(scenario == "finish_without_done")
        assert progress["last_finish_reason"] == (
            "stop" if scenario == "finish_without_done" else None
        )
        encoded = json.dumps(progress)
        assert all(value not in encoded for value in ("secret-key", "private", "http://"))
        preserved = dict(progress)
    finally:
        release.set()
        assert ended.wait(1)
    assert progress == preserved
    assert len(calls) == 1


def test_progress_unknown_finish_reason_and_header_are_not_copied() -> None:
    progress = model_panel.Progress()
    progress.headers("private status secret-key")
    model_panel.parse_response(
        [
            b'data: {"choices":[{"delta":{},"finish_reason":"private secret-key"}]}\n',
            b"data: [DONE]\n",
        ],
        "requested",
        progress,
    )
    snapshot = progress.snapshot()
    assert snapshot["http_status"] is None
    assert snapshot["last_finish_reason"] == "other"
    assert snapshot["data_events"] == 2
    assert "private" not in json.dumps(snapshot) and "secret-key" not in json.dumps(snapshot)
    snapshot["phase"] = "caller mutation"
    assert progress.snapshot()["phase"] == "stream"


@pytest.mark.parametrize("failure", [False, True])
def test_request_progress_preserves_http_metadata_without_payloads(
    monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    class Response(io.BytesIO):
        status = 200

    def upstream(request: Any, timeout: float) -> Response:
        if failure:
            raise urllib.error.HTTPError(request.full_url, 429, "private secret-key", {}, None)  # type: ignore[arg-type]
        return Response(
            b'data: {"choices":[{"delta":{"content":"secret-key"},"finish_reason":"stop"}]}\n'
            b"data: [DONE]\n"
        )

    monkeypatch.setattr(urllib.request, "urlopen", upstream)
    reply = model_panel.request(
        "http://localhost/v1", "secret-key", "requested", "private", 1, model_panel.Progress()
    )
    assert reply.status == ("http_error" if failure else "completed")
    assert reply.progress is not None
    assert reply.progress["http_status"] == (429 if failure else 200)
    assert "secret-key" not in repr(reply)
    assert "private" not in json.dumps(reply.progress)
