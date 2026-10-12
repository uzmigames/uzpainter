"""The adapter's runner: executed by `UzPainter.exe run` for every Assets3D call (`MIGRATIONS.md`).

    UzPainter.exe run runner.py -- <code file> <session file> <report file>

It is the `__main__` script of the run; the Assets3D code it executes is given as a file, and its
`result` becomes this script's `result`, so the host's `UZP_JSON:` report carries it. In order:

1. **Session.** Painter keeps one session across `execute_python` calls; `run` is one process
   per call and closes the project left open with the native close, which keeps every committed
   revision (decisions 105, 111). The session file names what the previous call left open (the
   project file, the facade's project index behind `resource://project<N>` contexts, its
   `needs_saving()` and the active stack): the project is reopened through the facade and those
   values restored before the code runs. A carried project that no longer opens fails the call
   before the code runs and empties the session.
2. **Shim.** `_substance_painter.display.save_viewport(path, w, h, _)`, the pipeline's one
   private Painter call, is installed into `sys.modules` for this run only; it calls
   `uzpainter.render.capture(mode="painter_viewport")` and names that mode when it is missing.
3. **Code.** Executed as the community bridge executes it: in a fresh namespace `{"params": {}}`,
   `result` read back and normalised with `json.dumps(..., default=str)`. A namespace `open` maps
   the fixed-path redirects of `UZP_ASSETS3D_OPEN_REDIRECTS` (the wand fixture's repointed
   arguments files, decision 099 adaptation (a)); no redirect is set outside the fixture.
4. **Exports.** Each fixed-name copy the run's exports wrote (Painter's flat layout, the route
   Assets3D's consumers read) is verified against its generation's receipt before the run
   reports success, and each receipt's `manifest_files` are rebased under the Assets3D root
   (`UZP_ASSETS3D_ROOT`, decision 097).
5. **Report.** The session left open, the script's result and the exports go to the report file
   (also on failure). A project left open untitled cannot outlive the process: the call fails.

The pure functions below (`rebase_manifest`, `verify_fixed_names`) take no `uzpainter` import, so
host-side tests import this module directly; `main` runs only inside UzPainter.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import linecache
import os
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

CODE_FILE_NAME = "<uzpainter-assets3d-adapter>"
JOURNAL = "fixed-names.journal.json"
REDIRECTS_ENV = "UZP_ASSETS3D_OPEN_REDIRECTS"
ROOT_ENV = "UZP_ASSETS3D_ROOT"
VIEWPORT_OWNER = "phase2.2_preview-capture"


class AdapterSessionError(RuntimeError):
    """The session Painter keeps between calls cannot be carried to or from this run."""


class AdapterExportError(RuntimeError):
    """An export's fixed-name copy does not verify against its receipt."""


# ── Pure helpers (host-side tests import these) ─────────────────────────────────────────────────


def same_path(first: str, second: str) -> bool:
    return os.path.normcase(os.path.normpath(first)) == os.path.normcase(os.path.normpath(second))


def redirected_open(redirects: dict[str, str]) -> Callable[..., Any]:
    """The builtin `open`, except that each path of `redirects` opens its copy instead."""

    def open_file(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, os.PathLike)):
            for path, copy in redirects.items():
                if same_path(os.fspath(file), path):
                    file = copy
                    break
        return builtins.open(file, *args, **kwargs)

    return open_file


def under_root(path: str, root: str) -> str | None:
    """`path` relative to `root` with `/` (Assets3D manifest `$defs/path`), or None outside it."""
    full = Path(os.path.abspath(path))
    base = Path(os.path.abspath(root))
    parts, base_parts = full.parts, base.parts
    if len(parts) <= len(base_parts):
        return None
    if [os.path.normcase(p) for p in parts[: len(base_parts)]] != [
        os.path.normcase(p) for p in base_parts
    ]:
        return None
    return "/".join(parts[len(base_parts) :])


def rebase_manifest(
    receipt: dict[str, Any],
    generation_dir: str,
    project_path: str | None,
    mesh_path: str | None,
    root: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """The receipt's `manifest_files` with paths relative to the Assets3D root, beside its
    `manifest_export` block; `(None, reason)` when a path cannot be named under the root.

    The receipt's paths are relative to the generation (decision 097), except `project` and
    `mesh`, which name the project file and the imported mesh by file name only."""
    if receipt.get("manifest_export") is None:
        return None, "the export wrote no file, so it has no Assets3D export block"
    if root is None:
        return None, f"no Assets3D root is known ({ROOT_ENV} is not set)"
    files: dict[str, Any] = {}
    for key, entry in receipt["manifest_files"].items():
        if key == "project":
            source = project_path
        elif key == "mesh":
            source = mesh_path
        else:
            source = os.path.join(generation_dir, *str(entry["path"]).split("/"))
        if source is None:
            return None, f"manifest file `{key}` has no path on disk"
        relative = under_root(source, root)
        if relative is None:
            return None, f"manifest file `{key}` ({source}) lies outside the Assets3D root {root}"
        files[key] = {**entry, "path": relative}
    return {"manifest_files": files, "manifest_export": receipt["manifest_export"]}, None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with builtins.open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_fixed_names(directory: str, generation: str, receipt: dict[str, Any]) -> list[str]:
    """Problems of the fixed-name copy in `directory` against the receipt of `generation` (the
    copy's journal, decision 097): empty when the consumers may read it."""
    folder = Path(directory)
    journal_file = folder / JOURNAL
    try:
        journal = json.loads(journal_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"{journal_file}: {error}"]
    problems = []
    if journal.get("generation") != generation or receipt.get("generation") != generation:
        problems.append(
            f"{journal_file} names generation {journal.get('generation')}, the export "
            f"published {generation} (receipt {receipt.get('generation')})"
        )
    listed = sorted(str(f["path"]) for f in receipt["files"])
    if sorted(journal.get("files", [])) != listed:
        problems.append(f"{journal_file} lists other files than the receipt")
    if sorted(journal.get("copied", [])) != listed:
        problems.append(f"{journal_file}: the copy is incomplete")
    if journal.get("obsolete"):
        problems.append(f"{journal_file}: obsolete names were not removed")
    for entry in receipt["files"]:
        path = folder / str(entry["path"])
        if not path.is_file():
            problems.append(f"{path} is missing")
        elif path.stat().st_size != entry["bytes"] or sha256_of(path) != entry["sha256"]:
            problems.append(f"{path} differs from its receipt")
    return problems


def write_atomically(path: Path, text: str) -> None:
    """`text` into `path` through a staging file and a rename: a reader sees one or the other."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".staging")
    staging.write_text(text, encoding="utf-8")
    os.replace(staging, path)


def normalised(value: Any) -> Any:
    """`result` as the community bridge returns it: `json.dumps(..., default=str)`."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


# ── Inside UzPainter ────────────────────────────────────────────────────────────────────────────


def install_shim(uzpainter: Any) -> None:
    """`_substance_painter.display.save_viewport` for this run only (`MIGRATIONS.md` M3)."""

    def save_viewport(path: str, width: int, height: int, *_: Any) -> None:
        """The painting view as an image (Painter's private call): UzPainter's current state."""
        try:
            uzpainter.render.capture(mode="painter_viewport", path=path, width=width, height=height)
        except uzpainter.NotYetSupported as error:
            raise uzpainter.NotYetSupported(
                "_substance_painter.display.save_viewport needs the capture mode "
                f"painter_viewport of uzpainter.render.capture, which {VIEWPORT_OWNER} "
                f"delivers ({error})"
            ) from error

    package = types.ModuleType("_substance_painter", "UzmiGames shim of the Assets3D adapter.")
    display = types.ModuleType("_substance_painter.display", "UzmiGames shim: save_viewport.")
    display.save_viewport = save_viewport  # type: ignore[attr-defined]
    package.display = display  # type: ignore[attr-defined]
    sys.modules["_substance_painter"] = package
    sys.modules["_substance_painter.display"] = display


def restore_session(session_file: Path) -> dict[str, Any] | None:
    """Reopen what the previous call left open; the session restored, or None."""
    try:
        carried = json.loads(session_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not carried:
        return None
    import substance_painter.project as project
    import substance_painter.textureset as textureset
    import uzpainter
    from uzpainter_facade.state import SESSION

    path = carried["project"]
    try:
        SESSION.projects = int(carried["project_index"]) - 1  # open() counts this project
        project.open(path)
    except Exception as error:
        write_atomically(session_file, "{}")
        raise AdapterSessionError(
            f"the project the previous call left open ({path}) does not open: "
            f"{type(error).__name__}: {error}; the session was emptied"
        ) from error
    native = bool(uzpainter.project.needs_saving())
    if carried["needs_saving"] and not native:
        SESSION.dirty = True
    elif not carried["needs_saving"] and native:
        SESSION.clean_revision = uzpainter.project.revision()
    texture_set, stack = carried["active_stack"]
    textureset.set_active_stack(textureset.Stack.from_name(texture_set, stack))
    return dict(carried)


def session_left_open() -> dict[str, Any] | None:
    """The session this run leaves open (None when no project is open)."""
    import substance_painter.project as project
    import substance_painter.textureset as textureset
    from uzpainter_facade.state import SESSION

    if not project.is_open():
        return None
    active = textureset.get_active_stack()
    return {
        "project": project.file_path(),
        "project_index": SESSION.projects,
        "needs_saving": project.needs_saving(),
        "active_stack": [active.material().name(), active.name()],
    }


def exports_of_run(uzpainter: Any) -> list[dict[str, Any]]:
    """Every export the run published, the last one per fixed-name folder verified."""
    publications = [
        job.wait()
        for job in uzpainter.jobs.list()
        if job.kind == "export" and job.status == "succeeded"
    ]
    latest: dict[str, int] = {}
    for index, publication in enumerate(publications):
        for copy in publication["fixed_names"]:
            latest[os.path.normcase(os.path.abspath(copy["directory"]))] = index
    root = os.environ.get(ROOT_ENV)
    project_path = uzpainter.project.file_path() if uzpainter.project.is_open() else None
    mesh_path = uzpainter.project.last_imported_mesh_path() if project_path else None
    out = []
    problems = []
    for index, publication in enumerate(publications):
        receipt = json.loads(Path(publication["receipt"]).read_text(encoding="utf-8"))
        copies = []
        for copy in publication["fixed_names"]:
            key = os.path.normcase(os.path.abspath(copy["directory"]))
            current = latest[key] == index
            found = (
                verify_fixed_names(copy["directory"], copy["generation"], receipt)
                if current
                else []
            )
            problems += found
            copies.append({**copy, "verified": current and not found, "superseded": not current})
        manifest, reason = rebase_manifest(
            receipt,
            publication["directory"],
            project_path and str(project_path),
            mesh_path and str(mesh_path),
            root,
        )
        out.append(
            {
                "generation": publication["generation"],
                "directory": publication["directory"],
                "receipt": publication["receipt"],
                "receipt_sha256": publication["receipt_sha256"],
                "plan_hash": publication["plan_hash"],
                "revision": publication["revision"],
                "fixed_names": copies,
                "manifest": manifest,
                "manifest_unavailable": reason,
            }
        )
    if problems:
        raise AdapterExportError("; ".join(problems))
    return out


def main(argv: list[str]) -> Any:
    code_file, session_file, report_file = (Path(a) for a in argv[1:4])
    import uzpainter

    report: dict[str, Any] = {"session": None, "exports": [], "script_result": None}
    data = code_file.read_bytes()
    report["code_sha256"] = hashlib.sha256(data).hexdigest()
    session: dict[str, Any] | None = None
    try:
        report["carried"] = restore_session(session_file)
        install_shim(uzpainter)
        code = data.decode("utf-8")
        linecache.cache[CODE_FILE_NAME] = (len(code), None, code.splitlines(True), CODE_FILE_NAME)
        namespace: dict[str, Any] = {"params": {}}
        redirects = json.loads(os.environ.get(REDIRECTS_ENV) or "{}")
        report["redirects"] = redirects  # never silent: the reply lists every redirect applied
        if redirects:
            namespace["open"] = redirected_open(redirects)
        try:
            exec(compile(code, CODE_FILE_NAME, "exec", dont_inherit=True), namespace, namespace)
        finally:
            report["script_result"] = normalised(namespace.get("result"))
            session = session_left_open()
        report["exports"] = exports_of_run(uzpainter)
        if session is not None and session["project"] is None:
            raise AdapterSessionError(
                "the script left an untitled project open: UzPainter.exe run closes it with the "
                "process (decision 105), so it cannot be carried to the next call; save it first"
            )
        return report["script_result"]
    finally:
        carried = session if session is not None and session["project"] is not None else None
        if "carried" in report:  # the previous session was read: this run's state replaces it
            write_atomically(session_file, json.dumps(carried or {}))
        report["session"] = carried
        report_file.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    result = main(sys.argv)
