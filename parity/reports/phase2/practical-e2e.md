# Practical end-to-end run: UzPainter used as a client would use it

UzPainter was driven the way the pipeline and an AI client will drive it: over MCP, through `run` scripts, through the Assets3D adapter, and through the preview window. Every step was logged. This report lists what worked and every inconsistency found, with repro steps.

- **Date and build.** 2026-10-13, branch `wt/practical-e2e` from main `959b16a`. `zig build painter -Doptimize=ReleaseSafe` in its own worktree (2 min 47 s). `UzPainter.exe` SHA-256 `2710ac9795e414614646428bfe71e0cf79e8b91f6992ba30e16a14a169ca1f8f`. Server info `0.0.0+uzpainter-ReleaseSafe`, protocol `2025-06-18`.
- **Machine.** RTX 4090, DX12, driver 32.0.16.1714. Painter was not used. The full gate's CPU suite was running concurrently, so timings are indicative only.
- **Clients.** The official MCP Python SDK (`mcp`, stdio and Streamable HTTP clients) on the system Python 3.13.9.
- **Where things are.** Every call log (`calls.jsonl`: arguments, reply, `isError`, seconds), script and UzPainter capture is in the session scratchpad, not in the repository. This report holds numbers and hashes only. Painter's maps were read from the private store and compared in memory.

## Inputs

| Input | Source | SHA-256 |
|---|---|---|
| `21-Bracal-Esquerdo-low-v2b.obj` | Assets3D `Skeletal Mage/Models3D/21-Bracal-Esquerdo/Export` (copied) | `08bf0197…a8035dc` |
| `21-Bracal-Esquerdo_Normal_OpenGL_v2b.png` (16-bit normal) | the same asset's `Textures` (copied) | `c7fb6d4c…87fbecd57` |
| `colour_grad.png` (512², RGB8) / `colour_grad_2048.png` (2048², RGB8) | generated (gradient + checker) | `a675c627…` / `4ac1f9e7…` |
| `grey_mask.png` (512², L8) / `grey_mask16_2048.png` (2048², L16) | generated (radial ramp) | `61c982f6…` / `9c8a9838…` |
| Wand v1 inputs (25) | staged by `stage_inputs` from the R9 request `phase1/tier1/wand-v1`. The OBJ is no longer in Assets3D; it came from the store by hash | as pinned by the manifest |

The test material is called "the stack" below:

- A `Base` fill on BaseColor, SpecularRoughness and BaseMetalness. Its colours are uniform: sRGB (0.5, 0.35, 0.2), 0.6 and 0.25.
- A `Detail` group holding a `Tex` fill:
  - BaseColor is the colour bitmap, with sRGB colour space.
  - Blending is Multiply at opacity 0.8.
  - It has a Black mask whose mask-stack fill is the grey bitmap.
  - A content Levels effect sets input 0.1–0.9 and gamma 1.2.

The texture set is 2048, with OpenGL normals and the Normal mesh map bound.

## Results by scenario

| # | Scenario | Result |
|---|---|---|
| 1 | AI client over MCP stdio (Legacy and OCIO) | Every tool call kept its contract. The full stack built, saved, closed and reopened with an identical `layer_list`. Document-map exports work with `passthrough` padding: PNG16, PNG8, EXR 32f and 16f, with no NaN or Inf. Captures, `batch`, invalid calls, retries and worker-kill recovery all work. **No export containing the Normal map succeeds on a real mesh, under any padding.** Bugs B1, B4–B6, B11–B13, B15 |
| 2 | `UzPainter.exe run` + `substance_painter` facade | The same stack through the facade is byte-identical to MCP only when the MCP client passes **Working** values. With `color_space: "sRGB"`, MCP gives a different BaseColor (B1). The facade refuses OCIO sRGB components outside its measured table; MCP accepts them |
| 3 | Assets3D Wand pipeline via the adapter | create, sync and capture work. The pinned export is a clean, explained refusal and writes nothing. A user export with `passthrough` (four document maps) **equals Painter's R9 r1 maps on every island-interior texel (0 differing on all four maps)** |
| 4 | Preview window | Standalone `--preview` works on OCIO (36 frames). On a Legacy project it opens and shows the decision-038 refusal. The attached `--mcp --preview` shows nothing until an `evaluate_channel` call (B7) |
| 5 | Robustness | Missing paths give structured errors. Truncated or non-database `.uzp` files are refused cleanly. A scribbled `.uzp` opens and is edited unnoticed (B9). Paths with non-ASCII characters work over MCP but fail on the command line, and a non-ASCII `run` argument crashes the process (B2, B3). 8192² works (about 1 min and 5.6 GiB per export). With two HTTP clients, the lease is not bound to the project's creator (B8). Ctrl+Break gives an abrupt exit on stdio and a clean one on HTTP (B14) |

### 1. AI client over MCP (official SDK, stdio)

`UzPainter.exe --mcp --output-root <dir> --ledger <file> --crash-dir <dir>`. The server lists 67 tools, 7 resources and 4 prompts. `capabilities` reports supported 546, release-gap 363, pending-evidence 656 and desktop-only-omitted 15. `status` reports `gpu_status: ready` and `python: disabled`.

The run used 78 calls per mode. Wall time was 2 min 05 s for Legacy and 2 min 03 s for OCIO. The OCIO project was created with `ocio_config_hash` `15059d4b…a5e30a43b7f4`.

- **Build and lifecycle.** `project_create` took 0.24 s and gave revision 1, with texture set `default` at 2048.
  - The stack took 15 mutations, 0.02–0.06 s each.
  - `project_save_as` (full, 10.5 MB) took 0.5 s.
  - `project_close`, `project_open`, `project_inspect`, `project_recipe` and `snapshot_layer_tree` all succeeded.
  - The revision and `layer_list` were identical before and after the reopen.
  - Every mutating reply carried `committed_revision`, `revision`, `receipt` and the `changed/created/hidden/imported/skipped/warnings` lists.
- **Exports.** These are `config` exports; files were read back with OpenCV and OpenEXR:

| Configuration | Legacy | OCIO |
|---|---|---|
| 5 maps (with `Normal_OpenGL`), passthrough, any format | `capability_gap`: virtualMap passthrough outside the islands is not recorded | same |
| any map set, `infinite` | `capability_gap`: islands do not cover the tile | same |
| `diffusion` / `color` / `transparent` without `dilationDistance` | `call_failed RuntimeError` (B6) | same |
| the same with `dilationDistance` 16 | `capability_gap`: not fitted | same |
| `size_log2` ≠ resolution (preset, 2048→1024) | `capability_gap`: resize partly fitted | same |
| 4 document maps, PNG16, passthrough | ok 12.6 s; BaseColor `f54acc10…`, Roughness 39321 (`458d836a…`), Metallic 16448 (`173c71ac…`), Height 32767 (`f1cc29df…`) | ok 10.9 s; BaseColor `28058eda…`, the other three identical |
| 4 document maps, PNG8 | ok 12.1 s; BaseColor `74c860ac…` | identical to Legacy |
| 4 document maps, EXR 32f | ok 9.4 s; BaseColor `6b1935fe…` (linear, min 0.1748), Height 0.0 | identical to Legacy |
| 4 document maps, EXR 16f | ok 10.0 s; BaseColor `ea5a1726…` | identical to Legacy |

  - The first OCIO run used the 512² bitmaps and the 8-bit mask. Under OCIO every export, capture, `material_views`, `region_stats` and `evaluate_channel` was then refused with `evaluator:unsupported_source`. Only 1:1 8-bit colour and 16-bit grey masks are recorded, so the 2048² inputs were used afterwards. Legacy accepted the 512² inputs.
- **Captures.**
  - `base_color` (PNG16 2048²) is byte-identical to the BaseColor export (`f54acc10…` Legacy, `28058eda…` OCIO). `channel:roughness` equals the Roughness export (`458d836a…`).
  - `mask:<uid>` is PNG16 with values 0–65535 (`688c1ecf…`).
  - `painter_viewport` 1024² on OCIO took 13.9 s (`878de763…`, DX12, camera `fit`, default environment `44dcbed0…`). It is refused on Legacy (B13). The `ref_match` preset fails, because the project has no stored environment (B12).
  - `channel:Roughness` and `channel:SpecularRoughness` fail (B11). `painter_iray` gives `PathTracerUnavailable`, as documented.
- **Diagnostics.** `isolate_layer` took 2.5–3.1 s, `material_views` 17–19 s, `region_stats` 8–16 s and `evaluate_channel` 0.7–5.5 s. A constant channel returns an empty payload with per-tile `constant` values; that is by design.
- **`batch`.** With `stop_on_error` and an invalid uid in the middle, the result was `stopped`, 2 executed, 1 failed, the third `not_executed`. Without it the result was `completed_with_errors`, 3 executed, 1 failed.
- **Invalid calls.** A bad enum, a string uid, a short colour array and an unknown preset each gave `invalid_arguments` with JSON-pointer details. An unknown tool gave `unknown_tool`. `project_close` with no project open gave `project_error`.
- **Retries and jobs** (separate session).
  - A replayed key gave the same outcome. The same key with other arguments gave `idempotency_conflict`. A stale `expected_revision` gave `stale_revision`. A key without `expected_revision` gave `invalid_arguments`.
  - An asynchronous `project_create` followed by `job_status`, `wait_idle`, `job_result` and `job_list` worked (B15 aside).
  - `job_cancel` on a running export left it `cancelled`, `stopped: before_commit`, with no files.
  - All 5 resources and 2 prompts read correctly.
- **Worker kill.** `taskkill /F` on the worker (Release has no fault hooks). The next `status` answered at once. The next mutation committed (revision 20→21) on worker generation 2, and `layer_list` was intact.

### 2. `run` script with the facade versus MCP

`UzPainter.exe run s2_paint.py args.json` builds the same stack through `substance_painter`, then calls `export_project_textures` with the same 4-map PNG16 passthrough configuration. The run took 12.6 s and exited 0 with `ExportStatus.Success`.

| Comparison | BaseColor | Roughness / Metallic / Height |
|---|---|---|
| Legacy: MCP (`sRGB` tag) versus `run` | **differs on all 4,194,304 texels**; max 18755 codes; corner texel MCP (48360, 41122, 31840) versus run (32893, 22895, 13128) | identical |
| Legacy: MCP with the facade's Working values (0.214041, 0.100482, 0.033105) versus `run` | identical `56b1e9e1…` | identical |
| OCIO: `run` with sRGB (0.5, 0.35, 0.2) | refused: `NotYetSupported`, component 0.35 is not recorded (decision 202) | — |
| OCIO: `run` with (128, 89, 51)/255 versus MCP with the facade's Working values (0.215861, 0.099899, 0.033105) | identical `c53189f6…` | identical |

The recipes differ only in the `Base` BaseColor source and in the mask bitmap's colour-space tag:

- MCP stores `{rgb: [0.5, 0.35, 0.2], color_space: "sRGB"}`; the facade stores `{rgb: [0.2140…], color_space: "Working"}`.
- The mask bitmap is tagged `""` by MCP and `Data` by the facade. The output is the same.

The engine agrees byte for byte, so the difference is in what MCP `source_set` does with a colour space (B1).

### 3. Assets3D Wand pipeline through the adapter

This scenario uses `tests/adapters/assets3d/wand.py`'s `Wand`, unchanged, with the R9 request manifest. The work directory was in the scratchpad, and nothing was written under Assets3D.

| Step | Exit | Time | Result |
|---|---|---|---|
| `painter_create.py` via `client.py execute_python` | 0 | 0.73 s | set `11-Varinha-Madeira`, maps AO and Normal, `Resolution(2048, 2048)` |
| `painter_layer_stack.py sync` | 0 | 2.38 s | 13 layers, 14 masks imported, 0 hidden, group height blend LinearDodge |
| `run painter_export.py` (pinned: infinite padding, 5 maps) | 1 | 1.12 s | `NotYetSupported`: BaseColor `infinite` on a set whose islands do not cover the tile is not fitted (R-090, decision 090). The traceback names the export call, and the output folder holds no file. **A clean, explained refusal** |
| `painter_layer_stack.py capture --out …` (1700×1250, the shim) | 0 | 46.9 s | PNG16 1700×1250 `f22b9da6…`, no NaN |
| user export: same 5 maps, `passthrough` | 1 | 0.76 s | refused: Normal virtualMap passthrough outside the islands |
| user export: 4 document maps, `passthrough`, PNG16 | 0 | 39.9 s | `ExportStatus.Success` |

The comparison below is against Painter's R9 r1 maps from the private store. Painter's maps were exported with `infinite` padding, so only covered texels are comparable. Coverage is the OBJ's UV triangles rasterised at texel centres: 511,295 texels. The "interior" is that coverage eroded by 2 texels: 498,687 texels.

| Map | Painter r1 SHA-256 | UzPainter SHA-256 | Interior differing / max | Covered (incl. border) differing / max |
|---|---|---|---|---|
| BaseColor | `d90f391b…` | `f5202163…` | **0 / 0** | 2,916 / 27,787 |
| Roughness | `75f96466…` | `24171dfa…` | **0 / 0** | 1,439 / 18,761 |
| Metallic | `a7032d32…` | `9cd65935…` | **0 / 0** | 748 / 33,410 |
| Height | `c6dad51f…` | `e893061d…` | **0 / 0** | 853 / 42 |

The border differences sit only on edge texels. Those are where an approximate rasteriser's coverage meets Painter's padding, which is expected with a different padding. Outside the islands the maps differ, as `passthrough` versus `infinite` predicts.

### 4. Preview window

| Case | Result |
|---|---|
| `--preview bracal-ocio.uzp --gpu-backend dx12` | window "UzPainter preview - bracal-ocio.uzp", 976×639. The model rendered with the side panel and orbit hints. Closed with WM_CLOSE: `UZP_JSON:{"frames_rendered":36,"last_error":"","revision_shown":21,"status":"closed"}`, exit 0. `PrintWindow` returns black for the DX12 swap chain, so a screen copy was used |
| `--preview bracal-legacy.uzp` | the window shows the decision-038 refusal. The side panel still reads "display: OCIO, Painter's substance config". Exit 0 with `frames_rendered: 0` and `revision_shown: -1` (B13) |
| `--mcp --preview`, `project_open` then wait 12 s | the window reads "waiting for the first evaluation"; `preview_status` gives `frames_published: 0` |
| then `source_set` (BaseColor to green) and wait 8 s | no change; `frames_published: 0` |
| then `evaluate_channel BaseColor` | renders revision 22 with the green BaseColor only (no normal detail). `frames_published: 1` |
| then `project_close` | the window keeps showing revision 22 (B7) |

### 5. Robustness

| Case | Result |
|---|---|
| `project_create` / `project_open` / `project_inspect` on a missing file | `project_error` "cannot read …" / "no such file"; `call_failed` "is not a file". Clean |
| `resource_import` / `set_mesh_maps` with a missing PNG | `call_failed ResourceNotFoundError`. Clean |
| `.uzp` truncated to 1/3 | open and inspect: "corrupt: … database disk image is malformed". Clean |
| `.uzp` with a bad header / empty / plain text | "not_a_project: … file is not a database" / "has no meta table". Clean |
| `.uzp` with 64 KiB overwritten mid-file (SQLite `integrity_check` fails) | **opens, lists, exports, accepts a mutation and an incremental save.** `capture` then fails "corrupt: blob c7fb6d4c…", and a full save or `save_as` fails at `VACUUM INTO` (B9) |
| Unicode and spaces over MCP (`dir with spaces\ação ☃ 日本\malha bracal ☃.obj`, resource `cor ☃`, layer `Camada ☃ ação`, `save_as projeto ☃.uzp`, reopen) | all ok. The capture path `../escape.png` and an absolute path outside the output root give `invalid_arguments` |
| Unicode on the command line: `inspect`, `run <script ☃.py>` | **fail**: path mangled to `a��o ? ??` (B2). The same commands with an ASCII path that contains spaces work |
| `run script.py "ação ☃"` | **crash**: `libc++abi: terminating … pybind11::error_already_set: UnicodeDecodeError`, exit `0xC0000409`, no `UZP_JSON` line (B3) |
| `set_resolution` 16384 / 3000 / 0 | `invalid_arguments` (enum). Clean |
| 8192² Legacy set, fill + 16-bit mask, `size_log2` 13 | PNG8 66.3 s, PNG16 69.4 s, EXR 32f 54.6 s. Worker peak RSS 4.5–5.6 GiB. Values sane, no NaN. `capture base_color` 78.8 s. `size_log2` 14 gives `invalid_arguments` |
| Two clients over `--mcp-http 127.0.0.1:<port> --token …` | a wrong token gets HTTP 401. Both clients read `status`. A mutation without a lease gives `lease_required`. B holding the lease gives `lease_held` to A. After `lease_release`, the next owner works. **The client that created the project did not hold its lease** (B8) |
| Ctrl+Break on `--mcp-http` | exit 0, worker gone |
| Ctrl+Break on stdio `--mcp` (idle, or with a saved project open) / on `run` | exit `0xC000013A` within 0.25 s, worker gone. `.uzp.lock` and ledger `-wal/-shm` are left behind. The next `project_open` recovers the stale lock and shows the unsaved committed edit (B14, B10) |
| CLI usage errors | `--gpu-backend metal` exits 2. `run` of a missing script exits 1 with `FileNotFoundError` in `UZP_JSON`. `--preview` on a missing or truncated file exits 1 |

## Bugs and inconsistencies

Severity: **High** means silently wrong output or a crash on normal input. **Medium** means a contract or robustness gap a client will hit. **Low** means a usability or documentation issue. **Info** means something to confirm.

| ID | Severity | Finding | Suspected component |
|---|---|---|---|
| B1 | High | MCP `source_set` with `{kind: uniform_color, color, color_space: "sRGB"}` stores the values as working (linear) values and keeps `sRGB` only as a tag. The facade's `set_source(ch, Color(r, g, b))` decodes sRGB to Working before storing. The same instruction therefore gives a double-encoded BaseColor over MCP: a uniform sRGB 0.5 exports as 48360/65535 (0.738) instead of 32893 (0.502). Under OCIO, MCP also accepts components the facade refuses (0.35 is not in Painter's measured table, decision 202), producing values nobody has measured. Nothing is reported. The schema says "colour space of a uniform colour (sRGB, Working, Raw, …)", which invites exactly this call | `src/supervisor/typed_tools.cpp` `source_set` → native `set_source` (`src/python/bind_layerstack.cpp:232` keeps the tag), compared with `python/uzpainter_facade/colour.py` `stored_color` and `ocio_srgb_to_linear` |
| B2 | High | CLI verbs do not open non-ASCII paths: `inspect`, `run <script>` (and presumably `export` and `--preview`, which share the argv path) report "is not a file" / "cannot read" with the path mangled (`ação ☃ 日本` → `a��o ? ??`). The same files work over MCP | `src/main.cpp` argv decoding: ANSI `main` argv instead of the wide command line |
| B3 | High | `UzPainter.exe run script.py "ação ☃"` aborts with `libc++abi: terminating due to uncaught exception of type pybind11::error_already_set: UnicodeDecodeError`, exit `0xC0000409`. There is no `UZP_JSON` line, so it is none of the documented exits 0/1/2/3 | `src/python/run.cpp` building `sys.argv` (ANSI bytes decoded as UTF-8, exception not caught) |
| B4 | Medium | Release gaps are reported under three codes. Export padding and resize gaps are `capability_gap {tool, type, reason}` (11 §7). The evaluator's `NotYetSupported` (`evaluator:unsupported_source`, OCIO bitmap sampling) is `call_failed` in `export`, `capture`, `material_views` and `region_stats`, and `request_failed` in `evaluate_channel`. A client cannot detect a gap uniformly | worker error mapping in `src/supervisor/typed_tools.cpp` / `worker.cpp` |
| B5 | Low | Under OCIO, `source_set` with a bitmap the evaluator will refuse (an 8-bit colour bitmap not at 1:1, an 8-bit grey mask) commits with empty `warnings`. Every later export, capture and diagnostic then fails | `source_set` admission (no evaluator support check) |
| B6 | Medium | `paddingAlgorithm` `diffusion`, `color` or `transparent` without `dilationDistance` fails as `call_failed RuntimeError` "the parameter dilationDistance is undefined …". The call is malformed, so it should be `invalid_arguments`, or Painter's default should be applied if it has one | export configuration resolution (`src/export/`) |
| B7 | Medium | The attached preview (`--mcp --preview`) renders nothing after `project_open` or after edits; it publishes only on `evaluate_channel`. It then shows only the channels evaluated (BaseColor without the normal detail), and keeps showing a closed project. This matches `src/preview/PREVIEW.md` but not what an operator expects, nor `docs/architecture/07-preview-and-render-parity.md` §6 ("renders painter_viewport at a low rate on its own thread") | `src/supervisor/worker.cpp` publish points, `src/preview/` |
| B8 | Medium | HTTP lease: A calls `lease_acquire {owner: "client-A"}` with no project open (gets `lease: null`), then A's `project_create` succeeds. B's `lease_status` now shows `owner: null`, B's `lease_acquire` succeeds, and A's next `layer_insert` gets `lease_held {holder: "client-B"}`. The project's creator is locked out by a client that did nothing | `python/uzpainter_supervisor/admission.py` (lease bound to `project_uuid`, not carried to the created project) |
| B9 | Medium | A structurally corrupt `.uzp` (64 KiB overwritten; `PRAGMA integrity_check` reports "Tree 5 page 2556 cell 0: invalid page number …") opens with no warning, exports, accepts `layer_insert` (revision 22) and `project_save` incremental. The damage surfaces only when the broken blob is read (`capture`: "corrupt: blob c7fb6d4c…") or at `VACUUM INTO`. Writing into a damaged database risks worse loss | `src/store/` open path (no integrity check or quick_check on open) |
| B10 | Medium (design question) | `project_close` on a saved project with unsaved edits needs no `discard` and keeps the edits. `current` stays at the last committed revision (21 against `save-20`), and `project_open`, `inspect` and `--preview` all show the unsaved state. Painter discards unsaved changes on close. This is designed (09 §4: "the file at rest always holds the last committed revision"), but a facade script that closes and reopens to undo gets a different document from Painter | `src/store` checkpoint `current` against the facade `project.close` contract |
| B11 | Low | `capture` mode `channel:<name>` takes the export documentMap identifier (`roughness`, `specularroughness`, case-sensitive). `evaluate_channel` and `source_set` take ChannelType names (`SpecularRoughness`). `channel:Roughness` on a stack without Roughness says "the documentMap spelling "Roughness" is not recorded (decision 085)", not that there is no such channel | `src/python/capture.cpp` mode parsing; the tool description in `src/supervisor/worker.cpp:515` |
| B12 | Low | `capture painter_viewport` with `preset: "ref_match"` fails with "the project stores no environment 77eeed8d… (import its file with …)". Neither the reply nor the tool description says which file that is or where it lives, so an MCP client cannot use the standard preset | `uzpainter.render.display.apply_preset` message; `display_*` tool docs |
| B13 | Low | On Legacy projects the viewport capture and the preview are refused (decision 038). The README's "What works today" does not say they need OCIO. The preview's side panel shows "display: OCIO, Painter's substance config" on a Legacy project, and exits 0 with `frames_rendered: 0` | `README.md`; `src/preview/` panel text |
| B14 | Low | Ctrl+Break on the stdio supervisor or on `run` ends the process with `0xC000013A` (not in the documented exit set 0/2/3/4), leaving `.uzp.lock` and ledger `-wal/-shm`. The HTTP supervisor exits 0 cleanly. Stale-lock recovery on the next open works | `src/supervisor/supervisor.cpp`, `src/python/run.cpp` console control handling |
| B15 | Low | `job_status`, `job_list` and `job_result` of a succeeded `project_create` report `progress: 0.0`. `batch`'s reply has no `receipt` or top-level lists, unlike every other tool. `project_create`'s top-level `revision` is `null` while `committed_revision` is 1 | `python/uzpainter_supervisor/registry.py` / ledger |
| B16 | Low | `UzPainter.exe --help` exits 2. Its usage omits `--preview`, `--mcp-http`, `--token`, `--roots` and `--ledger` | `src/main.cpp` usage text |
| B17 | Info | For the same stack, PNG8 and EXR 32f/16f are identical between Legacy and OCIO, but PNG16 BaseColor differs by 1 code on 2,272,423 of 4,194,304 texels (`f54acc10…` against `28058eda…`). It needs confirming that Painter's OCIO 16-bit sRGB encode really differs from Legacy here; no Painter record was compared | `src/export` OCIO PNG16 encode |
| B18 | Info (known gaps, practical impact) | On a real mesh, no export that contains a Normal map (virtualMap `Normal_OpenGL`) can be produced. `passthrough` outside the islands is not recorded. `infinite` is not fitted on islands. Dilation is not fitted, and any `sizeLog2` other than the resolution is refused. Only document maps with `passthrough` export. The pipeline's own export, and the `assets3d-inline-five-map` preset at any size other than native, cannot run today | `parity/semantics/export-processing.json` entries `padding-islands`, `padding-dilation`, `resize` |
| B19 | Low (performance) | Exports re-evaluate the stack on every call: 9–12 s per 2048² four-map export, and 55–70 s per 8192² export with a 5.6 GiB worker. The adapter's viewport capture takes 47 s. `material_views` and `region_stats` take 8–19 s at 2048² | CPU evaluator; no evaluation cache across calls at one revision |

## Repro steps

All steps start a fresh `UzPainter.exe --mcp --output-root <out>` with the SDK's stdio client, unless noted. `<mesh>` is any OBJ; `<proj>` is a saved `.uzp`.

- **B1.**
  1. `project_create {mesh}`.
  2. `layer_insert {kind: fill, params: {active_channels: [BaseColor]}}`.
  3. `source_set {uid, channel: BaseColor, source: {kind: uniform_color, color: [0.5, 0.35, 0.2], color_space: "sRGB"}}`.
  4. `export` of `basecolor` at PNG16 with passthrough. A texel reads (48360, 41122, 31840).
  5. Repeat the build with `UzPainter.exe run`: `fill.set_source(ChannelType.BaseColor, colormanagement.Color(0.5, 0.35, 0.2))`. It reads (32893, 22895, 13128).
  6. Passing `color: [0.21404114, 0.10048152, 0.03310476], color_space: "Working"` over MCP makes the files byte-identical.
- **B2.** `UzPainter.exe inspect "C:\tmp\ação ☃\p.uzp"` (an existing file) gives "is not a file". `UzPainter.exe run "C:\tmp\ação ☃\s.py"` gives `FileNotFoundError`.
- **B3.** `UzPainter.exe run C:\tmp\s.py "ação ☃"`, where `s.py` is `result = 1`, aborts with exit `0xC0000409`.
- **B4.**
  1. On an OCIO project (`ocio_config_hash 15059d4b…`), set a fill's BaseColor to a 512² 8-bit bitmap on a 2048 set.
  2. `export` (document maps, passthrough) gives `call_failed`.
  3. `evaluate_channel {channel: BaseColor}` gives `request_failed`.
  4. Compare with `export` with `padding: infinite`, which gives `capability_gap`.
- **B5.** The same as B4: step 1's `source_set` reply has `warnings: []`.
- **B6.** `export {config}` with `exportParameters[0].parameters = {paddingAlgorithm: "diffusion"}` and no `dilationDistance` gives `call_failed RuntimeError`.
- **B7.** `UzPainter.exe --mcp --preview …`:
  1. `project_open {path: <OCIO proj>, wait: true}`. After 12 s, `preview_status` shows `frames_published: 0`.
  2. `source_set …`. After 8 s, still 0.
  3. `evaluate_channel {channel: BaseColor}`. `preview_status` shows `frames_published: 1`, `revision_shown` = the current revision.
  4. `project_close`. The window still shows the model.
- **B8.** `UzPainter.exe --mcp --mcp-http 127.0.0.1:<port> --token T`, with two `streamablehttp_client` sessions A and B:
  1. A: `lease_acquire {owner: A}`, then `project_create {mesh, wait: true}`.
  2. B: `lease_acquire {owner: B}` succeeds.
  3. A: `layer_insert {kind: fill}` gives `lease_held {holder: B}`.
- **B9.**
  1. Copy `<proj>` and overwrite 64 KiB at offset size/2 with `0xAB`.
  2. `project_open` succeeds, `layer_insert` commits and `project_save {mode: incremental}` succeeds.
  3. `capture {mode: painter_viewport}` gives "corrupt: blob …". `project_save {mode: full}` gives "corrupt: compact … VACUUM INTO".
- **B10.** `project_open <proj>` → `layer_set {uid, name: "x"}` → `project_close` (no `discard`) → `project_open <proj>`. The layer is named "x". `inspect <proj>` shows checkpoint `current` > the last `save-N`.
- **B11.** `capture {mode: "channel:SpecularRoughness", path: "a.png"}` fails; `capture {mode: "channel:specularroughness", …}` works.
- **B12.** On an OCIO project: `capture {mode: painter_viewport, size: [512, 512], preset: "ref_match", path: "a.png"}`.
- **B13.** `UzPainter.exe --preview <Legacy proj>`, then close the window: exit 0, `frames_rendered: 0`.
- **B14.**
  1. Start `UzPainter.exe --mcp` with `CREATE_NEW_PROCESS_GROUP` and open a saved project.
  2. Send `CTRL_BREAK_EVENT`. Exit `0xC000013A`, and `<proj>.uzp.lock` remains.
- **B15.**
  1. `project_create {mesh}` without `wait`, then `job_status {job_id}`: `status: succeeded, progress: 0.0`.
  2. `batch {calls: [...]}`: the reply keys are `result` and `committed_revision` only.
- **B16.** `UzPainter.exe --help` exits 2.

## Not covered

- **Worker fault hooks** (`--test-faults`, `test_fault`). They exist only in Debug builds. Recovery was exercised with `taskkill` instead.
- **`painter_iray`.** It is a documented release gap.
- **Painter-side comparisons other than the Wand R9 r1 maps.** Painter was in use by the owner.
- **Painter's Normal map for the Wand.** UzPainter cannot export it (B18).
- **The sync step of scenario 3 through the typed MCP `sync_stack`.** The adapter was used, as the scenario asked.
