"""The supervisor's frame codec, handshake check and exit classification
(python/uzpainter_supervisor/ipc.py; task phase2.1_supervisor-ipc-worker item 3.1).

Pure Python: the module uses the standard library only. The worker's C++ side of the same codec
and the fatal mismatch through a real supervisor are covered in test_supervisor_worker.py.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from python.uzpainter_supervisor import ipc

REQUESTED = ipc.Requested(protocol="uzp-ipc/1", gpu_backend="vulkan", python_allowed=False)


def handshake(**fields: Any) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "protocol": "uzp-ipc/1",
        "worker_pid": 4242,
        "build": "0.0.0+uzpainter-Debug",
        "gpu_backend": "vulkan",
        "gpu_status": "unavailable",
        "python": "disabled",
    }
    frame.update(fields)
    return frame


def test_frames_are_canonical_json_lines() -> None:
    data = ipc.encode_frame({"b": "line\nbreak", "a": 1, "é": [True, None]})
    assert data == '{"a":1,"b":"line\\nbreak","é":[true,null]}\n'.encode()
    assert data.count(b"\n") == 1


def test_decoder_joins_split_frames_and_keeps_order() -> None:
    decoder = ipc.FrameDecoder()
    data = ipc.encode_frame({"id": "1"}) + ipc.encode_frame({"id": "2"})
    frames: list[dict[str, Any]] = []
    for i in range(len(data)):  # one byte at a time
        got, errors = decoder.feed(data[i : i + 1])
        assert errors == []
        frames += got
    assert frames == [{"id": "1"}, {"id": "2"}]


def test_decoder_rejects_bad_frames_and_stays_usable() -> None:
    decoder = ipc.FrameDecoder()
    frames, errors = decoder.feed(b'[1,2]\nnot json\n\xff\xfe\n{"id":"ok"}\n')
    assert frames == [{"id": "ok"}]
    assert errors == [
        "frame is not a JSON object",
        errors[1],
        errors[2],
    ]
    assert errors[1].startswith("frame is not JSON") and errors[2].startswith("frame is not JSON")


def test_decoder_skips_an_oversized_frame_up_to_its_newline() -> None:
    decoder = ipc.FrameDecoder()
    big = b"x" * (ipc.MAX_FRAME_BYTES + 1)
    frames, errors = decoder.feed(big[:100])
    assert (frames, errors) == ([], [])
    frames, errors = decoder.feed(big[100:])
    assert frames == [] and errors == [f"frame exceeds {ipc.MAX_FRAME_BYTES} bytes"]
    frames, errors = decoder.feed(b"still the same frame\n" + ipc.encode_frame({"id": "next"}))
    assert frames == [{"id": "next"}] and errors == []


def test_encoder_refuses_an_oversized_frame() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        ipc.encode_frame({"text": "x" * ipc.MAX_FRAME_BYTES})


def test_matching_handshake_is_accepted() -> None:
    got = ipc.check_handshake(handshake(), REQUESTED)
    assert got == ipc.Handshake(4242, "0.0.0+uzpainter-Debug", "vulkan", False, False)
    ready = ipc.check_handshake(
        handshake(gpu_backend="dx12", gpu_status="ready", python="allowed"),
        ipc.Requested("uzp-ipc/1", "dx12", True),
    )
    assert ready.gpu_ready and ready.python_allowed


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("protocol", "uzp-ipc/2", "protocol: requested 'uzp-ipc/1', worker reported 'uzp-ipc/2'"),
        ("gpu_backend", "dx12", "gpu_backend: requested 'vulkan', worker reported 'dx12'"),
        ("python", "allowed", "python: requested 'disabled', worker reported 'allowed'"),
        ("gpu_status", "maybe", "gpu_status: 'maybe' is neither 'ready' nor 'unavailable'"),
        ("worker_pid", True, "worker_pid: True is not a process id"),
        ("build", "", "build: '' is not a build string"),
    ],
)
def test_every_handshake_mismatch_is_fatal(field: str, value: Any, message: str) -> None:
    with pytest.raises(ipc.HandshakeMismatch) as raised:
        ipc.check_handshake(handshake(**{field: value}), REQUESTED)
    assert raised.value.mismatches == [message]


def test_a_missing_handshake_field_is_a_mismatch() -> None:
    frame = handshake()
    del frame["gpu_backend"]
    with pytest.raises(ipc.HandshakeMismatch, match="gpu_backend: requested 'vulkan'"):
        ipc.check_handshake(frame, REQUESTED)


@pytest.mark.parametrize(
    ("code", "cause"),
    [
        (0x40000015, "abort"),
        (0xC0000005, "native_fault"),
        (-1073741819, "native_fault"),  # the same code as a signed int
        (5, "device_fault"),
        (4, "supervisor_gone"),
        (3, "start_failed"),
        (1, "terminated"),
        (77, "terminated"),
    ],
)
def test_exit_codes_name_their_cause(code: int, cause: str) -> None:
    assert ipc.classify_exit(code) == cause


def test_handshake_json_round_trip() -> None:
    frame = handshake()
    (decoded,), errors = ipc.FrameDecoder().feed(ipc.encode_frame(frame))
    assert errors == [] and decoded == json.loads(json.dumps(frame))
