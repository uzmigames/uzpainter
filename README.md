# UzPainter

[![Status](https://img.shields.io/badge/status-phase%201-yellow.svg)](#project-status)
[![Render core](https://img.shields.io/badge/render%20core-vendored%20from%20UzEngine-blue.svg)](docs/architecture/13-engine-integration.md)
[![Analyses](https://img.shields.io/badge/analyses-4%20topics-blue.svg)](docs/analysis/)

> **AI-operated texturing tool with a render core vendored from UzEngine — a replacement for Adobe Substance 3D Painter**

UzPainter is a texturing tool, in development, operated 100% by AI. Agents drive it through a Python API
and a native MCP server; there is no human editing UI, at most a read-only preview window.
Headless (CI / batch) is the primary mode. The render code is copied (vendored) from UzEngine;
UzPainter has no dependency on UzEngine and builds on its own, with DX12 as the primary backend and
Vulkan as the second ([decision 021](.rulebook/decisions/021-d12-engine-relationship-zero-uzengine-dependency-vendored-render-core-on-dx12-and-vulkan-with-an-own-build.md)).
The end goal is a standalone Windows 10/11 x64 `.exe` that anyone can run locally.

Its first job is to fully replace Substance 3D Painter in the
[Assets3D pipeline](docs/analysis/assets3d-pipeline/) (Tales of Shadowland creatures).

**Acceptance bar: output parity.** Given the same sequence of instructions, UzPainter must produce
the same textures and the same render as Substance 3D Painter. Matching features is not enough;
divergent output is a bug ([decision 001](.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md)).
The render result means Painter's Iray output, reproduced by a clean-room path tracer
([decision 018](.rulebook/decisions/018-d6-render-parity-painter-s-iray-as-the-target-through-a-clean-room-path-tracer-on-dxr-and-vulkan-ray-tracing.md)).

---

## Overview

```
Today                                     With UzPainter
────────────────────────────────────      ────────────────────────────────────
AI agent                                  AI agent
  │  stdio MCP                              │  native MCP  /  Python API
  ▼                                         ▼
SubstancePainterMCP (+ local patch)       UzPainter   ← layer stack, bake, export
  │  remote scripting (Python)              │           vendored render core, headless
  ▼                                         │
Substance 3D Painter 12.1 (GUI window)      │
  │                                         │
  ▼                                         ▼
16-bit PNG maps → Blender                 PBR / ORM / UzEngine maps → same consumers
```

Today an agent paints by sending Python through a community MCP bridge into a running Painter
window. UzPainter's goal is to remove the GUI application and the bridge: agents talk to the tool
directly, and it runs without a window.

---

## Planned Features

Part of this list exists today: the layer-stack compositor, the `.uzp` project file, export with
the PBR presets, the recipe dump, the Python API and the MCP server; parity is accepted only where
its gate passes ([Project Status](#project-status)). Smart materials and generators, native baking,
the Unreal and UzEngine presets and the release distribution are not implemented yet. These are the
owner's requirements plus the MUST/SHOULD list in
[requirements for UzPainter](docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md);
the numbered requirement list is the [PRD](docs/prd.md).

### Operation
- **AI-only** — Python API + native MCP server that mirror Substance's own API structures
- **Headless first** — runs on Windows with no window or focus; live preview is optional and read-only
- **Safe automation** — one writer at a time, explicit busy state, async jobs with ids, structured errors
- **Standalone `.exe`** — one Windows executable anyone can run locally, no Substance install needed

### Texturing
- **Layer stack** — fill layers, nested groups, masks, effects, per-channel opacity and blend modes
- **Smart materials and generators** — edge wear, cavity dirt and similar, driven by mesh maps
- **Baking** — AO, normal and other mesh maps from a high-poly mesh; externally baked maps also accepted
- **Declarative stacks** — existing stack JSON files and painting recipes load unchanged

### Output
- **Export presets** — separate PBR maps, Unreal ORM packing and UzEngine's own texture standard, preferably compressed
- **Deterministic export** — the same saved project exported twice gives byte-identical files
- **Compact project file** — self-contained like `.spp`, but far smaller
- **Recipe dump** — machine-readable record of the whole stack, enough to rebuild the project

---

## vs Substance 3D Painter

| Aspect | Substance 3D Painter (today) | UzPainter (target) |
|--------|------------------------------|--------------------|
| Control | Community MCP server (SubstancePainterMCP, 79 tools) + local patch, over remote scripting | Native MCP server + Python API |
| UI | Visible Painter window the user watches; agents never use mouse or keyboard | No editing UI; optional read-only preview |
| Concurrency | One agent at a time under an external lock; simultaneous commands crashed Painter | Built-in single-writer lock; concurrent writes rejected, not crashes |
| Renderer | Painter's own (Iray for the render result) | Render core vendored from UzEngine (C++23), DX12 primary and Vulkan; clean-room path tracer for the render result |
| Project file | `.spp`; 0.4–1.2 GB for the three pieces measured | Self-contained `.uzp`: SQLite container with a JSON manifest and zstd blobs ([decision 010](.rulebook/decisions/010-d8-project-file-sqlite-container-with-a-canonical-json-manifest-and-zstd-blobs.md)) |
| Output | Reference | Must match the reference (output parity) |

Left-column facts come from [how Painter is driven today](docs/analysis/assets3d-pipeline/02-painter-usage.md)
and [requirements NFR-04](docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md).

---

## Quick Start

Requirements: Windows 10/11 x64, Zig **0.15.2** exactly (`build.zig` refuses any other release)
and Python 3.13 on `PATH`, for the repository tooling and for `zig build painter`, which runs the
capability manifest generator (`-Dpython=<exe>` names another interpreter). Every include and
library path is inside this repository; the build reads no Windows SDK installation and no UzEngine
checkout.

```bash
zig build painter                  # zig-out/bin/UzPainter.exe with its run-time files
zig-out/bin/UzPainter.exe selftest # [--out-dir <dir>] [--report <file>] [--no-gpu]
```

`selftest` runs ordered stages and writes a JSON report (default
`%LOCALAPPDATA%\UzPainter\selftest\selftest-report.json`); exit code 0 = passed, 1 = a mandatory
stage failed, 2 = usage error. Stages:

- **DX12 hardware slice** (mandatory): `dx12-device`, `shader-compile`, `compute-readback`, `png16`, `embree`
- **Probes** (never fail the run): `dx12-ray-query`, `vulkan-availability`, `vulkan-ray-query`, `warp`
- **Embedded CPython** (mandatory, no GPU): `cpython-start`, `cpython-uzpainter`, `cpython-buffer16`, `cpython-exceptions`, `cpython-mcp-sdk`

`--no-gpu` or `UZP_NO_GPU=1` skips the stages that need a GPU. Other build steps:
`zig build render-core` (`uzrendercore.lib`), `zig build native-tests`, `zig build probe-tests`.

The other commands (`UzPainter.exe` with no argument prints their usage):

```bash
UzPainter.exe run <script.py> [args...] [--gpu-backend dx12|vulkan]  # script host with the substance_painter facade
UzPainter.exe export <file.uzp> --config <config.json> --app-version <version> --build <id>  # PNG / OpenEXR maps
UzPainter.exe inspect <file.uzp> [--revision N] [--verify | --recipe]  # also export-bundle, store-census
UzPainter.exe capabilities                                             # the capability manifest
UzPainter.exe --mcp [--gpu-backend dx12|vulkan] [--allow-python]       # MCP server on stdio
UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan]         # read-only preview window
```

Captures (`capture` in the Python API and the MCP server) render `painter_viewport`, `base_color`,
`channel:<name>` or `mask:<uid>`; `painter_iray` is refused until the path tracer exists.

Repository tooling (Python, `tools/`) and its quality gate. Apart from a codespell spelling check
on GitHub there is no hosted CI: every check runs locally, in the coordinator's full gate before the
owner pushes
([decision 200](.rulebook/decisions/200-the-owner-removed-the-hosted-parity-ci-and-the-local-full-gate-replaces-it.md); GPU and
Painter-oracle checks run on the owner's machine,
[decision 028](.rulebook/decisions/028-ci-github-runs-hosted-cpu-only-ci-gpu-and-painter-oracle-checks-run-locally-on-the-owner-s-machine.md)):

```bash
python -m pip install jsonschema==4.25.1 numpy==2.4.4 pyyaml==6.0.3 ruff==0.14.3 mypy==1.20.1 pytest==9.1.1
python -m tools.parity.guard && python -m tools.vendoring.vendor_check
zig build painter && ./zig-out/bin/UzPainter.exe selftest
python -m mypy && python -m ruff check . && python -m pytest
python -m tools.parity.store verify parity/schema/samples/public   # without a store: exit 1, oracle_unavailable
git config core.hooksPath .githooks   # once per clone: blocks committing recorded oracle outputs
```

---

## Repository Layout

| Path | Contents |
|------|----------|
| [`src/`](src/) | `UzPainter.exe`: entry point, `selftest/` stages, `render/` layer, `uzp_core/` document model, `store/` project store, `mesh/` importers, `evaluator/` compositor, `export/`, `python/` embedded interpreter and native API, `supervisor/` MCP supervisor and worker, `preview/` window |
| [`python/`](python/) | Python packages installed beside the executable: the `substance_painter` facade and the supervisor's MCP code (`uzpainter_supervisor/`) |
| [`adapters/`](adapters/) | Assets3D pipeline adapter (`assets3d/`) |
| [`assets/`](assets/) | Shipped project templates, export presets and display environments |
| [`build.zig`](build.zig) | Own Zig build: render core, native tests, `UzPainter.exe` |
| [`thirdparty/`](thirdparty/) | Vendored code with licences and provenance: `uzengine-render-core/`, DX12/Vulkan libraries, Embree, zlib, spng, CPython, pybind11, MCP SDK wheels |
| [`tools/`](tools/) | Python tooling: `parity/` (oracle store, recorder, guard, fits), `vendoring/`, `toolchain/`, `sources/` |
| [`tests/`](tests/) | Python tests, plus C++ tests in `native/` and the module folders |
| [`parity/`](parity/) | Parity contract, schemas, exception register, fixtures, published fits (`semantics/`) and run reports (`reports/`) |
| [`docs/`](docs/) | Build contract: vision, PRD, roadmap, DAG, [`architecture/`](docs/architecture/) 01–14 |
| [`docs/analysis/`](docs/analysis/) | Source-cited analyses, one theme per numbered file |
| [`.rulebook/tasks/`](.rulebook/tasks/) | Active work items (checklists); finished ones in `.rulebook/archive/` |
| [`.rulebook/decisions/`](.rulebook/decisions/) | Decision records |
| [`.rulebook/specs/`](.rulebook/specs/) | Project rules: quality gates, git, orchestration |

---

## Project Status

**Phase 1: Foundation and wand smoke** ([roadmap](docs/roadmap.md)), as of 2026-10-13. Phase 0 is
complete: gate G0 closed on 2026-10-13 ([gate record](parity/reports/phase0/gate-g0.md)). Phase 1
has 39 of its 43 tasks archived; it closes at gate G1 once the Wand v1 maps equal Painter's. Most
Phase 2 code (preview window and captures, supervisor and MCP server, recipe dump and diagnostics)
is written; its tasks wait on the Wand v1 pilot, and two of them also on Vulkan device-loss tests
(decisions 121, 200). The DX12 hardware slice and the four probes pass
on the owner's machine ([probe report](parity/reports/phase0/toolchain-probes.md)).

| Work | Status |
|------|--------|
| Analyses: Assets3D pipeline, UzEngine renderer, technology options, Substance parity | Done |
| Product and architecture documents (`docs/`) | Done |
| Decisions 001–209 (`.rulebook/decisions/`) | Recorded |
| Approved-source index; parity contract and schemas | Done |
| Render core and third-party libraries vendored; own Zig build | Done |
| Private oracle store, repository guard, Painter oracle recorder | Done |
| `UzPainter.exe selftest`: DX12 hardware slice; Vulkan, ray-query and WARP probes | Done |
| Tier 0 oracles recorded (defaults, templates, API probes, layer semantics); procedural feasibility | Done |
| Embedded CPython 3.13 and MCP SDK (`phase0.7_toolchain-cpython`) | Done |
| Tier 0 oracle stability and first formula fits (`phase0.7_tier0-stability-fits`, [report](parity/reports/phase0/tier0-stability.md)) | Done |
| Iray reference capture and noise floor (`phase0.9_render-reference-capture`, [path-tracer entry gate](parity/reports/phase0/gate-p3-pathtracer-entry.md)) | Done |
| Gate G0 — contract frozen ([gate record](parity/reports/phase0/gate-g0.md)) | Done |
| Render-core layer, document model, project store, mesh loader, compositor core, export engine | Done |
| Native Python API, `substance_painter` facade, `run`, Assets3D pipeline adapter (`phase1.19`–`phase1.23`) | Done |
| Compositor colour fits, Python API parent, Wand v1 pilot (`phase1.15_compositor-colour-fits`, `phase1.24_python-api-facade`, `phase1.25_pilot-wand`) | In progress |
| Gate G1 — foundation green | Planned |
| Phase 2: preview window and captures, supervisor and MCP server, recipe dump and diagnostics | In progress |
| Phase 2: Belt v5 and Tunic v10 pilots, gate G2; Phases 3–5: bake/render/presets, coverage, release | Planned |

Task list: [`.rulebook/tasks/README.md`](.rulebook/tasks/README.md). History: [`CHANGELOG.md`](CHANGELOG.md).

---

## Documentation

- [Documentation index](docs/README.md) — reading order; [vision](docs/vision.md), [PRD](docs/prd.md), [roadmap](docs/roadmap.md), [work-package DAG](docs/dag.md)
- [Architecture](docs/architecture/) — fourteen documents, from [overview](docs/architecture/01-overview.md) to [parity testing](docs/architecture/14-parity-testing.md)
- [Parity contract](parity/CONTRACT.md) — exact equality, tiers 0–3, exception register; operator guides [`STORE.md`](parity/STORE.md), [`RECORDER.md`](parity/RECORDER.md), [`GUARD.md`](parity/GUARD.md)
- [Assets3D pipeline](docs/analysis/assets3d-pipeline/) — how Painter is used today: bake, painting recipes, export, review render standard, lessons
- [Requirements for UzPainter](docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md) — MUST/SHOULD/COULD list traced to the pipeline, plus open questions
- [Substance parity](docs/analysis/substance-parity/) — Painter 12.1 Python API, layer-stack model, baking, export
- [UzEngine renderer](docs/analysis/uzengine-renderer/) — reusable modules, headless rendering, texture standard, build, gaps and risks
- [Technology options](docs/analysis/technology-options/) — Python embedding, texture compression, project container format, MCP SDKs
- [Decision 001](.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md) — acceptance criterion: output parity with Substance 3D Painter

---

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Development follows a strict
clean-room policy toward Substance 3D Painter: its behaviour is reproduced, never its code or assets
([licensing and clean room](docs/licensing-and-clean-room.md), [decision 002](.rulebook/decisions/002-license-apache-2-0-with-a-strict-clean-room-policy-toward-substance-painter.md)).
