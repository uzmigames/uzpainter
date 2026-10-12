"""The wand v1 fixture runner of the Assets3D adapter (task phase1.23 item 2.5; decision 113).

It runs the three Assets3D pipeline scripts byte-unchanged through the adapter
(`adapters/assets3d/layer_stack.py`) on the wand v1 inputs. The pins are those of the committed
R9 request manifest (`phase1/tier1/wand-v1`, decision 099), loaded by the recorder's own loader:
every input is hash-checked under the Assets3D root before anything runs, and each call passes
`--pin` for the layer-stack script and the script it runs, so the adapter refuses a changed
script before anything reaches UzPainter.

Nothing is written under the Assets3D root. The inputs are staged into `work/assets`, a mirror of
the Assets3D tree (`stage_inputs`). The two Painter-side scripts read their arguments from a
hard-coded Assets3D path; the runner's namespace `open` maps exactly that path to a copy in which
every absolute path under the Assets3D root names the same relative path under the mirror
(decision 099 adaptation (a)), so `dst` and `out` land in the mirror at their production-relative
paths. The session file lives in the work directory too.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapters.assets3d.runner import under_root
from tools.parity.recorder.script_run import ScriptJob, load_script_job, stage_inputs

REPO_ROOT = Path(__file__).resolve().parents[3]
ASSETS3D = Path(os.environ.get("UZP_TEST_ASSETS3D", r"E:\UzmiGames\Assets3D"))
REQUEST = (
    REPO_ROOT / "parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase1/tier1/wand-v1.json"
)
ENTRY = REPO_ROOT / "adapters" / "assets3d" / "layer_stack.py"


@dataclass(frozen=True)
class Call:
    """One adapter call: exit status, standard output and error."""

    status: int
    stdout: str
    stderr: str

    def document(self, marker: str | None = None) -> Any:
        """The JSON the script printed: after `marker` (`SYNC_DONE`), else all of stdout."""
        text = self.stdout
        if marker is not None:
            line = next(x for x in text.splitlines() if x.startswith(marker + " "))
            text = line[len(marker) + 1 :]
        return json.loads(text)


def repoint(value: Any, root: Path) -> Any:
    """`value` with an absolute path under the Assets3D root moved under `root`."""
    if isinstance(value, str):
        relative = under_root(value, str(ASSETS3D)) if os.path.isabs(value) else None
        if relative is not None:
            return str(root.joinpath(*relative.split("/")))
    return value


class Wand:
    """The wand v1 inputs staged in `work`, and the adapter calls over them."""

    def __init__(self, painter: Path, work: Path, manifest: Path = REQUEST) -> None:
        """`manifest`: the R9 request, or the golden admitted from it (the Tier 1 runner)."""
        self.job: ScriptJob = load_script_job(manifest, ASSETS3D)
        self.work = work
        self.root = work / "assets"
        self.staged = stage_inputs(self.job, self.root)
        self.session = work / "session.json"
        self.state = work / "sync-state.json"
        redirects = {}
        for step in (self.job.create, self.job.export):
            assert step.arguments is not None and step.hard_coded_args is not None
            copy = work / "arguments" / Path(step.hard_coded_args).name
            copy.parent.mkdir(parents=True, exist_ok=True)
            arguments = {key: repoint(v, self.root) for key, v in step.arguments.items()}
            copy.write_text(json.dumps(arguments), encoding="utf-8")
            redirects[step.hard_coded_args] = str(copy)
        self.redirects = redirects
        self.env = {
            **os.environ,
            "UZPAINTER_EXE": str(painter),
            "UZP_ASSETS3D_SESSION": str(self.session),
            "UZP_ASSETS3D_ROOT": str(self.root),
            "UZP_ASSETS3D_OPEN_REDIRECTS": json.dumps(redirects),
            "PYTHONIOENCODING": "utf-8",  # the test decodes the scripts' output as UTF-8
        }

    def script(self, input_id: str) -> Path:
        """The pinned script as the pipeline runs it: its real path in Assets3D."""
        return self.job.inputs[input_id].file

    def pins(self) -> list[str]:
        out = []
        for input_id in ("painter-layer-stack-py", "painter-create-py", "painter-export-py"):
            item = self.job.inputs[input_id]
            out += ["--pin", f"{item.file}={item.sha256}"]
        return out

    def call(self, *arguments: str, pins: list[str] | None = None) -> Call:
        """`python layer_stack.py --pin ... <painter_layer_stack.py> <arguments>`."""
        process = subprocess.run(
            [
                sys.executable,
                str(ENTRY),
                *(self.pins() if pins is None else pins),
                str(self.script("painter-layer-stack-py")),
                *arguments,
            ],
            cwd=self.work,
            env=self.env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        return Call(process.returncode, process.stdout, process.stderr)

    def create(self) -> Call:
        return self.call("run", str(self.script("painter-create-py")))

    def sync(self, *extra: str) -> Call:
        stack = self.staged["wand-stack"]
        masks = self.staged[self.job.sync.args["masks"][0]].parent
        return self.call(
            "sync", "--stack", str(stack), "--masks", str(masks), "--state", str(self.state), *extra
        )

    def export(self) -> Call:
        return self.call("run", str(self.script("painter-export-py")))

    def run_file(self, path: Path) -> Call:
        """A test's own Painter-side file through the script's `run` command."""
        return self.call("run", str(path))

    def probe(self, name: str, body: str) -> Any:
        """Runs `body` (it assigns `result`) through `run`; its result."""
        path = self.work / f"{name}.py"
        path.write_text(body, encoding="utf-8")
        call = self.run_file(path)
        assert call.status == 0, call.stdout + call.stderr
        return call.document()

    def argument(self, step: str, key: str) -> Path:
        """A repointed argument (`dst` of create, `out` of export)."""
        hard_coded = getattr(self.job, step).hard_coded_args
        copy = json.loads(Path(self.redirects[hard_coded]).read_text(encoding="utf-8"))
        return Path(copy[key])
