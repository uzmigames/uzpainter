"""The supervisor's request path around a worker that is about to exit
(python/uzpainter_supervisor/worker.py; task phase2.1_supervisor-ipc-worker items 2.8, 2.9, 3.3).

Pure Python: the generations are driven through stand-in pipes, so the case needs neither the
worker binary nor a GPU. The worker exits right after a `device_removed` or `timeout` reply
(02 §5); its end and the relaunch through a real worker are covered in test_supervisor_gpu.py.
The same stand-ins check which pending request a project switch is attributed to (decision 243).
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
    generation = _Generation(
        number, f"pipe-{number}", tmp_path, process, handshake, lambda *_: None
    )
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


def _revision(project_uuid: str | None, revision: int | None) -> dict[str, Any]:
    project = None if project_uuid is None else f"C:/p/{project_uuid}.uzp"
    return {
        "event": "revision",
        "project": project,
        "project_uuid": project_uuid,
        "revision": revision,
        "untitled": False,
    }


def test_a_project_switch_names_the_request_the_worker_runs(tmp_path: Path) -> None:
    """Decision 243 (practical-e2e B8): a `revision` event that switches the worker to another
    project reaches `on_project_switch` with the frame of the request the worker's command thread
    runs, the oldest one pending (`worker/cancel` aside, which the worker answers at once). The
    project is recorded first, so the hook sees it. A commit on the same project and a close are
    no switch. A request whose caller stopped waiting stays pending until its reply."""

    async def scenario() -> None:
        config = WorkerConfig("UzPainter.exe", "vulkan", False, None, tmp_path, tmp_path, True)
        supervisor = Supervisor(config)
        switches: list[tuple[dict[str, Any] | None, str | None]] = []
        supervisor.on_project_switch = lambda frame: switches.append(
            (frame, supervisor.project_uuid)
        )
        generation, pipe = _generation(1, tmp_path)
        generation.on_event = supervisor._on_event
        supervisor._current = generation
        supervisor._ready.set()

        create = {"method": "tools/call", "name": "project_create", "arguments": {}}
        opened = {"method": "tools/call", "name": "project_open", "arguments": {}}
        waiting = asyncio.ensure_future(supervisor.request(create))
        await asyncio.sleep(0)
        later = asyncio.ensure_future(supervisor.request(opened))
        cancel = asyncio.ensure_future(supervisor.request({"method": "worker/cancel"}))
        await asyncio.sleep(0)
        assert [frame["method"] for frame in pipe.frames] == [
            "tools/call",
            "tools/call",
            "worker/cancel",
        ]
        ids = [frame["id"] for frame in pipe.frames]
        waiting.cancel()  # the caller stops waiting; the worker still runs the request
        await asyncio.sleep(0)
        generation.on_frame({"id": ids[2], "result": {}})  # the cancel is answered at once
        generation.on_frame(_revision(None, None))  # the create's commit, before it switches
        generation.on_frame(_revision("uuid-1", 1))
        generation.on_frame(_revision("uuid-1", 2))  # a commit on the same project
        generation.on_frame({"id": ids[0], "result": {}})
        generation.on_frame(_revision(None, None))  # a close
        generation.on_frame(_revision("uuid-2", 7))
        generation.on_frame({"id": ids[1], "result": {}})
        await asyncio.gather(later, cancel)
        assert generation.sent == {} and generation.pending == {}
        assert len(switches) == 2, switches
        assert switches[0][0] is create and switches[0][1] == "uuid-1", switches
        assert switches[1][0] is opened and switches[1][1] == "uuid-2", switches

    asyncio.run(scenario())
