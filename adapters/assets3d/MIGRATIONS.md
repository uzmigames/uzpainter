# Assets3D pipeline adapter: migrations

The UzmiGames adapter that lets the Assets3D pipeline scripts drive UzPainter byte-unchanged. Task `phase1.23_pyapi-pipeline-adapter`, decision 113. Architecture: `docs/architecture/10-python-api.md` §2 and §6.

It is not part of the `substance_painter` facade. The facade holds Painter's documented symbols only. Every adaptation of how the pipeline reaches Painter is listed here, one entry per adapted call. The scripts themselves are never edited. The wand fixture pins them by SHA-256 (`tests/adapters/assets3d/wand.py`, from the R9 request manifest of decision 099, re-pinned to Assets3D `9a718b9` by decision 144):

| Script | SHA-256 |
|---|---|
| `Pipeline/retopology/wand11-v1/painter_create.py` | `6820831ccd59b66314eaab5a010607f7f55d720e6d2e628aadf9d44a6018535f` |
| `Pipeline/painting/painter_layer_stack.py` | `bf7006e256198879e5108b415439fb64d7e50b82d49afc58d2febaf3891ef62d` |
| `Pipeline/qa/route_check.py` (imported by the layer-stack script) | `d2024ead911d86527e4702fb74cccc7ddeeeebe425c86ee61cfd8f094f87dbc8` |
| `Pipeline/retopology/wand11-v1/painter_export.py` | `777ac278c7ce376bd8652bdd8400f0e5e5e1bef561262ccb7c22a9ac1c95c468` |

## Use

The pipeline reaches Painter through `painter_layer_stack.py` or, for a call with no project open yet, through the MCP client directly. The host-side change is one command prefix; the arguments and every absolute path stay as they are:

```sh
# before: "$MCP" "$CLIENT" execute_python ARGS.json   (painter_create.py's code; the MCP venv's python)
python E:/UzmiGames/UzPainter/adapters/assets3d/client.py execute_python ARGS.json
# before: "$MCP" "$LS" run painter_export.py
python E:/UzmiGames/UzPainter/adapters/assets3d/layer_stack.py "$LS" run painter_export.py
python E:/UzmiGames/UzPainter/adapters/assets3d/layer_stack.py "$LS" sync --stack S.json --masks DIR --state STATE.json
```

Since Assets3D `9a718b9` every layer-stack command (`run` included) first runs its route guard (M8), which needs a saved project open, so `painter_create.py` goes through the client.

Any Python 3.13 runs it; the script needs only the standard library. Environment: `UZPAINTER_EXE` (else `UzPainter.exe` on PATH), and optionally `UZP_ASSETS3D_SESSION` (the session file, default `%LOCALAPPDATA%/UzPainter/assets3d-adapter/session.json`) and `UZP_ASSETS3D_ROOT` (default: the script's own root). `--pin FILE=SHA256` (repeatable, before the script path) refuses the call when a file's bytes differ.

## Migrations

### M1. Transport: `painter_mcp_client.py execute_python` → `UzPainter.exe run`

- **Painter:** `painter_layer_stack.py`'s `execute(code)` runs `[MCP_PYTHON, CLIENT, "execute_python", args.json]`. The community MCP bridge executes the code in Painter's interpreter in the namespace `{"params": {}}` and returns `{"success": true, "data": result}`. A non-JSON value becomes its `str()` (`json.dumps(..., default=str)`). An uncaught exception is an MCP error, and the client exits 1.
- **UzPainter:** `adapters/assets3d/client.py execute_python args.json`, a drop-in for the MCP client with the same command line, runs `UzPainter.exe run adapters/assets3d/runner.py -- <code> <session> <report>`. The runner executes the code as the bridge executes it: the namespace `{"params": {}}`, and `result` normalised with `default=str`.
  - The reply is a superset of the bridge's envelope: `{"success", "data", "stdout", "stderr", "error": {type, message, traceback}, "code_sha256", "last_committed_revision", "session", "exports", "redirects"}`. It is printed as ASCII JSON and also written to `painter-last-response.json` in `SP_MCP_CLIENT_OUTPUT_DIR` when that is set.
  - The exit status is mapped explicitly, not forwarded: 0 when the code ran to its end; 1 for a structured failure (the code raised, or the adapter refused, as the MCP client exits on an error result); 2 for a usage error of the client; 3 when UzPainter could not run the code (missing executable, a host error, an unexpected exit of `run`, or a session held by another call).
  - Differences: the reply also returns the captured `print()` output, which Painter keeps in its log. The traceback names the code `<uzpainter-assets3d-adapter>`, where Painter names it `<substance-painter-mcp>`.

### M2. The layer-stack script's transport globals

- **Painter:** the pipeline runs `"$MCP" "$LS" <command>`. The script's `CLIENT` and `MCP_PYTHON` are hard-coded paths in Assets3D.
- **UzPainter:** `adapters/assets3d/layer_stack.py` reads the script's bytes once and compiles them with their real path, under the module name `uzp_assets3d_painter_layer_stack` (not `__main__`). It rebinds only `CLIENT` (to `client.py`) and `MCP_PYTHON` (to the running interpreter's `pythonw.exe`, which Windows never gives a console window, decision 252), then calls the script's own `main()` with its own arguments. This is what the script's `if __name__ == "__main__": main()` does. Its own `execute()`, reply parsing and errors run unchanged.
  - The recorder's alternative, replacing `execute()` itself (decision 099 4b), was rejected: it would skip the script's own reply handling.
  - `UZP_ASSETS3D_ROOT` defaults to the script's `ROOT` (the folder holding `AGENTS.md`).

### M3. Private call `_substance_painter.display.save_viewport(path, w, h, _)` (`capture`)

- **Painter:** a private module saves the painting view. It can return a stale camera (`docs/analysis/assets3d-pipeline/02-painter-usage.md` §8).
- **UzPainter:** a UzmiGames shim exists only in the runner. It is installed into `sys.modules` as `_substance_painter` and `_substance_painter.display` for the adapter's run only, and calls `uzpainter.render.capture(path, "painter_viewport", size=(w, h))`, which always captures the committed revision (decision 148): the PNG at `path`, with an OpenEXR and the capture receipt beside it. A plain `UzPainter.exe run` script and the facade have no such module or symbol, and the capability manifest names none.
- **Today:** `painter_viewport` renders only the pinned display configuration (OCIO with Painter's substance config, decisions 038, 134). A project created without `OCIO` is Legacy colour-managed, so on such a project the shim raises `UnsupportedInUzPainter` naming `unsupported_configuration` before any evaluation or device, writes nothing, and the revision is unchanged. On an OCIO project without fill sources the capture succeeds; such a project is opened natively in the call (decision 148; since decision 202 the facade opens it too). Evaluating and exporting fill sources under OCIO are fitted for what Session O records (decisions 190 and 202). Since decision 207, `project.create` with `OCIO` naming Painter's substance config creates an OCIO project (M9). A created project names no environment, so since decision 212 its capture is lit by the installation's default environment (the shipped CC0 `studio-small-09.exr`, verified by SHA-256), as Painter lights a new project with an installed default: the receipt's `environment` names it with `default: true`, and the capture is a non-parity preview. The wand's pipeline `capture` runs this way.

### M4. Session carried between calls

- **Painter:** one persistent process. `painter_create.py` creates and saves a project. `sync`, in the next call, edits it without saving. `painter_export.py` saves and exports it. The session also keeps the `resource://project<N>` context counter, the active stack and `needs_saving()`.
- **UzPainter:** `run` is one process per call. It closes the project left open with the native close, which keeps every committed revision (decisions 105, 111). The session file names what a call left open:
  - the project file, as the absolute path `open` or `save_as` resolved when it named the file (`uzpainter.project.absolute_file_path()`, decision 118). Each call runs in the client's working directory, so a script that changed directory before a relative `save_as` is still reopened where it saved;
  - the facade's project index;
  - the facade's `needs_saving()`;
  - the active stack (texture set and stack name).

  The next call reopens the project through the facade and restores those values before the code runs. Uncommitted state does not exist: every API call is a durable revision.
  - Calls are serialised per session file by an OS lock (`<session>.lock`). The lock is released if the process dies. A call that cannot take it within about ten seconds is a host error, because Painter serves one call at a time.
  - The session file is replaced atomically (a staging file, then a rename).
  - A carried project that no longer opens fails the call before the code runs and empties the session. So does a session file that names a relative path (written before decision 118).
  - A call that leaves an untitled (never saved) project open fails with `AdapterSessionError`, with the script's `result` kept in `data`: the native close removes an untitled project's folder, so it cannot outlive the process.
  - Not carried: the layer selection, selection types, the UI mode and collapsed state. They are inert script context (10 §3): nothing in evaluation or export reads them.
- **Until:** `phase2.1_supervisor-ipc-worker`'s persistent worker, which makes the carry unnecessary.

### M5. `painter_layer_stack.py smart` refused before any call

- **Painter:** `smart`'s Painter-side code first deletes the root nodes named `SM *` and `Layer 1`, then inserts and edits fills, and only then calls `insert_smart_mask` and `resource.search`. Every call commits on its own.
- **UzPainter:** smart masks and resource search are release gaps (`phase3.6_smart-presets-projections`). Running the code would leave a half-changed project. The entry therefore refuses `smart` before any call reaches UzPainter. It prints `{"success": false, "error": {"type": "NotYetSupported", "capability": "smart presets", "owner": ..., "missing": [...]}}` and exits 1.
  - The gate (`GATES` in `layer_stack.py`) reads the shipped `capabilities.json` (`UzPainter.exe capabilities`). It opens by itself once every symbol it needs is `supported`. A `pending-evidence` symbol works but is unverified, so it keeps the gate closed.
  - Code sent through `run FILE` is not gated. A missing call there raises where it is reached, after the script's earlier calls committed, as Painter's contract has it (10 §5).

### M6. Exports: the consumers' route, the receipt and the manifest

- **Painter:** `export_project_textures` writes the maps into `exportPath` under their file names. Assets3D's consumers (the Blender delivery and review scripts) read them there by name, later, with no lock.
- **UzPainter:** the export publishes a generation with its receipt (`exportPath/generations/<N>/`), and the facade copies it under its fixed names into `exportPath`, which is Painter's flat layout, through a journalled copy (decision 097).
  - **Route.** The consumers keep that fixed-name copy, the only layout the unchanged scripts and consumers know. Before the call reports success, the runner verifies the copy of the run's last export into each folder: the journal names the generation the export published, it is complete (`copied` = `files`, `obsolete` empty), and every file has the receipt's size and SHA-256. Otherwise the call fails with `AdapterExportError`.
  - **Residual: reads after the call are not locked.** Unchanged Blender consumers cannot take the publication lock or open a pinned generation. Another export into the same folder while they read would race them. Assets3D's own Painter lock (`collab.py lock acquire --app Painter`, one agent at a time) serialises exports and reads. The pinned-generation route (`OpenPinnedDelivery`) is for consumers that can change, owned by `phase3.1_assets3d-cutover`.
  - **Manifest.** Each export appears in the reply's `exports[]` with its generation, receipt, fixed-name copies and `manifest`. `manifest` holds the receipt's `manifest_files`, with its paths rebased under the Assets3D root (`UZP_ASSETS3D_ROOT`), beside its `manifest_export` block (Assets3D manifest schema v2 `$defs/export`). Generation-relative paths take the generation folder; `project` and `mesh` take the project file and the imported mesh. When a path lies outside the root, `manifest` is null and `manifest_unavailable` gives the reason; the export itself still succeeds. A diagnostic measure export (`UZP_ASSETS3D_DIAGNOSTIC_MEASURE_EXPORT=1`, the Tier 1 runner's measure mode, decision 286) is not conformant: its receipt says `non_conformant` and it never gets a manifest.
  - **App version and build.** The native export already passes them: `uzpainter.application.version()` and `uzpainter-<build mode>`.

### M7. Fixture only: repointed arguments files (`UZP_ASSETS3D_OPEN_REDIRECTS`)

- **Painter:** `painter_create.py` and `painter_export.py` read their arguments from a hard-coded Assets3D path. Those arguments name the production `.spp` and export folder.
- **UzPainter, the wand fixture only:** the runner's namespace `open` maps exactly the paths given in `UZP_ASSETS3D_OPEN_REDIRECTS` (JSON `{path: copy}`) to their copies. This is decision 099's adaptation (a). The fixture's copies name a mirror of the Assets3D tree in its work directory, so nothing is written under Assets3D.
  - The reply's `redirects` lists every redirect applied, so none is silent.
  - The pipeline never sets the variable, and with it unset `open` is the builtin.

### M8. The layer-stack script's route guard (Assets3D `9a718b9`, decision 144)

- **Painter:** before each command, `route_guard` sends its own probe `GUARD_CODE` through the script's `execute()`: the open project's `file_path()`, the texture set of the active (or named) stack and its root group names. It then calls `route_check.locate()` on the project path. Outside a new-layout character (`Creatures/<Family>/<Name>/Project/`, a folder beside `Concept/`) the verdict is `legacy` and the command runs with no attempt token. Inside one, the production runner (`Pipeline/production/run.py`) must have the piece's paint stage open and the project must be the copy in its attempt folder; the command then passes that attempt's token to the MCP client as `UZ_ROUTE_TOKEN`. No saved project open: the probe fails, or the guard exits `ROUTE BLOCKED`.
- **UzPainter:** the probe is an ordinary `execute()` call (M1), served by the facade's documented calls, and `route_check` is the script's own import. Nothing is adapted. The wand fixture runs the scripts from their staged, pinned copies, so the import is the pinned `route_check.py` (`--pin` covers it).
- **Difference:** Assets3D's MCP client has its own guard since `9a718b9`: code that changes a project of a new-layout character is refused unless `UZ_ROUTE_TOKEN` carries the open attempt's token. `client.py` ignores `UZ_ROUTE_TOKEN` and has no such check. For a project outside the new layout (every fixture here, and the Skeletal Mage), both pass. A new-layout character through the adapter is not guarded by the client; owner decision pending (decision 144).

### M9. `OCIO` set by `painter_create.py` before `create`

- **Painter:** `project.create` takes its colour management from the environment, as documented: `OCIO` naming a configuration gives an OCIO project, else `PAINTER_ACE_CONFIG` an ACE project, else Legacy. The script sets `os.environ["OCIO"]` to Painter's substance config just before `create`.
- **UzPainter:** nothing is adapted. The script runs in the `run` process, and the facade's `create` reads both variables at the call (decision 207). The file `OCIO` names is hashed: Painter's substance config (SHA-256 `15059d4b…`) creates an OCIO project with that hash. Any other configuration, and ACE, raise `NotYetSupported`, and a file that cannot be read raises `ProjectError`, before anything is created. The adapter passes the caller's environment unchanged, so an `OCIO` set in the shell reaches `create` too.

### M10. Saving onto an existing project

- **Painter:** `project.save_as(path)` replaces an existing, closed project without raising (P23-A, decision 180).
- **UzPainter:** the facade now replaces that destination through an explicit store policy; the adapter makes no change to the script. The compared `phase1-save-as-existing` replay verifies the result, events and reopened content. A locked destination, the current project or its alias, and a destination with SQLite recovery companions are refused before replacement. Native `save_as` and facade `save_as_copy` retain their create-only policy.

### M11. Read-only upstream gate preflight (decision 360)

`python -m adapters.assets3d check-production REQUEST.json [--diagnostic]` checks
pinned Assets3D v2 prerequisite evidence without importing a mesh or executing a
pipeline script. Exit 0 means the recorded prerequisites checked; exit 1 reports
missing, stale, failed or unsupported proof. `production_authorized` is always
false: this command does not grant G2, the owner-signed amendment or production
execution. `--diagnostic` labels the report; it does not turn a failure into a pass.

The request is a JSON object with these fields:

```json
{
  "schema": "uzpainter/assets3d-admission/1",
  "root": "E:/UzmiGames/Assets3D",
  "manifest": {"path": "piece/manifest.json", "sha256": "<64 lowercase hex>"},
  "import_report": {"path": "piece/import.json", "sha256": "<64 lowercase hex>"},
  "requirements": {
    "geometry_fit": ["/gates/visual/geometry-producer", "/gates/visual/geometry-review"],
    "low_uv": ["/gates/technical/uv-producer", "/gates/technical/uv-review"],
    "bake": ["/gates/technical/bake-producer", "/gates/technical/bake-review"],
    "low_high_fidelity": ["/gates/visual/fidelity-producer", "/gates/visual/fidelity-review"]
  }
}
```

The gate names are examples, not required names. `geometry_fit` is the combined
geometry/fit obligation: both producer and independent evidence must cover both
stages. The same independent pair may review several requirements. Each reviewer
has a nonempty agent/session/model; the independent agent and session differ from
the producer's for that requirement. Fidelity must explicitly reference the
`/low_high_fidelity` evidence selector as well as cover the bake stage; a generic
bake tag cannot silently discharge it.

The manifest is schema-v2's `type: piece-manifest, schema: 1` document. All declared
upstream gates covering geometry, fit, coverage, low_uv or bake are checked, not
only the requested bindings. A parallel pending/fail or unverified/reopened gate
cannot be hidden by another pass. A confirmed `not_applicable` gate requires a
justification and never satisfies a required role. Evidence and dependency file
references must resolve inside the root with verified SHA-256 and byte counts.
Only JSON Pointer selectors into JSON files are supported; other selector formats
refuse explicitly. Dependencies must be current equal/equivalent records and bind
the same current low mesh. Invalidations at or after the gate's recorded moment
refuse; input bytes are checked again before the report is returned. This is a
validator of the consumed prerequisite fields, not a replacement for Assets3D's
complete manifest schema or its visual review process.

`import_report` is the native mesh import report (`mesh_import.cpp`), including
`source.{sha256,size}`, `hashes` and `certificate.{status,hashes}`. Its source must
match the manifest's low mesh, and its hashes must match the certificate. A fail
or unknown status refuses; warn is retained in the assessment. External mesh
files currently refuse because their import-boundary binding is not implemented.

**Execution remains unguarded by this preflight.** The existing generic script
route and M8's route-token gap are unchanged. Item 2.5 of
`phase3.1_assets3d-cutover` stays open until the real selection/import boundary
checks the consumed mesh, certificate and evidence before mutation. A successful
preflight is not a reusable ticket: a later execution must check again and bind
its actual import. Synthetic CPU tests establish the checker's behavior, not
approval of any real pilot.

## Not adapted (UzPainter differs; owners named)

- **The wand's five-map export:** its BaseColor is written exactly (decision 126), but `infinite` padding on the wand's UV islands is refused before writing, naming recording R-090 (decision 127). Owner: `phase1.25_pilot-wand` item 2.7.
