"""Oracle stability: does Painter reproduce itself? (`parity/CONTRACT.md` §2, §6.2)

Every recording of a golden is compared with its first recording (`r1`, the session that built
the state; `r2` is after save and reopen). Exported maps are decoded at native depth and
compared value for value; readbacks and captures are compared for equality as JSON. Each map
is classified by its measured storage format (container, sample type, bits per channel,
channel count, encoding), never by its name.

Readback rule, stated once: a resource URL or context names the project's resource context
(`projectNN`), a counter Painter increments per opened project. Readbacks are compared both
raw and with that counter replaced by `project#`; the normalised comparison decides stability
and the raw count is reported next to it. Outputs present in only one recording (API probes
record different steps before and after reopen) are listed, not compared.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.parity.fit.oracle import Golden
from tools.parity.fit.stats import Array, Difference, difference

STABLE, UNSTABLE = "stable", "unstable"
RESOURCE_CONTEXT = re.compile(r"(resource://|\"context\": \")project\d+")


def storage_key(storage_format: dict[str, Any]) -> str:
    """`container/sample-type bits/channels/encoding`, e.g. `png/uint16/3ch/srgb`."""
    return (
        f"{storage_format['container']}/{storage_format['sample_type']}"
        f"{storage_format['bits_per_channel']}/{storage_format['channels']}ch/"
        f"{storage_format.get('encoding') or 'unspecified'}"
    )


def classify(diff: Difference) -> str:
    return STABLE if diff.equal else UNSTABLE


def compare_maps(a: Array, b: Array) -> tuple[str, Difference]:
    """Classification and statistics of two decoded recordings of one map."""
    diff = difference(a, b)
    return classify(diff), diff


def normalised(value: Any) -> str:
    return RESOURCE_CONTEXT.sub(r"\1project#", json.dumps(value, sort_keys=True))


@dataclass(frozen=True)
class MapComparison:
    output_id: str
    recordings: tuple[str, str]
    storage: str
    sha256: tuple[str, str]
    difference: Difference

    @property
    def classification(self) -> str:
        return classify(self.difference)


@dataclass(frozen=True)
class OutputComparison:
    output_id: str
    kind: str
    recordings: tuple[str, str]
    equal_raw: bool
    equal: bool  # after the resource-context normalisation


@dataclass
class GoldenStability:
    golden_id: str
    manifest: str
    record_sha256: str
    recordings: list[tuple[str, str]]  # (recording id, condition)
    maps: list[MapComparison] = field(default_factory=list)
    outputs: list[OutputComparison] = field(default_factory=list)
    unpaired: list[str] = field(default_factory=list)  # output ids recorded in one recording

    @property
    def classification(self) -> str:
        stable = all(m.difference.equal for m in self.maps) and all(o.equal for o in self.outputs)
        return STABLE if stable else UNSTABLE

    def unstable_maps(self) -> list[MapComparison]:
        return [m for m in self.maps if not m.difference.equal]

    def unstable_outputs(self) -> list[OutputComparison]:
        return [o for o in self.outputs if not o.equal]


def golden_stability(golden: Golden, repository: Path) -> GoldenStability:
    ids = sorted(golden.recordings)
    first = ids[0]
    result = GoldenStability(
        golden.golden_id,
        golden.manifest_path.resolve().relative_to(repository.resolve()).as_posix(),
        golden.record_sha256,
        [(r, golden.recordings[r].condition) for r in ids],
    )
    unpaired: set[str] = set()
    for other in ids[1:]:
        left = golden.recordings[first].outputs
        right = golden.recordings[other].outputs
        unpaired |= set(left) ^ set(right)
        for output_id in sorted(set(left) & set(right)):
            a, b = left[output_id], right[output_id]
            pair = (first, other)
            if a["kind"] == "exported_map":
                diff = difference(
                    golden.map(first, output_id).values, golden.map(other, output_id).values
                )
                result.maps.append(
                    MapComparison(
                        output_id,
                        pair,
                        storage_key(a["storage_format"]),
                        (str(a["blob"]["sha256"]), str(b["blob"]["sha256"])),
                        diff,
                    )
                )
            else:
                result.outputs.append(
                    OutputComparison(
                        output_id, str(a["kind"]), pair, a == b, normalised(a) == normalised(b)
                    )
                )
    result.unpaired = sorted(unpaired)
    return result


@dataclass
class ChannelType:
    """Aggregate over every compared map of one measured storage format."""

    storage: str
    maps: int = 0
    unstable_maps: int = 0
    values: int = 0
    differing: int = 0
    affected_texels: int = 0
    max: float = 0.0
    sum_abs: float = 0.0

    @property
    def classification(self) -> str:
        return STABLE if self.differing == 0 else UNSTABLE

    @property
    def mean(self) -> float:
        return self.sum_abs / self.values if self.values else 0.0

    def add(self, comparison: MapComparison) -> None:
        d = comparison.difference
        self.maps += 1
        self.unstable_maps += not d.equal
        self.values += d.total
        self.differing += d.differing
        self.affected_texels += d.affected_texels
        self.max = max(self.max, d.max)
        self.sum_abs += d.mean * d.total


def channel_types(goldens: list[GoldenStability]) -> list[ChannelType]:
    types: dict[str, ChannelType] = {}
    for golden in goldens:
        for comparison in golden.maps:
            types.setdefault(comparison.storage, ChannelType(comparison.storage)).add(comparison)
    return [types[k] for k in sorted(types)]
