"""R-131 state contract: bind each comparison to its intended texture set."""

from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics.recording_requests import ao_mixed_grid_probe


def test_ao_mixed_request_pins_operand_state_before_export() -> None:
    steps = ao_mixed_grid_probe().sequence.steps
    assert steps[0]["args"]["default_texture_resolution"] == 256
    channels = [s["args"] for s in steps if s["call"] == ps.ADD_CHANNEL]
    assert channels == [{"channel": "AO", "format": "L16"}]
    resources = {s["args"]["input"]: s["step"] for s in steps if s["call"] == ps.IMPORT_RESOURCE}
    mesh_maps = [s["args"] for s in steps if s["call"] == ps.SET_MESH_MAP]
    assert mesh_maps == [{"usage": "AO", "resource_step": resources["grey-a"]}]
    fills = [s for s in steps if s["call"] == ps.INSERT_FILL]
    assert [s["args"]["texture_set"] for s in fills] == ["s0", "s1", "s2", "s3"]
    for fill, (filtering, opacity) in zip(
        fills,
        [("Nearest", 0.5), ("Nearest", 0.75), ("Nearest", 1.0), ("BilinearHQ", 0.5)],
        strict=True,
    ):
        edits = {
            s["call"]: {k: v for k, v in s["args"].items() if k != "node_step"}
            for s in steps
            if s["args"].get("node_step") == fill["step"]
        }
        assert edits == {
            ps.SET_ACTIVE_CHANNELS: {"channels": ["AO"]},
            ps.SET_SOURCE: {"channel": "AO", "resource_step": resources["grey-b"]},
            ps.SET_PROJECTION: {
                "filtering_mode": filtering,
                "uv_wrapping_mode": "RepeatNone",
                "scale_mode": "Factors",
                "scale": [1.0, 1.0],
                "rotation": 0.0,
                "offset": [0.0, 0.0],
            },
            ps.SET_BLENDING_MODE: {"blending_mode": "Normal", "channel": "AO"},
            ps.SET_OPACITY: {"opacity": opacity, "channel": "AO"},
        }
