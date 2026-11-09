"""Certification batches of the generator goldens (decisions 222 and 303, `tools.parity.proc_cert`).

`python -m tools.parity.proc_generators.batch occlusion` writes the Ambient Occlusion batch under
`parity/manifests/phase3/proc-cert/generator__occlusion@<version>/` from the admitted goldens of
`goldens.py`: `batch.json` (the asset, its certified domain, the §6 matrix and both case lists
pinned by SHA-256), `calibration/cases.json` and `held-out/cases.json`. Nothing here fits or
reads a case to change a candidate: the oracles are only re-hashed, masked and stored.

Each case is one User channel of one golden:

- **Inputs** are the baked mesh maps of the same recording, as Painter exported them (OpenEXR
  32f, the store's blobs): the map the generator reads (`AO`) and the World Space Normals map,
  baked with no dilation, which marks Painter's own UV coverage (every covered texel holds a unit
  normal encoded n / 2 + 1/2, so never three zeros; every other texel is 0). The compared texels
  are the covered ones whose 3 x 3 neighbourhood is covered (`covered_texels`).
- **Oracle**: the r1 export of the case's User channel, with every texel outside that coverage
  set to 0, stored as raw little-endian float32 (rows top first). Under `passthrough` padding
  Painter leaves those texels undefined: the two recordings of a golden differ there and only
  there, and on island-edge texels. The batch refuses a golden whose r1 and r2 differ on a
  compared texel. Every oracle is masked the same way, whatever its values, so the rule does not
  depend on them. A candidate reproduces the mask from its World Space Normals
  input; the comparison is therefore over every compared texel.
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
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.fit.decode import decode_exr
from tools.parity.proc_cert.batch import BATCH_SCHEMA, CASES_SCHEMA, canonical
from tools.parity.proc_generators import goldens as gold
from tools.parity.proc_generators.coverage import covered_texels
from tools.parity.proc_generators.requests import FAMILY, MESHES, Golden
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

BATCHES = REPO_ROOT / "parity" / "manifests" / "phase3" / "proc-cert"
SCRATCH = REPO_ROOT / "tmp" / "scratch"
EXPORT_NAMES = {"AO": "ambient_occlusion", "WorldSpaceNormal": "world_space_normals"}
CHANNELS = {"AO": 1, "WorldSpaceNormal": 3}
COVERAGE = "WorldSpaceNormal"
Floats = npt.NDArray[np.float32]


class BatchBuildError(Exception):
    """An admitted golden that cannot become certification cases."""


@dataclass(frozen=True)
class Asset:
    asset: str  # proc_cert asset id, <family>/<id>
    version: int
    domain: Mapping[str, Any]
    parameter_sets: tuple[tuple[str, str, Mapping[str, Any]], ...]  # (id, role, params)
    seed: int


def occlusion_asset() -> Asset:
    output = {"resolutions": list(gold.RESOLUTIONS), "formats": ["f32"]}
    output |= {"colour_spaces": ["linear"], "channels": [1]}
    inputs = {
        usage: {
            "resolutions": list(gold.RESOLUTIONS),
            "formats": ["f32"],
            "colour_spaces": ["Raw"],
            "channels": [CHANNELS[usage]],
        }
        for usage in gold.MAPS
    }
    domain = {
        "parameters": {"ao_invert": {"set": [0, 1]}, "global_invert": {"set": [0, 1]}},
        "constraints": [],
        "seeds": {"policy": "listed", "seeds": [0]},
        "geometry": {
            "mesh_classes": ["sphere", "bevelled-cube", "garment"],
            "uv_tiles": 1,
            "inputs": inputs,
        },
        "output": output,
    }
    sets = tuple(
        (set_id, role, {"ao_invert": ao, "global_invert": glob})
        for set_id, role, ao, glob in gold.OCCLUSION_SETS
    )
    return Asset("generator/occlusion", 2, domain, sets, 0)


def records(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {record["record_id"]: record for record in manifest["private_records"]}


def texture_set(found: Mapping[str, Mapping[str, Any]]) -> str:
    # Record ids are r<n>-<texture set>-<map>; a texture set name may hold hyphens.
    names = {
        rid[len("r1-") : -len("-user0")]
        for rid in found
        if rid.startswith("r1-") and rid.endswith("-user0")
    }
    if len(names) != 1:
        raise BatchBuildError(f"one texture set expected, found {sorted(names)}")
    return names.pop()


def exr(store: OracleStore, record: Mapping[str, Any]) -> Floats:
    data = store.load(record["sha256"], record["size_bytes"])
    if data is None:
        raise BatchBuildError(f"{record['record_id']}: oracle_unavailable")
    values = decode_exr(data).values
    return np.asarray(values, dtype=np.float32)


def blob(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "record_id": record["record_id"],
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
        "encoding": "exr",
    }


def put(store: OracleStore, data: bytes) -> tuple[str, int]:
    sha = hashlib.sha256(data).hexdigest()
    source = SCRATCH / f"proc-cert-{sha}"
    source.write_bytes(data)
    try:
        store.put_blob(source, sha)
    finally:
        source.unlink()
    return sha, len(data)


def golden_cases(
    golden: Golden, asset: Asset, set_name: str, store: OracleStore, root: Path = REPO_ROOT
) -> list[dict[str, Any]]:
    path = manifest_root(current_envelope(root), root) / FAMILY / f"{golden.name}.json"
    found = records(json.loads(path.read_text(encoding="utf-8")))
    ts = texture_set(found)
    inputs = {usage: found[f"r1-{ts}-{EXPORT_NAMES[usage]}"] for usage in golden.mesh_maps}
    for usage, record in inputs.items():
        if found[f"r2-{ts}-{EXPORT_NAMES[usage]}"]["sha256"] != record["sha256"]:
            raise BatchBuildError(f"{golden.name}: the two recordings baked {usage} differently")
    covered = covered_texels(exr(store, inputs[COVERAGE]))
    sets = {canonical(params): (set_id, params) for set_id, _, params in asset.parameter_sets}
    cases = []
    for k, case in enumerate(golden.cases):
        params = dict(case.parameters)
        set_id, _ = sets[canonical(params)]
        r1 = exr(store, found[f"r1-{ts}-user{k}"])[..., 0]
        r2 = exr(store, found[f"r2-{ts}-user{k}"])[..., 0]
        if not np.array_equal(r1[covered], r2[covered]):
            raise BatchBuildError(f"{golden.name} user{k}: r1 and r2 differ on a covered texel")
        masked = np.where(covered, r1, np.float32(0.0)).astype("<f4")
        sha, size = put(store, masked.tobytes())
        mesh = MESHES[golden.mesh]
        cases.append(
            {
                "case_id": f"{set_id}--{golden.mesh}--{golden.resolution}",
                "mesh": {"id": golden.mesh, "class": mesh.mesh_class, "uv_tiles": 1},
                "params": params,
                "seed": asset.seed,
                "output": spec(golden.resolution, 1, "linear"),
                "inputs": {
                    usage: {**spec(golden.resolution, CHANNELS[usage], "Raw"), **blob(record)}
                    for usage, record in inputs.items()
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


def spec(resolution: int, channels: int, colour_space: str) -> dict[str, Any]:
    return {
        "resolution": resolution,
        "format": "f32",
        "colour_space": colour_space,
        "channels": channels,
    }


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
        cases = [c for g in chosen for c in golden_cases(g, asset, set_name, store, root)]
        data = (
            json.dumps({"schema": CASES_SCHEMA, "set": set_name, "cases": cases}, indent=1) + "\n"
        ).encode()
        path = directory / folder / "cases.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        corpus = f"{asset.asset.replace('/', '-')}-{asset.version}-{folder}-2026-11-09"
        pins[set_name] = {
            "corpus_id": corpus,
            "path": f"{folder}/cases.json",
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    meshes = sorted({g.mesh for g in calibration})
    resolutions = sorted({g.resolution for g in calibration})
    document = {
        "schema": BATCH_SCHEMA,
        "asset": asset.asset,
        "asset_version": asset.version,
        "domain": asset.domain,
        "matrix": {
            "meshes": meshes,
            "resolutions": resolutions,
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
    parser = argparse.ArgumentParser(prog="python -m tools.parity.proc_generators.batch")
    parser.add_argument("asset", choices=["occlusion"])
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    store = locate()
    if store is None:
        raise SystemExit("no private store on this machine")
    goldens = gold.occlusion_goldens()
    calibration = [g for g in goldens if g.stage == "calibration"]
    held_out = [g for g in goldens if g.stage == "held-out"]
    print(write_batch(occlusion_asset(), calibration, held_out, store))
    _ = args
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
