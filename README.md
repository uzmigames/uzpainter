# UzPainter

[![Status](https://img.shields.io/badge/status-analysis%20phase-yellow.svg)](#project-status)
[![Engine](https://img.shields.io/badge/engine-UzEngine-blue.svg)](docs/analysis/uzengine-renderer/)
[![Analyses](https://img.shields.io/badge/analyses-4%20topics-blue.svg)](docs/analysis/)

> **AI-operated texturing tool built on UzEngine — a replacement for Adobe Substance 3D Painter**

UzPainter is a planned texturing tool operated 100% by AI. Agents drive it through a Python API
and a native MCP server; there is no human editing UI, at most a read-only preview window.
Headless (CI / batch) is the primary mode, the renderer is built from UzEngine, and the end goal
is a standalone Windows `.exe` that anyone can run locally.

Its first job is to fully replace Substance 3D Painter in the
[Assets3D pipeline](docs/analysis/assets3d-pipeline/) (Tales of Shadowland creatures).

**Acceptance bar: output parity.** Given the same sequence of instructions, UzPainter must produce
the same textures and the same render as Substance 3D Painter. Matching features is not enough;
divergent output is a bug ([decision 001](.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md)).

---

## Overview

```
Today                                     With UzPainter
────────────────────────────────────      ────────────────────────────────────
AI agent                                  AI agent
  │  stdio MCP                              │  native MCP  /  Python API
  ▼                                         ▼
SubstancePainterMCP (+ local patch)       UzPainter   ← layer stack, bake, export
  │  remote scripting (Python)              │           UzEngine renderer, headless
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
[requirements for UzPainter](docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md).

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
| Renderer | Painter's own | UzEngine (C++23, DX12 primary) |
| Project file | `.spp`; 0.4–1.2 GB for the three pieces measured | Compact container (format not chosen yet) |
| Output | Reference | Must match the reference (output parity) |

Left-column facts come from [how Painter is driven today](docs/analysis/assets3d-pipeline/02-painter-usage.md)
and [requirements NFR-04](docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md).

---

## Quick Start

Not available yet. The repository holds analysis documents only — there is no source code, build
script or executable. Build and run instructions arrive with the first code.

---

## Repository Layout

| Path | Contents |
|------|----------|
| [`docs/analysis/`](docs/analysis/) | Source-cited analyses, one theme per numbered file |
| [`.rulebook/tasks/`](.rulebook/tasks/) | Active work items (checklists) |
| [`.rulebook/decisions/`](.rulebook/decisions/) | Decision records |
| [`.rulebook/specs/`](.rulebook/specs/) | Project rules: quality gates, git, orchestration |

---

## Project Status

**Phase: Analysis** — no code yet. The current pipeline, UzEngine and the technology options have
been analyzed; the Substance parity analysis is in progress. Architecture comes next.

| Phase | Status |
|-------|--------|
| Assets3D pipeline analysis | Done |
| UzEngine renderer analysis | Done |
| Technology options research | Done |
| Substance 3D Painter parity analysis | In progress |
| Acceptance criterion — output parity | Proposed |
| Architecture document | Planned |
| Implementation | Planned |

---

## Documentation

- [Assets3D pipeline](docs/analysis/assets3d-pipeline/) — how Painter is used today: bake, painting recipes, export, review render standard, lessons
- [Requirements for UzPainter](docs/analysis/assets3d-pipeline/08-requirements-for-uzpainter.md) — MUST/SHOULD/COULD list traced to the pipeline, plus open questions
- [Substance parity](docs/analysis/substance-parity/) — Painter 12.1 Python API, layer-stack model, baking, export
- [UzEngine renderer](docs/analysis/uzengine-renderer/) — reusable modules, headless rendering, texture standard, build, gaps and risks
- [Technology options](docs/analysis/technology-options/) — Python embedding, texture compression, project container format, MCP SDKs
- [Decision 001](.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md) — acceptance criterion: output parity with Substance 3D Painter

---

## License

Not chosen yet — this repository has no `LICENSE` file.
