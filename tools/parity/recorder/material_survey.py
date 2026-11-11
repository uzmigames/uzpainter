"""Material survey for `phase3.2_proc-material-families` item 2.1.

The task's four materials are named by the recipes (`docs/analysis/assets3d-pipeline/
04-painting-recipes-and-materials.md` §4): the starter materials `fabric_felt` and
`leather_grain` (the hat recipe names their versioned URLs), and burlap and leather pattern,
which the recipes reach through the starter smart materials Fabric Burlap and Leather Damaged.
This survey, through the documented Python API only (`painter_material_survey.py`):

- describes each listed material as a fill's material source: source mode, active channels,
  every documented `Property` getter of every parameter, presets, image inputs and outputs,
  `output_mapping` and `mask_output`;
- finds each listed smart material by GUI name (`s:starterassets u:smartmaterial`), inserts it
  and walks its layers with their sources, so the sources behind burlap and leather pattern are
  named by their versioned URLs.

No pixel is read and nothing is exported. Under the shared Painter lock, Painter runs in its
Legacy environment with `--enable-remote-scripting` and no project open (`--launch` starts and
finally stops it without `OCIO` and `PAINTER_ACE_CONFIG`); the session
waits for the shelves to finish crawling, creates a throwaway project on the authored plane and
closes it without saving.

The survey is private (it describes asset contents and smart-material structures) and goes under
the recorder's private work root. `tools.parity.proc_materials.discovery` publishes from it only
the public parameter semantics. `python -m tools.parity.recorder.material_survey`
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
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.output import work_root
from tools.parity.recorder.session import REMOTE_HOST, REMOTE_PORT, HttpTransport, PainterSession
from tools.parity.schemas import REPO_ROOT

PLANE = REPO_ROOT / "parity/fixtures/meshes/plane.obj"
PAINTER_SURVEY = Path(__file__).with_name("painter_material_survey.py")
SCHEMA = "uzpainter/material-survey/1"
# The versioned URLs the hat recipe records (Assets3D `10-Chapeu/report.json`).
MATERIAL_URLS: dict[str, str] = {
    "felt": "resource://starter_assets/fabric_felt/fabric_felt"
    "?version=cf02206c2e551010986f8e41bdec60878ad843eb.sbsar",
    "leather-grain": "resource://starter_assets/leather_grain/leather_grain"
    "?version=540286d1112f9b9f88e09eede773eed3931d38a1.sbsar",
}
# Documented search syntax (python-doc layerstack example: "s:starterassets u:substance ...").
SMART_QUERY = "s:starterassets u:smartmaterial"
# The smart materials the recipes name (Assets3D `25-Faixa-Cintura`, `22-Bracal-Direito`).
SMART_MATERIALS: dict[str, str] = {"burlap": "Fabric Burlap", "leather-pattern": "Leather Damaged"}


def extension_code(source: str) -> str:
    """Statements that execute `painter_material_survey.py` into a copy of the recorder's
    namespace."""
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return (
        "import base64\n"
        "uzp_material_survey = dict(uzp_recorder)\n"
        f"exec(base64.b64decode('{encoded}').decode('utf-8'), uzp_material_survey)\n"
    )


def survey(session: PainterSession) -> dict[str, Any]:
    identity = session.connect()
    session.transport.run(extension_code(PAINTER_SURVEY.read_text(encoding="utf-8")))
    session.wait_catalog_ready(600)
    create = {"mesh": "plane", "normal_map_format": "OpenGL", "default_texture_resolution": 128}
    session.call("apply_step", step=1, call=ps.CREATE, args=create, resolved={"mesh": str(PLANE)})
    session.wait_ready()
    materials: dict[str, Any] = {}
    smart: dict[str, Any] = {}
    try:
        for family, url in MATERIAL_URLS.items():
            materials[family] = session.call("material_describe", url=url)
            session.wait_ready()
        found = session.call("smart_material_search", query=SMART_QUERY)
        for family, name in SMART_MATERIALS.items():
            matches = [item for item in found if item["gui_name"] == name]
            if not matches:  # the GUI name alone, still filtered by the SMART_MATERIAL usage
                named = session.call("smart_material_search", query=name)
                matches = [item for item in named if item["gui_name"] == name]
            entry: dict[str, Any] = {"gui_name": name, "matches": [m["url"] for m in matches]}
            if len(matches) == 1:
                entry["described"] = session.call("smart_material_describe", url=matches[0]["url"])
                session.wait_ready()
            smart[family] = entry
    finally:
        session.call("close_project")
    return {
        "schema": SCHEMA,
        "painter_build": identity.painter_build(),
        "materials": materials,
        "smart_materials": smart,
    }


def latest() -> Path:
    """The newest private survey."""
    found = sorted((work_root() / "material-survey").glob("survey-*.json"))
    if not found:
        raise FileNotFoundError("no material survey under the private work root")
    return found[-1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.material_survey")
    parser.add_argument("--host", default=REMOTE_HOST)
    parser.add_argument("--port", type=int, default=REMOTE_PORT)
    parser.add_argument("--launch", action="store_true", help="start and stop Painter (Legacy)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    session = PainterSession(HttpTransport(args.host, args.port))
    launcher = PainterLauncher() if args.launch else None
    if launcher is not None:
        launcher.start({"OCIO": None, "PAINTER_ACE_CONFIG": None})
    try:
        result = survey(session)
    finally:
        if launcher is not None:
            launcher.stop(session)
    target = work_root() / "material-survey" / f"survey-{time.strftime('%Y%m%dT%H%M%S')}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(result, indent=1, sort_keys=True).encode("utf-8")
    target.write_bytes(data)
    print(
        json.dumps(
            {
                "materials": sorted(result["materials"]),
                "smart_materials": {
                    family: len(entry["matches"])
                    for family, entry in result["smart_materials"].items()
                },
                "private": str(target),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
