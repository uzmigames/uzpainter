"""Serialize native edit+build cycles between agents sharing one checkout (decision 041).

python -m tools.native_lock acquire --owner padding [--wait 540]
python -m tools.native_lock release --owner padding
python -m tools.native_lock status

Hold the lock from the first C++/header edit until the build and its tests end.
A lock older than --stale seconds (default 5400) is taken over and reported.
Exit 0 on success, 1 when the lock stays held by another owner after --wait.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

LOCK = Path(__file__).resolve().parents[1] / "tmp" / "scratch" / "native-build.lock"


def read() -> dict[str, Any] | None:
    try:
        record = json.loads(LOCK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def acquire(owner: str, wait: float, stale: float) -> int:
    deadline = time.monotonic() + wait
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = read()
            if held is not None and held.get("owner") == owner:
                print(json.dumps({"acquired": True, "reentrant": True, **held}))
                return 0
            since = float(held.get("since", 0)) if held else 0.0
            if time.time() - since > stale:
                print(json.dumps({"stale_takeover": held}), file=sys.stderr)
                LOCK.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                print(json.dumps({"acquired": False, "held_by": held}))
                return 1
            time.sleep(5)
            continue
        record = {"owner": owner, "since": time.time()}
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        print(json.dumps({"acquired": True, **record}))
        return 0


def release(owner: str) -> int:
    held = read()
    if held is None:
        print(json.dumps({"released": False, "reason": "not held"}))
        return 0
    if held.get("owner") != owner:
        print(json.dumps({"released": False, "held_by": held}))
        return 1
    LOCK.unlink(missing_ok=True)
    print(json.dumps({"released": True, "owner": owner}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    take = sub.add_parser("acquire")
    take.add_argument("--owner", required=True)
    take.add_argument("--wait", type=float, default=540.0)
    take.add_argument("--stale", type=float, default=5400.0)
    drop = sub.add_parser("release")
    drop.add_argument("--owner", required=True)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "acquire":
        return acquire(args.owner, args.wait, args.stale)
    if args.command == "release":
        return release(args.owner)
    print(json.dumps({"held_by": read()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
