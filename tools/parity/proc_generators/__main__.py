"""Write the generator goldens' recording requests (`goldens.py`).

    python -m tools.parity.proc_generators write

No Painter is involved: the requests go under the current envelope's
`requests/phase3/proc-generators/`, where `python -m tools.parity.recorder.batch plan` schedules
them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tools.parity.proc_generators.goldens import goldens
from tools.parity.proc_generators.requests import write_requests


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.proc_generators")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("write")
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    for path in write_requests(goldens()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
