"""One 9router review: UTF-8 stdin, JSON stdout, no retries or prompt/credential logs.

python -m tools.model_panel --model kimi/kimi-k3 --deadline 180 < dossier.txt
Reads NINEROUTER_BASE_URL and NINEROUTER_API_KEY from the repository .env.
The deadline bounds the whole call, including streaming heartbeats.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Reply:
    requested_model: str
    status: str = "incomplete"
    model: str | None = None
    content: str = ""
    finish_reason: str | None = None
    http_status: int | None = None
    progress: dict[str, Any] | None = None


class Progress:
    """Thread-safe metadata only; never retains request, response text, URLs or headers.

    Body counters/times describe lines delivered to the parser, not socket-level packets.
    SSE data events include [DONE]; comments/heartbeats count as bytes, not data events.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._state: dict[str, Any] = {
            "phase": "before_request",
            "http_status": None,
            "headers_s": None,
            "first_data_s": None,
            "last_data_s": None,
            "bytes_read": 0,
            "data_events": 0,
            "last_finish_reason": None,
        }

    def headers(self, status: Any) -> None:
        with self._lock:
            self._state["phase"] = "headers"
            self._state["headers_s"] = time.monotonic() - self._started
            self._state["http_status"] = (
                status if type(status) is int and 100 <= status <= 599 else None
            )

    def body(self, size: int, data_event: bool) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._started
            self._state["phase"] = "stream"
            if self._state["first_data_s"] is None:
                self._state["first_data_s"] = elapsed
            self._state["last_data_s"] = elapsed
            self._state["bytes_read"] += size
            self._state["data_events"] += int(data_event)

    def finish(self, reason: str) -> None:
        with self._lock:
            self._state["last_finish_reason"] = (
                reason
                if reason in {"stop", "length", "content_filter", "tool_calls", "function_call"}
                else "other"
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state, "elapsed_s": time.monotonic() - self._started}


def parse_response(
    lines: Iterable[bytes], requested_model: str, progress: Progress | None = None
) -> Reply:
    """Parse an OpenAI JSON response or SSE stream; a header alone is not completion."""
    reply = Reply(requested_model)
    plain: list[str] = []
    streamed = False

    def accept(value: Any, streaming: bool) -> None:
        if not isinstance(value, dict):
            raise ValueError("response is not an object")
        if "error" in value:
            reply.status = "provider_error"
            return
        model = value.get("model")
        if isinstance(model, str):
            if reply.model is not None and model != reply.model:
                raise ValueError("response changed model")
            reply.model = model
        choices = value.get("choices", [])
        if not choices:
            return
        choice = choices[0]
        payload = choice.get("delta" if streaming else "message", {})
        content = payload.get("content")
        if isinstance(content, str):
            reply.content += content
        finish = choice.get("finish_reason")
        if isinstance(finish, str):
            reply.finish_reason = finish
            if progress is not None:
                progress.finish(finish)

    for raw in lines:
        if progress is not None:
            progress.body(len(raw), raw.strip().startswith(b"data:"))
        line = raw.decode("utf-8").strip()
        if line.startswith("data:"):
            streamed = True
            data = line[5:].strip()
            if data == "[DONE]":
                break
            accept(json.loads(data), True)
        elif not streamed and line and not line.startswith((":", "event:", "id:")):
            plain.append(line)
    if not streamed:
        accept(json.loads("\n".join(plain)), False)
    if reply.status != "provider_error" and reply.finish_reason == "stop" and reply.content:
        reply.status = "completed"
    return reply


def request(
    base: str,
    key: str,
    model: str,
    prompt: str,
    deadline: float,
    progress: Progress | None = None,
) -> Reply:
    """Perform one HTTP request; never expose provider errors or request credentials."""
    url = base.rstrip("/")
    url += "/chat/completions" if url.endswith("/v1") else "/v1/chat/completions"
    body = json.dumps(
        {"model": model, "stream": True, "messages": [{"role": "user", "content": prompt}]}
    ).encode("utf-8")
    outgoing = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(outgoing, timeout=deadline) as response:
            if progress is not None:
                progress.headers(getattr(response, "status", None))
            reply = parse_response(response, model, progress)
    except urllib.error.HTTPError as error:
        if progress is not None:
            progress.headers(error.code)
        reply = Reply(model, "http_error", http_status=error.code)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        reply = Reply(model, "transport_or_response_error")
    # An upstream error or completion can echo a header; never relay a credential.
    reply.content = reply.content.replace(key, "[REDACTED]") if key else reply.content
    if reply.model and key:
        reply.model = reply.model.replace(key, "[REDACTED]")
    if progress is not None:
        reply.progress = progress.snapshot()
    return reply


def bounded_request(base: str, key: str, model: str, prompt: str, deadline: float) -> Reply:
    """Bound wall time independently of socket activity. CLI exit ends the daemon worker."""
    if not math.isfinite(deadline) or deadline <= 0:
        raise ValueError("deadline must be positive")
    replies: queue.Queue[Reply] = queue.Queue(maxsize=1)
    progress = Progress()

    def work() -> None:
        replies.put(request(base, key, model, prompt, deadline, progress))

    threading.Thread(target=work, daemon=True).start()
    try:
        return replies.get(timeout=deadline)
    except queue.Empty:
        return Reply(model, "deadline_exceeded", progress=progress.snapshot())


def configuration(path: Path) -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    base, key = values["NINEROUTER_BASE_URL"], values["NINEROUTER_API_KEY"]
    if not base.startswith(("http://", "https://")) or not key:
        raise ValueError("invalid configuration")
    return base, key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--deadline", type=float, default=180)
    args = parser.parse_args(argv)
    if not math.isfinite(args.deadline) or args.deadline <= 0 or not args.model.strip():
        parser.error("model must be nonempty and deadline positive")
    try:
        base, key = configuration(Path(__file__).resolve().parents[1] / ".env")
        prompt = sys.stdin.read()
        if not prompt.strip():
            raise ValueError("empty prompt")
        reply = bounded_request(base, key, args.model, prompt, args.deadline)
    except (OSError, KeyError, ValueError):
        reply = Reply(args.model, "configuration_or_input_error")
    sys.stdout.write(json.dumps(asdict(reply), ensure_ascii=False) + "\n")
    return 0 if reply.status == "completed" else 1


if __name__ == "__main__":
    if isinstance(sys.stdin, io.TextIOWrapper):
        sys.stdin.reconfigure(encoding="utf-8")
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
