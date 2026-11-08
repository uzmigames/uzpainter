"""The sRGB8 threshold-tie probe's authored request and count-only verdict (decision 406), without
Painter or oracle data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from tools.parity.fit.decode import decode_exr
from tools.parity.recorder.job import EXPORT
from tools.parity.recorder.probes import manifest_symbol_problems, probe_job_from_manifest
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.tier0_semantics import ocio16_bitmap_control as control
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics import srgb8_threshold_ties as ties


def test_request_is_the_committed_ocio_probe() -> None:
    data = ties.request()
    assert validation_errors(data, Schema.GOLDEN_PUBLIC) == []
    assert manifest_symbol_problems(data) == []
    assert data["private_records"] == data["expectations"] == []
    assert data["golden_id"] == ties.GOLDEN_ID
    assert json.loads(ties.request_path().read_text(encoding="utf-8")) == data
    assert [s for s in data["applied_settings"] if s["name"] == "OCIO"] == [rr.OCIO_SETTING]
    for item in data["inputs"]:
        assert hashlib.sha256((REPO_ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    job = probe_job_from_manifest(data)
    setters = [p.args for p in job.state_steps if p.call == control.SET_SPACE]
    assert setters == [
        {"node_step": 4, "channel": "BaseColor", "color_space": "GenericColorSpace.Raw"}
    ]
    assert [(p.call, p.args["typed"]) for p in job.probe_steps] == [(control.GET_SPACE, True)]
    assert len(job.exports) == 1
    config = job.exports[0].config(Path("unused"), ["uzp_plane"])
    assert config["exportParameters"][0]["parameters"] == {
        "fileFormat": "png",
        "bitDepth": "8",
        "dithering": False,
        "paddingAlgorithm": "passthrough",
    }
    steps = data["instruction_sequence"]["steps"]
    assert [s["step"] for s in steps if s["call"] == EXPORT] == [ties._export_step()]


def test_field_holds_every_threshold_and_its_neighbours() -> None:
    t = ties.thresholds()
    assert len(t) == 256 and t[0] == 0.0 and np.all(np.diff(t) > 0)
    values = ties.field_values()
    decoded = np.asarray(decode_exr(ties.field()).values)
    assert np.array_equal(decoded.astype(np.float32), values)
    half = ties.SIZE // 2
    top, bottom = values[0], values[half]
    assert np.all(values[:half] == top) and np.all(values[half:] == bottom)
    assert np.array_equal(top[:, 0], t) and np.array_equal(bottom[:, 1], t)
    rest = t[1:]
    # the binary16 neighbours are binary16 values strictly around t, the float32 ones adjacent
    for column, side in ((1, -1), (2, 1)):
        neighbour = top[1:, column]
        assert np.array_equal(neighbour.astype(np.float16).astype(np.float32), neighbour)
        assert np.all(np.sign(neighbour - rest) == side)
    assert np.array_equal(bottom[1:, 0], np.nextafter(rest, np.float32(-1.0)))
    assert np.array_equal(bottom[1:, 2], np.nextafter(rest, np.float32(2.0)))
    # no neighbour reaches the next or previous threshold
    assert np.all(top[1:, 1] > t[:-1]) and np.all(top[1:-1, 2] < t[2:])


def test_verdict_separates_the_two_store_rules() -> None:
    predicted = ties.predictions()
    k = np.arange(256)
    assert np.array_equal(predicted["at_or_above"][0, :, 0], k)
    assert np.array_equal(predicted["strict"][0, 1:, 0], k[1:] - 1)
    strict = ties.verdict(predicted["strict"])
    native = ties.verdict(predicted["at_or_above"])
    assert strict["strict"]["all_misses"] == 0 and native["at_or_above"]["all_misses"] == 0
    exact = ("threshold_binary16", "threshold_float32")
    assert sum(strict["at_or_above"][kind]["misses"] for kind in exact) == 256 * 255
    assert strict["distinct_thresholds_hit"] == 255
    assert strict["strict"]["threshold_binary16"]["samples"] == 256 * 188
    # a neighbour stored on the other side counts as a miss of its own kind only
    codes = predicted["strict"].copy()
    codes[0, 5, 1] += 1
    moved = ties.verdict(codes)["strict"]
    assert moved["binary16_below"]["misses"] == 1 and moved["all_misses"] == 1
