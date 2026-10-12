# 105. The native Python API keeps autosaved revisions, stores floats as float32 and exports as a publishing job

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle, phase1.22_pyapi-cli-capabilities, phase1.18_export-engine, phase4.1_nodes-paint-layers

## Context

Task phase1.19 builds the native `uzpainter` module (`src/python/`) over the project store, the document model and the export engine. Several behaviours had to be chosen where the architecture leaves them open.

Measured facts:

- **Store semantics.** The project store commits every API call durably as a revision; the commit is the autosave (`09-project-file-format.md` §4). `save()` writes a named checkpoint; `needs_saving()` is "current revision ≠ last named checkpoint"; reopening a file gives its current revision. `ProjectStore::SaveAs` refuses an existing target.
- **Painter's documentation.** `close()`: "Any unsaved data will be lost". `save_as` creates missing folders. A never-saved project has `file_path()` None.
- **Tier 0 probes** (private records, both recordings):
  - `fill-layer-readback` reads opacity 0.85 back as 0.8500000238418579 and a Raw uniform 0.35 as 0.3499999940395355, both float32 values.
  - `insert_fill` names its node "Fill", `insert_group` "Folder".
  - `textureset-project-readback` reads `name()` of a never-saved project as "Untitled", the name the `$project` export wildcard uses.
  - Every new stack holds an empty paint layer "Layer 1" at its bottom.
- **The evaluator** casts every stored value to float32 before use. Rounding at the API boundary therefore changes no texture: float(double(float(x))) = float(x).
- **The export engine pieces exist.** They are `CompilePlan`, `PublishExport` (a new generation with plan, receipt and an atomic `current.json`) and `CopyFixedNames` (fixed names into any folder; into `exportPath` it gives Painter's flat layout). The CPU evaluator is the reference the export tests compare exactly with Painter's goldens. The GPU path needs the engine thread of a later phase.
- **Paint layers are outside the Phase 1 subset.** The evaluator and `RequireSupported` refuse paint layers (`phase4.1_nodes-paint-layers`), and an empty paint layer changes no channel.

The model panel could not be consulted: the 9router proxy refused every connection (two attempts, WinError 10061). The brief asks for a decision anyway. This one follows the measured facts and records the claims the panel would have been asked.

## Decision

1. **Saving.** Native `close()` keeps the autosaved current revision: a reopened project shows it and `needs_saving()` stays true. Painter's "unsaved data lost" belongs to the facade (phase1.20/phase1.21), which can revert to the named checkpoint before closing. A project created from a mesh lives in a private folder of the temporary directory until `save_as`. Its `file_path()` is None and `name()` is "Untitled", as Painter reads it. Native `save()` on it raises `ProjectError`, and `save_as` to an existing file raises `ProjectError` (store semantics) instead of overwriting. Closing an untitled project removes its folder.
2. **float32 values.** Every float a native setter stores is rounded to float32: opacity, uniform colour components, UV scale, rotation and offset, levels parameters and the values `sync_stack` writes. Native readbacks then equal Painter's exactly. Colours are otherwise kept as given: `value_raw` and the colour-space string, read back unchanged. Conversions and the deduction of a missing space are the facade's colour rules (phase1.20).
3. **Default names.** Inserts take Painter's default names: "Fill" for a fill layer or effect, "Folder" for a group.
4. **No default "Layer 1".** The native project does not create Painter's empty "Layer 1" paint layer. Paint layers are a release gap (`phase4.1_nodes-paint-layers`), and the empty layer is invisible in every channel. The Tier 0 structure comparison strips it from the golden after asserting it is exactly that empty layer. `phase4.1_nodes-paint-layers` adds it when paint layers enter the subset.
5. **Export.** `uzpainter.export.export_project_textures(config, fixed_names=[])` runs as a worker job (`uzpainter.jobs`). It exports the revision current at submission on the CPU evaluator and publishes a generation with its receipt (`PublishExport`). It copies fixed names only into the folders the caller lists, and never writes Painter's flat layout implicitly; the facade passes `fixed_names=[exportPath]` to reproduce Painter. The synchronous form waits with the GIL released. Closing or saving the project while a job is queued or running raises `BusyError(job_id)`. `export.plan(config)` is the typed dry run (decision 085) and `export.list_project_textures(config)` the Painter-shaped one (decision 091).
6. **Script runner.** The script runner core lives in `src/python/script.cpp`: the file runs as `__main__`, standard output and error are captured, `result` is returned as JSON, and a failure carries its class, message and traceback with the last committed revision and every committed result. The test-only `uzp-pyapi-tests.exe` drives it. The `UzPainter.exe run` verb, its JSON lines and exit codes stay in phase1.22.

## Alternatives Considered

- Revert to the named checkpoint on native `close()`. Rejected: it discards durable work in the API every tool and the MCP server share. Painter's behaviour is a facade concern.
- Store setter values unrounded. Rejected: readbacks would differ from Painter's float32 values with no gain, since the evaluator rounds anyway.
- Create the empty "Layer 1" paint layer. Rejected for Phase 1: every request touching it would hit the paint-layer release gap.
- Export to Painter's flat layout by default. Rejected: the publication with receipts is UzPainter's delivery (decision 097). The flat copy is one explicit argument.

## Consequences

The facade (phase1.20) implements Painter's close semantics, colour conversions and the `exportPath` flat copy over these primitives. `phase4.1_nodes-paint-layers` owns the default "Layer 1". If the panel later disagrees with a point, it is re-opened through a new decision.
