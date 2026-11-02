"""Write the Tier 2b bake fixtures and their recording requests (decision 384).

    python -m tools.parity.tier2b_bakes write

No Painter is involved: the fixtures are generated from `tests/bake/bake_fixtures.h`'s geometry and
the requests go under the current envelope's `requests/tier2b/bakes/`, where
`python -m tools.parity.recorder.batch plan` schedules them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tools.parity.tier2b_bakes.fixtures import write_fixtures
from tools.parity.tier2b_bakes.requests import write_requests


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.tier2b_bakes")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("write")
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    for path in [*write_fixtures(), *write_requests()]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
