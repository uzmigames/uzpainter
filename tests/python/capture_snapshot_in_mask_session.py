"""Owner-machine capture and recording of one Painter session for item 2.15 of
`phase3.3_procedural-families` (decision 431: a composite over a seeded snapshot is compared with
a recording made in the Painter session that captured the snapshot).

Not collected by default (no `test_` prefix). Run it explicitly, with the Assets3D Painter lock and
the native lock held, no Painter running, and Legacy colour management:

    python -m pytest tests/python/capture_snapshot_in_mask_session.py -s

In one Painter session it captures every snapshot of `capture_grunge_snapshots.CAPTURES` into a new
destination project (store record `snapshot-in-mask-session-project`), then records the Tier 0
requests `snapshot-in-mask-session` (the composites) and `snapshot-in-mask-read` (every 16-bit code
on the same mask path) into the oracle inbox. The printed summary holds hashes and inbox run paths.
Admit each run with `python -m tools.parity.store record <manifest> --run <run>`.
"""

from __future__ import annotations

import pytest

from tests.python.capture_grunge_snapshots import capture_session
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.tier0_semantics.snapshot_in_mask import READ_NAME, SESSION_NAME


def test_capture_and_record_in_one_session(tmp_path_factory: pytest.TempPathFactory) -> None:
    requests = manifest_root(current_envelope()).parent / "requests" / "tier0" / "semantics"
    capture_session(
        tmp_path_factory,
        [requests / f"{SESSION_NAME}.json", requests / f"{READ_NAME}.json"],
        "snapshot-in-mask-session-project",
    )
