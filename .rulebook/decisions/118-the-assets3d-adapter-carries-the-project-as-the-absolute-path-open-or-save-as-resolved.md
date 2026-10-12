# 118. The Assets3D adapter carries the project as the absolute path open or save_as resolved

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.24_python-api-facade, phase1.23_pyapi-pipeline-adapter, phase1.19_pyapi-native-module

## Context

The Codex audit of phase1.24 found a P2 bug in the Assets3D adapter's session carry (`adapters/assets3d/runner.py`). The runner wrote `substance_painter.project.file_path()` into the session file as the next call's project. That is the path as the script named it.

- **Trigger.** A script calls `os.chdir(work)`, then `save_as("A.uzp")`. The session names `A.uzp`, relative.
- **Why it breaks.** Every call is a new `UzPainter.exe run` process started by `client.py` with no working-directory override, so it runs in the client's directory, not in `work`.
- **Result.** With no `A.uzp` in the client's directory, the call fails with `AdapterSessionError` and the session is emptied. With one there, another project is silently reopened.
- Both cases reproduce host-only (`scripts/tmp/codex-audit/test_session_carry_review.py`, 0.04 s).

The native session already holds the right value. Since phase1.24, `Session::Open` and `Session::SaveAs` store `OpenProject::project_source`, the file resolved against the working directory when the call ran. Export jobs name their project with it, the same way `MeshReference.source` names the mesh. Python could not read it.

## Decision

1. **`uzpainter.project.absolute_file_path()`**, a UzPainter-only native function, returns `project_source`, or None while the project is untitled. `file_path()` is unchanged: it still returns the path as the call named it.
2. **The runner carries `absolute_file_path()`** as the session's `project`. It never resolves `file_path()` under the directory the script ends in.
3. **A session file that names a relative path** fails the call before anything opens, and the session is emptied. Such a file was written before this decision, and resolving it under the client's directory is the bug itself.
4. The capability manifest lists the function as `pending-evidence` (decision 112). It is UzPainter-only, as `template()` is (decision 115 §4).

## Alternatives Considered

- **Make the native `file_path()` absolute.** Rejected: the facade's `file_path()` reproduces Painter's, and what Painter returns after a relative `save_as` is unrecorded.
- **Wrap `open` and `save_as` in the runner to remember the path.** Rejected: it duplicates what the native session already records, and it misses a project opened or saved through `uzpainter.project` directly.
- **Give the client's `subprocess.run` the script's last directory.** Rejected: the directory the script ended in is not the one it saved in.

## Consequences

- `tests/adapters/assets3d/test_adapter_units.py`: host tests of both audit cases, with and without a same-named file, and of a relative session file being refused.
- `tests/adapters/assets3d/test_pipeline_adapter.py`: a native two-call regression. The first call changes directory and saves under a relative path. The second, run from another directory that holds a same-named project, must reopen the saved project, same UUID and same path.
- Docs: `adapters/assets3d/MIGRATIONS.md` M4, `src/python/PYAPI.md`, `docs/architecture/10-python-api.md` §7.
- phase1.24's report §5 lists the carry as open, owned by phase1.24, until the native regression passes.
