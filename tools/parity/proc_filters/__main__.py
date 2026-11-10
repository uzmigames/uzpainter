"""Write the filter goldens' content bitmaps and recording requests (`goldens.py`).

    python -m tools.parity.proc_filters fixtures
    python -m tools.parity.proc_filters write

No Painter is involved: the bitmaps go under `parity/fixtures/proc-filters/`, the requests under
the current envelope's `requests/phase3/proc-filters/`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tools.parity.proc_filters.goldens import goldens
from tools.parity.proc_filters.requests import write_fixtures, write_requests


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.proc_filters")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fixtures")
    commands.add_parser("write")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    paths = write_fixtures() if args.command == "fixtures" else write_requests(goldens())
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
