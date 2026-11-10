"""Decision 429 over a real capture: grunges and the three grunge-reading generators are served
only from project-private snapshots of the user's own Painter, byte-equal to its export for the
exact signature, and refused for any single-field change.

The project is the private derived artifact of `tests/python/capture_grunge_snapshots.py`:
UzPainter's own project on the authored plane at 256 px with four authored mesh maps, holding the
fixed grunges `rock` and `dirt-large`, the seeded `dirt-a` at seeds 1 and 2 (fill sources), and the
Dirt (at its default seed and at seed 2), Metal Edge Wear and Mask Builder - Legacy generators at
their defaults (in a mask, reading those mesh maps). It is resolved from the private oracle store by
hash and size, and its Painter exports are the capture receipts `UzPainter.exe assets snapshot`
left under `%LOCALAPPDATA%/UzPainter/snapshot-recordings/`, found by the SHA-256 of their
`capture.json`. Without either the tests skip as `oracle_unavailable`. Messages name hashes only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.procedural.test_proc_snapshot_served_capture import (
    export_float32,
    recordings_dir,
    served_rows,
)
from tests.python.test_assets3d_production_guard import painter as painter
from tools.parity.store.store import Status, locate, resolve_oracle

# The capture of 2026-11-10 (`tests/python/capture_grunge_snapshots.py`; Painter lock 2374/2375).
PROJECT_BLOB: dict[str, Any] = {
    "record_id": "grunge-snapshots-project",
    "sha256": "97a8d3358e417005c44b8491a2bce89370f8e562279575000916863da7aefeb8",
    "size_bytes": 1413120,
}
# Each capture's receipt (`capture.json`): SHA-256 and size.
RECEIPTS: dict[str, tuple[str, int]] = {
    "rock": ("744562600f6c345d1205b800af2ebc816a7f1ae8da83b76a47df56de92530d1c", 19098),
    "dirt-large": ("2f9fc160449b0b7cc0af7e58c9b76fe4d3f07d335ed3c24e48a076f3cce3b58c", 16450),
    "dirt-a-seed-1": ("5aed7061b9bb69ca89124c7c98e0b114a0be06127d8523a636780db1a44652dd", 18776),
    "dirt-a-seed-2": ("45d69257803aa34296a63e692d5e11f4002891c22cbddc117e82a859cf1e26a8", 18776),
    "dirt": ("565af07259517ee1b623ea59aa3d59dd366aeb984702877a1b1562e71f4b487d", 12924),
    "dirt-seed-2": ("ea5e561921d469e72cd815636df3aa5967af02833f99f9e5c2a20cc1016d1891", 12934),
    "metal-edge-wear": ("01a0d9121da79b388195b9283f7d0319cbd81fd686b49d5f1c890524746bb472", 13168),
    "mask-builder-legacy": (
        "927b6a167f5c6649d9d2287710f3d603fc3c56b5d5a76e34a84342565d219902",
        15646,
    ),
}
# Each capture's signature SHA-256, as `assets snapshot` reported it.
SIGNATURES: dict[str, str] = {
    "rock": "2c598e07d7d63accb37edf033bbb9a09eeae999276099c1e9c53a7b392092d12",
    "dirt-large": "7be9fb4de842be5d4ca675993809c4c7c57a6b07d814d4dc937b00003127f9d3",
    "dirt-a-seed-1": "a174cc25c82ae2baf3ca86592a925f71f00caa7719749b77b5316293ab995fd9",
    "dirt-a-seed-2": "40618519347a6155d34fbf8d72d7b1c54049c44ebf9178bb8dd8b95d4d73ec29",
    "dirt": "408670191a3836e77a195e613bae7de7a7a0095261e94fa2ab5d1e933c2f2315",
    "dirt-seed-2": "dfc42bb4c5b635aeb4250282e964134e6e92e11df902c310f5b42f97664226c4",
    "metal-edge-wear": "e22c52228ac19d3960332787054baef17a0575cdeff9b02dc1c8866271d24a6b",
    "mask-builder-legacy": "55e9c36177e65381114fcf532428692a130b90d7904a8998560f3c859393e494",
}
GENERATORS = {"dirt", "dirt-seed-2", "metal-edge-wear", "mask-builder-legacy"}


def find_receipts() -> dict[str, Path]:
    wanted = {value: name for name, value in RECEIPTS.items()}
    found: dict[str, Path] = {}
    root = recordings_dir()
    if root.is_dir():
        for receipt in sorted(root.glob("*/capture.json")):
            data = receipt.read_bytes()
            name = wanted.get((hashlib.sha256(data).hexdigest(), len(data)))
            if name is not None:
                found[name] = receipt.parent
    return found


def staged_project(tmp_path: Path) -> Path:
    resolved = resolve_oracle(locate(), PROJECT_BLOB)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    target = tmp_path / "grunges.uzp"
    target.write_bytes(resolved.path.read_bytes())
    data = target.read_bytes()
    if (hashlib.sha256(data).hexdigest(), len(data)) != (
        PROJECT_BLOB["sha256"],
        PROJECT_BLOB["size_bytes"],
    ):
        pytest.fail("the copied capture project differs from its store record", pytrace=False)
    return target


def receipts_or_skip() -> dict[str, Path]:
    receipts = find_receipts()
    missing = sorted(set(RECEIPTS) - set(receipts))
    if missing:
        pytest.skip(f"oracle_unavailable: capture receipts not on this machine: {missing}")
    return receipts


def test_every_snapshot_is_served_byte_equal_to_painter_export(
    procedural_tests: Path, tmp_path: Path
) -> None:
    """Each capture's snapshot is served (`Stored`, `Evaluate`) byte-equal to the float32 samples
    of its Painter export; both exports of each capture and both channel views are equal."""
    project = staged_project(tmp_path)
    receipts = receipts_or_skip()
    rows = served_rows(procedural_tests, project)
    assert len(rows) == len(RECEIPTS) and len({r["signature_sha256"] for r in rows}) == len(rows)
    for name, work in sorted(receipts.items()):
        receipt = json.loads((work / "capture.json").read_text(encoding="utf-8"))
        assert receipt["schema"] == "uzpainter/procedural-capture/3", name
        assert receipt["usage"] == ("GENERATOR" if name in GENERATORS else "PROCEDURAL"), name
        signature = receipt["signature"]
        resolution = int(signature["output"]["resolution"])
        assert resolution == 256, name
        assert (signature["inputs"] != {}) == (name in GENERATORS), name
        first = export_float32(work / "export1/user0.exr", 1)
        assert first == export_float32(work / "export2/user0.exr", 1), name
        for repeat in ("export1", "export2"):
            rgb = export_float32(work / repeat / "user1.exr", 3)
            assert all(
                rgb[i * 12 + 4 * c : i * 12 + 4 * c + 4] == first[i * 4 : i * 4 + 4]
                for i in range(0, resolution * resolution, 4093)
                for c in range(3)
            ), name
        served = [row for row in rows if row["signature"] == signature]
        assert len(served) == 1, f"{name}: {len(served)} entries hold its signature"
        row = served[0]
        expected = hashlib.sha256(first).hexdigest()
        assert (row["format"], row["resolution"], row["channels"]) == ("f32", resolution, 1), name
        assert row["stored_sha256"] == expected, f"{name}: Stored differs from the Painter export"
        assert row["evaluated"] == {
            "width": resolution,
            "height": resolution,
            "channels": 1,
            "sha256": expected,
        }, f"{name}: Evaluate differs from the Painter export"


def test_seed_changes_the_seeded_captures_and_not_the_fixed_ones(tmp_path: Path) -> None:
    """The seed is a signature field: dirt-a at seeds 1 and 2 are two snapshots with different
    texels, and so are the Dirt generator at its default seed and at seed 2."""
    receipts = receipts_or_skip()
    del tmp_path

    def texels(name: str) -> bytes:
        return export_float32(receipts[name] / "export1/user0.exr", 1)

    def signature(name: str) -> dict[str, Any]:
        receipt = json.loads((receipts[name] / "capture.json").read_text(encoding="utf-8"))
        value: dict[str, Any] = receipt["signature"]
        return value

    for a, b in (("dirt-a-seed-1", "dirt-a-seed-2"), ("dirt", "dirt-seed-2")):
        assert signature(a)["seed"] != signature(b)["seed"], (a, b)
        assert texels(a) != texels(b), f"{a} and {b} have equal texels"
    assert "$randomseed" not in signature("dirt-large")["params"]


def own_rows(exe: Path, project: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    proc = subprocess.run(
        [str(exe), "snapshot-own-request", str(project)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0 and "FAIL " not in proc.stdout, proc.stdout + proc.stderr
    rows = [line.split(" ", 1) for line in proc.stdout.splitlines()]
    own = [json.loads(body) for kind, body in rows if kind == "OWN"]
    changes = [json.loads(body) for kind, body in rows if kind == "MISMATCH"]
    return own, changes


def test_the_project_asks_for_each_signature_and_every_single_change_is_refused(
    procedural_tests: Path, tmp_path: Path
) -> None:
    """The project's own texture set asks for exactly each stored signature, which is served; a
    changed seed, parameter, resolution, mesh or mesh map is `unavailable`, naming its field."""
    project = staged_project(tmp_path)
    own, changes = own_rows(procedural_tests, project)
    assert len(own) == len(RECEIPTS) and all(row["served"] for row in own), own
    assert sum(row["generator"] for row in own) == len(GENERATORS)
    expected_fields = {
        "seed": {"params.$randomseed", "seed"},
        "mesh": {"settings.mesh.sha256"},
    }
    seen: dict[str, set[str]] = {}
    for change in changes:
        kind = change["change"]
        assert "refused_before_request" not in change, change
        assert change["served"] is False and change["stored"] is False, change
        assert change["reason"] == "no snapshot with this signature", change
        field = change["field"]
        if kind.startswith("parameter "):
            assert field == "params." + kind.removeprefix("parameter "), change
        elif kind.startswith("resolution "):
            assert field == "output.resolution" or (
                field.startswith("inputs.") and field.endswith(".resolution")
            ), change
        elif kind.startswith("mesh map "):
            assert field == f"inputs.{kind.removeprefix('mesh map ')}.sha256", change
        else:
            assert field in expected_fields[kind], change
        seen.setdefault(change["signature_sha256"], set()).add(kind.split(" ")[0])
    for row in own:
        kinds = seen.get(row["signature_sha256"], set())
        assert {"seed", "resolution", "mesh"} <= kinds, (row["signature_sha256"], kinds)
        if row["generator"]:
            assert "mesh" in kinds and any(c["change"].startswith("mesh map ") for c in changes)


def test_a_grunge_snapshot_binds_and_serves_as_a_fill_source(painter: Path, tmp_path: Path) -> None:  # noqa: F811
    """Each fill-source capture binds to a User L32F fill of the capture project through
    `assets bind-snapshot` and is served by the provider after save and reopen."""
    project = staged_project(tmp_path)
    receipts = receipts_or_skip()
    script = tmp_path / "fill.py"
    out = tmp_path / "fill.json"
    script.write_text(
        "import json\nfrom substance_painter import layerstack as ls, project, textureset as ts\n"
        f"project.open({project.as_posix()!r})\n"
        "stack = ts.get_active_stack()\n"
        "stack.add_channel(ts.ChannelType.User0, ts.ChannelFormat.L32F)\n"
        "node = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))\n"
        "node.active_channels = {ts.ChannelType.User0}\n"
        "uid = node.uid()\nproject.save()\nproject.close()\n"
        f"open({out.as_posix()!r}, 'w').write(json.dumps(uid))\n",
        encoding="utf-8",
    )
    created = subprocess.run(
        [str(painter), "run", str(script)], capture_output=True, text=True, timeout=300, check=False
    )
    assert created.returncode == 0, created.stdout + created.stderr
    node = json.loads(out.read_text(encoding="utf-8"))
    for name in sorted(receipts):
        if name in GENERATORS:
            continue
        signature = SIGNATURES[name]
        request = tmp_path / "bind.json"
        request.write_text(
            json.dumps(
                {
                    "signature_sha256": signature,
                    "node": node,
                    "channel": "User0",
                    "resolution_override": None,
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(painter), "assets", "bind-snapshot", str(project), "--request", str(request)],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        line = next(x for x in result.stdout.splitlines() if x.startswith("UZP_JSON:"))
        report = json.loads(line.removeprefix("UZP_JSON:"))
        assert result.returncode == 0 and report["status"] == "ok", (name, report)
        assert report["verified_after_reopen"] is True, name
