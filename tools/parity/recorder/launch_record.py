"""Start Painter, wait for its shelves, run `record` on one or more requests, stop Painter.

    python -m tools.parity.recorder.launch_record <request.json> [<request.json> ...]

`record` needs a running Painter with remote scripting and no project open. This helper starts one
under Legacy colour management (`OCIO` and `PAINTER_ACE_CONFIG` unset) with `PainterLauncher`,
waits for the shelf crawl (a fresh Painter refuses `resource://` starter assets until it ends),
records each request in that session and always stops Painter. Hold the Assets3D Painter lock
around it. First used for `tier0/semantics/snapshot-in-mask` (phase3.3_procedural-families 2.15).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.session import REMOTE_HOST, REMOTE_PORT, HttpTransport, PainterSession


def main(requests: Sequence[str]) -> int:
    if not requests:
        print(__doc__, file=sys.stderr)
        return 2
    launcher = PainterLauncher()
    launcher.start({"OCIO": None, "PAINTER_ACE_CONFIG": None})
    status = 0
    try:
        session = PainterSession(HttpTransport(REMOTE_HOST, REMOTE_PORT))
        session.connect()
        session.wait_catalog_ready(600)
        for request in requests:
            command = [sys.executable, "-m", "tools.parity.recorder", "record", request]
            status = max(status, subprocess.run(command, check=False, timeout=3000).returncode)
    finally:
        launcher.stop()
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
