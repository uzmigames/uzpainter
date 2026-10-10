# 01 — UzPainter architecture proposal (Claude, round 1, 2026-10-10)

Independent position paper for the fourteen open decisions. Written before reading Astra's paper. Labels: **Fact** (with path), **Hypothesis** (inferred, not verified), **Recommendation** (my position). Effort figures are Hypotheses. Paths: `UZP` = `E:\UzmiGames\UzPainter`, `A3D` = `E:\UzmiGames\Assets3D`, `UZE` = `E:\UzmiGames\UzEngine`, `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`.

## 0. Executive summary

1. **Recommendation:** one `UzPainter.exe` (C++, Zig-built against a pinned, clean UzEngine commit) that embeds CPython 3.13 and hosts the MCP server in-process on the official Python SDK. No second process; one GPU thread; synchronous API; checkpoints for crash recovery.
2. **Recommendation:** two Python surfaces on one core: the native `uzpainter` package and a `substance_painter` compatibility shim so `painter_create.py`, `painter_layer_stack.py` and `painter_export.py` run with no edits other than the host.
3. **Recommendation:** parity is a contract, not a hope. Phase 0 records golden outputs from the installed Painter 12.1.0 (micro-tests per blend mode, mask operation, projection, export option) and derives the exact formulas; the evaluator reproduces Painter's per-channel storage formats so fixed-point channels match to the LSB. Float channels and renders get owner-approved tolerances.
4. **Fact:** Painter's procedural content runs on the proprietary Substance Engine (`PAINTER\substance_linker.dll`, `substance_sse2_blend.dll`, `substance_vk_sal.dll`) and cannot be executed by UzPainter. **Recommendation:** frozen bitmap captures for static grunges/textures, HLSL reimplementations calibrated against Painter for mesh-map generators and the six smart masks and two smart materials the pipeline uses; parity per asset is measured and published.
5. **Fact:** Painter's viewport shaders ship as GLSL source in the install (`PAINTER\resources\starter_assets\shaders\*.glsl` and the library in `PAINTER\resources\shader-doc\lib-*.html`, ~346 K characters of code). **Recommendation:** a small forward "parity viewport" in HLSL derived from them is the render-parity target; Iray is declared out of reach; UzEngine's deferred renderer is the engine-preview mode, not the parity oracle.
6. **Recommendation:** CPU Embree baker first (deterministic, runs on any machine, same ray-tracing library Painter ships), DXR later as an accelerator behind the same interface; external Blender normal/AO remain first-class inputs.
7. **Recommendation:** project file = ZIP container with a JSON recipe, content-addressed original resource bytes and zstd-compressed mesh maps; no raster cache by default. Expected ≤ 10 % of the `.spp` baseline for the same content (Hypothesis, to be measured on the body piece).
8. **Recommendation:** pilot = 11-Varinha-Madeira v1, then 23-Cinto v5, then the approved 18-Tunica v10 as the recovery proof; the owner decides tolerance policy, the legal stance on the shader port and asset names, and the UzEngine baseline before Phase 1 starts.

## 1. System context

### 1.1 Components

| Component | Language / host | Responsibility | Reuses |
|---|---|---|---|
| `uzp_core` document model | C++ | Project, texture sets, stacks, channels, layer/effect tree, sources, projections, masks, geometry masks, anchors, instances, smart presets; stable 64-bit node ids persisted in the file; JSON (de)serialisation | nlohmann/json (`UZE\runtime\thirdparty`) |
| Resource store | C++ | Content-addressed blobs (SHA-256) for imported images, meshes, HDRIs, presets; original bytes kept; decoded rasters cached in RAM/VRAM only | xxHash/zstd/libpng/spng/tinyexr (vendored in UzEngine) |
| Mesh module | C++ | OBJ/FBX/glTF import into a texturing mesh (no `.uzmesh`), MikkTSpace tangents (per-vertex or per-fragment), UV/TBN certification, UV-space rasterisation (position/normal/tangent/island/ID buffers), high-poly streaming into Embree | `mikktspace.c`, ufbx, fastgltf (vendored), own OBJ parser |
| Evaluator | C++ + generated HLSL compute | Lazy, cached evaluation of every channel of every stack; one kernel per node type; explicit per-channel storage formats mirroring Painter's `ChannelFormat`; dilation; height→normal; normal blending | UzEngine RHI (DX12; WARP for CI), `ShaderPipeline::LoadBytecodeFromSource` |
| Baker | C++ (Embree) | 10 mesh maps with Painter's parameter names; cage/distance/match-by-name; subsampling; dilation; RAW + coverage + miss evidence | Embree 4 (new vendored dependency) |
| Exporter | C++ | Painter JSON export config, presets, wildcards, padding, dithering, resize, PNG 8/16, EXR, TGA/BMP/JPEG, DDS BC7/BC5/BC4, `.uztexture` + `.uzmat` | libpng, tinyexr, stb, etcpak, `WriteUzTexture` |
| Renderers | C++/HLSL | (a) parity viewport: forward pass derived from Painter's shader library; (b) engine preview: UzEngine `SceneRenderer` with the exported UzEngine material | UzEngine RHI + `SceneRenderer` |
| Capture | C++ | Offscreen render → readback → PNG with explicit camera/resolution/state; FLIP + per-map diff | `FlipPass`, `ImageDiff`, own `TextureReadback` |
| Jobs | C++ | Job ids, progress, cancellation, terminal status; busy flag; single-writer document lock | `JobSystem` |
| Project IO | C++ | Atomic save (temp + rename), previous checkpoint kept, autosave, `inspect` without opening | miniz/zip (vendored via tinyexr's miniz or libzip — to decide) |
| `uzpainter` module | C++ (pybind11, linked into the exe) | Native Python API mirroring Painter's modules | CPython 3.13 embeddable |
| `substance_painter` shim | Python | Painter-named namespace over `uzpainter`; event dispatcher pumped per call; `bake_async`/`StopSource` emulation | — |
| `uzpainter.mcp` | Python (official MCP SDK, pinned) | stdio server (default) and optional loopback Streamable HTTP; ~25 high-level tools, resources, prompts; job tools | — |
| `uzpainter.cli` | Python | `run script.py`, `export`, `bake`, `capture`, `inspect`, `selftest` with prefixed JSON lines for CI | convention from `UZE\runtime\tools\uzengine.cpp` |
| Preview window | C++ | Optional read-only window on its own thread; never pauses evaluation; no input handling beyond close | `platform/windows/platform_window.h` |

### 1.2 Process and thread boundaries

**Recommendation:** one process.

- **Main thread**: command loop (MCP server event loop, or the Python script, or the CLI). Owns the CPython interpreter.
- **Engine thread**: owns the RHI device, the evaluator caches and the document lock for GPU-side work. Receives commands from a queue; all document mutations are serialised through the document lock (cheap CPU mutations happen on the caller's thread under the lock; GPU evaluation happens on the engine thread when a consumer asks for results).
- **Job pool** (`JobSystem`): Embree baking, encoders, mesh import.
- **Preview thread** (optional): window message loop and a low-rate render that reads the last completed evaluation through a double buffer; it cannot block or pause evaluation (lesson `A3D\Docs\Pipeline\Licoes\operacao-painter-exclusivo-modo.md`).

Python calls release the GIL around engine work (`py::gil_scoped_release`). MCP tool bodies run in a thread executor so progress notifications and cancellation flow while a bake runs.

Crash isolation: SEH + minidump (`UZE\runtime\platform\windows\crash_handler.h`); an autosave checkpoint is written after every mutating command (throttled); device-removed errors are reported as job failures, the CPU-side document survives, and the host can relaunch with `--open <autosave>`. A worker-process split is not needed in v1; the command queue is the natural boundary if it becomes needed (see D1 reversal cost).

### 1.3 Data flow

```mermaid
flowchart LR
  subgraph Assets3D["Assets3D (unchanged tools)"]
    OBJ[low OBJ + usemtl] --> UZP
    HI[high OBJ/FBX] --> UZP
    NRM[Blender normal/AO PNG16] --> UZP
    MASKS[M_*.png / T_*.png] --> UZP
    STACK[stack JSON / smart JSON] --> PY[painter_layer_stack.py via substance_painter shim]
    PY --> UZP
  end
  subgraph UZP["UzPainter.exe"]
    IMP[Mesh import + certification] --> RAS[UV raster]
    RAS --> EVAL[Evaluator]
    BAKE[Embree baker] --> EVAL
    EVAL --> EXP[Exporter]
    EVAL --> VP[Parity viewport / engine preview]
    VP --> CAP[Capture PNG]
    DOC[(project.uzpaint)] <--> EVAL
  end
  EXP --> PNG16[PNG16 maps for Blender deliver/paintrender]
  EXP --> UE[Unreal: BaseColor / ORM / Normal-DX (PNG, DDS BC7)]
  EXP --> UZE[UzEngine: .uztexture BC7/BC5/BC4 + .uzmat]
  CAP --> GATE[Gate boards / FLIP]
  MCP[AI host] -- stdio MCP --> UZP
```

## 2. Decisions

### D1 — Runtime topology

**Options considered**
1. Single C++ `.exe` hosting UzEngine + embedded CPython + MCP server (Python SDK in-process).
2. Single C++ `.exe` with a native C++ JSON-RPC/MCP implementation; Python optional.
3. Python host (`python.exe`) loading the engine as a DLL; MCP in Python.
4. Separate processes: thin MCP front + engine worker (fork-style containment as in `UZE\extension\src\runtime-client.ts`).

**Position:** Option 1. `UzPainter.exe --mcp` is what the AI host spawns; the same exe runs scripts (`run`), the CLI and the optional preview window. CPython 3.13 (the version Painter 12.1 ships — **Fact**, `PAINTER\python313.dll`, `UZP\docs\analysis\substance-parity\01-python-api-inventory.md` §1), conventional GIL build, pybind11 for embedding and bindings, the `uzpainter` module compiled into the exe (`PyImport_AppendInittab`), no separate `.pyd`. Transports: stdio default; loopback Streamable HTTP optional for a resident instance (`--mcp-http 127.0.0.1:<port>`).

**Rationale**
- The MCP tools are written once on top of the Python API that scripts also use, so there is one code path from MCP to core (the "never a second code path" rule in `UZP\docs\analysis\uzengine-renderer\08-mcp-and-ipc-patterns.md` §5).
- The official Python SDK gives schema generation, progress, cancellation and, when the pinned release supports it, the Tasks extension (**Fact** that the extension exists, `UZP\docs\analysis\technology-options\04-mcp-server-options.md`; **not confirmed** which SDK release/Claude client supports it, per `UZP\docs\analysis\reviews\technology-options-astra-review.md` finding 26).
- Option 2 means maintaining a protocol implementation in C++ with no official SDK (**Fact**, no official C++ SDK in the inspected SDK list, same review finding 27).
- Option 3 ties the product to a Python launcher; the owner asked for a standalone exe (**Fact**, `UZP\README.md` → "Standalone `.exe` — one Windows executable anyone can run locally").
- Option 4 adds IPC serialisation of large images and a second lifecycle; the Painter crashes the pipeline suffered were inside Adobe's code (`A3D\Docs\Pipeline\Licoes\operacao-painter-export-mixed-ao.md`); our own faults are better handled by checkpoints than by a relay process.
- Astra's review finding 29 (same file) shows the subprocess-MCP topology of the technology-options document is incoherent (who owns the renderer); Option 1 answers it: the exe owns everything.

**Threading, GIL, crash isolation:** see §1.2.

**Risks**
- A native fault in a tool handler kills the process (mitigated by autosave checkpoints and relaunch; measured recovery time becomes a test).
- Embedded Python + vendored MCP SDK dependency tree (pydantic, anyio, httpx) increases the distributable (size not confirmed; measured in Phase 0).
- asyncio event loop starvation if a tool blocks on the loop thread (prevented by executor threads; tested).

**Cost to reverse:** low to medium. Moving the MCP server into a front process keeps the Python API; the command queue already isolates the engine thread. Replacing the Python MCP by a C++ one changes only `uzpainter.mcp`.

### D2 — API scope for v1

**Options considered**
1. Mirror all 572 public symbols.
2. Mirror the 16 non-UI modules; omit `ui`, `js`, `substance_painter_plugins`; omit UI-only symbols inside kept modules.
3. Mirror only what the pipeline calls today.

**Position:** Option 2, with Option 3 as the order of implementation. Kept modules: `application`, `async_utils`, `baking`, `colormanagement`, `display`, `event`, `exception`, `export`, `layerstack`, `levels`, `logging`, `project`, `properties`, `resource`, `source`, `textureset`. Omitted: `ui.*` (PySide6), `js.evaluate`, `substance_painter_plugins.*`, `layerstack.get_selected_nodes/set_selected_nodes/get_selection_type/set_selection_type`, `GroupLayerNode.is_collapsed/set_collapsed`, `Resource.show_in_ui`, `show_resources_in_ui`, `event.GraphicalUserInterfaceStarted`, `TextureStateEvent` throttling.

**Decision rule (Recommendation):** a symbol may be omitted only if, in Painter, calling it changes no exported texture and no rendered pixel (**Fact** for the list above: they drive Qt widgets, selection highlight, collapse state or plugin loading; sources `PAINTER\resources\python\modules\substance_painter\ui.py`, `layerstack.py` selection section, inventory `UZP\docs\analysis\substance-parity\01-python-api-inventory.md`). Omitted symbols exist in the shim and raise `uzpainter.UnsupportedInUzPainter` with the reason; nothing is silently a no-op. Paint strokes are not reachable from Painter's Python API at all (**Fact**, `layereffect\paint.html` quoted in the inventory §3), so `insert_paint` creates an empty paint layer/effect that evaluates as transparent, exactly as Painter does for an unpainted layer; stroke painting is out of v1 scope (G-02's paint standard uses fills only, `A3D\AGENTS.override.md` → "Paint standard").

Gaps Painter leaves to the JS API that affect output get native UzPainter symbols: `display.get/set_shader_parameters` (double-sided, etc. — the pipeline set `doubleSided` on the tunic, **Fact** `A3D\...\18-Tunica\report.json` per `UZP\docs\analysis\assets3d-pipeline\02-painter-usage.md` §5), `display.set_exposure/set_environment_rotation/set_environment_opacity/set_shadows` (today driven through Qt widgets, same file §10), `display.capture(path, camera, size)` (Painter only has the private `save_viewport`).

**Rationale:** the pipeline's live call set (`UZP\docs\analysis\assets3d-pipeline\02-painter-usage.md` §4) is a strict subset of Option 2; Option 1 would spend effort on Qt and plugin machinery with no output effect.

**Risks:** a script that depends on an omitted symbol fails loudly (intended). Resource-shelf semantics differ (no Adobe starter assets; see D4) — scripts that search by Adobe asset names need the alias shelf.

**Cost to reverse:** low; omitted symbols can be added without changing kept ones.

### D3 — Layer stack model and compositing semantics

**Options considered**
1. Reimplement Painter's model one-to-one (texture set → stacks → channels; layer tree with content-effect stack and mask stack; per-channel blend/opacity).
2. A simpler fills-and-masks model matching only the paint standard.
3. A generic node graph (material-graph style) with layers as sugar.

**Position:** Option 1. Data model (persisted as JSON in the project):

- `TextureSet { id, name, original_name, resolution, uv_tiles[], mesh_maps{usage → resource_ref + provenance}, stacks[] }`
- `Stack { id, name, channels{ type → { format, label } }, root_layers[] }` — formats are Painter's nine `ChannelFormat` values (**Fact**, `UZP\docs\analysis\substance-parity\02-layer-stack-model.md` §6.2).
- `Layer (uid, kind ∈ {fill, paint, group, instance}, name, visible, blending{channel → {mode, opacity}}, content_effects[], mask?{background, enabled, effects[], blending{mode, opacity}}, geometry_mask, fill{source_mode, sources{channel → Source}, active_channels, projection, symmetry}, children[] (group), instance_source (instance))`
- `Effect (uid, kind ∈ {fill, paint, generator, filter, levels, compare_mask, color_selection, anchor}, blending, params…)`
- `Source ∈ {uniform_color{value, color_space}, bitmap{resource, color_space}, vector, font, procedural{asset, params, preset, image_inputs, output_mapping, resolution}, reference{anchor, channel_mapping, alpha_matte, levels}}`
- Smart material = serialised group subtree; smart mask = serialised mask-effect list (as Painter: **Fact** `insert_smart_material` returns a `GroupLayerNode`, same analysis §11).
- UV tiles: a `tile` dimension on every raster from day one; v1 ships `ProjectWorkflow.Default` only and refuses UVs outside 0–1 with a clear error (the pipeline is single-tile; **Fact** `A3D\Docs\Pipeline\MCP\substance-painter-mcp-local.patch`).

Compositing semantics (Recommendation, to be confirmed by the Phase 0 micro-tests):
- Per stack, per channel, bottom-up: `acc = blend(mode_c, acc, layer_c, opacity_c × mask)`; groups composite children into a temporary and blend the temporary with the group's per-channel mode/opacity (`PassThrough` = children blend directly into `acc`).
- Content effects transform the layer's own channel values in order before the layer blends with `acc`; a mask stack evaluates mono-channel from the background value through its effects, each with its own blend/opacity.
- Normal channel: `NormalMapCombine` = whiteout, `NormalMapDetail` = reoriented normal mapping, `NormalMapInverseDetail` = swapped operands (**Fact**, `BlendingMode` docstring in `PAINTER\resources\python\modules\substance_painter\layerstack.py`; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\shader-doc\lib-normal.html.]).
- Height→normal conversion is applied for export and preview (observable in Painter's outputs). [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\shader-doc\lib-normal.html.]
- Storage format emulation: each channel's accumulator is quantised to its `ChannelFormat` at the points Painter quantises (per layer or at the end — **not confirmed**; the evaluator has a switch and Phase 0 decides). This is what makes LSB-exact parity on 8-bit channels plausible; the pipeline already observed byte-identical BaseColor/Roughness/Metallic re-exports and ±1…135/65535 drift only on 16-bit-float Height/Normal (**Fact**, `UZP\docs\analysis\assets3d-pipeline\05-export-and-consumers.md` §6).

**Where reference formulas come from:** (1) Painter's shipped GLSL library for everything the viewport computes (normal blend, height→normal, sRGB conversions; [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\shader-doc\lib-utils.html.]); (2) Adobe's blending-mode documentation and the W3C/Photoshop separable/non-separable definitions as the starting hypothesis for the 32 modes; (3) the authoritative source: numerical derivation from Painter itself through remote scripting (two uniform fills per mode at a sweep of opacities and values, exported at 16-bit, fitted to candidate formulas); (4) `.spp` type names only as naming cross-checks ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.]).

**How parity is verified:** Tier 0 and Tier 1 of D13.

**Risks**
- Painter may blend sRGB8 channels in encoded space or in linear space; masks may be 8-bit; either choice silently breaks parity if guessed (mitigated: micro-tests decide, evaluator keeps both paths behind flags).
- Mask-stack blending and `Replace`/`Disable`/`SignedAddition` semantics are undocumented (mitigated the same way).
- Anchor references across texture sets and instance layers add dependency-graph complexity (scheduled late; data model supports them from day one).

**Cost to reverse:** high for the data model (it is the file format and the API); low for compositing formulas (they are per-node kernels).

### D4 — Procedural content strategy

**Options considered**
1. Execute `.sbsar` with the Substance Engine (requires Adobe's SDK licence; not redistributable with a standalone exe).
2. Reimplement a defined subset in HLSL, calibrated against Painter output.
3. Freeze procedural outputs as bitmaps captured once from Painter (per asset and parameter set), ship as bitmap resources.
4. Use Painter as an external oracle at run time (transition only).
5. Drop procedurals; 3D masks only (the paint standard).

**Position:** 3 + 2, with 4 as a migration aid while Painter is installed, and 5 as the documented primary workflow for new pieces. Concretely:
- **Captured assets (exact by construction):** every static procedural the recipes use (`grunge_*`, `dirt_*`, `bnw_spots_*`, `gaussian_spots_*`, `cracks_leather`, `fabric_linen`, `Grunge Map 009/012`, Fabric Burlap and Leather Pattern at their recorded parameters; list in `UZP\docs\analysis\assets3d-pipeline\04-painting-recipes-and-materials.md` §4) captured from Painter at 4096² (ResolutionMode Auto evaluates at the texture-set resolution — **Fact**, `02-layer-stack-model.md` §7.3) with the parameter hash as part of the asset id. Parameter edits beyond those captured are unsupported and raise.
- **Reimplemented generators (calibrated):** `mg_mask_builder` (Mask Builder – Legacy), `mg_mask_editor`, `mg_metal_edge_wear`, `mg_dirt`, `mg_curvature`, `mg_position`, `mg_world_space_normals`, `mg_ambient_occlusion` (**Fact** list of shipped generators, `03-baking.md` §6), plus the six smart masks (Dirt Cavities, Edge Dirty Cracks, Edges Uber, Ground Dirt, Dust Dirty, Occlusion Strong) and two smart materials (Leather Damaged, Bronze Armor) exercised by the body and bracer recipes (**Fact** they exist in `PAINTER\resources\starter_assets\smart-masks\` and `smart-materials\`). Their recipes are extracted through Painter's Python API (insert → dump node details with all parameters, as the pipeline already does for the hat: 70 834 characters, **Fact** `02-painter-usage.md` §9) into UzPainter preset JSON; the generator kernels are written in HLSL from the documented parameter semantics and tuned against Painter outputs on parameter sweeps.
- **Parity definition for procedurals:** per asset, one of `exact` (captured bitmap, identical up to resampling), `calibrated` (published metric: mean |Δ| and p99 |Δ| on 8-bit output over the sweep corpus; proposed gate mean ≤ 1/255, p99 ≤ 4/255, owner to approve), `unavailable` (import raises). The status table is a product artefact (`uzpainter assets list --parity`).
- **Test corpus:** three meshes (unit sphere, bevelled cube, the hat v6 low with its Painter-baked mesh maps) × each asset × 5 parameter sets from the recipes and defaults, at 1024², exported from Painter via remote scripting.

**Rationale:** Option 1 contradicts "standalone exe anyone can run" and is not licensable for redistribution (Hypothesis on licensing; owner to confirm). Option 5 alone fails the owner's "same functionality" and the locked bracer recipe (`A3D\...\22-Bracal-Direito\report.json → leather_family_recipe_r9`, **Fact** per the pipeline review). Captures give exact parity cheaply for the majority of the recipe corpus; reimplementation effort concentrates on the eight mesh-map generators that cannot be frozen (they depend on the mesh).

**Risks**
- Legal: redistributing captured renders of Adobe assets or recipes extracted from `.spsm` files may be restricted (owner question Q3).
- Calibrated generators will not be LSB-exact; the acceptance metric must be approved (Q1).
- Users (AI agents) may expect any `.sbsar` to load; the import error must say why and point to the captured-asset path.

**Cost to reverse:** medium. Moving to Option 1 later only adds a source kind (`procedural_sbsar`) to the model; captured and reimplemented assets remain valid.

### D5 — Baking

**Options considered**
1. GPU DXR (RayQuery compute on UzEngine's BLAS/TLAS; DX12 Tier 1.1 only).
2. CPU Embree.
3. Both from day one.

**Position:** Option 2 first, Option 1 later behind the same `IBaker` interface and the same sample sequences.

- **Fact:** Painter ships `embree3.dll` (`PAINTER\embree3.dll`); its CPU bakers are the family we can most plausibly match. **Fact:** Adobe's 12.0 release notes document a CPU/GPU AO difference (cited in `UZP\docs\analysis\reviews\technology-options-astra-review.md` finding 1), so the parity reference is explicitly Painter's CPU baker.
- **Fact:** UzEngine's DXR path exposes only a Tier ≥ 1.0 boolean while inline `RayQuery` needs Tier 1.1/SM6.5 (`uzengine-renderer-astra-review.md` F04); Embree sidesteps the capability matrix and runs on any machine, which the owner's "anyone can run locally" requires.
- Determinism: fixed sample sequences (Hammersley per texel index), fixed thread partitioning (tile-based), no fast-math → bit-reproducible on the same build (Hypothesis until tested).

**Baker list and parameters:** the ten `MeshMapUsage` bakers with Painter's internal/Python names (`OutputSize` log2 pair, `DilationWidth`, `ApplyDiffusion`, `HipolyMesh` pipe-joined `file:///` URLs, `LowAsHigh`, `CageMode`, `CageMesh`, `MaxHeight`, `MaxDepth`, `RelativeScale`, `SmoothNormals`, `IgnoreBackface`, `FilterMethod`, `LowpolySuffix`/`HipolySuffix`/`BackfaceCullingSuffix`, `SubSampling`; AO `NbSecondary`, `MinDistance`, `MaxDistance`, `MaxDistanceRelativeScale`, `Spread`, `Distribution`, `IgnoreBackfaceSecondary`, `Attenuation`, `GroundPlane`, `GroundOffset`; Curvature `SamplingRadius`, `AutoMinMax`, `TonemappingBounds`; Position `Mode`, `Axis`, `Normalization`, `NormalizationScale`; Thickness/Height `MaximizeRange`, `Divisor`; ID `ColorSource`, `ColorGenerator`) — **Fact** for the keys marked Fact in `UZP\docs\analysis\substance-parity\03-baking.md` §3, **Hypothesis** for the pairings marked so there; Phase 0 confirms them by printing `common().keys()` and `baker(usage).keys()` in Painter. `BakingParameters.common()/baker()/set()` and `Property` are mirrored so `configure_baking`-style scripts port unchanged. Defaults: the values read from `layerstack-cube.spp` ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp.]) are stored specimen values, not Painter 12.1 initialisation defaults (**Fact**, `UZP\docs\analysis\reviews\substance-parity-astra-review.md` F05); Phase 0 captures current defaults, ranges and enum labels through `Property.properties()`/`enum_values()` on a fresh project and stores them as the UzPainter defaults.

**Semantics:** cage = custom mesh or distance-based (frontal/rear, optionally relative to bounding box); match by name with suffixes; antialiasing = `SubSampling` supersamples per texel then averages; dilation = `DilationWidth` pixels + optional diffusion; curvature `FromMesh` with explicit, recorded normalisation bounds (never silently auto-rescaled across sets without recording the effective bounds — lesson `A3D\...\00-Corpo\report.json → painting_v6.rebake_mesh_maps.curvatura_membros`).

**External mesh maps:** `TextureSet.set_mesh_map_resource(usage, resource)` and `project.create(..., mesh_map_file_paths=[...])` accept 16-bit PNG/EXR, as the pipeline does for Blender normal/AO (**Fact**, `A3D\Docs\Pipeline\Retopologia\cajado-v10\painter_create.py`). Provenance (source hash, UV map, triangulation hash, parameters) is stored per map; a mesh reload invalidates and flags them (BAK-06).

**Evidence outputs:** RAW map, coverage (straight hit / cage hit / texel centre / conservative used-surface), miss map and per-class counts, never repairing used surface (lesson `A3D\Docs\Pipeline\Licoes\bake-raw-cobertura-estagios.md`).

**Job model:** `bake_async(ts) → Job` (id, progress 0–1, `cancel()`, terminal status `Success|Cancel|Fail` with per-baker error detail — richer than Painter's single status); `BakingProcessAboutToStart/Progress/Ended` emitted by the shim.

**Risks**
- Painter's exact ray distributions, attenuation curves and curvature algorithm are undocumented; per-texel equality is unlikely. Parity for bakes is tolerance-based (D13 Tier 2b) and, for the Assets3D corpus, bypassed by importing the same external maps into both tools.
- Embree is a new vendored dependency (Apache 2.0; needs TBB or its internal tasking) — build integration effort (Hypothesis: days).

**Cost to reverse:** low; the interface and the sample sequences are shared; adding the DXR implementation does not change the API or the file format.

### D6 — Preview and render parity

**Options considered**
1. Use UzEngine's deferred `SceneRenderer` as the parity target.
2. Port Painter's viewport shader to HLSL in a small forward pass (parity viewport) and keep `SceneRenderer` for engine preview.
3. Path-traced preview comparable to Cycles/Iray.

**Position:** Option 2. Two render modes, both headless-capturable:
- `painter_viewport` (parity target): forward pass over the texturing mesh with the evaluated channels bound as textures; BRDF, IBL and normal handling derived from Painter's shader library (**Fact** sources: `PAINTER\resources\starter_assets\shaders\{pbr-metal-rough,open-pbr}.glsl` and `PAINTER\resources\shader-doc\lib-pbr-specular.html`, `lib-env.html`, `lib-normal.html`, `lib-utils.html`, `lib-sampler.html`, …). Lighting: [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\shader-doc\lib-env.html.] Environment exposure and rotation follow Painter's display settings (observable).
- `engine_preview`: UzEngine `SceneRenderer` with the exported UzEngine material, for validating the UzEngine preset and for the human preview window.

**Render-parity target (Recommendation, precise):** Painter 12.1.0 realtime viewport, shader `open-pbr` (the current default; the pipeline's channel names and `_double_sided` parameter indicate it — **Fact** `02-painter-usage.md` §5 marks the shader name as Hypothesis) and `pbr-metal-rough` for legacy projects; environment = the project's environment resource identified by SHA-256 (the pipeline's standard uses `Studio White Soft.exr`, **Fact** present in `PAINTER\resources\starter_assets\environments\Studio\`), exposure 0, rotation 0, environment opacity 0, blur 0, shadows off, no post effects, no colour LUT, tone mapping `Linear`, view transform sRGB (the pipeline measured Painter "Default – sRGB" vs Blender Standard within 0.0036 of an 8-bit level, **Fact** `06-review-render-standard.md` §6), camera from `display.Camera` (perspective, FOV, position, Euler rotation), 1200×1200. `ToneMappingFunction.ACES` is supported as a second measured mode. Iray is out of reach and is not a target; the pipeline's Cycles `ref_match` stays the artistic gate (`A3D\Docs\Pipeline\Render\Render-Comparison-Standard.json`).

**Headless capture:** render to an offscreen RGBA16F target → display transform → readback → PNG; v1 uses the hidden-HWND path UzEngine already runs (`UZE\runtime\tools\uzengine.cpp --hidden`, **Fact** `02-headless-rendering.md` §1) for `engine_preview` and a window-less RHI path (as the FLIP mode does) for `painter_viewport`, which needs no swapchain at all.

**Rationale:** the parity viewport is a few hundred lines of HLSL plus an env-prefilter compute (SH projection, mip chain) — far less than bending the deferred renderer, whose post chain (auto exposure, TAA, specular AA) has semantics Painter does not have (**Fact**, `uzengine-renderer-astra-review.md` F01/F18). Painter publishes these shaders precisely so users can write compatible ones.

**Risks**
- Legal: the shipped GLSL carries an "ADOBE CONFIDENTIAL" header (**Fact**, every file in `PAINTER\resources\starter_assets\shaders\`); a derived HLSL port may be a derivative work. Alternative: clean-room from the public shader-API documentation and the standard GGX/Smith/Schlick/split-sum references, then calibrate (owner question Q2).
- Painter's viewport uses sparse virtual texturing, [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\shader-doc\lib-*.html.] and possibly temporal accumulation; pixel-exact equality with a different GPU/driver is not achievable. Parity is therefore a measured tolerance (FLIP + 8-bit |Δ| percentiles, D13 Tier 3), to be approved.
- Capturing Painter's reference frames reliably is itself hard (`save_viewport` returned stale frames — **Fact**, `A3D\Docs\Pipeline\Licoes\operacao-projeto-captura-reais.md`); the pipeline's `capture_live_view` approach is reused for the corpus.

**Cost to reverse:** low; the parity viewport is an isolated module.

### D7 — Export

**Options considered**
1. Painter-compatible JSON configuration and presets, extended with UzEngine/Unreal/DDS outputs.
2. A new, simpler export API only.

**Position:** Option 1. The exporter accepts Painter's `json_config` verbatim (`exportPath`, `exportShaderParams`, `defaultExportPreset`, `exportPresets[].maps[].{fileName, channels[], parameters}`, `exportList[].{rootPath, filter, exportPreset}`, `exportParameters[].{filter, parameters}` with the same resolution rules — **Fact** `UZP\docs\analysis\substance-parity\04-export.md` §2), the wildcards (`$mesh`, `$textureSet`, `$project`, `$sceneMaterial`, `$colorSpace`, `$udim`, `$uvTileName`, optional groups), `srcMapType ∈ {documentMap, meshMap, virtualMap, defaultMap}` with the documented names, the padding algorithms (`passthrough`, `color`, `transparent`, `diffusion`, `infinite` + `dilationDistance`), `dithering`, `sizeLog2` (int or `[w,h]`), `bitDepth`, `fileFormat`. Dithering and resize filters are derived from Painter in Phase 0 (dithering is most likely an ordered Bayer matrix — `lib-bayer.glsl` exists for the viewport; **Hypothesis** for export).

Formats: PNG 8/16 (libpng; 16-bit through `PngCodec::EncodeMemory` + own file write, because `EncodeFile` is 8-bit only — **Fact**, `uzengine-renderer-astra-review.md` F17), EXR 16f/32f (tinyexr), TGA/BMP (stb), JPEG (libjpeg-turbo), DDS (own header + etcpak BC1/3/4/5/7), `.uztexture`. TIFF/PSD/WebP/J2K: not in v1 (no vendored codec; raise with message).

Shipped presets (as JSON, verified in Phase 0 against `ResourceExportPreset.list_output_maps()` in Painter — the decoded `.spexp` tables are **Hypothesis**-grade, `04-export.md` §7.1): `PBR Metallic Roughness`, `Blender (Principled BSDF)` (used by the pipeline, **Fact** `05-export-and-consumers.md` §1), `Unreal Engine (Packed)` (BaseColor+opacity A, `OcclusionRoughnessMetallic` = AO_Mixed/roughness/metallic, Normal DirectX, Emissive), `Mesh Maps`, `glTF PBR Metal Roughness` (`_baseColor`, `_normal`, `_occlusionRoughnessMetallic`, `_emissive`; packing confirmed in Phase 0).

**UzEngine preset (Recommendation, from `UZP\docs\analysis\uzengine-renderer\04-material-and-texture-standard.md` §8 and the pipeline review C07–C12):**

| Output | Source | File | `.uztexture` | Colour | Notes |
|---|---|---|---|---|---|
| `<set>_albedo` | basecolor RGB + opacity A | PNG8 + companion | BC7 sRGB | sRGB | opacity in alpha because the fixed-PBR path samples `.a` while the cooker would pack a standalone opacity as BC4 (**Fact**, `gbuffer_ps.hlsl` lines cited in that analysis §2.1) |
| `<set>_normal` | virtual Normal (convention per calibration, see D11) | PNG8/16 + companion | BC5 | linear | engine reconstructs Z (**Fact**, same §2.1) |
| `<set>_orm` | AO_Mixed / roughness / metallic | PNG8 + companion | BC7 linear | linear | R=AO, G=roughness, B=metallic (**Fact**, same §2.1) |
| `<set>_emissive` | emissive | PNG8 + companion | BC7 sRGB | sRGB | |
| `<set>_height` | height | PNG16 + companion | BC4 | linear | explicit format metadata, never filename heuristics (pipeline review C10) |
| `<set>.uzmat` | — | JSON | — | — | `TextureSample → PBROutput` pins 0..6 (**Fact**, `04-material-and-texture-standard.md` §7) |

`.uztexture` companions are written directly (`WriteUzTexture` + etcpak, the same code path as `uzcook`) with full mip chains generated in UzPainter with sRGB-aware filtering and normal renormalisation (the cooker box-filters bytes — **Fact**, `texture_importer.cpp` per that analysis §5.3). Canonical 16-bit/float data is kept in the project; cooked outputs are derivatives (review F07).

**Unreal preset:** `Unreal Engine (Packed)` output as PNG/TGA 8-bit (safe default) and optionally DDS BC7 (BaseColor/ORM/Emissive) + BC5 (Normal) for "already compressed"; the Unreal importer version and pass-through behaviour are **not confirmed** (technology-options review finding 13) — Q11.

**Determinism and verification:** export reads a snapshot of the evaluated document; encoders use fixed settings (zlib level/strategy pinned); files are written to a temp name and renamed; the result lists path, bytes, SHA-256, per-map format/bit depth/colour space (fills the manifest `exportacao` block, INT-21); `list_project_textures` is the dry run. Virtual maps (`Normal_OpenGL/DirectX`, `AO_Mixed`, `Diffuse`, `Specular`, `Glossiness`, `f0`, `1/ior`, `reflection`) are evaluator outputs with formulas confirmed in Phase 0 (Mixed AO combination is **not confirmed**: multiply vs min).

**Risks:** `.spexp` decoding hypotheses; Painter's resize/dither algorithms; DDS/Unreal acceptance; `Mixed_AO` must not crash (it crashed Painter 12.1 — **Fact**, `A3D\Docs\Pipeline\Licoes\operacao-painter-export-mixed-ao.md`).

**Cost to reverse:** low; presets are data.

### D8 — Project file format

**Options considered**
1. HDF5 (as `.spp`).
2. ZIP container + JSON recipe + content-addressed blobs.
3. SQLite.
4. Custom chunked binary.

**Position:** Option 2, file extension `.uzpaint`:

```
project.uzpaint (ZIP64, members stored or deflated)
  manifest.json            format_version, app version, project uuid, settings, texture sets, stacks, layer tree, sources,
                           bake parameters, display state, export defaults, resource index {sha256 → member, mime, size}
  mesh/<sha256>.obj.zst    original mesh bytes (and high-poly references by path+hash, bytes optional)
  res/<sha256>.<ext>       original resource bytes (PNG/EXR/HDR as imported; no re-encoding)
  meshmaps/<set>/<usage>.<fmt>.zst   baked maps at native precision (R16/RGB16/R32F), zstd per entry
  assets/<id>.json         captured/reimplemented procedural presets referenced by the stack
  cache/ (optional)        evaluated channel rasters for fast reopen; never required; dropped by `--compact`
  checkpoints/<n>.json     manifest snapshots for revert (SAV-02); blobs are shared
```

**Compactness strategy and target:** the `.spp` baseline stores decoded resources, the processed mesh ([Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\python\modules\automated_tests\resources\layerstack-cube.spp; PAINTER\resources\samples\MeetMat.spp.]), baked maps and a texture cache (**Fact**, Adobe's own explanation quoted in `UZP\docs\analysis\substance-parity\05-project-and-spp.md` §6). UzPainter stores the original compressed bytes once (content-addressed, deduplicated), no raster cache by default, and a recipe that is kilobytes. **Hypothesis:** for the hat v8 (21 masks + 1 colour texture at 4096, `.spp` 556 MB) the result is the sum of the PNG inputs (tens of MB) plus mesh maps; ≤ 10 % of the `.spp` for the same content is the proposed acceptance proxy, measured on the three supplied body versions and the hat (Q13).

**Incremental save:** every save writes a new ZIP atomically (temp + rename) copying unchanged members without re-encoding; the previous file is kept as `<name>.prev.uzpaint`; autosave to `<name>.autosave.uzpaint` throttled after mutations. No in-place append protocol (Astra's finding 20 on ZIP mutation is accepted; rewriting tens of MB is cheap).

**Versioning:** `format_version` semver; readers refuse a newer major, migrate older minors; unknown JSON keys are preserved.

**AI inspectability:** `unzip -l`, `manifest.json` readable, PNG resources viewable; `uzpainter inspect project.uzpaint` prints the recipe digest, layer tree and resource provenance without opening the project; the same data is an MCP resource.

**Rationale:** the technology-options review (findings 2, 18–22) asks for an authoritative procedural model, lossless precision and explicit failure boundaries rather than a container choice; Option 2 satisfies them with the least machinery (one JSON schema, one zip writer). SQLite's transactional strengths matter for many small writes; an AI-driven batch tool makes few, large saves. `.spp` import is not required: recovery is by recipe + resources (pipeline review answer Q2).

**Risks:** manifest JSON grows large for 40-layer stacks with per-node parameters (hundreds of KB — fine); duplicate-content detection relies on SHA-256 of original bytes, so a re-encoded PNG of the same mask is a new blob (accepted).

**Cost to reverse:** medium (the manifest schema is the real asset; swapping the container is mechanical).

### D9 — Python API shape

**Options considered**
1. Only a `substance_painter`-compatible package.
2. Only a new `uzpainter` package.
3. Both: native `uzpainter` plus a pure-Python `substance_painter` shim.

**Position:** Option 3. `uzpainter` is the documented, typed, synchronous API (`uzpainter.project`, `.textureset`, `.layerstack`, `.source`, `.resource`, `.baking`, `.export`, `.display`, `.colormanagement`, `.jobs`, `.diagnostics`), same class and function names as Painter wherever a Painter symbol exists. `substance_painter` is a shim that imports from `uzpainter` and adds Painter's idioms: `event.DISPATCHER` (events are dispatched synchronously on the calling thread when the corresponding operation completes, and pumped on every API call), `baking.bake_async → StopSource` (runs the job on the pool; `project.is_busy()` is true while it runs), `project.create/open` (synchronous in UzPainter; the shim fires `ProjectOpened/Created` then `ProjectEditionEntered` immediately after), `execute_when_not_busy`, `ScopedModification` (batches evaluation; evaluation is lazy anyway), `application.enable_engine_computations` (accepted, no effect: evaluation is lazy), `_substance_painter.display.save_viewport` (maps to `display.capture`).

**Compatibility check against the three scripts (Fact, files read this session):**
- `A3D\Docs\Pipeline\Retopologia\cajado-v10\painter_create.py`: `os.environ["OCIO"]` (accepted and recorded; UzPainter projects are always colour-managed with linear working space and sRGB I/O, equivalent to Painter's shipped `substance` OCIO config — exactness of that config is verified in Phase 0), `project.Settings(normal_map_format, default_texture_resolution, import_cameras)`, `project.create`, `is_busy`, `all_texture_sets`, `import_project_resource`, `set_mesh_map_resource`, `get_mesh_map_resource().url()`, `save_as(path, ProjectSaveMode.Full)`, `file_path`, `needs_saving` — all mirrored.
- `painter_export.py`: `save(Full)`, inline preset with `documentMap` and `virtualMap Normal_OpenGL`, `exportParameters` — mirrored (D7).
- `painter_layer_stack.py` (`SYNC_CODE`, `SMART_CODE`, `CAPTURE_CODE`): `set_active_stack`, `get_active_stack`, `insert_group/insert_fill` with `InsertPosition.{from_textureset_stack, inside_node, above_node, below_node}`, `NodeStack`, `add_mask(MaskBackground.Black)`, `set_source(None|channel, ResourceID|Color)`, `set_projection_mode`, `get/set_projection_parameters`, `UVProjectionParams(...)`, `list_available_color_spaces`, `set_color_space`, `active_channels`, `set_opacity(v, ch)`, `set_blending_mode(mode, ch)`, `get_blending_mode`, `set_visible`, `delete_node`, `get_root_layer_nodes`, `sub_layers`, `uid`, `insert_smart_mask`, `insert_levels_effect` + `LevelsParams` replace, `SourceSubstance.set_parameters`, `resource.search(query)`, `ResourceID.from_url`, `Color(..., color_space=GenericColorSpace.sRGB|Raw)` with the Legacy fallback — all mirrored; `search` finds captured/reimplemented assets by their Painter names when the alias shelf is enabled (Q3).
- Scripts that reach into Qt (`ui.get_main_window` for exposure sliders) must switch to `uzpainter.display.*`; they are Painter-internal hacks by the pipeline's own account (`02-painter-usage.md` §10).

**Error semantics:** every failure raises (`ProjectError`, `ResourceNotFoundError`, `ValueError`, `UnsupportedInUzPainter`); no silent partial success (QG-03); results of sync/bake/export list exactly what changed/was written/skipped. Resource URLs are `resource://project/<name>?version=<sha256>` and remain valid across sessions (RES-02).

**Mutation contract (Recommendation, prompted by `UZP\docs\analysis\reviews\substance-parity-astra-review.md` F01–F04 and questions 4–7):**
- API objects are thin handles with `__slots__`; assigning an unknown attribute raises instead of creating a Python-only attribute (the community bridge's `node.active_channels = …` on a Paint layer "succeeded" without reaching any native setter — **Fact**, that review F01). Every setter is paired with a getter that re-resolves the node by uid, and the test suite asserts set→get→save→reopen→get equality.
- Every operation accepts an explicit `(texture_set, stack)` address; `set_active_stack`/`get_active_stack` exist for compatibility only and never influence export or evaluation (that review question 7).
- Each API call is atomic under the document lock; composite operations (`sync_stack`, `apply_smart`, `insert_smart_material`) build their subtree detached and attach it only on success, so a failure leaves the document unchanged (not best-effort cleanup — that review F04). Results enumerate created/modified/hidden nodes by uid.
- `project.reload_mesh(path, settings, callback)` runs synchronously and then invokes the callback with `ReloadMeshStatus` on the calling thread (Painter's mesh reload is callback-based, not event-based — **Fact**, that review V64).
- Node uids are persisted in `.uzpaint` and survive save/reopen; Painter only promises an internal integer id with invalidation (**Fact**, that review V03), so this is a UzPainter guarantee, not a mirrored one.

**Risks:** the shim's synchronous event emulation differs from Painter's queued events for scripts that register callbacks and return to the Qt loop (none in the pipeline). Painter reports API version `0.3.5` at runtime while shipping 0.3.7 symbols (**Fact**, inventory §1); the shim reports `0.3.7` and `hasattr`-based feature detection keeps working.

**Cost to reverse:** low; the shim is thin.

### D10 — MCP server

**Options considered**
1. In-process official Python SDK (D1 Option 1).
2. Native C++ JSON-RPC.
3. Out-of-process bridge over a private socket.

**Position:** Option 1; stdio default, loopback Streamable HTTP optional. Tool design: two tiers plus resources.
- **High-level tools (~25)**: `status`, `project_create`, `project_open`, `project_save`, `project_close`, `project_inspect`, `import_resource`, `set_mesh_maps`, `sync_stack` (the `painter_layer_stack.py` stack JSON, native), `apply_smart` (the smart JSON), `list_layers`/`snapshot_layer_tree`/`diff_snapshots`, `set_layer` (name/visible/blend/opacity), `set_fill` (sources/projection/active channels), `set_mask` (background/effects/replace resource in place — LAY-08), `insert_smart_material`/`insert_smart_mask`, `configure_baking`, `bake`, `export` (preset name or inline config), `capture` (mode, camera, size, display preset), `isolate_layer` (per-layer contribution export — LAY-09), `mesh_reload`, `get_job`/`cancel_job`, `assets_search`.
- **Escape hatch**: `run_python` (the full `uzpainter` API; enabled with `--allow-python`, as the community bridge's `SP_MCP_ALLOW_EXECUTE_PYTHON` — **Fact**, `UZP\docs\analysis\substance-parity\06-mcp-tools-inventory.md` §2.1). There is no 1:1 "API mirror" tool tier: 572 tools would bury the useful ones, and `run_python` covers the long tail.
- **Resources**: `uzpainter://project/manifest`, `uzpainter://project/layers`, `uzpainter://project/recipe` (the INT-20 `painter_recipe` block), `uzpainter://assets/parity`, `uzpainter://jobs/<id>`; **prompts**: recipe templates (stack JSON, smart JSON, baking preset).
- **Long jobs**: tools take `wait` (default true, with progress notifications and the SDK's cancellation); `wait=false` returns `job_id` for `get_job`; the MCP Tasks extension is adopted when the pinned SDK and the owner's clients support it (**not confirmed**).
- **Single writer and busy state**: one document lock; a mutating call while a job runs returns a structured `busy` error with the job id (INT-04/05); in HTTP mode an `owner` token is required for mutations (`acquire_lock`/`release_lock` tools), reads are free.
- **Path sandbox**: `--roots project=… mesh=… resource=… export=…` allowlists (mirroring `SP_MCP_*_ROOTS`, **Fact** `A3D\Docs\Pipeline\MCP\painter_mcp_client.py`), canonicalised absolute Windows paths, symlink-resolved; results never contain data outside the roots.
- **Images**: `capture` returns the PNG path plus an MCP image content block (downscaled) so the agent can look at it.

**Rationale:** the community bridge's 79 tools were mostly bypassed by the pipeline in favour of `execute_python` (**Fact**, `02-painter-usage.md` §2–3); a small, task-shaped tool set plus the escape hatch matches observed use.

**Risks:** SDK release churn (pin; vendored); Tasks support uncertain; HTTP mode needs origin/auth rules (loopback only, token).

**Cost to reverse:** low.

### D11 — Mesh import and texture sets

**Options considered**
1. Reuse UzEngine's cook importers (`.uzmesh`/UZMH).
2. A UzPainter-owned raw mesh loader on top of the vendored parsers.

**Position:** Option 2. Formats: OBJ (own parser: preserves triangulation, per-corner normals and UVs, `usemtl` → texture set, `o`/`g` → mesh names for geometry masks), FBX (ufbx), glTF/GLB (fastgltf) — all producing the same `TexturingMesh {positions, corner normals, corner UVs, tangents, material id, mesh name, triangles}`; no welding, no re-triangulation, no LOD, no SDF (**Fact** that the cook path does those unconditionally or by thresholds, `UZP\docs\analysis\uzengine-renderer\05-mesh-import.md` §3, review F11; the 32/48-byte UZMS defect, review F03, is avoided entirely because UzPainter never reads `.uzmesh`). Units: metres as given; `mesh_unit_scale` honoured; Painter's Y-up convention kept inside UzPainter (camera conversion to Blender per the pipeline's `coordinate_contract`, VIS-05).

**Tangent basis:** MikkTSpace (`UZE\runtime\thirdparty\mikktspace\mikktspace.c`), with `TangentSpace.PerVertex` (bitangent interpolated) and `PerFragment` (bitangent rebuilt per pixel from interpolated N and T with the stored sign), default `PerFragment` as the pipeline uses (**Fact**, `A3D\...\22-Bracal-Direito\report.json → painting.tangent_space`). Whether Painter's "per fragment" equals this construction is **not confirmed** → Phase 0 fixture: bake a known hemisphere normal in Painter and in UzPainter, compare in tangent space; the same fixture settles UzEngine's green-channel convention (review F10/G10).

**Texture sets:** one per material name, in file order; names must be unique; resolution per set (2048/4096 today; 8192 supported if VRAM admits — budget check at creation, G05 of the engine review). UV tiles: data model ready, `ProjectWorkflow.UVTile` deferred to v2.

**Validation (certificate JSON, no auto-repair):** non-finite or zero corner normals/tangents/bitangents, coincident opposite faces (the 2 641-black-texel lesson, `A3D\Docs\Pipeline\Licoes\bake-normais-tbn-por-canto.md`), flipped UV triangles (signed area), zero-area UV triangles, UVs outside 0–1, overlaps per set, per-island texel density at the set resolution. Import succeeds with warnings; the Assets3D adapter (a pipeline-side script) may refuse to proceed.

**High-poly ingestion:** streamed straight into Embree geometry buffers (positions, indices; normals/vertex colours/material ids as side streams for ID/normal transfer), per object with transforms, match-by-name suffix filtering; memory ≈ 12 B/vertex + 12 B/triangle plus side streams (Hypothesis; 10 M triangles ≈ 0.5–1 GB).

**Mesh reload:** match sets by material name, keep stacks, re-rasterise, invalidate mesh maps/bakes (flagged, not deleted), report changed sets/islands.

**Risks:** OBJ parser edge cases (negative indices, multiple UV sets); FBX unit/axis conventions; per-fragment tangent equivalence unproven.

**Cost to reverse:** low.

### D12 — Engine integration and packaging

**Options considered**
1. Build UzPainter inside the UzEngine tree (another `tools/*.cpp`).
2. Separate repository with its own `build.zig` consuming a pinned UzEngine checkout (git submodule or Zig package) and linking `runtime.lib`.
3. MSVC/CMake build consuming the engine DLL through the C ABI.

**Position:** Option 2. Zig toolchain (the engine's primary; mixing MSVC objects with Zig archives fails — **Fact**, `UZE\docs\engine\06-build-toolchain\04-napi-bridge.md` "LNK1143" per `07-build-and-packaging.md` §6). Pin UzEngine to commit `19ffb9b94333f56d624eb1485192cf5c6d174bd0` (2026-07-27) checked out clean — **Fact** (this session): HEAD is that commit, the working tree is dirty and 15 source/shader files under `runtime/engine` and `runtime/shaders` contain conflict markers (`frame_constants.cpp`, `scene_renderer.h`, `deferred_lighting_ps.hlsl`, the `gi/` files, …). UzPainter must never consume that working tree; it consumes a tagged commit, and the conflict resolution is the engine owner's task (Q6).

**What to link:** `rhi`, `shader` (DXC pipeline, embedded-shader registry), `asset/formats` (`uztexture`, `uzmesh` writers), `asset/importers/png_codec`, `texture_importer` (etcpak path), `asset/mesh/mikktspace_tangents`, `job`, `logging/paths/config/cvar`, `platform/windows`, `ipc/frame_readback` (as reference), `renderer` + `ecs` (only for `engine_preview`), `editor/screenshot` or an own copy. Excluded link set: FFmpeg, DLSS, LuaJIT, Brixelizer, atmosphere/VFX content (**Fact**, hard-wired for all tools in `UZE\runtime\build.zig`, so UzPainter needs its own recipe — `07-build-and-packaging.md` §2.1).

**What to add, and where:** UV raster pass, dilation compute, compositor kernels, mip generation, format-generic `TextureReadback` (review F08 rules: per-export ownership, aligned pitch, fence-linked map-after-completion, drain), DDS writer — all UzPainter-side on the public RHI. Engine changes kept to a minimum and sent upstream as PRs against the pinned baseline, with the pin bumped when merged: (i) WARP adapter selection (`--adapter warp`) for CI; (ii) optional swapchain-less `SceneRenderer` target (G1) — only if `engine_preview` headless capture needs it beyond the hidden HWND; (iii) `D3D12_FEATURE_FORMAT_SUPPORT` queries (G25). No local patches of engine sources.

**Zig vs CMake:** Zig; CMake mirror not maintained for UzPainter.

**Distributable (single folder, Hypothesis on the final list):** `UzPainter.exe`, `D3D12Core.dll` (+ `d3d12SDKLayers.dll` debug), `dxcompiler.dll`, `dxil.dll`, `python313.dll` + `python313.zip` stdlib + `Lib/site-packages` (vendored, pinned: mcp SDK and deps), `embree4.dll` (+ `tbb12.dll` unless built with internal tasking), `assets/` (captured/reimplemented procedurals, presets, shaders embedded), `cache/` created at run time. Agility SDK path layout (`.\D3D12\` export vs bin root) verified in Phase 0 (review F13). Release build `-Doptimize=ReleaseFast`; sizes measured, not promised.

**Risks:** engine baseline unresolved; Zig/clang ABI for CPython (C ABI only — fine) and pybind11 (compiled by the same toolchain — fine); Tracy defines unconditionally on in the engine build (review F20) — override in the UzPainter recipe.

**Cost to reverse:** medium (build recipes); the code does not depend on the build system.

### D13 — Parity testing

**Position (Recommendation):** a four-tier golden corpus recorded from the installed Painter 12.1.0 through `--enable-remote-scripting` (`localhost:60041`, **Fact** `06-mcp-tools-inventory.md` §2), pinned by Painter version, project settings, asset versions and SHA-256 of every input.

| Tier | Content | Compared | Metric (proposed; owner approves) |
|---|---|---|---|
| 0 Semantics | Synthetic meshes (plane, sphere, bevelled cube) × each blend mode × opacity/value sweeps; mask ops (background, fill effect, levels, subtract, compare mask, colour selection); projections (UV filters/wrap/transform, triplanar hardness/scale, planar/spherical/cylindrical); channel formats and default channel sets per template; uniform colour spaces; height→normal both methods; normal blends; export padding/dithering/resize/bit depth; current baking defaults and property metadata; API semantics probes (set→get readback, mask-context `None` channel rules, insertion rules) | Exported 16-bit maps; JSON captures of defaults and readbacks | Fixed-point channels: 100 % texels exact at channel depth (allowance ±1 LSB only where rounding-mode ambiguity is proven); float channels: |Δ| ≤ 2·2⁻¹⁰ after normalisation; API probes: exact |
| 1 Recipes | The Assets3D stacks rebuilt from the same JSON and resources in both tools: wand v1, belt v5, staff v10, tunic v10 (approved), hat v8 (procedurals), bracer r9 (locked smart materials), body v6b (3 sets, smart stack) — with identical external mesh maps imported in both tools | All exported maps per set | Same as Tier 0 per channel; AO/normal/height additionally p99 angular error ≤ 0.25° on combined normals |
| 2 Procedurals and bakes | (a) each captured/reimplemented asset × parameter sets × 3 meshes; (b) the ten bakers on wand/hat lows with their highs, Painter CPU baker settings recorded | Asset outputs; mesh maps | (a) exact for captures; calibrated: mean ≤ 1/255, p99 ≤ 4/255 at 8-bit; (b) per map: mean ≤ 1/255 and p99 ≤ 4/255 for AO/thickness/curvature after recorded normalisation; position/WSN exact to 1 LSB |
| 3 Renders | `painter_viewport` vs Painter captures at the D6 settings, 6 fixed cameras per asset, Linear and ACES | 8-bit sRGB images | FLIP mean ≤ 0.02 and p99 |Δ| ≤ 2/255 (initial), reported per image |

Rules: a tolerance change needs an owner decision recorded under `.rulebook/decisions/`; a failed tier blocks release; goldens are regenerated only when Painter's version changes and the diff is reviewed. CI: unit tests + Tier 0 run on hosted Windows runners with WARP (**Hypothesis**: WARP executes the compute kernels; verified in Phase 0 `selftest`); Tier 1–3 on a self-hosted GPU runner (Q9). Painter is required only to record goldens, never in CI.

### D14 — Delivery roadmap

See §4.

## 3. Parity strategy

**What "same output" means (Recommendation, to be approved):** for every exported texture, the decoded native pixels equal Painter's for fixed-point channels and lie within a declared tolerance for float channels; encoded file bytes are additionally identical between two UzPainter runs on the same build (not with Painter — PNG byte layout differs by encoder); renders match within the Tier 3 metric. Comparison always happens on decoded pixels at native depth (Pillow truncates RGB16 — **Fact**, `A3D\Docs\Pipeline\Licoes\exportacao-spp-mapas-precisao-nativa.md`).

**How it is achieved**
1. Semantics first: Phase 0 derives formulas from Painter numerically (Tier 0) before any evaluator code is frozen.
2. Storage-format emulation: channel accumulators quantised like Painter's `ChannelFormat`s.
3. Explicit colour math in shaders (Painter's constants), no hardware sRGB conversion, no fast-math, point sampling plus manual filtering where Painter's filter is known.
4. Same inputs: the corpus imports identical external mesh maps into both tools so compositing parity is measured independently of baking parity.
5. Captured procedurals are exact by construction; reimplemented ones are calibrated and published with their error.
6. Renders: a forward pass derived from Painter's own shader library, with every display parameter pinned and recorded in the capture manifest.

**What cannot be reproduced exactly, and the mitigation**

| Item | Why | Mitigation |
|---|---|---|
| `.sbsar` execution | Proprietary Substance Engine (`PAINTER\substance_*.dll`, **Fact**) | Captured bitmaps (exact at recorded parameters) + calibrated reimplementations; parity status per asset; `.sbsar` import raises |
| Iray | Proprietary path tracer (`PAINTER\resources\mdl`, `iraysettings2.ini` in `.spp` — **Fact**) | Not a target; Cycles `ref_match` remains the artistic gate; `painter_viewport` is the parity render |
| Pixel-exact viewport | Different GPU/driver, SVT, [Redacted under the clean-room policy (docs/licensing-and-clean-room.md). Source withheld: PAINTER\resources\shader-doc\lib-*.html.], possible temporal accumulation | Tolerance metric (Tier 3), fixed camera/env/exposure, no post |
| Painter's own cross-session drift on 16F channels (up to 135/65 535 — **Fact**, `05-export-and-consumers.md` §6) | Painter is not bit-stable itself | Float tolerances; UzPainter is bit-stable per build |
| Bakers | Undocumented sampling/attenuation/curvature algorithms | Tolerance metric; recorded normalisation; external maps accepted for the corpus |
| Paint strokes | Not in Painter's Python API (**Fact**); the acceptance premise replays instruction sequences, which cannot contain strokes | Out of v1 scope as an *instruction* surface, not as a product exemption (the Substance review's D14 disposition); empty paint layers evaluate identically; stroke painting is an owner decision for a later phase (Q8) |
| Adobe assets (HDRIs, smart materials, grunges, shaders) | Licensing | User-supplied files identified by hash; captures/reimplementations as owner permits (Q2, Q3) |
| OCIO exactness | Painter's `substance` config is Adobe's | Link OpenColorIO (BSD) and accept `OCIO` pointing at the user's config; ship an equivalent minimal config; measured in Tier 0 |
| Export encoders | Different PNG/EXR writers | Compare decoded pixels, not bytes |

## 4. Roadmap

Durations are Hypotheses for one architect-grade engineer plus AI agents; acceptance criteria are Recommendations.

| Phase | Scope | Acceptance |
|---|---|---|
| **0 Contract and skeleton** (≈2–3 weeks) | Owner decisions Q1–Q6; UzEngine pinned clean; `UzPainter/build.zig` producing `UzPainter.exe --selftest` (device, compute kernel, readback, PNG16) on GPU and WARP; Painter golden recorder scripts; Tier 0 corpus recorded; formulas derived and written into `docs/parity-contract.md`; Agility/DXC packaging verified; tangent/normal-convention fixture run in Painter, UzPainter (planned) and UzEngine | Tier 0 goldens and formulas exist with Fact labels; selftest green on both adapters; decisions recorded |
| **1 Fills pilot** (≈5–6 weeks) | Document model + `.uzpaint`; OBJ import + certification + UV raster + MikkTSpace; fill layers, groups, bitmap/uniform sources, UV projection, masks with fill effects and levels, per-channel blend/opacity; evaluator with storage-format emulation; export (Painter JSON, PNG16, padding, presets `PBR Metallic Roughness`, `Blender`); `uzpainter` + `substance_painter` shim; `painter_create.py`, `painter_layer_stack.py sync`, `painter_export.py` run unchanged against `UzPainter.exe run` | Pilot 11-Varinha-Madeira v1 then 23-Cinto v5: Tier 1 metrics pass against Painter goldens; export byte-stable across two runs; `.uzpaint` ≤ 10 % of the piece's `.spp` |
| **2 Operation** (≈3–4 weeks) | MCP server (stdio, tools, resources), CLI, jobs, busy/lock, path sandbox, autosave/checkpoints, `inspect`, layer isolation, snapshot/diff, recipe dump (INT-20), manifest export block (INT-21); preview window; `painter_viewport` + capture; Tier 3 first measurements | An agent completes the belt round end-to-end through MCP only; captures reproducible; Tier 3 numbers published (pass/fail against the proposed metric) |
| **3 Procedurals, bakes, engine presets** (≈6–8 weeks) | Embree bakers (10 maps, Painter parameter names, evidence outputs); captured assets and the eight generators, six smart masks, two smart materials; triplanar/planar/spherical/cylindrical projections; anchors; UzEngine preset (`.uztexture` + `.uzmat`, verified by loading in `engine_preview`) and Unreal preset (PNG/TGA + DDS); tunic v10 recovery proof | Tier 1 passes on hat v8, bracer r9, body v6b; Tier 2 published; tunic v10 rebuilt from recipe + resources matches its Painter goldens; UzEngine loads the preset and renders |
| **4 Completeness and packaging** (≈4 weeks) | Instances, compare mask, colour selection, warp and UV-set projections, symmetry, UV tiles (v2 workflow), EXR/DDS variants, DXR baker (optional), single-folder release, docs, parity status report | Full Tier 0–3 suite green on CI; release folder runs on a machine without the SDKs installed |

**Pilot piece:** 11-Varinha-Madeira v1 (one set, 2048, uniform fills + bitmap masks, Blender normal/AO, no procedurals — **Fact** `02-painter-usage.md` §6), because it isolates the compositing/export contract; 23-Cinto v5 adds `base_tex` swatches; 18-Tunica v10 is the approved-baseline recovery test (G-03).

**What the owner must decide first:** Q1, Q2, Q3, Q6 block Phase 0; the rest block later phases.

## 5. Questions for the owner

1. **Tolerance policy.** Fixed-point channels: exact. Float channels, calibrated procedurals, bakes and renders: are the Tier 0–3 metrics above acceptable as the acceptance contract, and who signs a tolerance change?
2. **Shader port legal stance.** Painter's viewport GLSL ships with "ADOBE CONFIDENTIAL" headers. Port it (derivative work risk) or clean-room from public BRDF references plus calibration (slower, lower parity)?
3. **Assets and names.** May UzPainter (a) capture Adobe procedural outputs and smart-material recipes from your Painter licence for internal use, (b) expose them under Painter's asset names so existing scripts resolve them, and (c) ship them in the distributable? Separate answers for internal use vs redistribution.
4. **`.sbsar` execution.** Confirm that licensing the Substance Engine is not an option; otherwise D4 changes.
5. **Painter as oracle.** Keep Painter 12.1.0 installed and licensed on this machine for golden recording and migration until Phase 3 completes?
6. **UzEngine baseline.** Approve pinning commit `19ffb9b` (clean) and assigning the working-tree conflict resolution to the engine project; approve the PR-only policy for engine changes.
7. **Pilot order.** Wand v1 → Belt v5 → Tunic v10 (recovery) → Hat v8/Bracer r9/Body v6b. Agree?
8. **Scope of v1.** Strokes excluded; UV tiles, warp/UV-set projections, instances deferred to Phase 4. Agree?
9. **CI hardware.** Is a self-hosted Windows runner with a DX12 GPU available for Tier 1–3?
10. **Packaging.** Single folder (exe + DLLs + assets) is the v1 target; is a single-file exe required later?
11. **Unreal target.** Which Unreal version/importer, and is DDS BC7/BC5 pass-through wanted or PNG/TGA sufficient?
12. **Render target shader.** Confirm `open-pbr` (current default) as the primary parity shader and `pbr-metal-rough` as secondary; confirm Linear tone mapping and `Studio White Soft` (user-supplied by hash) as the reference environment.
13. **Compact-file metric.** Accept "≤ 10 % of the `.spp` size for the same content, measured on hat v8 and the three body versions" as the acceptance proxy for requirement 7?
14. **Governance.** The Assets3D rule "painting is always in Substance Painter" (`A3D\AGENTS.override.md`) — amend it when the pilot passes Tier 1, or now?
