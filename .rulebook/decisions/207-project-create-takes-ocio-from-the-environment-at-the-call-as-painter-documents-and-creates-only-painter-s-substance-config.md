# 207. `project.create` takes OCIO from the environment at the call, as Painter documents, and creates only Painter's substance config

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase1.24_python-api-facade, phase1.15_compositor-colour-fits

## Context

Decision 202 left the Wand pilot blocked: UzPainter's `project.create` always made a Legacy project. The facade's OCIO profile (decisions 190 and 202) was reachable only by opening a project that already declared OCIO. The Wand's `painter_create.py` runs unchanged through the adapter (decisions 124 and 144). In UzPainter it built a Legacy project, but its golden (R9, decision 180) was recorded under OCIO in Session O.

Facts:
1. **What Painter documents** (`project.html`, `create`; `docs/analysis/substance-parity/05-project-and-spp.md`): the colour-management mode is chosen at creation from the environment.
   - `OCIO` naming a `.ocio` file gives OCIO mode, and it wins when `PAINTER_ACE_CONFIG` is also set.
   - `PAINTER_ACE_CONFIG` alone, naming a `.json` preset, gives ACE mode.
   - With neither, the project is Legacy.
   - An invalid configuration raises `ProjectError`.
   - `project.Settings` has no colour-management member.
2. **What the pipeline does.** `painter_create.py` sets `os.environ["OCIO"]` to Painter's `resources\ocio\substance\config.ocio` inside the Painter process, just before `create`. The Assets3D lesson ("OCIO antes de criar o projeto") says a project created without it became Legacy and could not be converted. The recorder also started Session O with `OCIO` in the shell (RECORDER §11.2), and its Painter side reads the mode `create` selects from the same two variables (`painter_side.colour_management`).
3. **How UzPainter runs the script.** It runs in the `UzPainter.exe run` process, where the facade's `create` runs too. So `os.environ` at the call holds both the inherited environment and the script's own assignment. The adapter starts one `run` process per call and passes it the caller's environment.
4. **The file.** The installed `config.ocio` has SHA-256 `15059d4b…`, which is `kPainterOcioConfigSha256` (decision 134).
5. **Working space.** Painter's working-space name under that configuration is neither readable through the documented API nor recorded. The evaluator and export key OCIO on `mode` and `config_hash` only (`evaluator::PainterOcio`).

Model panel (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-13, one round):
- C1, read `OCIO` and `PAINTER_ACE_CONFIG` at the call, not at start-up: AGREE x3.
- C2, hash the file `OCIO` names: the substance hash creates OCIO, an unreadable file raises `ProjectError`, any other hash raises `NotYetSupported`, all before mutation: AGREE x2, PARTLY x1.
  - GPT: a hash cannot tell an invalid configuration from a valid unsupported one. Kept: telling them apart would mean parsing the configuration, and both are refused before anything is created.
  - Kimi: "unreadable means invalid" is an inference. Accepted as the stated assumption.
- C3, `PAINTER_ACE_CONFIG` alone raises `NotYetSupported`, and neither variable (or empty strings) gives Legacy: AGREE x2, PARTLY x1.
  - GPT: a missing ACE preset is invalid too, so it should raise `ProjectError`. Adopted.
- C4, an explicit native `ocio_config_hash`, with no environment read in native code, no `--ocio-config` flag and no adapter change: AGREE x2, PARTLY x1. Grok: omitting it must still give Legacy, which it does.
- C5, leave `working_space` empty rather than guess: AGREE x1, PARTLY x2. Kimi: say that the field is empty on purpose. Grok: the OCIO path must still evaluate with the substance config, which it does, keyed on the hash.

## Decision

1. **The facade reads the environment at the call** (`colour.creation_ocio_config_hash`, called by `project.create` before any native call). This follows Painter's documented rule, not a read at start-up, which would miss the pipeline's in-process `OCIO` (fact 2).
   - `OCIO` set and non-empty: the file it names is hashed (SHA-256 of its bytes, never parsed or copied).
     - Painter's substance config creates an OCIO project with that hash, whatever `PAINTER_ACE_CONFIG` holds.
     - A readable file with any other hash raises `NotYetSupported`.
     - A file that cannot be read raises `ProjectError`, Painter's invalid configuration.
   - `PAINTER_ACE_CONFIG` alone: an unreadable preset raises `ProjectError`, and a readable one raises `NotYetSupported` (ACE is not fitted).
   - Neither variable set, or both empty: Legacy, as before. Treating an empty string as unset is an assumption, and the recorder's Painter side does the same.
   - Every refusal comes before anything is created: no project is open after it.
2. **The native API takes the configuration explicitly.** `uzpainter.project.Settings(ocio_config_hash=...)` creates the project with `color_management.mode = "ocio"` and that hash. Any hash but `kPainterOcioConfigSha256` raises `NotYetSupported` before the mesh is read. Native code reads no environment. Omitting the member gives a Legacy project (mode ""). `working_space` stays empty on purpose (fact 5).
3. **No new channel.** The adapter, `run` and the MCP `project_create` tool are unchanged, and there is no `--ocio-config` flag. The variable already reaches the facade from the script or the caller's shell (fact 3). A flag would be a second channel that the unchanged scripts never use.
4. **A bitmap is bound in its default space in one native call.** `FillLayerNode.set_source(channel, resource)` used to bind the bitmap with no space and then set Painter's default space in a second call. Under OCIO, the per-call support check refused the intermediate bitmap: a BaseColor bitmap without a space is unrecorded (decision 190). The Wand's `T_base` failed the sync this way. The native `set_source` now takes an optional `color_space` for a bitmap, and the facade passes the default space it already computed. Under Legacy the committed result is unchanged.
5. **The native `sync_stack` refuses an sRGB base colour under OCIO.** The native composite (decision 115) decoded a layer's sRGB `base` with the facade's Legacy float32 rule whatever the project's mode. Under OCIO the facade stores Painter's measured decode (`ocio_srgb.py`, decision 202), which the native module does not hold, so the two groups differed. `sync_stack` now raises `NotYetSupported` there, and the transaction commits nothing. It stays exact under Legacy. Porting the table to native code is the gap's fix, with the same owner as decision 202's table.
6. **The Wand through the adapter** (`UzPainter.exe` of this branch, the pinned R9 inputs, nothing written under Assets3D):
   - `painter_create.py` creates an OCIO project with the substance hash (`get_color_management`: mode `ocio`, `config_hash` `15059d4b…`).
   - `sync` runs (13 layers, 14 masks, `T_base` on BaseColor in sRGB).
   - `painter_export.py` is refused before writing, only by `infinite` padding on UV islands (phase1.25 item 2.7).
   - The pipeline's `capture` subcommand now passes the colour check on the wand. It is then refused before rendering, because a created project names no environment (RES-03: no substitute). The Legacy refusal stays tested in `tests/preview/test_preview_capture.py`.
7. **Evidence.**
   - `test_create_takes_colour_management_from_the_environment_at_the_call` (facade): Legacy by default and with empty variables; another configuration and ACE raise `NotYetSupported`; unreadable files raise `ProjectError`; no project is open after any refusal; OCIO wins over ACE; the Wand's in-process assignment gives an OCIO project whose sRGB BaseColor reads Painter's measured value, binds a colour bitmap in sRGB, and keeps OCIO through save and reopen.
   - `test_a_project_is_created_under_painters_ocio_config_only` (native).
   - `tests/adapters/assets3d/test_pipeline_adapter.py` on the OCIO wand:
     - create, sync and the export's padding refusal (`test_wand_create_sync_and_export_run_unchanged`);
     - the capture's environment refusal;
     - the native `sync_stack` refusal of item 5, with the script's group and the revision unchanged.
   - The test needs Painter's installed config to hash and skips without it. The file is never copied into the repository.

## Alternatives Considered

- **Reading `OCIO` once at process start-up.** Rejected (panel C1): the Wand sets it in-process just before `create`, and Painter documents the choice at `create`.
- **A `--ocio-config` flag or an adapter-supplied setting only.** Rejected (C4): the scripts never pass it, and it would let UzPainter and Painter disagree on the same environment.
- **Accepting the configuration by path.** Rejected: the hash pins the content Session O ran, whatever the install path.
- **Naming a working space (for example `ACEScg`).** Rejected (C5): it is not recorded.

## Consequences

### Positive
- The unchanged Wand scripts produce an OCIO project exactly when Painter would, and `create` and `sync` run under OCIO. The pilot's remaining blocker is the padding fit (item 2.7).

### Negative
- An OCIO project can be created only on a machine where the file `OCIO` names has the substance config's bytes, which in practice means Painter is installed. Elsewhere, `create` with that `OCIO` raises `ProjectError` or `NotYetSupported`.
- ACE, and every other OCIO configuration, stay refused at `create`.
- On an OCIO project the native `sync_stack` (and the MCP tool over it) is refused for sRGB base colours. The wand no longer evidences decision 115's native-equals-script equality. The Legacy sync tests in `tests/python/test_pyapi_native.py` still do.
