# UzPainter

UzPainter is a Windows texturing tool for AI agents and automated pipelines. Agents work through
typed MCP tools or Python scripts; an optional read-only viewport shows the result.

**In development.** The goal is to replace Adobe Substance 3D Painter in the UzmiGames Assets3D
pipeline, preserving its texture outputs and matching its Iray renders under the project's parity
contract. UzPainter is not yet a complete Painter replacement or a qualified release.

The rendering foundation is vendored from UzEngine. UzPainter builds independently, with no
UzEngine checkout or runtime dependency. Its own compositor, project store, APIs and exporters
sit above that foundation.

## What works today

Implemented features have different evidence and support limits. Use the
[capability manifest guide](tools/capabilities/README.md) for individual operations and contexts.

| Area | Available now | Current limits |
|---|---|---|
| Automation | Embedded Python, a documented `substance_painter` facade subset, typed MCP tools, jobs and worker recovery | API coverage is partial; `run_python` requires `--allow-python` |
| Projects | Self-contained `.uzp` files, revisions, save/reopen, recipe inspection and rebuild | No `.spp` reader; migration uses Painter's documented APIs |
| Texturing | Fill layers, groups, masks, levels, blend modes, uniform and bitmap sources, supported UV projection cases | Colour conversion and texture filtering have bounded support and remaining parity gaps across combinations; consult capabilities and subsystem evidence |
| Export | PNG and OpenEXR, supported PBR configurations, publication and receipts | Wand export is still under qualification, including UV-island padding |
| Preview and capture | Read-only viewport, offscreen viewport captures and channel/mask captures | Preview is not render-parity evidence; `painter_iray` is unavailable |
| Baking and procedurals | Imported mesh maps; feasibility prototypes and private reference data | Native bakers, editable procedural families and the clean-room path tracer remain future work |

Brush strokes are outside the agreed scope. Arbitrary `.sbsar` execution is unsupported. Unreal
and UzEngine export integration, broader node coverage and release packaging still have open work.

### Acceptance status

Status as of 2026-10-13. Gates measure usable results, not task counts.

| Gate | State | What it establishes |
|---|---|---|
| G0 - Contract and feasibility | Accepted ([record](parity/reports/phase0/gate-g0.md)) | Reference collection, test contract and initial feasibility evidence; not full implementation feasibility |
| G1 - Foundation and Wand | Open | The Wand's complete exported maps must equal Painter's and remain byte-stable across runs |
| G2 - Production pilots | Open | Belt and Tunic parity, rebuilds and a complete MCP-only Belt round; implemented tooling alone does not close it |
| G3-G5 - Broader capability and release | Future gates | Native bake, procedurals, render parity, consumer integration, coverage and a qualified offline distribution |

See the [roadmap](docs/roadmap.md), [task index](docs/task-index.md) and
[changelog](CHANGELOG.md). Schedule estimates are hypotheses, not delivery commitments.

## Build from source

Run these commands from the repository root in PowerShell.

Requirements:

- Windows 10/11 x64, the target platform.
- **Zig 0.15.2 exactly**; the build rejects other versions.
- Python 3.13 on `PATH` for build-time capability generation and repository tooling.
- A compatible GPU and driver for GPU operations. DX12 is the implemented GPU backend and requires
  Shader Model 6.6. Selecting Vulkan currently reports GPU operations unavailable; implementation
  and hardware qualification remain planned.

Dependencies are vendored. No separate Windows SDK installation or UzEngine build is used.

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

## Run

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

For an MCP client, configure the absolute path to `zig-out\bin\UzPainter.exe` as its server command,
with `--mcp` as an argument. The server uses stdio; arbitrary Python execution is disabled unless
`--allow-python` is supplied. See the [MCP contract](docs/architecture/11-mcp-server.md) for typed
tools, jobs and roots, and the [Python API](docs/architecture/10-python-api.md) for script support.

## Parity and contributions

Texture acceptance requires equal native decoded values. A non-zero difference is a failure unless
an explicit, versioned owner exception covers it. Iray is stochastic: render acceptance requires
measured references, a noise-floor analysis and approved exceptions. Preview images and passing
micro-tests cannot stand in for production-pilot acceptance.

Painter outputs are private oracle data, never repository assets. Full parity checks need the
owner's private store and qualified local environment; a fresh clone does not contain those goldens.
Runtime operation does not require Painter, but recording new Painter references does.

Before contributing, follow the [implementation reading guide](docs/README.md#reading-order),
[clean-room rules](docs/licensing-and-clean-room.md) and [approved-source index](docs/approved-sources.md).
Install the repository's commit guard once per clone:

```powershell
git config core.hooksPath .githooks
```

Run the checks required by the affected subsystem. GPU and oracle checks run locally; the full
local gate, rather than hosted parity CI, supplies acceptance evidence.

## Documentation

- [Documentation index](docs/README.md) and [architecture overview](docs/architecture/01-overview.md)
- [Product requirements](docs/prd.md), [roadmap](docs/roadmap.md) and [dependency graph](docs/dag.md)
- [Parity contract](parity/CONTRACT.md) and [testing architecture](docs/architecture/14-parity-testing.md)
- [Private store](parity/STORE.md), [recorder](parity/RECORDER.md) and [repository guard](parity/GUARD.md)

## License

Apache License 2.0. See [LICENSE](LICENSE), [NOTICE](NOTICE) and the
[licensing and clean-room policy](docs/licensing-and-clean-room.md).
Behaviour is implemented from permitted public sources and black-box observations; Adobe code,
assets and recorded outputs are not redistributed.
