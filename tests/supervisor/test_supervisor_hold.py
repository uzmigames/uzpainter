"""The supervisor's request path around a worker that is about to exit
(python/uzpainter_supervisor/worker.py; task phase2.1_supervisor-ipc-worker items 2.8, 2.9, 3.3).

Pure Python: the generations are driven through stand-in pipes, so the case needs neither the
worker binary nor a GPU. The worker exits right after a `device_removed` or `timeout` reply
(02 §5); its end and the relaunch through a real worker are covered in test_supervisor_gpu.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from python.uzpainter_supervisor import ipc
from python.uzpainter_supervisor.worker import Supervisor, WorkerConfig, _Generation


class _Pipe(asyncio.WriteTransport):
    """The supervisor's end of one worker pipe: records the frames written to it."""

    def __init__(self) -> None:
        super().__init__()
        self.frames: list[dict[str, Any]] = []

    def write(self, data: bytes | bytearray | memoryview) -> None:
        frames, errors = ipc.FrameDecoder().feed(bytes(data))
        assert not errors and len(frames) == 1, (frames, errors)
        self.frames.append(frames[0])


def _generation(number: int, tmp_path: Path) -> tuple[_Generation, _Pipe]:
    loop = asyncio.get_running_loop()
    handshake: asyncio.Future[dict[str, Any]] = loop.create_future()
    handshake.set_result({})
    process = cast(asyncio.subprocess.Process, SimpleNamespace(returncode=None, pid=number))
    generation = _Generation(number, f"pipe-{number}", tmp_path, process, handshake, lambda _: None)
    pipe = _Pipe()
    generation.transport = pipe
    return generation, pipe


@pytest.mark.parametrize("code", ["device_removed", "timeout"])
def test_a_call_after_a_device_fault_reply_waits_for_the_relaunch(
    tmp_path: Path, code: str
) -> None:
    """A call made after the worker replied `device_removed` or `timeout`, while that worker is
    still running and its pipe still open, is not sent to it: it is held until the next generation
    replaces it and then forwarded there once, so it is answered rather than `interrupted`."""

    async def scenario() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        config = WorkerConfig("UzPainter.exe", "dx12", False, None, tmp_path, tmp_path, True)
        supervisor = Supervisor(config)
        dying, dying_pipe = _generation(1, tmp_path)
        supervisor._current = dying
        supervisor._ready.set()

        evaluate = asyncio.ensure_future(supervisor.request({"method": "evaluate_channel"}))
        await asyncio.sleep(0)
        assert len(dying_pipe.frames) == 1, dying_pipe.frames
        dying.on_frame({"id": dying_pipe.frames[0]["id"], "error": {"code": code}})
        assert (await evaluate)["error"]["code"] == code

        inspect = asyncio.ensure_future(supervisor.request({"method": "project_inspect"}))
        for _ in range(10):
            await asyncio.sleep(0)
        assert not inspect.done() and len(dying_pipe.frames) == 1, dying_pipe.frames

        fresh, fresh_pipe = _generation(2, tmp_path)
        supervisor._current = fresh
        dying.replaced.set()
        for _ in range(10):
            await asyncio.sleep(0)
        assert len(fresh_pipe.frames) == 1, fresh_pipe.frames
        fresh.on_frame({"id": fresh_pipe.frames[0]["id"], "result": {"revision": 1}})
        return await inspect, dying_pipe.frames, fresh_pipe.frames

    reply, dying_frames, fresh_frames = asyncio.run(scenario())
    assert reply == {"id": fresh_frames[0]["id"], "result": {"revision": 1}}, reply
    assert [frame["method"] for frame in dying_frames] == ["evaluate_channel"], dying_frames
    assert [frame["method"] for frame in fresh_frames] == ["project_inspect"], fresh_frames
