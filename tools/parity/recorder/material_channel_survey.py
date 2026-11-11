"""Material channel survey for `phase3.3_procedural-families` item 2.16 (decision 432 §3).

A diagnostic survey, not a golden: it separates what the item's fits need before any request is
authored (`painter_material_channel_survey.py`, documented Python API only):

- how `SourceSubstance.get_parameters()` returns the colour parameters of felt and leather grain,
  and what `set_parameters` accepts and reads back for them (the typed codec of step 1);
- in one Painter instance, on the authored plane at 128 px, every channel export of each
  material's default material fill, of that fill under each UV scale mode (Factors 2,
  MaterialPhysicalSize, CustomPhysicalSize), and of the paired split User0 L32F / User1 RGB32F
  source at each output (steps 3 and 4).

Under the shared Painter lock, Painter runs in its Legacy environment with
`--enable-remote-scripting` and no project open (`--launch` starts and finally stops it without
`OCIO` and `PAINTER_ACE_CONFIG`). The survey and its exports are private and go under the
recorder's private work root, `material-channel-survey/<timestamp>/`.

    python -m tools.parity.recorder.material_channel_survey --launch
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.parity.recorder import vocabulary as ps
from tools.parity.recorder.launcher import PainterLauncher
from tools.parity.recorder.material_survey import MATERIAL_URLS, PLANE, extension_code
from tools.parity.recorder.output import work_root
from tools.parity.recorder.session import REMOTE_HOST, REMOTE_PORT, HttpTransport, PainterSession

PAINTER_SURVEY = Path(__file__).with_name("painter_material_channel_survey.py")
SCHEMA = "uzpainter/material-channel-survey/1"
SCALES = [
    ["factors-2", "Factors", [2.0, 2.0]],
    ["material-1", "MaterialPhysicalSize", [1.0, 1.0]],
    ["custom-1", "CustomPhysicalSize", [1.0, 1.0]],
    ["custom-100", "CustomPhysicalSize", [100.0, 100.0]],
]


def survey(session: PainterSession, directory: Path) -> dict[str, Any]:
    identity = session.connect()
    source = PAINTER_SURVEY.read_text(encoding="utf-8")
    session.transport.run(extension_code(source).replace("uzp_material_survey", "uzp_mcs"))
    session.wait_catalog_ready(600)
    result: dict[str, Any] = {"schema": SCHEMA, "painter_build": identity.painter_build()}
    for family, url in MATERIAL_URLS.items():
        create = {"mesh": "plane", "normal_map_format": "OpenGL", "default_texture_resolution": 128}
        session.call(
            "apply_step", step=1, call=ps.CREATE, args=create, resolved={"mesh": str(PLANE)}
        )
        session.wait_ready()
        try:
            colour = session.call("mcs_colour", url=url)
            session.wait_ready()
            exports = session.call(
                "mcs_exports",
                url=url,
                directory=directory.as_posix(),
                prefix=family,
                scales=SCALES,
            )
            session.wait_ready()
        finally:
            session.call("close_project")
        result[family] = {"colour": colour, "exports": exports}
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.material_channel_survey")
    parser.add_argument("--host", default=REMOTE_HOST)
    parser.add_argument("--port", type=int, default=REMOTE_PORT)
    parser.add_argument("--launch", action="store_true", help="start and stop Painter (Legacy)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    directory = work_root() / "material-channel-survey" / time.strftime("%Y%m%dT%H%M%S")
    directory.mkdir(parents=True)
    session = PainterSession(HttpTransport(args.host, args.port))
    launcher = PainterLauncher() if args.launch else None
    if launcher is not None:
        launcher.start({"OCIO": None, "PAINTER_ACE_CONFIG": None})
    try:
        result = survey(session, directory)
    finally:
        if launcher is not None:
            launcher.stop(session)
    data = json.dumps(result, indent=1, sort_keys=True).encode("utf-8")
    (directory / "survey.json").write_bytes(data)
    print(json.dumps({"private": str(directory), "sha256": hashlib.sha256(data).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
