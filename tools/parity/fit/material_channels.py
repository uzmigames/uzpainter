"""Decision-413 P413-A diagnostic: how Painter composes the probe's material outputs into channels.

`python -m tools.parity.fit.material_channels` reads the admitted `source-substance-channels-*`
goldens (P413-A, private store) and the decision-413 snapshot capture of the same states (the
exports kept under `%LOCALAPPDATA%/UzPainter/snapshot-recordings/`, found by their request), and
prints, per golden and recording, whether each channel export equals the candidate model:

- Height of the material fill: `binary16_toward_zero(float32(2 x - 1))`, `x` the L32F view of the
  output its `output_mapping` gives Height (the existing Height rule of float operands);
- BaseColor and Normal of the material fill: untouched (Height is its only active channel);
- the masked configurations and the split BaseColor fill are reported as values in binary16
  ulps, since one constant per recording cannot separate candidate models.

Only derived numbers are printed; nothing is written. Owner machine only (private store and
snapshot exports).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode_exr
from tools.parity.store.store import OracleStore, locate
from tools.parity.tier0_semantics.source_substance_channels import CHANNELS_PREFIX, STATES
from tools.parity.tier0_semantics.source_substance_presets import INPUT_COLOR, RESOURCE_URL

F64 = npt.NDArray[np.float64]
SNAPSHOTS = Path(os.environ.get("LOCALAPPDATA", "")) / "UzPainter" / "snapshot-recordings"
# Decision 413: output0 is `normal`, output1 `height` (the order of `image_outputs`).
OUTPUT_DIRS = {"normal": "output0", "height": "output1"}
PRESET, INPUT = "Inflated", "curvature"


def capture_request(state: str) -> dict[str, Any]:
    """The decision-413 capture request of the source state a P413-A golden reaches."""
    edits = [call for call, _ in STATES[state]]
    inputs: dict[str, Any] = {}
    for call, args in STATES[state]:
        if call == "set_source":
            inputs = {INPUT: {"color": INPUT_COLOR} if "color" in args else {"bitmap": "grey-a"}}
        elif call == "reset_source":
            inputs = {}
        elif call == "remove_source":
            inputs = {INPUT: {"remove": True}}
    return {"preset": PRESET if "apply_preset" in edits else None, "inputs": inputs}


def capture_dir(request: dict[str, Any]) -> Path:
    # The newest complete capture (an interrupted attempt leaves a request without exports).
    for directory in sorted(SNAPSHOTS.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True):
        path = directory / "request.json"
        if not path.is_file() or not (directory / "capture.json").is_file():
            continue
        body = json.loads(path.read_text(encoding="utf-8"))
        inputs = {
            name: {"bitmap": "grey-a"}
            if "bitmap" in value and Path(value["bitmap"]).name == "grey-a.png"
            else value
            for name, value in body.get("inputs", {}).items()
        }
        if (
            body.get("resource") == RESOURCE_URL
            and body.get("parameters") == {}
            and body.get("preset") == request["preset"]
            and inputs == request["inputs"]
        ):
            return directory
    raise FileNotFoundError(f"no decision-413 capture of {request}")


def snapshot(state: str, output: str, view: str) -> F64:
    path = capture_dir(capture_request(state)) / f"{OUTPUT_DIRS[output]}-export1" / f"{view}.exr"
    return np.asarray(decode_exr(path.read_bytes()).values, dtype=np.float64)


def binary16_toward_zero(values: npt.ArrayLike) -> F64:
    single = np.asarray(values, dtype=np.float32)
    half = single.astype(np.float16)
    over = np.abs(half.astype(np.float32)) > np.abs(single)
    half = np.where(over, np.nextafter(half, np.float16(0)), half)
    return np.asarray(half.astype(np.float64))


def height_model(x: F64) -> F64:
    single = x.astype(np.float32)
    return binary16_toward_zero(np.float32(2) * single - np.float32(1))


def exports(store: OracleStore, name: str) -> dict[tuple[str, str], F64]:
    manifest_path = manifest_root(current_envelope()) / "tier0/api-probes" / f"{name}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    (ref,) = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
    record = json.loads(store.blob_path(ref["sha256"]).read_text(encoding="utf-8"))
    result: dict[tuple[str, str], F64] = {}
    for recording in record["recordings"]:
        for output in recording["outputs"]:
            if output["kind"] == "exported_map":
                data = store.blob_path(output["blob"]["sha256"]).read_bytes()
                values = np.asarray(decode_exr(data).values, dtype=np.float64)
                result[(recording["recording_id"], output["map"])] = values
    return result


def mapped_height_output(state: str) -> str:
    swaps = sum(1 for _, args in STATES[state] if args.get("roundtrip") == "swap")
    return "normal" if swaps % 2 else "height"


def masked(state: str) -> bool:
    return any(call == "mask_output" for call, _ in STATES[state])


def ulps(values: F64) -> list[float]:
    """Distinct values in binary16 ulps of the binade [0.125, 0.25) (2^-13)."""
    return sorted({float(v) * 8192 for v in np.unique(values)})


def report(store: OracleStore) -> Iterator[str]:
    split = exports(store, CHANNELS_PREFIX + "split-only")
    material = exports(store, CHANNELS_PREFIX + "material-only")
    for key in ("basecolor", "normal"):
        same = all(np.array_equal(material[(r, key)], material[("r1", key)]) for r in ("r1", "r2"))
        yield f"material-only {key}: constant {np.unique(material[('r1', key)]).tolist()} {same}"
    defaults = snapshot("defaults", "height", "user0")[..., 0]
    for recording in ("r1", "r2"):
        exact = np.array_equal(height_model(defaults), material[(recording, "height")][..., 0])
        yield f"material-only height {recording}: {'exact' if exact else 'differs'}"
    view = snapshot("defaults", "normal", "user1")
    yield (
        f"split-only basecolor: view {np.unique(view.reshape(-1, 3), axis=0).tolist()} -> "
        f"{np.unique(split[('r1', 'basecolor')].reshape(-1, 3), axis=0).tolist()} "
        f"(r1 == r2: {np.array_equal(split[('r1', 'basecolor')], split[('r2', 'basecolor')])})"
    )
    for state in STATES:
        maps = exports(store, CHANNELS_PREFIX + state)
        x = snapshot(state, mapped_height_output(state), "user0")[..., 0]
        for recording in ("r1", "r2"):
            height = maps[(recording, "height")][..., 0]
            base = all(
                np.array_equal(maps[(recording, key)], split[("r1", key)])
                for key in ("basecolor", "normal")
            )
            if masked(state):
                yield f"{state} {recording}: masked height {ulps(height)} ulps; others {base}"
                continue
            exact = np.array_equal(height_model(x), height)
            yield f"{state} {recording}: height {'exact' if exact else 'differs'}; others {base}"


def main() -> int:
    store = locate()
    if store is None:
        print("oracle_unavailable: no private store on this machine")
        return 2
    for line in report(store):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
