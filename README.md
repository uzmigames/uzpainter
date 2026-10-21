# UzPainter

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![C++23](https://img.shields.io/badge/C%2B%2B-23-blue.svg)]()
[![Zig](https://img.shields.io/badge/Zig-0.15.2-orange.svg)]()
[![Python](https://img.shields.io/badge/Python-3.13-yellow.svg)]()
[![DX12](https://img.shields.io/badge/DX12-SM_6.6-green.svg)]()
[![Platform](https://img.shields.io/badge/Windows-10%2F11_x64-lightgrey.svg)]()

Windows texturing tool for AI agents and automated pipelines. **The texture painter built to be operated by AI, with output parity as its acceptance rule.**

UzPainter is a C++23 layer compositor, project store and exporter on a render core vendored from UzEngine. Agents work through typed MCP tools or Python scripts; an optional read-only viewport shows the result. The goal is to replace Adobe Substance 3D Painter in the UzmiGames Assets3D pipeline, preserving its texture outputs and matching its Iray renders under the project's parity contract. UzPainter is not yet a complete Painter replacement or a qualified release.

## Contents

- [Key Features](#key-features)
- [Project Status](#project-status)
- [Capabilities](#capabilities)
- [Repository Layout](#repository-layout)
- [Getting Started](#getting-started)
- [Command-Line Reference](#command-line-reference)
- [Projects and File Formats](#projects-and-file-formats)
- [Python Scripting](#python-scripting)
- [MCP Server](#mcp-server)
- [Parity Testing](#parity-testing)
- [Architecture](#architecture)
- [Conventions](#conventions)
- [AI-Driven Development](#ai-driven-development)
- [Quality](#quality)
- [Thirdparty Dependencies](#thirdparty-dependencies)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

## Key Features

- **Output parity** — acceptance is equal native decoded values against Painter's own exports; a non-zero difference fails unless a versioned owner exception covers it
- **AI-operated** — typed MCP tools with jobs, idempotency keys and worker recovery; no command opens a window unless asked
- **Scriptable** — embedded CPython 3.13 with a documented `substance_painter` facade subset over the native `uzpainter` module
- **Self-contained projects** — `.uzp` files with revisions, save/reopen, recipe inspection and rebuild
- **Standalone** — the render core is vendored (copied, not linked) from UzEngine; no UzEngine checkout or runtime dependency
- **Vendored dependencies** — one `zig build` with a pinned toolchain; no separate Windows SDK installation
- **Clean room** — behaviour is implemented from permitted public sources and black-box observations; no Adobe code or assets
- **Inspectable** — `selftest`, `capabilities` and `inspect` print machine-readable JSON

## Project Status

UzPainter is **in development** (no versioned release yet) — see [`CHANGELOG.md`](CHANGELOG.md).

| Platform | Status |
|----------|--------|
| **Windows 10/11 x64** | Only target. DX12 is the implemented GPU backend (Shader Model 6.6) |
| **Vulkan (Windows)** | Planned second backend. Selecting it currently reports GPU operations unavailable; implementation and hardware qualification remain open |
| **Linux / macOS** | Out of scope |

### Acceptance gates

Status as of 2026-10-21. Gates measure usable results, not task counts.

| Gate | State | What it establishes |
|------|-------|---------------------|
| **G0** — Contract and feasibility | Accepted ([record](parity/reports/phase0/gate-g0.md)) | Reference collection, test contract and initial feasibility evidence; not full implementation feasibility |
| **G1** — Foundation and Wand | Open ([draft record](parity/reports/phase1/gate-g1.md)) | The Wand's complete exported maps must equal Painter's and remain byte-stable across runs |
| **G2** — Production pilots | Open | Belt and Tunic parity, rebuilds and a complete MCP-only Belt round; implemented tooling alone does not close it |
| **G3–G5** — Broader capability and release | Future gates | Native bake, procedurals, render parity, consumer integration, coverage and a qualified offline distribution |

**Active work:** the Wand v1 clauses of G1 (`phase1.25_pilot-wand`) — Tier 1 map equality and byte stability across two runs. Plan: [roadmap](docs/roadmap.md), [task index](docs/task-index.md). Schedule estimates are hypotheses, not delivery commitments.

## Capabilities

Implemented features have different evidence and support limits. Use the
[capability manifest guide](tools/capabilities/README.md) for individual operations and contexts.

| Area | Available now | Current limits |
|------|---------------|----------------|
| **Automation** | Embedded Python, a documented `substance_painter` facade subset, typed MCP tools, jobs and worker recovery | API coverage is partial; `run_python` requires `--allow-python` |
| **Projects** | Self-contained `.uzp` files, revisions, save/reopen, recipe inspection and rebuild | No `.spp` reader; migration uses Painter's documented APIs |
| **Texturing** | Fill layers, groups, masks, levels, blend modes, uniform and bitmap sources, supported UV projection cases | Colour conversion and texture filtering have bounded support and remaining parity gaps across combinations; consult capabilities and subsystem evidence |
| **Export** | PNG and OpenEXR, supported PBR configurations, publication and receipts | Wand export is still under qualification, including UV-island padding |
| **Preview and capture** | Read-only viewport, offscreen viewport captures and channel/mask captures | Preview is not render-parity evidence; the viewport and its captures need an OCIO project (Legacy is refused, decision 038); `painter_iray` is unavailable |
| **Baking and procedurals** | Imported mesh maps; feasibility prototypes and private reference data | Native bakers, editable procedural families and the clean-room path tracer remain future work |

Brush strokes are outside the agreed scope. Arbitrary `.sbsar` execution is unsupported. Unreal
and UzEngine export integration, broader node coverage and release packaging still have open work.

## Repository Layout

| Package | Description | Build |
|---------|-------------|-------|
| [`src/`](src/) | UzPainter C++ sources: evaluator, store, export, render, bake, mesh, preview, supervisor, Python host | Zig (`build.zig`) |
| [`python/`](python/) | `substance_painter` facade, `uzpainter_facade` implementation, supervisor (MCP SDK host) | Installed into `bin/python/` |
| [`adapters/`](adapters/) | UzmiGames pipeline adapter (`assets3d`) | Python |
| [`assets/`](assets/) | Project templates, export presets, procedural library, environments, baking defaults | JSON / EXR |
| [`parity/`](parity/) | Parity contract, public golden manifests and envelopes, fixtures, semantics fits, reports | JSON / Markdown |
| [`tools/`](tools/) | Repository tooling: parity recorder, store, guard and fits; capabilities; vendoring; sources | Python |
| [`tests/`](tests/) | pytest suites, including the drivers of the native C++ tests | pytest / Zig |
| [`thirdparty/`](thirdparty/) | Vendored UzEngine render core and third-party libraries, each with `ORIGIN.md` | Zig |
| [`docs/`](docs/) | PRD, architecture, roadmap, DAG, task index, analyses | Markdown |

Inside `src/`:

```
src/
├── main.cpp       Command dispatch for UzPainter.exe
├── uzp_core/      Document model, manifest, operation records, transactions
├── store/         Project store (.uzp), inspect, export-bundle, census
├── evaluator/     Layer-stack compositor (fills, masks, levels, blends)
├── render/        GPU layer over the vendored render core (kernels, readback, UV raster, caches)
├── export/        Plan compiler, PNG/OpenEXR writers, padding, presets, receipts
├── mesh/          Mesh importers, certificate, tangents
├── bake/          CPU baker (Embree)
├── procedural/    Procedural sources and the asset library
├── preview/       Read-only viewport and offscreen captures
├── supervisor/    MCP supervisor, worker IPC, jobs, lease, ledger
├── python/        Embedded CPython host and the native uzpainter module
└── selftest/      Hardware, shader, readback and embedded-Python checks
```

## Getting Started

Run these commands from the repository root in PowerShell.

### Prerequisites

- Windows 10/11 x64, the target platform
- **[Zig 0.15.2](https://ziglang.org/download/0.15.2/release-notes.html) exactly**; the build rejects other versions
- Python 3.13 on `PATH` for build-time capability generation and repository tooling
- A compatible GPU and driver for GPU operations: DX12 with Shader Model 6.6

Dependencies are vendored. No separate Windows SDK installation or UzEngine build is used.

### Build

```powershell
zig build painter
.\zig-out\bin\UzPainter.exe selftest
.\zig-out\bin\UzPainter.exe capabilities
```

`zig build painter` installs the executable and its runtime files into `zig-out\bin`. Keep that
folder together: the build includes embedded CPython, native libraries, Python packages and assets.
It is not a single-file executable. This development build is not the final release qualification.

`selftest` reports hardware, shader, readback and embedded-Python checks. Its default report is
`%LOCALAPPDATA%\UzPainter\selftest\selftest-report.json`. To run only checks that need no GPU:

```powershell
.\zig-out\bin\UzPainter.exe selftest --no-gpu
```

Skipping GPU checks does not qualify a GPU backend. For toolchain details, backend requirements
and packaging constraints, see the [build and runtime contract](docs/architecture/13-engine-integration.md).

### Run

The following commands use your own script, project and export configuration. Replace example
paths and export identity values with yours.

```powershell
# Host a script with the embedded API and compatibility facade.
.\zig-out\bin\UzPainter.exe run .\paint.py --gpu-backend dx12

# Inspect a saved project, or dump its rebuild recipe.
.\zig-out\bin\UzPainter.exe inspect .\project.uzp
.\zig-out\bin\UzPainter.exe inspect .\project.uzp --recipe

# Export using a supported Painter-style JSON configuration.
.\zig-out\bin\UzPainter.exe export .\project.uzp --config .\export.json --app-version "<version>" --build "<build-id>"

# Open the optional read-only preview.
.\zig-out\bin\UzPainter.exe --preview .\project.uzp --gpu-backend dx12
```

### Test

Python tests run with pytest; the native C++ tests are built by `zig build` steps and driven by
their pytest suites (for example `tests/render/` builds `zig build render-tests`).

```powershell
python -m pytest tests/<area>        # one subsystem's suite
python -m ruff check <paths>         # lint
python -m mypy                       # strict type-check (files from pyproject.toml)
```

GPU and oracle checks run locally on a qualified machine; see [Parity Testing](#parity-testing).

## Command-Line Reference

`UzPainter.exe --help` prints the usage below.

| Command | Description |
|---------|-------------|
| `selftest [--out-dir <dir>] [--report <file>] [--no-gpu]` | Hardware, shader, readback and embedded-Python checks with a JSON report |
| `inspect <file.uzp> [--revision N] [--verify \| --recipe]` | Print the project manifest, verify it, or dump its rebuild recipe |
| `export-bundle <file.uzp> <dir\|file.zip> [--revision N]` | Write the project as ZIP + JSON + PNG for humans and tools |
| `store-census --inputs <inputs.json> --assets-root <dir> --work <dir> --out <report.json> [--edits N]` | Project size census |
| `export <file.uzp> --config <config.json> --app-version <version> --build <id>` | Export maps with a Painter-style JSON configuration |
| `export --recover <exportPath> [--fixed-names <dir>]...` | Recover an interrupted export publication |
| `run <script.py> [args...] [--gpu-backend dx12\|vulkan] [-- args...]` | Run a Python script with the embedded API and facade |
| `capabilities` | Print the capability manifest |
| `assets list [--parity] [--library <dir>]` | List the procedural asset library |
| `cache info \| clear` | Inspect or clear the render caches |
| `--preview <file.uzp> [--gpu-backend dx12\|vulkan] [--headless]` | Open the read-only preview window |
| `--mcp [--mcp-http <host>:<port> [--token <token>] [--allow-remote]] [--roots <kind>=<dir>;...] [--gpu-backend dx12\|vulkan] [--allow-python]` | Start the MCP server (stdio by default) |

### Global options

| Option | Description |
|--------|-------------|
| `--headless` (or `UZP_HEADLESS=1`) | Refuse any window; a requested preview is a usage error. Set it for agents |
| `--no-cache` (or `UZP_NO_CACHE=1`) | Disable the render caches for this process and its workers |
| `--gpu-backend dx12\|vulkan` | One backend per process, fixed for its life; no silent fallback (default DX12) |

No command opens a window unless `--preview` asks for one; captures render offscreen.

## Projects and File Formats

A **project** (`.uzp`) is a SQLite database holding revisions, content-addressed blobs and
operation records; every payload is zstd-compressed. The container is an implementation detail:
the **public schema is the JSON manifest**, which `inspect` prints and `export-bundle` writes.
See [project file format](docs/architecture/09-project-file-format.md) and
[project model](docs/architecture/03-project-model.md).

| File | Encoding | Content |
|------|----------|---------|
| `.uzp` | SQLite + zstd | Project: revisions, manifests, blobs, operation records |
| Manifest | JSON | Document: texture sets, stacks, channels, layer trees, sources, resources, mesh maps, bake settings |
| Export configuration | JSON | Painter-style export settings ([`assets/export-presets/`](assets/export-presets/)) |
| Project template | JSON | Channel set and storage format per channel ([`assets/templates/`](assets/templates/)) |
| `capabilities.json` | JSON | Capability manifest generated at build time (`zig build capabilities`) |
| `.uzmat` / `.uztexture` | JSON / binary | UzEngine export preset, written with UzPainter's own code |

## Python Scripting

`UzPainter.exe run <script.py>` hosts a script in the embedded CPython 3.13. Scripts written for
Painter's documented Python API run against the `substance_painter` facade subset.

| Package | Role |
|---------|------|
| `substance_painter` | Painter's documented modules; each re-exports documented names only |
| `substance_painter_plugins` | Plugin loading for non-UI `startup/`, `plugins/` and `modules/` folders |
| `uzpainter_facade` | Pure-Python implementation over the native `uzpainter` module |
| `uzpainter` | Native module (pybind11) over the document, evaluator and exporter |

A documented symbol that is not implemented raises `AttributeError` or `NotYetSupported`; the
capability manifest lists it as a gap. Details: [Python API](docs/architecture/10-python-api.md),
[facade](python/FACADE.md), [native module](src/python/PYAPI.md).

## MCP Server

Configure the absolute path to `zig-out\bin\UzPainter.exe` as the MCP client's server command,
with `--mcp` as an argument. The server uses stdio; `--mcp-http` runs a resident HTTP instance.

- **Typed tools** — project, texture set, resource, stack, recipe, baking and mesh families; capability gates are checked per argument value and fail closed
- **Jobs** — long operations (bake, export, capture, import, reload) return a `job_id` with progress, cancellation and a terminal status
- **Resources** — `uzpainter://capabilities` publishes the shipped capability manifest
- **Roots** — file access is limited to the allowlisted `--roots`
- **`run_python`** — arbitrary Python is disabled unless `--allow-python` is supplied

See the [MCP contract](docs/architecture/11-mcp-server.md) for tools, jobs and roots.

## Parity Testing

Texture acceptance requires equal native decoded values. A non-zero difference is a failure unless
an explicit, versioned owner exception covers it. Iray is stochastic: render acceptance requires
measured references, a noise-floor analysis and approved exceptions. Preview images and passing
micro-tests cannot stand in for production-pilot acceptance.

| Tier | Compares |
|------|----------|
| **Tier 0 — Semantics** | Synthetic fixtures: blend modes, masks, projections, defaults, templates, API behaviour |
| **Tier 1 — Recipes** | Assets3D stacks rebuilt from the same JSON and resources in both tools: exported maps |
| **Tier 2a — Procedurals** | Certified procedural asset outputs |
| **Tier 2b — Bakes** | Native baker hit/coverage evidence, then maps |
| **Tier 3 — Renders** | Clean-room path tracer (`painter_iray`) against Painter Iray references |

Painter outputs are private oracle data, never repository assets. Full parity checks need the
owner's private store and qualified local environment; a fresh clone does not contain those goldens.
Runtime operation does not require Painter, but recording new Painter references does.

Contract and tooling: [parity contract](parity/CONTRACT.md), [testing architecture](docs/architecture/14-parity-testing.md),
[private store](parity/STORE.md), [recorder](parity/RECORDER.md), [repository guard](parity/GUARD.md).

## Architecture

### Processes

One executable, two roles. The process an AI client launches is the one that survives faults:

```
AI client ──stdio / HTTP──→ UzPainter.exe --mcp            Supervisor
                              │  MCP SDK on embedded CPython, command admission,
                              │  mutation lease, durable job ledger
                              │
                              └──named pipe (JSON frames)──→ UzPainter.exe --worker
                                                             One document, project store,
                                                             RHI device, evaluator, bakers,
                                                             exporter, embedded facade
```

`run`, the CLI verbs and `--preview` host the worker role directly in a single process.
Details: [runtime topology](docs/architecture/02-runtime-topology.md).

### Vendored render core

```
UzEngine (clean commit) ──copy once──→ thirdparty/uzengine-render-core/
                                         RHI (DX12, Vulkan), shader compiler and cache,
                                         .uztexture header, math, logging
                                            │
                                            └──→ src/render/   UzPainter's GPU layer
                                                 (kernels, TextureReadback, UV raster)
```

There is no link against UzEngine, no submodule, no pin and no patch queue; the copy evolves
independently and its modifications are listed in
[`MODIFICATIONS.md`](thirdparty/uzengine-render-core/MODIFICATIONS.md).

More: [system overview](docs/architecture/01-overview.md), [`docs/architecture/`](docs/architecture/).

## Conventions

| Category | Convention |
|----------|------------|
| Acceptance | Exact equality of native decoded values; divergence only through a versioned owner exception |
| Revisions | Monotonic integer per committed mutation; results, exports and captures name their revision |
| Resources | Immutable bytes identified by SHA-256 |
| Tangent frame | MikkTSpace |
| Normal maps | OpenGL (+Y) for the Assets3D contract; the UzEngine preset writes DirectX |
| GPU backend | One per process, part of every render receipt |

## AI-Driven Development

The repository is set up so AI agents can work on it end to end:

- **MCP-first product** — the same typed operations serve agents and the pipeline; `capabilities` tells an agent what is supported before it calls
- **Rulebook** — tasks, decisions and memory via the `rulebook` MCP server ([`.mcp.json`](.mcp.json)). Rules live in [`AGENTS.md`](AGENTS.md) and [`AGENTS.override.md`](AGENTS.override.md); tasks in `.rulebook/tasks/`, indexed in [`docs/task-index.md`](docs/task-index.md)
- **Machine-readable evidence** — `selftest`, `capabilities`, `inspect` and export receipts are JSON
- **Evidence gates** — each phase closes at a gate record under `parity/reports/`, never by task count

## Quality

| Tool | Native (C++) | Python tooling and facade |
|------|--------------|---------------------------|
| **Build** | Zig 0.15.2 (`build.zig`) | — |
| **Lint** | — | ruff |
| **Type-check** | C++23 compiler | mypy `--strict` |
| **Test** | Native test executables driven by pytest | pytest |
| **Guard** | Pre-commit repository guard (`tools.parity.guard --staged`) | |
| **CI** | Codespell (`.github/workflows/codespell.yml`) | |

- **Local evidence** — GPU and oracle checks run on the owner's machine; the full local gate, rather than hosted parity CI, supplies acceptance evidence
- **Repository guard** — blocks any commit that would record a private oracle output

## Thirdparty Dependencies

All dependencies are vendored under [`thirdparty/`](thirdparty/), each with an `ORIGIN.md` and a
`MANIFEST.json`: the UzEngine render core, CPython 3.13 (embeddable) and its wheels, pybind11,
Agility SDK, DirectX-Headers, DirectXMath, DXC, D3D12MA, Vulkan-Headers, volk, VMA, SPIRV-Reflect,
Embree, MikkTSpace, ufbx, fastgltf, simdjson, SQLite, zstd, zlib, spng, tinyexr, etcpak, spdlog,
Tracy and the Visual C++ runtime. Attribution is in [`NOTICE`](NOTICE).

## Documentation

| Where | What |
|-------|------|
| [Documentation index](docs/README.md) | Reading order and map of the docs |
| [Architecture](docs/architecture/01-overview.md) | System context, vocabulary, components ([all documents](docs/architecture/)) |
| [PRD](docs/prd.md) / [Vision](docs/vision.md) | Product requirements and goals |
| [Roadmap](docs/roadmap.md) / [DAG](docs/dag.md) / [Task index](docs/task-index.md) | Phases and gates, dependency graph, rulebook tasks |
| [Parity contract](parity/CONTRACT.md) | Equality rule, exceptions, golden schemas |
| [Clean room](docs/licensing-and-clean-room.md) / [Approved sources](docs/approved-sources.md) | Licensing policy and permitted sources |
| [Analyses](docs/analysis/) | Historical evidence; not implementation inputs until cleared |
| [Changelog](CHANGELOG.md) | Changes, task by task |

## Contributing

Before contributing, follow the [implementation reading guide](docs/README.md#reading-order),
[clean-room rules](docs/licensing-and-clean-room.md) and [approved-source index](docs/approved-sources.md).
Install the repository's commit guard once per clone:

```powershell
git config core.hooksPath .githooks
```

Run the checks required by the affected subsystem. Commits follow Conventional Commits (`feat`,
`fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`).

## License

[Apache License 2.0](LICENSE) — Copyright 2026 UzmiGames. See [NOTICE](NOTICE) and the
[licensing and clean-room policy](docs/licensing-and-clean-room.md).
Behaviour is implemented from permitted public sources and black-box observations; Adobe code,
assets and recorded outputs are not redistributed.
