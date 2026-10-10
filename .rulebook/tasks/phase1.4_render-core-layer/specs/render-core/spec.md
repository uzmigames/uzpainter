## ADDED Requirements

### Requirement: Render-core layer accepted on DX12
The render-core layer SHALL pass its unit tests on synthetic meshes and its readback drain tests on the DX12 hardware adapter before P1-COMPOSITOR builds on it.

#### Scenario: Phase 1 acceptance run
Given all four children of `phase1.4_render-core-layer` are accepted
When the render-layer suite runs on the DX12 hardware adapter in a local run on the owner's machine (decision 028)
Then the synthetic-mesh unit tests and the readback drain tests pass and the run records hardware, driver, backend and build hash

### Requirement: Backend-neutral render-layer interfaces
UzPainter code above the render layer MUST depend only on backend-neutral interfaces; no DX12 type SHALL cross the interface, and the backend SHALL be chosen only by `--gpu-backend` with no silent fallback between backends.

#### Scenario: Caller compiled without backend headers
Given the compositor and exporter sources
When they are compiled
Then they include only `src/render/backend.h` and no DX12 or Vulkan header

#### Scenario: Requested backend unavailable
Given a process started with a backend whose device cannot be created
When an operation that needs the GPU is requested
Then it fails with `gpu_backend_unavailable {backend, reason}` before mutating anything and no other backend is used

### Requirement: No UzEngine dependency in the render layer
The render layer MUST build from the vendored copy only: no include path, library path or build step SHALL refer to a UzEngine checkout or artifact.

#### Scenario: Vendoring check on the render layer
Given the render-layer build
When the vendoring check of `docs/architecture/13-engine-integration.md` §3.3 runs
Then it reports no path outside the UzPainter repository and no unlogged change under `thirdparty/uzengine-render-core/`
