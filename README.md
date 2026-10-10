# UzPainter

[![Status](https://img.shields.io/badge/status-phase%200-yellow.svg)](#project-status)
[![Render core](https://img.shields.io/badge/render%20core-vendored%20from%20UzEngine-blue.svg)](docs/architecture/13-engine-integration.md)
[![Analyses](https://img.shields.io/badge/analyses-4%20topics-blue.svg)](docs/analysis/)

> **AI-operated texturing tool with a render core vendored from UzEngine — a replacement for Adobe Substance 3D Painter**

UzPainter is a planned texturing tool operated 100% by AI. Agents drive it through a Python API
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

Nothing below is implemented yet. These are the owner's requirements plus the MUST/SHOULD list in
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

Only the Phase 0 build exists: `UzPainter.exe` has a single command, `selftest`. Requirements:
Windows 10/11 x64, Zig **0.15.2** exactly (`build.zig` refuses any other release) and Python 3.13
for the repository tooling. Every include and library path is inside this repository; the build
reads no Windows SDK installation and no UzEngine checkout.

```bash
zig build painter                  # zig-out/bin/UzPainter.exe with its run-time files
zig-out/bin/UzPainter.exe selftest # [--out-dir <dir>] [--report <file>] [--no-gpu]
```

`selftest` runs ordered stages and writes a JSON report (default
`%LOCALAPPDATA%\UzPainter\selftest\selftest-report.json`); exit code 0 = passed, 1 = a mandatory
stage failed, 2 = usage error. Stages:

- **DX12 hardware slice** (mandatory): `dx12-device`, `shader-compile`, `compute-readback`, `png16`, `embree`
- **Probes** (never fail the run): `dx12-ray-query`, `vulkan-availability`, `vulkan-ray-query`, `warp`
- **Embedded CPython** (`cpython-*`): in progress, task `phase0.7_toolchain-cpython`

`--no-gpu` or `UZP_NO_GPU=1` skips the stages that need a GPU. Other build steps:
`zig build render-core` (`uzrendercore.lib`), `zig build native-tests`, `zig build probe-tests`.

Repository tooling (Python, `tools/`) and its quality gate, as hosted CI runs them
([`.github/workflows/parity.yml`](.github/workflows/parity.yml), CPU-only; GPU and Painter-oracle
checks run locally on the owner's machine, [decision 028](.rulebook/decisions/028-ci-github-runs-hosted-cpu-only-ci-gpu-and-painter-oracle-checks-run-locally-on-the-owner-s-machine.md)):

```bash
python -m pip install jsonschema numpy pyyaml ruff mypy pytest   # pinned versions: parity.yml
python -m mypy && python -m ruff check . && python -m pytest
git config core.hooksPath .githooks   # once per clone: blocks committing recorded oracle outputs
```

---

## Repository Layout

| Path | Contents |
|------|----------|
| [`src/`](src/) | `UzPainter.exe`: entry point, `selftest/` stages, `python/` embedded interpreter |
| [`build.zig`](build.zig) | Own Zig build: render core, native tests, `UzPainter.exe` |
| [`thirdparty/`](thirdparty/) | Vendored code with licences and provenance: `uzengine-render-core/`, DX12/Vulkan libraries, Embree, zlib, spng, CPython, pybind11, MCP SDK wheels |
| [`tools/`](tools/) | Python tooling: `parity/` (oracle store, recorder, guard, fits), `vendoring/`, `toolchain/`, `sources/` |
| [`tests/`](tests/) | Python tests, plus C++ tests in `native/` |
| [`parity/`](parity/) | Parity contract, schemas, exception register, fixtures, published fits (`semantics/`) and run reports (`reports/`) |
| [`docs/`](docs/) | Build contract: vision, PRD, roadmap, DAG, [`architecture/`](docs/architecture/) 01–14 |
| [`docs/analysis/`](docs/analysis/) | Source-cited analyses, one theme per numbered file |
| [`.rulebook/tasks/`](.rulebook/tasks/) | Active work items (checklists); finished ones in `.rulebook/archive/` |
| [`.rulebook/decisions/`](.rulebook/decisions/) | Decision records |
| [`.rulebook/specs/`](.rulebook/specs/) | Project rules: quality gates, git, orchestration |

---

## Project Status

**Phase 0: Contract and feasibility** ([roadmap](docs/roadmap.md)). Analyses, architecture and the
owner's decisions are done. Phase 0 code exists: the vendored render core with its own build,
`UzPainter.exe selftest` and the parity tooling. No texturing feature is implemented yet. The DX12
hardware slice and the four probes pass on the owner's machine
([probe report](parity/reports/phase0/toolchain-probes.md)).

| Work | Status |
|------|--------|
| Analyses: Assets3D pipeline, UzEngine renderer, technology options, Substance parity | Done |
| Product and architecture documents (`docs/`) | Done |
| Owner decisions 001–030 (`.rulebook/decisions/`) | Recorded |
| Approved-source index; parity contract and schemas | Done |
| Render core and third-party libraries vendored; own Zig build | Done |
| Private oracle store, repository guard, Painter oracle recorder | Done |
| `UzPainter.exe selftest`: DX12 hardware slice; Vulkan, ray-query and WARP probes | Done |
| Tier 0 oracles recorded (defaults, templates, API probes, layer semantics); procedural feasibility | Done |
| Embedded CPython 3.13 and MCP SDK (`phase0.7_toolchain-cpython`) | In progress |
| Tier 0 oracle stability and first formula fits (`phase0.7_tier0-stability-fits`) | In progress |
| Iray reference capture procedure (`phase0.6_render-reference-procedure`) | In progress |
| Gate G0 — contract frozen | Planned |
| Phases 1–5: foundation, pilot parity, bake/render/presets, coverage, release | Planned |

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
