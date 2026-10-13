# 212. A project that names no environment is lit by the installation's default in `painter_viewport`; the OCIO decode and OCIO creation reach native code and MCP

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.25_pilot-wand, phase2.2_preview-capture, phase1.15_compositor-colour-fits, phase2.6_mcp-typed-tool-families

## Context

Decision 207 left three follow-ups on the Wand-under-OCIO path:

1. **The native decode.** The facade reads Painter's measured OCIO decode of an sRGB uniform colour from `python/uzpainter_facade/ocio_srgb.py` (449 entries, decision 202). The native `sync_stack` had only the Legacy rule, so decision 207 made it refuse an sRGB base colour under OCIO. That removed decision 115's "native group equals script group" evidence on the wand.
2. **Capture on a created project.** The pipeline's `capture` on the OCIO wand was refused with "the project names no environment (RES-03: no substitute)".
   - Decision 132 §2: a new project starts with no environment, because the standard's environment cannot be shipped.
   - Decision 134 §4: a missing environment fails with no substitute, "so does a project that names no environment".
   - Painter lights a new project with an installed default environment. That environment is a shelf asset, not a project resource, so it is not in `list_project_resources()`.
   - The fixed standard's environments cannot serve:
     - `common`'s Studio White Soft is an Adobe asset, used only as a private test input.
     - `ref_match`'s `TOS-RefMatch-Skeletal-Mage.exr` lives in Assets3D, and its shipping licence is an owner decision.
   - UzPainter ships one CC0 environment, `assets/environments/studio-small-09.exr` (SHA-256 `44dcbed0…`). Its provenance record gives it the role `non-parity-preview`, for "projects that do not light with a standard environment".
   - `painter_viewport` is never parity evidence (decision 148).
3. **MCP.** `project_create` always created Legacy. The worker reads no user environment, so it never sees the `OCIO` variable that the facade's `create` reads.

Model panel on item 2 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-13, one round). The four options:
- A: the standard's environment.
- B: import the shipped environment into every created project.
- C: light a project that names no environment with the installation's default when it renders, changing no document.
- D: keep the refusal.

The claims:
- C1, A is out (clean room; ref_match unlicensed): AGREE ×1, PARTLY ×2. The ref_match point is beside the question, since A names only `common`'s environment.
- C2, C over B: PARTLY ×3. C does amend decision 134, and "least code" is unproven. All three still prefer C over B, because B makes every created project's resource listing differ from Painter's.
- C3, C does not violate RES-03: DISAGREE ×1 (GPT), PARTLY ×2.
  - GPT: RES-03 speaks of resources stored with the project; an installed file is not one. C needs an explicit, preview-only exception.
  - Kimi and Grok: the installed file plus its hash fits the "retrievable locator plus hash" reading. Record it as an amendment, not as continuity.
- C4, the default must be visible (receipt hash, a default flag, parity false): AGREE ×2, PARTLY ×1. Kimi: expose it in `render.display.state()` too, not only in the receipt.
- C5, the preview window and the capture light the same way: AGREE ×3. Test the missing or mismatching installed file, and keep a named missing environment failing.

## Decision

1. **One OCIO decode table, generated into native code.**
   - `ocio_srgb.py` stays the one source.
   - `tools/parity/ocio_srgb_table.py` renders it as `src/evaluator/ocio_srgb_table.inc`, keyed exactly as the facade keys it: the float32 bits of `c / 255` and of each recorded component, with a recorded component overriding a code of the same bits.
   - `evaluator::PainterOcioSrgbDecode(float)` looks up that file and returns nothing for an unrecorded component.
   - `tests/parity/test_ocio_srgb_table.py` fails when the committed `.inc` differs from what the generator renders.
2. **The native `sync_stack` under OCIO** stores each sRGB base component as that table's working value, as the facade does. It refuses what the facade refuses, with `NotYetSupported` and nothing committed:
   - a component the table does not record;
   - an sRGB base colour on a BaseColor that does not decode it (not sRGB8, or absent).

   Under Legacy nothing changes. `sync_stack` is the only native decode of an sRGB uniform colour: native setters and the MCP `source_set` store colours as given, and the facade does every other decode. The preview's sRGB8 background is a display value, not a uniform colour, and is out of scope. Decision 207 §5's refusal is withdrawn, and the wand's native-equals-script test is restored (`test_native_sync_stack_builds_the_document_the_script_builds`).
3. **Option C, adopted as an explicit amendment of decision 134 §4's last sentence, for `painter_viewport` only.** When `painter_viewport` renders a project that names no environment, it lights it with the installation's default environment. This applies to both the capture and the preview window, which share `preview::SceneOf`.
   - The default is the shipped `bin/assets/environments/studio-small-09.exr` (`preview::DefaultEnvironment`, `kDefaultEnvironmentSha256`). It is read once and checked against that hash. A missing or different file is an explicit error (`RuntimeError` in the capture, the preview's message).
   - The document is unchanged. `display.get_environment_resource()` stays None, and no resource is added.
   - Visibility:
     - The capture receipt gains `environment {sha256, default, rotation, exposure}`, null for the diagnostic modes; `default` is also in the render-state digest.
     - `render.display.state()` gains `environment_default`.
     - `parity` stays false, and such a capture is never parity evidence (decision 148).
   - RES-03 is unchanged for every named environment: a project naming an environment whose bytes are missing still fails with no substitute. The exception does not reach `painter_iray` or any parity path.
   - Recorded as GPT asked: this narrows decision 134 §4 by amendment. It does not reinterpret it.
4. **MCP `project_create` takes `ocio_config_hash`** (a 64-hex string, the native `Settings` member of decision 207).
   - Painter's substance config creates an OCIO project with that hash.
   - Any other hash is refused `capability_gap` (`NotYetSupported`, `python::CheckCreateSettings`) before the job, so nothing is created. A malformed value is `invalid_arguments`.
   - Omitting it gives Legacy.
   - This replaces decision 207 §3's "MCP unchanged" for the worker only. The worker has no user environment to read, so this is an explicit argument and not a second channel for the scripts. The adapter and `run` stay unchanged.
   - The argument gates no capability value, so `mcp-tools.json` is unchanged. The `project.create` matrix row's notes say how colour management is chosen.
   - The native member `uzpainter.project.Settings.ocio_config_hash` gets its capability-manifest entry (`pending-evidence`, UzPainter-only).

## Alternatives Considered

- **A, the standard's `common` environment read from Painter's install.** Rejected: a product path would depend on an Adobe asset (clean room).
- **B, importing the shipped environment at `create`.** Rejected: every created project would carry 1.3 MB and one more project resource than Painter lists. Decision 132 §2 would also change.
- **D, keeping the refusal.** Rejected: the owner's acceptance needs the Wand's capture step to run.
- **Two hand-kept copies of the table, or a data file both read.** Rejected: the facade installs only `.py` files, and two hand-kept copies drift. Generating the native copy from the facade's table with a freshness test keeps one source.

## Consequences

### Positive
- The Wand's create, sync, native sync and capture all run under OCIO. The native composite again equals the script's group on the wand.
- MCP clients can create the OCIO projects the pipeline uses.

### Negative
- A project that names no environment renders lit by the CC0 studio, not by Painter's own default, which is unrecorded and unshippable. The receipt and `state()` say so.
- A `painter_viewport` render now depends on the installed default file when the project names no environment.
