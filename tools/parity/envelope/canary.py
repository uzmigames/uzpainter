"""The 10-golden canary (decision 034 (d); task phase0.9_oracle-envelope 4.1-4.2).

After a GPU, driver, OS or Painter update the canary re-records a fixed subset of the corpus and
diffs it exactly against the current envelope's goldens. Under decision 037 the canary decides
nothing on its own: a new Painter build always gets a full re-record (`refresh.py`), whose first
ten goldens are the canary; under the same build, a canary that equals the current goldens
exactly records the running environment as equivalent, and any difference starts the full
re-record under a new envelope. Originals are never touched: the new envelope's records go to
their own manifests (and, under the same build, their own record ids), the old ones stay in the
store, their r1 targets and decision 032 records unchanged.

Subset (one golden per area the compositor and baker depend on):
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from tools.parity.envelope.compare import RecordSource, SourceUnavailable, run_source, store_source
from tools.parity.envelope.corpus import golden_index, job_manifest, record_golden
from tools.parity.envelope.drift import DriftInput, drift_document, tier3_goldens
from tools.parity.envelope.registry import corpus_manifests, manifest_root
from tools.parity.recorder.environment import envelope_sha256
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.schemas import REPO_ROOT, load_json
from tools.parity.store.store import OracleStore

CANARY: tuple[tuple[str, str], ...] = (
    ("tier0/semantics/blend-basic", "blends: separable modes on every channel format"),
    ("tier0/semantics/blend-component", "blends: component (HSV) and normal modes"),
    ("tier0/semantics/quantisation-thirds", "quantisation: 1/3 steps on every format"),
    ("tier0/semantics/colour-ramps-srgb", "sRGB store: sRGB8 encoding of ramps"),
    ("tier0/semantics/height-normal-sphere", "height-to-normal on a curved mesh"),
    ("tier0/semantics/resample-uv", "resampling: UV projection filtering"),
    ("tier0/semantics/levels-clamp", "effects: levels with clamping"),
    ("phase0/normal-convention/hemisphere/per-fragment", "a bake: tangent-space normal bake"),
    ("tier0/api-probes/fill-layer-readback", "API readback: set/get of fill-layer properties"),
    ("tier0/defaults-templates/baking-defaults", "API readback: baking defaults"),
)
__doc__ = (__doc__ or "") + "\n".join(f"- `{g}`: {why}" for g, why in CANARY) + "\n"


def canary_manifests(entry: Mapping[str, Any], repo_root: Path = REPO_ROOT) -> list[Path]:
    """The canary goldens' manifests in an envelope (refuses a canary golden it lacks)."""
    index = golden_index(sorted(manifest_root(entry, repo_root).rglob("*.json")))
    missing = [g for g, _ in CANARY if g not in index]
    if missing:
        raise RecorderError(f"envelope {entry['envelope_id']} lacks canary goldens {missing}")
    return [index[g] for g, _ in CANARY]


def previous_source(
    store: OracleStore | None, manifest_path: Path, prefix: str
) -> tuple[RecordSource | None, str | None]:
    try:
        return store_source(store, manifest_path, f"{prefix}golden-record"), None
    except (SourceUnavailable, OSError, ValueError) as error:
        return None, str(error)


def run_canary(
    session: PainterSession,
    current: Mapping[str, Any],
    store: OracleStore | None,
    work: Path,
    inbox: Path,
    now: Callable[[], datetime],
    today: date,
    repo_root: Path = REPO_ROOT,
) -> tuple[dict[str, Any], list[Path]]:
    """Re-record the canary on the running Painter and diff it against the current envelope.

    Returns the drift document (scope `canary`) and the inbox runs. The runs carry record ids
    prefixed `canary-<stamp>-` and are evidence only: they are never merged into the current
    envelope's manifests."""
    identity = session.connect()
    stamp = now().strftime("%Y%m%dt%H%M%S%fz")
    prefix = f"canary-{stamp}-"
    runs: list[Path] = []
    items: list[DriftInput] = []
    for path in canary_manifests(current, repo_root):
        manifest = load_json(path)
        run = record_golden(
            session,
            job_manifest(manifest, identity),
            work / "canary" / stamp,
            inbox / "canary" / stamp,
            now,
            prefix,
            repo_root,
        )
        runs.append(run)
        previous, error = previous_source(store, path, str(current["record_prefix"]))
        items.append(
            DriftInput(
                str(manifest["golden_id"]), str(manifest["tier"]), previous, run_source(run), error
            )
        )
    assert identity.environment is not None
    running = {
        "envelope_id": current["envelope_id"]
        if identity.build_id == current["painter_build"]
        else f"painter-{identity.build_id}",
        "painter_build": identity.build_id,
        "envelope_sha256": envelope_sha256(identity.environment),
    }
    document = drift_document(
        "canary",
        running,
        current,
        items,
        tier3_goldens(corpus_manifests(current, repo_root, frozenset({"3"}))),
        today,
        repo_root,
    )
    return document, runs


def drift_free(document: Mapping[str, Any]) -> bool:
    """Every canary golden unchanged (exact equality of every paired recording)."""
    return all(g["status"] == "unchanged" for g in document["goldens"])


def canary_ids() -> Sequence[str]:
    return [g for g, _ in CANARY]
