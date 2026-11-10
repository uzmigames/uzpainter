"""Write the grunge goldens' recording requests (`goldens.py`).

    python -m tools.parity.proc_grunges write

No Painter is involved: the requests go under the current envelope's
`requests/phase3/proc-grunges/`, where `python -m tools.parity.recorder.batch plan` schedules
them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tools.parity.proc_grunges.goldens import goldens
from tools.parity.proc_grunges.requests import write_requests


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.proc_grunges")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("write")
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    for path in write_requests(goldens()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
