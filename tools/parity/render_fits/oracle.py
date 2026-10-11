"""The admitted Iray references read from the private store (owner's machine only).

For one golden: the two `separate_session` renders and the `k_times_samples` render as 16-bit
codes (float64, RGB), their recording ids and the expected-silhouette regions of
`tools/parity/render_procedure/noise.py`. Nothing read here leaves the process except numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.recorder.iray import K_TIMES_SAMPLES
from tools.parity.render_procedure.noise import (
    FULL_SCALE,
    NoiseError,
    admission_problems,
    private_record,
    reference_output,
    region_masks,
    rgb,
)
from tools.parity.render_procedure.references import MANIFEST_DIR
from tools.parity.store.store import OracleStore, load_oracle

F64 = npt.NDArray[np.float64]
U16 = npt.NDArray[np.uint16]
Mask = npt.NDArray[np.bool_]
SAMPLES, K = 256, 4


@dataclass
class References:
    golden_id: str
    s: tuple[U16, U16]  # 16-bit codes, (H, W, 3)
    k: U16
    recordings: tuple[str, str, str]
    regions: dict[str, Mask]
    manifest: dict[str, Any]


def manifest_path(name: str) -> Path:
    return MANIFEST_DIR / f"{name}.json"


def load(store: OracleStore | None, name: str) -> References:
    manifest = json.loads(manifest_path(name).read_text(encoding="utf-8"))
    record = private_record(store, manifest)
    problems = admission_problems(record, SAMPLES, K)
    if problems:
        raise NoiseError(f"{name}: not admissible: {'; '.join(problems)}")
    by_hash = {r["sha256"]: r for r in manifest["private_records"]}
    separate: list[tuple[str, U16]] = []
    k_image: tuple[str, U16] | None = None
    for recording in sorted(record["recordings"], key=lambda r: str(r["recording_id"])):
        digest = reference_output(recording)["blob"]["sha256"]
        data = load_oracle(store, by_hash[digest]) if digest in by_hash else None
        if data is None:
            raise NoiseError(f"{recording['recording_id']}: render {digest} is not in the store")
        image = np.round(rgb(data) * FULL_SCALE).astype(np.uint16)
        if recording["condition"] == K_TIMES_SAMPLES:
            k_image = (recording["recording_id"], image)
        else:
            separate.append((recording["recording_id"], image))
    if k_image is None or len(separate) < 2:
        raise NoiseError(f"{name}: needs two separate-session renders and one k*S render")
    height, width, _ = k_image[1].shape
    regions = region_masks(manifest, record["key"], (width, height))
    return References(
        manifest["golden_id"],
        (separate[0][1], separate[1][1]),
        k_image[1],
        (separate[0][0], separate[1][0], k_image[0]),
        regions,
        manifest,
    )
