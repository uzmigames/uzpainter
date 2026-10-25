"""Peer relay cannot turn model prose or unrelated tool output into delivery proof."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools import claude_peer


def events(tool: str = "SendMessage", success: bool = True) -> str:
    return "\n".join(
        json.dumps(row)
        for row in [
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": tool, "id": "call-1"}]},
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {"success": success, "msg_id": "peer-message"}
                                    ),
                                }
                            ],
                        }
                    ]
                },
            },
        ]
    )


def test_model_prose_and_other_tools_do_not_prove_delivery() -> None:
    prose = json.dumps({"type": "result", "result": "Message delivered successfully"})
    assert claude_peer.delivery_results(prose + "\n" + events("Read")) == []


def test_actual_delivery_and_refusal_are_preserved() -> None:
    assert claude_peer.delivery_results(events()) == [{"success": True, "msg_id": "peer-message"}]
    assert claude_peer.delivery_results(events(success=False)) == [
        {"success": False, "msg_id": "peer-message"}
    ]


def test_noise_and_invalid_events_are_ignored() -> None:
    noise = 'warning\nnull\n[]\n{"message": null}\n{"message": {"content": 3}}\n'
    assert claude_peer.delivery_results(noise + events()) == [
        {"success": True, "msg_id": "peer-message"}
    ]


def test_send_preserves_message_without_shell_or_permission_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "claude.exe")
    message = "Coordena\u00e7\u00e3o: `literal` $HOME $(literal)\nSecond line"

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[0] == "claude.exe"
        assert command[command.index("--tools") + 1] == "SendMessage"
        assert command[command.index("--permission-mode") + 1] == "dontAsk"
        assert "--no-session-persistence" in command
        assert not kwargs.get("shell", False)
        assert kwargs["encoding"] == "utf-8" and kwargs["timeout"] == 90
        payload = json.loads(kwargs["input"].split("\n", 1)[1])
        assert payload == {"recipient": "uzpainter-66", "message": message}
        return subprocess.CompletedProcess(command, 0, stdout=events(), stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert claude_peer.send("uzpainter-66", message, Path.cwd(), 90)[0]["success"] is True


def test_timeout_is_unconfirmed_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "claude.exe")
    calls = 0

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="delivery is unconfirmed"):
        claude_peer.send("uzpainter-66", "Task", Path.cwd(), 1)
    assert calls == 1
