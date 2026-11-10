"""Filter parameter survey for `phase3.2_proc-filter-families` item 2.1.

The item discovers each filter's parameter names, ranges and labels through the documented
`Property` API (`05-procedural-content.md` §3). This survey lists, through the documented Python
API only (`painter_filter_survey.py`), every starter-asset resource with the `FILTER` usage and
describes each one's source: every documented `Property` getter of every parameter (value, name,
short name, label, widget type, enum values, the `properties()` metadata), the preset list, image
inputs and outputs. No pixel is read and nothing is exported.

The operator starts Painter (Legacy environment, `--enable-remote-scripting`) under the shared
Painter lock with no project open. The session waits for the shelves to finish crawling, creates
a throwaway project on the authored plane, describes each filter in the content stack of a fill
it deletes again, and closes the project without saving.

The survey is private (it describes asset contents) and goes under the recorder's private work
root. `tools.parity.proc_filters.discovery` publishes from it only the public parameter semantics
(names, labels, widget types, ranges, enum labels and the default values), with the survey's
SHA-256 as provenance. `python -m tools.parity.recorder.filter_survey`
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.output import work_root
from tools.parity.recorder.session import REMOTE_HOST, REMOTE_PORT, HttpTransport, PainterSession
from tools.parity.schemas import REPO_ROOT

PLANE = REPO_ROOT / "parity/fixtures/meshes/plane.obj"
PAINTER_SURVEY = Path(__file__).with_name("painter_filter_survey.py")
# Documented search syntax (python-doc layerstack example: "s:starterassets u:substance ...").
QUERY = "s:starterassets u:filter"
SCHEMA = "uzpainter/filter-survey/1"


def extension_code(source: str) -> str:
    """Statements that execute `painter_filter_survey.py` into a copy of the recorder's
    namespace."""
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return (
        "import base64\n"
        "uzp_filter_survey = dict(uzp_recorder)\n"
        f"exec(base64.b64decode('{encoded}').decode('utf-8'), uzp_filter_survey)\n"
    )


def survey(session: PainterSession) -> dict[str, Any]:
    identity = session.connect()
    session.transport.run(extension_code(PAINTER_SURVEY.read_text(encoding="utf-8")))
    session.wait_catalog_ready()
    create = {"mesh": "plane", "normal_map_format": "OpenGL", "default_texture_resolution": 128}
    session.call("apply_step", step=1, call=ps.CREATE, args=create, resolved={"mesh": str(PLANE)})
    session.wait_ready()
    rows: list[dict[str, Any]] = []
    try:
        for item in session.call("filter_search", query=QUERY):
            row = session.call("filter_describe", url=item["url"])
            rows.append({**row, "gui_name": item["gui_name"]})
            session.wait_ready()
    finally:
        session.call("close_project")
    return {
        "schema": SCHEMA,
        "query": QUERY,
        "painter_build": identity.painter_build(),
        "rows": rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.filter_survey")
    parser.add_argument("--host", default=REMOTE_HOST)
    parser.add_argument("--port", type=int, default=REMOTE_PORT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    result = survey(PainterSession(HttpTransport(args.host, args.port)))
    target = work_root() / "filter-survey" / f"survey-{time.strftime('%Y%m%dT%H%M%S')}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(result, indent=1, sort_keys=True).encode("utf-8")
    target.write_bytes(data)
    names = sorted(row["gui_name"] for row in result["rows"])
    print(
        json.dumps(
            {
                "rows": len(result["rows"]),
                "gui_names": names,
                "private": str(target),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
