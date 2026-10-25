"""Deliver a message to an existing Claude peer through its public CLI tools.

Example (PowerShell): 'Task brief' | python -m tools.claude_peer --to uzpainter-66
Peer names come from `claude agents --json --cwd <repository>`, not session UUIDs.
The helper exits after delivery; ongoing peers reply through the agreed channel.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def delivery_results(output: str) -> list[dict[str, Any]]:
    """Trust actual SendMessage tool results, never an assistant's delivery claim."""
    calls: set[str] = set()
    results: list[dict[str, Any]] = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message", {})
        if not isinstance(message, dict):
            continue
        content = message.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                if block.get("name") == "SendMessage" and isinstance(block.get("id"), str):
                    calls.add(block["id"])
            elif (
                event.get("type") == "user"
                and block.get("type") == "tool_result"
                and block.get("tool_use_id") in calls
            ):
                value = block.get("content")
                parts = [{"text": value}] if isinstance(value, str) else value
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if not isinstance(part, dict) or not isinstance(part.get("text"), str):
                        continue
                    try:
                        result = json.loads(part["text"])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(result, dict):
                        results.append(result)
    return results


def send(peer: str, message: str, cwd: Path, timeout: float) -> list[dict[str, Any]]:
    executable = shutil.which("claude")
    if executable is None:
        raise RuntimeError("Claude CLI is not installed")
    prompt = (
        "Use only SendMessage to deliver the exact message in the JSON payload below to "
        "the named existing peer. Do not summarize, edit files, resume/fork sessions or use "
        "private IPC. Return the actual tool result; never invent delivery.\n"
        + json.dumps({"recipient": peer, "message": message}, ensure_ascii=True)
    )
    command = [
        executable,
        "-p",
        "--model",
        "haiku",
        "--tools",
        "SendMessage",
        "--allowedTools",
        "SendMessage",
        "--permission-mode",
        "dontAsk",
        "--no-session-persistence",
        "--verbose",
        "--output-format",
        "stream-json",
    ]
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Claude peer delivery timed out; delivery is unconfirmed") from error
    if completed.returncode:
        raise RuntimeError(f"Claude CLI exited with status {completed.returncode}")
    return delivery_results(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Existing peer name, not a session UUID")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    message = sys.stdin.read().strip()
    if not message or not 0 < args.timeout <= 600:
        parser.error("provide a nonempty message on stdin and a timeout in (0, 600]")
    try:
        results = send(args.to, message, args.cwd, args.timeout)
    except (OSError, RuntimeError) as error:
        print(json.dumps({"success": False, "error": str(error)}, ensure_ascii=True))
        return 1
    for result in results:
        print(json.dumps(result, ensure_ascii=True))
    if any(result.get("success") is True and result.get("msg_id") for result in results):
        return 0
    print(json.dumps({"success": False, "error": "No confirmed SendMessage delivery"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
