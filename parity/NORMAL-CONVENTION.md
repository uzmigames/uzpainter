# Normal convention fixture

Work package P0-NORMAL (`docs/dag.md`), task `phase0.9_normal-convention-fixture`. It settles, with recorded evidence, the green-channel convention of Painter's baked tangent-space normal and which MikkTSpace frame mode equals Painter's bake, before the mesh loader freezes its tangent code (`docs/architecture/12-mesh-import.md` §3). Code: `tools/parity/normal_convention/` and `src/prototype/`; tests: `tests/parity/normal_convention/`. Verdicts: `parity/semantics/tangent-frame.json`; numbers: `parity/reports/phase0/normal-convention.md`.

## 1. Fixtures

Two UzmiGames-authored low/high pairs in `parity/fixtures/normal-convention/`, written from closed-form geometry by `python -m tools.parity.normal_convention fixtures` (conventions in `fixtures.py`). Every high mesh is faceted (three own vertices and the geometric normal per triangle), so the world normal a bake ray reads is constant per high triangle and known analytically.

| Pair | Low | High | Settles |
|---|---|---|---|
| `plane-dome` | the square [-1, 1]² in XZ, normal +Y, u = (x + 1) / 2, v = (1 − z) / 2: constant frame T = +X, B = −Z, N = +Y | faceted spherical cap above it (16 × 6), footprint radius 0.8 | green-channel direction; DirectX conversion; texels with no hit |
| `hemisphere` | coarse smooth unit hemisphere (8 × 4 + pole), radial normals, top-down UVs | the same triangles scaled by 1.002, faceted | frame mode: per-corner frames vary inside every triangle, so `PerVertex` and `PerFragment` differ |

The comparison domain is every texel whose 5 × 5 neighbourhood lies in one low and one high triangle (`analytic_field`), so neither the ray hit nor the frame interpolation can change across an edge.

## 2. Goldens

`python -m tools.parity.normal_convention manifests` writes one public manifest per golden in `parity/manifests/phase0/normal-convention/`: `plane-dome/opengl`, `plane-dome/directx`, `hemisphere/per-fragment`, `hemisphere/per-vertex` and `hemisphere/project-default` (the tangent-space mode left at Painter's default). Each creates a project from the low mesh (512 px), sets `OutputSize` (and `MaxHeight` 0.2 on the plane-dome pair) and `HipolyMesh` through `BakingParameters.set`, enables the Normal baker, bakes with `bake_async` and exports `meshMap/normal_base` at 16 bits (`parity/RECORDER.md` §2). The bake backend cannot be read or set through the documented API and is listed under `uncontrolled_settings`. Recording and admission:

```
python -m tools.parity.recorder record parity/manifests/phase0/normal-convention/<golden>.json
python -m tools.parity.store record parity/manifests/phase0/normal-convention/<golden>.json --run <run>
```

## 3. Prototype

`uzp-normal-prototype.exe` (`src/prototype/normal_prototype.cpp`, `zig build normal-prototype`) bakes a pair as a texture-space baker does: per texel centre inside a low UV triangle it interpolates position, normal and the per-corner MikkTSpace frame (Mikkelsen's `mikktspace.c`, `thirdparty/mikktspace/`, `genTangSpaceDefault`), casts a ray along the interpolated normal from the cage (first hit from `max-height` above down to `max-depth` below, back faces ignored) and expresses the hit normal in the frame. It writes every combination of

- frame mode: `PerVertex` (bitangent interpolated from the corners' `sign · cross(n, t)`) and `PerFragment` (bitangent rebuilt per texel as `sign · cross(vN, vT)`);
- transform: `inverse` (the exact inverse of the shading transform `normalize(x vT + y vB + z vN)`, as `mikktspace.h` prescribes for samplers) and `projection` (dot products with the normalized vectors);
- format: OpenGL (green = +bitangent) and its DirectX conversion (green code → 65535 − green),

plus the world-space normal, the triangle ids and a summary with round-trip errors. Codes are the nearest UNORM16 of x / 2 + 1 / 2.

## 4. Comparison and outputs

`python -m tools.parity.normal_convention run` builds the prototype, bakes both pairs, reads the recorded maps from the private store and writes the semantics and the report; `check` re-runs and fails if any residual differs. Comparisons are at native depth (16-bit codes) in tangent space: oracle stability (`r1` against `r2`), each recording against each prototype map, the project default against the explicit modes, and the direction check (mean green on texels leaning towards +v and −v). The UzEngine consumer run is recorded in `tools/parity/normal_convention/uzengine-consumer.json` and quoted in the report.

## 5. Results (2026-10-10, Painter `12.1.0+js-api.1.1.20`, owner's machine)

All five goldens were recorded in one Painter session under the shared Painter lock and admitted to the store; every `r1` export equals its `r2` export. The prototype's `<mode>-inverse` map equals Painter's bake with the same tangent-space setting to within 1 code (ties of the final rounding on a few texels), and the other mode is off by about 69 codes on average, so both modes are identified. Painter's project default bakes byte for byte as `PerVertex`. Green encodes +v in the OpenGL format; Painter's DirectX bake equals the green-inverted conversion exactly. Texels whose ray hits nothing are left empty (code 0) and filled by the bake's dilation near hit texels; texels beyond the dilation's reach are compared and equal. UzEngine, as an external consumer of a mesh cooked by `uzmesh` from OBJ, reads green as −v (DirectX). Details: `parity/reports/phase0/normal-convention.md`.
