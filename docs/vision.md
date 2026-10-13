# Vision

## What UzPainter is

UzPainter is UzmiGames' version of Adobe Substance 3D Painter in functionality, operated 100 % by AI agents. There is no human editing UI; at most a read-only preview window a person can watch. Its primary mode is headless (CI and batch). Its render system is built from rendering code copied (vendored) from UzEngine (`E:\UzmiGames\UzEngine`); UzPainter has no dependency on UzEngine and the two are separate systems. It replaces Substance Painter completely in the Assets3D pipeline (`E:\UzmiGames\Assets3D`), and it ships as a standalone one-folder distribution for Windows 10/11 x64 (DX12 primary, Vulkan as the second backend) that anyone can run locally.

## Owner requirements (2026-10-09 and 2026-10-10, recorded in `UZP\README.md` and the architecture brief)

1. Substance Painter's functionality, 100 % AI-operated; never a human editing UI; at most a preview window; headless/CI as the primary mode.
2. The same functionality: layers, smart materials, rendering, export, Python scripting, a native MCP server any AI can use.
3. The render system is built from UzEngine.
4. Complete replacement of Substance Painter in the Assets3D pipeline.
5. Mirror Substance's Python API and MCP structures without inventing unnecessary processes; bake from high-poly for AO, detailed normal and the other mesh maps, like Substance.
6. Export PBR like Substance, plus Unreal's ORM standard and UzEngine's own standard, preferably already compressed.
7. Save progress like `.spp` but far more compact (real `.spp` files measure 0.88–1.19 GB per piece: `A3D\Creatures\Undead\Skeletal Mage\Models3D\00-Corpo\00-Corpo-v5.spp` 879,248,615 B, `-v6.spp` 1,087,438,533 B, `-v6b.spp` 1,190,431,812 B).
8. In the end, a standalone Windows `.exe` anyone can run locally.
9. Acceptance premise: following the same sequence of instructions, UzPainter produces the same texture result and the same render result as Substance Painter. Output parity, not just feature parity. Divergence is a bug.

The owner's answers of 2026-10-10 (`open-questions.md`) make these requirements precise:

- **Render (Q2):** the render result means Painter's **Iray** output. UzPainter reproduces it with a clean-room path tracer (public literature; NVIDIA's MDL specification and the open-source MDL SDK allowed; nothing from Adobe or Iray internals) on DX12 ray tracing and Vulkan ray tracing. The realtime viewport is the human preview and a fast check, not the parity target.
- **Scope (Q5):** brush strokes are out of scope because Painter's Python API does not expose them; paint layers remain layers that receive bitmaps and projections. Milestones are named by proven scope, and nothing is called a full replacement while a required gap is open.
- **Engine (Q8):** requirement 3 means the rendering code UzPainter needs is copied from a clean UzEngine commit (Apache-2.0 headers and attribution kept); there is no link, pin, patch queue, upstream obligation or submodule. UzEngine may consume UzPainter in the future.
- **Platform (Q9):** Windows 10/11 x64 only for now; DX12 primary and Vulkan as the second backend; no Linux or macOS. A GPU is required for compositing, preview and path tracing; CPU baking runs on the qualified configurations.
- **Cutover (Q13):** the Assets3D rule that painting is always done in Substance is amended after Tunic v10 passes its parity gate.

## Acceptance (decision 001)

`.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md`: UzPainter is satisfactory only when, given the same sequence of instructions, it produces the same texture result and the same render result as Adobe Substance 3D Painter 12.1.0. Decision 037 (2026-10-11) replaces that version pin: the reference is the Painter build of the current oracle envelope, which follows Creative Cloud's automatic updates. The binding formulation adopted by both architects (`docs/analysis/architecture-discussion/05-resolution.md` D13):

> Default acceptance is equal native decoded texture values and the agreed reference render output. Every divergence is a failure unless an owner-approved, versioned exception explicitly covers that domain and metric. Explained differences are still failures without that exception. Diagnostic metrics do not grant an exception.

The owner confirmed the record as accepted on 2026-10-10 (`open-questions.md` Q1): exact equality is the rule, a divergence is accepted only through an owner-approved exception with evidence in the exception register, and there are no preset tolerances. The reference render is Painter's Iray output (Q2). Iray is stochastic, so pixel-exact render equality is not achievable: the render is compared with converged Iray references, and every residual goes through the exception register.

## Personas

- **AI agents** (Claude, Codex and others) are the only operators. They drive UzPainter through the MCP server or the Python API, in CI or interactively, and never through a GUI.
- **The owner** approves scope, exceptions, legal routes and pilots, and watches the optional preview. Artistic approval of assets stays with people and the Assets3D manifests; UzPainter records facts only.
- **Assets3D pipeline scripts** (`painter_create.py`, `painter_layer_stack.py`, `painter_export.py` and their successors) are integration clients; they must run against the `substance_painter` facade with no edits other than the host.

## Licence and clean room (owner decision 002, 2026-10-10)

UzPainter is released under the Apache License 2.0 (root `LICENSE`). Nothing may exceed what Substance Painter's licence permits: no code, shader, asset, preset or documentation text is copied from Adobe; UzPainter reproduces behaviour from public documentation and literature plus black-box calibration against Painter's outputs, which are kept as private test oracles. Rules and the dependency inventory: `licensing-and-clean-room.md`.

## Non-goals

- A human editing UI (layer panel, brush tools, viewport interaction). A read-only preview window is allowed.
- Brush strokes and any stroke engine. Painter's Python API does not expose strokes, so no AI operator can use them in Painter either (owner Q5); paint layers and paint effects are supported as layers that receive bitmaps and projections.
- Linux and macOS builds for now (owner Q9).
- Any build or run-time dependency on UzEngine (owner Q8); UzPainter vendors the rendering code it needs.
- Reading or writing `.spp` files; migration rebuilds projects from recipes and resources through Painter's documented API while Painter is installed, proven by output equality (owner Q6).
- Executing `.sbsar` files or depending on any Adobe binary; procedural content comes from UzPainter's own certified implementations, with project-private frozen snapshots only for migrating existing assets (a licensed Substance runtime was considered and rejected by the owner).
- Redistributing Adobe content of any kind (HDRIs, grunges, smart materials, presets, captures).
- Replacing the parts of the Assets3D pipeline that are not painting: Meshy generation, assembly, retopology, UV, the Blender geometry-normal bake, 3D mask computation, swatch generation, Cycles gate renders, GLB/FBX export, manifests (`docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md` §5).

## Success metrics

| Metric | Target | Measured by |
|---|---|---|
| Texture parity | Native decoded values equal to Painter goldens for every map of the certified corpus; any divergence passes only through an owner-approved recorded exception (Q1) | `architecture/14-parity-testing.md` Tiers 0–2 |
| Render parity | Equal to converged Painter Iray references; because Iray is stochastic, every residual is accepted only through an owner-approved recorded exception | Tier 3 |
| Pipeline replacement | Wand v1, Belt v5, Tunic v10 (approved), bracers (locked recipe), Hat v8, Body v6b reproduced from their recipes with equal maps; the Assets3D governance text amended after Tunic v10 passes G2 | `roadmap.md` gates G2–G5 |
| Compactness | Self-contained, portable `.uzp`; candidate budget 10 % of the matched `.spp`, ratified after the census; current and previous checkpoints plus the last 50 mutation revisions retained (owner Q11) | `architecture/09-project-file-format.md` |
| Operability | A full paint round completed through MCP alone, with Python disabled, recovering from a worker crash without losing the last committed revision | `architecture/11-mcp-server.md`, `02-runtime-topology.md` |
| Standalone | One folder runs on a clean, offline Windows 10/11 x64 machine with a GPU, without Python, Painter, Blender or SDKs installed | `architecture/13-engine-integration.md` |

The full requirement list with priorities, sources and acceptance criteria is `prd.md`.
