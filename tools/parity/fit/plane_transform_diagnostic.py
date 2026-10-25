"""Bounded CPU-only Householder diagnostic; stdout contains hashes and counts only.

Two pinned existing datasets, no captures, fitting, admission, production changes,
temporary files or private samples in reports. Run as a module after review.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import time
import types
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.envelope.registry import current_envelope
from tools.parity.fit.padding_plane_control import REFERENCE_SHA256, checked_bytes
from tools.parity.fit.plane_transforms import Construction, Plane, Vector, rotate_between_planes
from tools.parity.recorder.environment import envelope_sha256
from tools.parity.recorder.job import canonical_json
from tools.parity.schemas import REPO_ROOT, record_problems
from tools.parity.store.store import OracleStore, load_oracle, locate
from tools.parity.tier0_semantics.recording_requests import kernel_bitmaps

MANIFESTS = {
    "hinge-far": "0cd290499261ad3e10b3519b536cfc93a217ca36bd312daf7e120d5ed6ad24aa",
    "tau-prism": "b7f91cb30b7e9d62e5ff42f79dee2df062ae3ff752f28fbec32b848724574937",
}
MANIFEST_ROOT = REPO_ROOT / (
    "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/tier0/semantics"
)
type Image = npt.NDArray[np.float32]
type Point = tuple[int, int]


class DiagnosticFailure(ValueError):
    """A public categorical failure; never include private values in its message."""


def reference() -> Any:
    path = REPO_ROOT / "tests/export/padding_reference.py"
    checked_bytes(path, REFERENCE_SHA256)
    return load_module(path, "plane_diagnostic_reference")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("reference unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_record(record: dict[str, Any], manifest: dict[str, Any]) -> None:
    recordings = record["recordings"]
    if len(recordings) != 2 or {r["recording_id"] for r in recordings} != {"r1", "r2"}:
        raise ValueError("expected separate recording identities")
    for recording in recordings:
        outputs = recording["outputs"]
        if len(outputs) != len({o["output_id"] for o in outputs}):
            raise ValueError("duplicate output identity")
        expected = "same_session" if recording["recording_id"] == "r1" else "after_save_reopen"
        if recording["condition"] != expected:
            raise ValueError("recording condition mismatch")
    if record_problems(record):
        raise DiagnosticFailure("record_schema")
    envelope, key = current_envelope(), record["key"]
    if (
        record["golden_id"] != manifest["golden_id"]
        or record["tier"] != "0"
        or key["painter_build"]["build_id"] != envelope["painter_build"]
        or envelope_sha256(record.get("environment", {})) != envelope["envelope_sha256"]
        or key["instruction_sequence_sha256"]
        != hashlib.sha256(canonical_json(manifest["instruction_sequence"])).hexdigest()
        or key["inputs"]
        != [{"input_id": row["input_id"], "sha256": row["sha256"]} for row in manifest["inputs"]]
    ):
        raise ValueError("record identity mismatch")


def image(path: Path) -> Image:
    import OpenEXR

    with OpenEXR.File(str(path), separate_channels=True) as exr:
        channels = exr.channels()
        if set(channels) != {"R", "G", "B"}:
            raise ValueError("expected RGB channels")
        planes = [channels[c].pixels for c in "RGB"]
        if any(p.dtype != np.float32 or p.shape != (512, 512) for p in planes):
            raise ValueError("expected 512x512 RGB32F")
        result = np.stack(planes, axis=-1)
    if not np.isfinite(result).all():
        raise ValueError("nonfinite samples")
    return result


def samples(record: dict[str, Any], material: str, store: OracleStore) -> dict[Any, Image]:
    images: dict[Any, Image] = {}
    cache: dict[str, Image] = {}
    for recording in record["recordings"]:
        templates = [o for o in recording["outputs"] if o["kind"] == "template_capture"]
        if len(templates) != 1:
            raise ValueError("ambiguous template")
        sets = templates[0]["values"]["texture_sets"]
        if set(sets) != {material}:
            raise ValueError("unexpected texture sets")
        texture = sets[material]
        if texture["resolution"] != [512, 512] or set(texture["stacks"]) != {""}:
            raise ValueError("unexpected resolution or stacks")
        channels = {key.lower(): value for key, value in texture["stacks"][""].items()}
        if any(
            channels[f"user{i}"]["format"] != "RGB32F"
            or channels[f"user{i}"]["bit_depth"] != 32
            or channels[f"user{i}"]["is_floating"] is not True
            for i in range(8)
        ):
            raise ValueError("template channel precision mismatch")
        groups: dict[tuple[str, int], dict[int, Image]] = {}
        for output in recording["outputs"]:
            if output["kind"] != "exported_map":
                continue
            if output["texture_set"] != material or output["map"] not in [
                f"user{i}" for i in range(8)
            ]:
                raise ValueError("unexpected exported map")
            settings = output["export_settings"]
            mode, step = settings["paddingAlgorithm"], settings["step"]
            if (
                type(step) is not int
                or {45: "infinite", 46: "infinite", 47: "passthrough", 48: "passthrough"}.get(step)
                != mode
            ):
                raise ValueError("unexpected export step")
            if settings != {
                "paddingAlgorithm": mode,
                "step": step,
                "map_type": "documentMap",
                "map_channels": "RGB",
                "encoding_basis": "file",
                "fileFormat": "exr",
                "bitDepth": "32f",
                "dithering": False,
            } or output["storage_format"] != {
                "container": "exr",
                "sample_type": "float",
                "bits_per_channel": 32,
                "channels": 3,
                "encoding": "linear",
            }:
                raise ValueError("export domain mismatch")
            channel = int(output["map"][4:])
            group = groups.setdefault((mode, step), {})
            if channel in group:
                raise ValueError("duplicate exported channel")
            blob = output["blob"]
            sha = blob["sha256"]
            if sha not in cache:
                if load_oracle(store, blob) is None:
                    raise ValueError("export blob unavailable")
                cache[sha] = image(store.blob_path(sha))
            group[channel] = cache[sha]
        if len(groups) != 4 or any(set(group) != set(range(8)) for group in groups.values()):
            raise ValueError("incomplete export groups")
        for (mode, step), group in groups.items():
            images[(recording["recording_id"], mode, step)] = np.concatenate(
                [group[i] for i in range(8)], axis=-1
            )
    return images


def source_plane(ring: Any, k: int, tau: int) -> int | None:
    source, target = ring.tris[k], ring.tris[tau]
    if source.chart == target.chart:
        return None
    paths = ring._paths(source.face, target.face)
    if len(paths) != 1:
        return None
    edges = [ring.links[b][a] for a, b in itertools.pairwise(paths[0])]
    seams = [(i, j) for i, j, _, _ in edges if ring.tris[i].chart != ring.tris[j].chart]
    if len(seams) != 1:
        return None
    i, j = seams[0]
    if (
        ring.tris[i].chart != target.chart
        or ring.tris[j].chart != source.chart
        or ring.tris[i].face == target.face
    ):
        return None
    return int(j)


def install_frame(ring: Any, ref: Any, construction: Construction) -> None:
    cache: dict[tuple[int, int], int | None] = {}

    def frame(self: Any, p: Vector, k: int, tau: int, q: Vector) -> Vector:
        if (k, tau) not in cache:
            cache[k, tau] = source_plane(self, k, tau)
        source = cache[k, tau]
        if source is not None:
            target, origin = self.tris[tau], self.tris[source]
            if (
                ref.norm(
                    ref.cross(tuple(map(float, target.normal)), tuple(map(float, origin.normal)))
                )
                > 1e-10
            ):
                return rotate_between_planes(
                    p,
                    Plane(origin.normal, origin.p[0]),
                    Plane(target.normal, target.p[0]),
                    construction=construction,
                )
        result: Vector = ref.Ring.frame(self, p, k, tau, q)
        return result

    ring.frame = types.MethodType(frame, ring)


def neighbours(ring: Any, ref: Any, x: int, y: int) -> list[Point]:
    return [
        (x + dx, y + dy)
        for dy, dx in ref.NEIGHBOURS
        if 0 <= x + dx < 512 and 0 <= y + dy < 512 and ring.owner[y + dy, x + dx] >= 0
    ]


def targets(ring: Any, ref: Any, dataset: str) -> set[Point]:
    selected: set[Point] = set()
    for x, y, candidates, count in ring.texels():
        if dataset == "hinge-far":
            selected.add((x, y))
            continue
        tau = ring.tau(x, y, neighbours(ring, ref, x, y))
        for _, far, (tx, ty) in candidates[:count]:
            if not far:
                continue
            k = int(ring.owner[ty, tx])
            for path in ring._paths(ring.tris[k].face, ring.tris[tau].face):
                gates = []
                for a, b in itertools.pairwise(path):
                    i, j, _, _ = ring.links[b][a]
                    if ring.tris[i].chart == ring.tris[tau].chart == ring.tris[j].chart:
                        gates.append(ring.folded(i, j))
                if len(gates) >= 2 and any(gates) and not all(gates):
                    selected.add((x, y))
    if not selected or (dataset == "tau-prism" and len(selected) != 96):
        raise ValueError("authored target population changed")
    return selected


def check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("diagnostic execution limit reached")


def validate_baseline(dataset: str, misses: dict[str, dict[str, set[Point]]]) -> None:
    expected = (395, 7) if dataset == "hinge-far" else (96, 3)
    for key, baseline in misses["baseline"].items():
        intersection = misses["intersection"][key]
        if (len(baseline), len(intersection)) != expected or (
            dataset == "hinge-far"
            and (len(baseline - intersection), len(intersection - baseline)) != (389, 1)
        ):
            raise DiagnosticFailure("historical_baseline_drift")


def run_dataset(dataset: str, store: OracleStore, ref: Any, deadline: float) -> dict[str, Any]:
    validator = load_module(
        REPO_ROOT / "tests/export/padding_probe_diagnostic.py", "plane_diagnostic_exports"
    )

    path = MANIFEST_ROOT / f"export-padding-{dataset}.json"
    manifest = json.loads(checked_bytes(path, MANIFESTS[dataset]))
    refs = [r for r in manifest["private_records"] if r["record_id"] == "golden-record"]
    if len(refs) != 1 or (raw := load_oracle(store, refs[0])) is None:
        raise ValueError("private record unavailable")
    record = json.loads(raw)
    validate_record(record, manifest)
    inputs = {row["input_id"]: row for row in manifest["inputs"]}
    for row in inputs.values():
        checked_bytes(REPO_ROOT / row["path"], row["sha256"])
    source = np.concatenate(
        [image(REPO_ROOT / inputs[key]["path"]) for key in kernel_bitmaps(512)], axis=-1
    )
    material = "uzp_hinge" if dataset == "hinge-far" else "uzp_tau_prism"
    ring = ref.Ring(REPO_ROOT / inputs[dataset]["path"], material, 512, 512)
    actual = samples(record, material, store)
    try:
        stability = validator.validate_exports(source, ring.owner >= 0, actual)
    except ValueError:
        raise DiagnosticFailure("export_coverage_or_domain") from None
    if any(stability["infinite"].values()):
        raise DiagnosticFailure("unstable_infinite_exports")
    points = targets(ring, ref, dataset)
    misses: dict[str, dict[str, set[Point]]] = {}
    for policy in ("baseline", "intersection", "householder"):
        check_deadline(deadline)
        if policy == "householder":
            validate_baseline(dataset, misses)
        if policy != "baseline":
            install_frame(ring, ref, "intersection" if policy == "intersection" else "householder")
        errors: dict[str, set[Point]] = {
            f"{rid}/step-{step}": set() for rid, mode, step in actual if mode == "infinite"
        }
        for x, y in sorted(points):
            check_deadline(deadline)
            own = neighbours(ring, ref, x, y)
            candidates, _ = ring.candidates(x, y, own, ring.tau(x, y, own))
            taps = candidates[: ref.tap_count(candidates)]
            weights = ring.chain_fractions(x, y, taps)
            values = np.asarray([source[ty, tx] for _, _, (tx, ty) in taps])
            prediction = np.array([ref.chain(values[:, c], weights) for c in range(24)], np.float32)
            for (rid, mode, step), value in actual.items():
                if mode == "infinite" and not np.array_equal(
                    prediction.view(np.uint32), value[y, x].view(np.uint32)
                ):
                    errors[f"{rid}/step-{step}"].add((x, y))
        misses[policy] = errors
    counts = {
        policy: {key: len(value) for key, value in errors.items()}
        for policy, errors in misses.items()
    }
    new = {
        key: len(value - misses["intersection"][key])
        for key, value in misses["householder"].items()
    }
    remaining = {
        key: len(value & (misses["intersection"][key] - misses["baseline"][key]))
        for key, value in misses["householder"].items()
    }
    return {
        "manifest_sha256": MANIFESTS[dataset],
        "record_sha256": refs[0]["sha256"],
        "tested": len(points),
        "stability": stability,
        "mismatches": counts,
        "new_vs_intersection": new,
        "remaining_intersection_regressions": remaining,
        "continue": not any(new.values()) and not any(remaining.values()),
    }


def main() -> int:
    deadline = time.monotonic() + 900
    try:
        store = locate()
        if store is None:
            raise ValueError("store unavailable")
        ref = reference()
        reports = {}
        for dataset in MANIFESTS:
            check_deadline(deadline)
            reports[dataset] = run_dataset(dataset, store, ref, deadline)
            if not reports[dataset]["continue"]:
                break
    except DiagnosticFailure as error:
        print(json.dumps({"status": str(error)}))
        return 2
    except TimeoutError:
        print(json.dumps({"status": "execution_timeout"}))
        return 2
    except (ValueError, KeyError, TypeError, OSError):
        print(json.dumps({"status": "invalid_input_or_unavailable_blob"}))
        return 2
    print(json.dumps({"datasets": reports, "reference_sha256": REFERENCE_SHA256}, sort_keys=True))
    return 0 if len(reports) == 2 and all(r["continue"] for r in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
