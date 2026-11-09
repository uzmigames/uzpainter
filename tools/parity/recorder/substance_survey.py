"""Starter-asset survey for `phase3.2_source-substance-presets-inputs` (decision 412).

Every recorded SourceSubstance so far has zero presets, zero image inputs and one output. This
survey lists, through the documented Python API only (`painter_survey.py`), which starter-asset
Substance resources have presets, image inputs and several outputs, so that the Tier 0 probe can
name one by its exact versioned URL. It reads counts only: no parameter value, preset content
or pixel is read, and nothing is exported.

The operator starts Painter (Legacy environment, `--enable-remote-scripting`) under the shared
Painter lock with no project open. The session checks the build against the envelope, waits for
the shelves to finish crawling, creates a throwaway project on the authored plane, surveys each
resource on a fill it deletes again, and closes the project without saving.

The result is private (it describes asset contents) and goes under the recorder's private work
root. `python -m tools.parity.recorder.substance_survey`
"""

from __future__ import annotations

import argparse
import base64
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
PAINTER_SURVEY = Path(__file__).with_name("painter_survey.py")
# Documented search syntax (python-doc layerstack example: "s:starterassets u:substance ...").
# Materials bind as a fill's material source, procedurals as its BaseColor source.
QUERIES = (("s:starterassets u:substance", True), ("s:starterassets u:procedural", False))


def extension_code(source: str) -> str:
    """Statements that execute `painter_survey.py` into a copy of the recorder's namespace."""
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return (
        "import base64\n"
        "uzp_survey = dict(uzp_recorder)\n"
        f"exec(base64.b64decode('{encoded}').decode('utf-8'), uzp_survey)\n"
    )


def survey(session: PainterSession) -> dict[str, Any]:
    session.connect()
    session.transport.run(extension_code(PAINTER_SURVEY.read_text(encoding="utf-8")))
    session.wait_catalog_ready()
    create = {"mesh": "plane", "normal_map_format": "OpenGL", "default_texture_resolution": 128}
    session.call("apply_step", step=1, call=ps.CREATE, args=create, resolved={"mesh": str(PLANE)})
    session.wait_ready()
    rows: list[dict[str, Any]] = []
    try:
        for query, material in QUERIES:
            for item in session.call("survey_search", query=query):
                row = session.call("survey_one", url=item["url"], material=material)
                rows.append({**row, "gui_name": item["gui_name"], "query": query})
                session.wait_ready()
    finally:
        session.call("close_project")
    return {"schema": "uzpainter/substance-survey/1", "rows": rows}


def count(row: dict[str, Any], key: str) -> int:
    value = row.get(key, {}).get("value")
    return value if isinstance(value, int) else 0


def qualifies(row: dict[str, Any]) -> bool:
    """Presets, image inputs and several outputs (task item 2.2)."""
    return (
        count(row, "presets") > 0
        and count(row, "image_inputs") > 0
        and (count(row, "image_outputs") > 1)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.substance_survey")
    parser.add_argument("--host", default=REMOTE_HOST)
    parser.add_argument("--port", type=int, default=REMOTE_PORT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    result = survey(PainterSession(HttpTransport(args.host, args.port)))
    target = work_root() / "substance-survey" / f"survey-{time.strftime('%Y%m%dT%H%M%S')}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    chosen = [row["url"] for row in result["rows"] if qualifies(row)]
    print(json.dumps({"rows": len(result["rows"]), "qualifying": chosen, "private": str(target)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
