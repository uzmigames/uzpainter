"""Certification batches of the filter goldens (decisions 222 and 303, `tools.parity.proc_cert`).

`python -m tools.parity.proc_filters.batch {sharpen,levels}` writes the batch under
`parity/manifests/phase3/proc-cert/filter__<id>@<version>/` from the admitted goldens of
`goldens.py`: `batch.json` (the asset, its certified domain, the §6 matrix and both case lists
pinned by SHA-256), `calibration/cases.json` and `held-out/cases.json`. Nothing here fits or
reads a case to change a candidate: the oracles are only re-hashed, masked and stored.

Each case is one User channel of one golden:

- **Inputs** are the r1 exports of the same recording, as Painter exported them (OpenEXR 32f, the
  store's blobs): `content`, the User0 channel (the layer content the filter reads, on every
  texel: a filter reads neighbours across island borders), and the World Space Normals map,
  baked with no dilation, which marks Painter's own UV coverage (decision 423 §1). The compared
  texels are the covered ones whose 3 x 3 neighbourhood is covered (`covered_texels`).
- **Oracle**: the r1 export of the case's User channel, with every texel outside that coverage
  set to 0, stored as raw little-endian float32 (rows top first). The batch refuses a golden
  whose r1 and r2 differ on a compared texel, or whose two recordings exported different
  content or coverage. Every oracle is masked the same way, whatever its values. A candidate
  reproduces the mask from its World Space Normals input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.proc_cert.batch import BATCH_SCHEMA, CASES_SCHEMA
from tools.parity.proc_filters import goldens as gold
from tools.parity.proc_filters.requests import FAMILY, Golden
from tools.parity.proc_generators.batch import blob, exr, put, records, spec
from tools.parity.proc_generators.coverage import covered_texels
from tools.parity.proc_generators.requests import MESHES
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

BATCHES = REPO_ROOT / "parity" / "manifests" / "phase3" / "proc-cert"
CONTENT = "content"
COVERAGE = "WorldSpaceNormal"
CORPUS_DATE = "2026-11-10"
GEOMETRY = {"mesh_classes": ["sphere", "bevelled-cube", "garment"], "uv_tiles": 1}


class BatchBuildError(Exception):
    """An admitted golden that cannot become certification cases."""


@dataclass(frozen=True)
class Asset:
    asset: str  # proc_cert asset id, <family>/<id>
    version: int
    domain: Mapping[str, Any]
    parameter_sets: tuple[tuple[str, str, Mapping[str, Any]], ...]  # matrix (id, role, params)
    held_out_sets: tuple[tuple[str, str, Mapping[str, Any]], ...]
    seed: int


def _domain(parameters: Mapping[str, Any], constraints: list[Any]) -> dict[str, Any]:
    rasters = {"resolutions": list(gold.RESOLUTIONS), "formats": ["f32"]}
    inputs = {
        CONTENT: {**rasters, "colour_spaces": ["linear"], "channels": [1]},
        COVERAGE: {**rasters, "colour_spaces": ["Raw"], "channels": [3]},
    }
    return {
        "parameters": dict(parameters),
        "constraints": constraints,
        "seeds": {"policy": "listed", "seeds": [0]},
        "geometry": {**GEOMETRY, "inputs": inputs},
        "output": {**rasters, "colour_spaces": ["linear"], "channels": [1]},
    }


def sharpen_asset() -> Asset:
    domain = _domain({"intensity": {"range": [0, 4]}}, [])
    sets = tuple((i, role, {"intensity": v}) for i, role, v in gold.SHARPEN_SETS)
    held = tuple((i, role, {"intensity": v}) for i, role, v in gold.SHARPEN_HELD_OUT)
    return Asset("filter/sharpen", 2, domain, sets, held, 0)


def levels_asset() -> Asset:
    parameters = {
        "input_min": {"range": [0, 1]},
        "input_max": {"range": [0, 1]},
        "gamma": {"range": [0.125, 8]},
        "output_min": {"range": [0, 1]},
        "output_max": {"range": [0, 1]},
        "clamp": {"set": [0, 1]},
    }
    constraints = [{"coefficients": {"input_min": 1, "input_max": -1}, "max": -0.00390625}]
    domain = _domain(parameters, constraints)
    return Asset("filter/levels", 2, domain, gold.LEVELS_SETS, gold.LEVELS_HELD_OUT, 0)


ASSETS = {
    "sharpen": (sharpen_asset, gold.sharpen_goldens),
    "levels": (levels_asset, gold.levels_goldens),
}


def texture_set(found: Mapping[str, Mapping[str, Any]]) -> str:
    names = {
        rid[len("r1-") : -len("-user0")]
        for rid in found
        if rid.startswith("r1-") and rid.endswith("-user0")
    }
    if len(names) != 1:
        raise BatchBuildError(f"one texture set expected, found {sorted(names)}")
    return names.pop()


def golden_cases(
    golden: Golden, asset: Asset, store: OracleStore, root: Path = REPO_ROOT
) -> list[dict[str, Any]]:
    path = manifest_root(current_envelope(root), root) / FAMILY / f"{golden.name}.json"
    found = records(json.loads(path.read_text(encoding="utf-8")))
    ts = texture_set(found)
    inputs = {CONTENT: found[f"r1-{ts}-user0"], COVERAGE: found[f"r1-{ts}-world_space_normals"]}
    covered = covered_texels(exr(store, inputs[COVERAGE]))
    content_r2 = exr(store, found[f"r2-{ts}-user0"])[..., 0]
    if not np.array_equal(exr(store, inputs[CONTENT])[..., 0][covered], content_r2[covered]):
        raise BatchBuildError(f"{golden.name}: the two recordings hold different content")
    if found[f"r2-{ts}-world_space_normals"]["sha256"] != inputs[COVERAGE]["sha256"]:
        raise BatchBuildError(f"{golden.name}: the two recordings baked the coverage differently")
    sets = {i: params for i, _, params in (*asset.parameter_sets, *asset.held_out_sets)}
    mesh = MESHES[golden.mesh]
    channels = {CONTENT: 1, COVERAGE: 3}
    spaces = {CONTENT: "linear", COVERAGE: "Raw"}
    cases = []
    for k, case in enumerate(golden.cases, start=1):
        r1 = exr(store, found[f"r1-{ts}-user{k}"])[..., 0]
        r2 = exr(store, found[f"r2-{ts}-user{k}"])[..., 0]
        if not np.array_equal(r1[covered], r2[covered]):
            raise BatchBuildError(f"{golden.name} user{k}: r1 and r2 differ on a covered texel")
        masked = np.where(covered, r1, np.float32(0.0)).astype("<f4")
        sha, size = put(store, masked.tobytes())
        cases.append(
            {
                "case_id": f"{case.case_id}--{golden.mesh}--{golden.resolution}",
                "mesh": {"id": golden.mesh, "class": mesh.mesh_class, "uv_tiles": 1},
                "params": dict(sets[case.case_id]),
                "seed": asset.seed,
                "output": spec(golden.resolution, 1, "linear"),
                "inputs": {
                    name: {**spec(golden.resolution, channels[name], spaces[name]), **blob(rec)}
                    for name, rec in inputs.items()
                },
                "oracle": {
                    "record_id": f"covered-{golden.name}-user{k}",
                    "sha256": sha,
                    "size_bytes": size,
                    "encoding": "raw",
                },
            }
        )
    return cases


def write_batch(
    asset: Asset,
    calibration: Sequence[Golden],
    held_out: Sequence[Golden],
    store: OracleStore,
    root: Path = REPO_ROOT,
) -> Path:
    directory = BATCHES / f"{asset.asset.replace('/', '__')}@{asset.version}"
    pins: dict[str, Any] = {}
    for set_name, folder, chosen in (
        ("calibration", "calibration", calibration),
        ("held_out", "held-out", held_out),
    ):
        cases = [c for g in chosen for c in golden_cases(g, asset, store, root)]
        data = (
            json.dumps({"schema": CASES_SCHEMA, "set": set_name, "cases": cases}, indent=1) + "\n"
        ).encode()
        path = directory / folder / "cases.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        corpus = f"{asset.asset.replace('/', '-')}-{asset.version}-{folder}-{CORPUS_DATE}"
        pins[set_name] = {
            "corpus_id": corpus,
            "path": f"{folder}/cases.json",
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    document = {
        "schema": BATCH_SCHEMA,
        "asset": asset.asset,
        "asset_version": asset.version,
        "domain": asset.domain,
        "matrix": {
            "meshes": sorted({g.mesh for g in calibration}),
            "resolutions": sorted({g.resolution for g in calibration}),
            "parameter_sets": [
                {"id": set_id, "role": role, "params": dict(params)}
                for set_id, role, params in asset.parameter_sets
            ],
            "seeds": [asset.seed],
        },
        **pins,
    }
    batch = directory / "batch.json"
    batch.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8", newline="\n")
    return batch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.proc_filters.batch")
    parser.add_argument("asset", choices=sorted(ASSETS))
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    store = locate()
    if store is None:
        raise SystemExit("no private store on this machine")
    make_asset, make_goldens = ASSETS[args.asset]
    goldens = make_goldens()
    calibration = [g for g in goldens if g.stage == "calibration"]
    held_out = [g for g in goldens if g.stage == "held-out"]
    print(write_batch(make_asset(), calibration, held_out, store))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
