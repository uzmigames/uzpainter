"""Compare DX12/Vulkan export bundles of one project/revision at native sample depth.

python -m tools.parity.cross_backend dx12.json vulkan.json --report REPORT
    [--mapping MAPS.json] [--regions MASKS.json] [--store PRIVATE_STORE]

Bundles contain project_uuid, revision, project_sha256 (canonical ProjectToJson),
evaluator_profile, build_sha256, resource_hashes (ID -> SHA-256), backend, adapter,
driver and files [{texture_set, map, path, sha256}]. Paths resolve beside the bundle.
An optional refused:true explicitly records an export refusal. No files never passes.
Both native decoded values AND file bytes must equal; no exceptions apply here.

Mapping JSON: [{texture_set, map, kind}], kind normal/id/alpha. Region JSON:
[{id, path, sha256}], nonzero first-channel mask pixels, resolved beside that JSON.
Masks must match a compared resolution; no resampling. All metadata, inputs and map
sets are checked before comparison. Public reports contain only counts, IDs and hashes;
map IDs hash [texture_set,map], adapter/driver and resource IDs are hashed. Raw paths,
refusal messages, image values and difference maps never enter the public report.
Optional difference images go only to an existing private OracleStore. FLIP is diagnostic.
This is a backend comparison, not Painter parity evidence or capability promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit.decode import Decoded, decode
from tools.parity.fit.stability import storage_key
from tools.parity.recorder.capture import PNG_SIGNATURE, exr_format, png_format
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import OracleStore, StoreError
from tools.parity.tier1.compare import (
    ALPHA,
    FLIP_VERSION,
    FLIP_WHEEL_SHA256,
    ID_LABELS,
    MapKey,
    Mask,
    exact_check,
    flip_mean,
    map_entry,
    normal_diagnostics,
    region_diagnostics,
    store_difference_map,
)
from tools.parity.verdict import diagnose

REPORT_SCHEMA = "uzpainter/parity/cross-backend-report/1"
IDENTITY = (
    "project_uuid",
    "revision",
    "project_sha256",
    "evaluator_profile",
    "build_sha256",
    "resource_hashes",
)
SHA = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def map_id(key: MapKey) -> str:
    return "map-" + digest(canonical(key))


def storage_format(data: bytes) -> dict[str, Any]:
    measured = png_format(data) if data.startswith(PNG_SIGNATURE) else exr_format(data)
    return measured.as_schema(measured.encoding or "undetermined")


class BundleError(ValueError):
    """A machine-readable structural failure; no raw bundle text enters the report."""


def _load(path: Path, backend: str) -> tuple[dict[str, Any], dict[MapKey, bytes], str]:
    try:
        raw = path.read_bytes()
        bundle = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise BundleError("input_unreadable") from exc
    if not isinstance(bundle, dict):
        raise BundleError("bundle_invalid")
    if bundle.get("backend") != backend:
        raise BundleError("backend_mismatch")
    if bundle.get("refused") is True:
        raise BundleError("export_refused")
    if "refused" in bundle and bundle["refused"] is not False:
        raise BundleError("bundle_invalid")
    for field in ("project_uuid", "evaluator_profile"):
        if not isinstance(bundle.get(field), str) or not ID.fullmatch(bundle[field]):
            raise BundleError("identity_invalid")
    if type(bundle.get("revision")) is not int or bundle["revision"] < 0:
        raise BundleError("identity_invalid")
    for field in ("project_sha256", "build_sha256"):
        if not isinstance(bundle.get(field), str) or not SHA.fullmatch(bundle[field]):
            raise BundleError("identity_invalid")
    for field in ("adapter", "driver"):
        if (
            not isinstance(bundle.get(field), str)
            or not bundle[field].strip()
            or bundle[field].strip().casefold() == "unknown"
        ):
            raise BundleError("identity_invalid")
    resources = bundle.get("resource_hashes")
    if not isinstance(resources, dict) or any(
        not isinstance(k, str) or not k or not isinstance(v, str) or not SHA.fullmatch(v)
        for k, v in resources.items()
    ):
        raise BundleError("identity_invalid")
    files = bundle.get("files")
    if not isinstance(files, list) or not files:
        raise BundleError("no_maps")
    found: dict[MapKey, bytes] = {}
    for entry in files:
        if (
            not isinstance(entry, dict)
            or any(
                not isinstance(entry.get(k), str) or not entry[k]
                for k in ("texture_set", "map", "path", "sha256")
            )
            or not SHA.fullmatch(entry["sha256"])
        ):
            raise BundleError("map_invalid")
        key = (entry["texture_set"], entry["map"])
        if key in found:
            raise BundleError("duplicate_map")
        try:
            data = (path.parent / entry["path"]).read_bytes()
        except OSError as exc:
            raise BundleError("map_unreadable") from exc
        if digest(data) != entry["sha256"]:
            raise BundleError("map_hash_mismatch")
        found[key] = data
    return bundle, found, digest(raw)


def _identity(bundle: Mapping[str, Any], bundle_hash: str) -> dict[str, Any]:
    return {
        "backend": bundle["backend"],
        "bundle_sha256": bundle_hash,
        **{k: bundle[k] for k in IDENTITY if k != "resource_hashes"},
        "resource_hashes": sorted(bundle["resource_hashes"].values()),
        "resource_identity_sha256": digest(canonical(bundle["resource_hashes"])),
        "adapter_sha256": digest(bundle["adapter"].encode()),
        "driver_sha256": digest(bundle["driver"].encode()),
    }


def report_problems(report: Any) -> list[str]:
    """Schema plus verdict consistency, shared by writer and repository guard."""
    errors = validation_errors(report, Schema.CROSS_BACKEND_REPORT)
    if errors:
        return errors

    def finite(node: Any) -> bool:
        if isinstance(node, dict):
            return all(finite(value) for value in node.values())
        if isinstance(node, list):
            return all(finite(value) for value in node)
        return not isinstance(node, float) or math.isfinite(node)

    if not finite(report):
        errors.append("report contains non-finite numbers")
    if "flip_tool" in report and report["flip_tool"] != {
        "version": FLIP_VERSION,
        "sha256": FLIP_WHEEL_SHA256,
    }:
        errors.append("FLIP identity differs from the pinned tool")
    ids = [m["output_id"] for m in report["maps"]]
    if len(ids) != len(set(ids)):
        errors.append("duplicate output_id")
    passing = (
        bool(report["maps"])
        and not report["structural"]
        and all(m["bytes_equal"] and m["differing"]["count"] == 0 for m in report["maps"])
    )
    if passing != (report["outcome"] == "pass"):
        errors.append("outcome disagrees with map equality or structural failures")
    for m in report["maps"]:
        if m["bytes_equal"] != (m["dx12_sha256"] == m["vulkan_sha256"]):
            errors.append("bytes_equal disagrees with hashes")
        if m["bytes_equal"] and m["differing"]["count"]:
            errors.append("equal bytes cannot have differing samples")
        checks = m.get("exact_checks", [])
        if len({check["check"] for check in checks}) != len(checks):
            errors.append("duplicate exact check")
        for check in checks:
            if check["edge_coverage_differing_count"] > check["differing_count"]:
                errors.append("edge differences exceed exact differences")
            if check["differing_count"] > m["differing"]["count"]:
                errors.append("exact differences exceed whole-map differences")
            if report["outcome"] == "pass" and (
                not check["equal"]
                or check["differing_count"]
                or check["edge_coverage_differing_count"]
            ):
                errors.append("pass requires equal exact checks")
        region_ids = [region["region"] for region in m["regions"]]
        if len(region_ids) != len(set(region_ids)):
            errors.append("duplicate region")
        for region in m["regions"]:
            if (
                region["differing"]["count"] > m["differing"]["count"]
                or region["differing"]["total"] > m["differing"]["total"]
            ):
                errors.append("region differences exceed whole-map counts")
        normal = m.get("normal")
        if (
            normal
            and m["differing"]["count"] == 0
            and (normal["angular_max_deg"] or normal["angular_mean_deg"])
        ):
            errors.append("equal maps cannot have angular differences")
        for stats in (m, *m["regions"]):
            count, total = stats["differing"]["count"], stats["differing"]["total"]
            if total == 0 or count > total:
                errors.append("invalid differing count or total")
            elif not math.isclose(stats["differing"]["percent"], 100 * count / total):
                errors.append("differing percent disagrees with counts")
            delta = stats["abs_diff"]
            if (count == 0 and any(delta.values())) or (count > 0 and delta["max"] == 0):
                errors.append("absolute differences disagree with count")
            if delta["mean"] > delta["max"] or delta["p99"] > delta["max"]:
                errors.append("absolute difference exceeds maximum")
    if report["outcome"] == "pass":
        if len(report["runs"]) != 2 or [r["backend"] for r in report["runs"]] != ["dx12", "vulkan"]:
            errors.append("pass requires both backend identities")
        else:
            a, b = report["runs"]
            for key in (*IDENTITY, "resource_identity_sha256"):
                if a[key] != b[key]:
                    errors.append(f"pass has mismatched {key}")
    return errors


def compare(
    dx12: Path,
    vulkan: Path,
    *,
    kinds: Mapping[MapKey, str] | None = None,
    regions: Mapping[str, Mask] | None = None,
    store: OracleStore | None = None,
) -> dict[str, Any]:
    """Return an exact comparison or explicit structural failure, never a vacuous pass."""
    kinds, regions = kinds or {}, regions or {}
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "record_class": "cross_backend_report",
        "outcome": "fail",
        "runs": [],
        "maps": [],
        "structural": [],
    }

    def fail(reason: str, backend: str = "pair", key: MapKey | None = None) -> None:
        report["structural"].append(
            {"reason": reason, "backend": backend, **({"output_id": map_id(key)} if key else {})}
        )

    loaded = []
    for path, backend in ((dx12, "dx12"), (vulkan, "vulkan")):
        try:
            bundle, files, hashed = _load(path, backend)
            loaded.append((bundle, files))
            report["runs"].append(_identity(bundle, hashed))
        except BundleError as exc:
            fail(str(exc), backend)
    if report["structural"]:
        return report
    (a, left), (b, right) = loaded
    for field in IDENTITY:
        if a[field] != b[field]:
            fail(f"{field}_mismatch")
    if set(left) != set(right):
        for key in sorted(set(left) ^ set(right)):
            fail("map_missing", "vulkan" if key in left else "dx12", key)
    if set(kinds) - set(left) or any(k not in ("normal", "id", "alpha") for k in kinds.values()):
        fail("mapping_invalid")
    if any(
        not ID.fullmatch(name) or mask.dtype != np.bool_ or mask.ndim != 2
        for name, mask in regions.items()
    ):
        fail("regions_invalid")
    if report["structural"]:
        return report
    decoded: dict[MapKey, tuple[Decoded, Decoded, dict[str, Any]]] = {}
    for key in sorted(left):
        try:
            # Measure exactly the hashed bytes, never reread a file that could have changed.
            formats = [storage_format(data) for data in (left[key], right[key])]
            lmap, rmap = decode(left[key]), decode(right[key])
            if storage_key(formats[0]) != storage_key(formats[1]):
                fail("storage_format_mismatch", key=key)
            elif lmap.values.shape != rmap.values.shape or not lmap.values.size:
                fail("shape_mismatch", key=key)
            elif (kinds.get(key) == "normal" and lmap.values.shape[-1] < 3) or (
                kinds.get(key) == "alpha" and lmap.values.shape[-1] not in (1, 2, 4)
            ):
                fail("mapping_invalid", key=key)
            else:
                decoded[key] = (lmap, rmap, formats[0])
        except (
            OSError,
            ValueError,
            RuntimeError,
            ImportError,
            IndexError,
            struct.error,
            RecorderError,
        ) as exc:
            fail(
                "decoder_unavailable" if isinstance(exc, ImportError) else "map_decode_failed",
                key=key,
            )
    if any(
        mask.shape not in {v[0].values.shape[:2] for v in decoded.values()} or not mask.any()
        for mask in regions.values()
    ):
        fail("regions_invalid")
    if report["structural"]:
        return report
    for key, (lmap, rmap, stored) in decoded.items():
        whole = diagnose(lmap.values, rmap.values)
        if not all(
            math.isfinite(v) for v in (whole.max_abs_diff, whole.mean_abs_diff, whole.p99_abs_diff)
        ):
            fail("nonfinite_difference", key=key)
            continue
        kind = kinds.get(key)
        normal = normal_diagnostics(lmap, rmap) if kind == "normal" else None
        exact = (
            exact_check(ID_LABELS if kind == "id" else ALPHA, lmap, rmap)
            if kind in ("id", "alpha")
            else None
        )
        flip = flip_mean(lmap, rmap)
        difference = store_difference_map(store, lmap, rmap) if whole.differing_count else None
        row = map_entry(
            map_id(key),
            stored,
            whole,
            region_diagnostics(lmap.values, rmap.values, regions),
            normal,
            difference,
            flip,
            exact=exact,
        )
        row.update(
            dx12_sha256=digest(left[key]),
            vulkan_sha256=digest(right[key]),
            bytes_equal=left[key] == right[key],
        )
        report["maps"].append(row)
        if flip is not None:
            report["flip_tool"] = {"version": FLIP_VERSION, "sha256": FLIP_WHEEL_SHA256}
    if (
        report["maps"]
        and not report["structural"]
        and all(m["bytes_equal"] and m["differing"]["count"] == 0 for m in report["maps"])
    ):
        report["outcome"] = "pass"
    return report


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    if problems := report_problems(report):
        raise ValueError("invalid cross-backend report: " + "; ".join(problems))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dx12", type=Path)
    parser.add_argument("vulkan", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--regions", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args(argv)
    kinds: dict[MapKey, str] = {}
    regions: dict[str, Mask] = {}
    try:
        if args.mapping:
            for entry in json.loads(args.mapping.read_text(encoding="utf-8")):
                key = (entry["texture_set"], entry["map"])
                if key in kinds:
                    raise ValueError("duplicate map mapping")
                kinds[key] = entry["kind"]
        if args.regions:
            for entry in json.loads(args.regions.read_text(encoding="utf-8")):
                data = (args.regions.parent / entry["path"]).read_bytes()
                if digest(data) != entry["sha256"] or entry["id"] in regions:
                    raise ValueError("invalid region pin or duplicate ID")
                regions[entry["id"]] = decode(data).values[..., 0] != 0
        store = OracleStore.open(args.store) if args.store else None
        result = compare(args.dx12, args.vulkan, kinds=kinds, regions=regions, store=store)
        write_report(args.report, result)
    except (OSError, ValueError, KeyError, TypeError, StoreError):
        print("cross-backend: invalid options or report", file=sys.stderr)
        return 2
    print("cross-backend: " + result["outcome"])
    return 0 if result["outcome"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
