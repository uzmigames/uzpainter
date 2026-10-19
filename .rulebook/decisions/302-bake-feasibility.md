# 302. CPU baker feasibility on Embree 4.4.1: a serial BVH build, fixed 16 x 16 tiles cast by any number of workers under one floating-point state, Hammersley samples addressed by texel index and sample id, an integer AO reduction in which every hit occludes, and four texel classes and four ray classes reported, never filled; parity pending-evidence

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_baker-request-model, phase3.4_baker-ao, phase3.5_embree-bakers

## Context

SUP-014 and `docs/roadmap.md` rule 1 permit native-bake feasibility while Painter is occupied. The coordinator asked for a slice of `phase3.1_baker-request-model`, not its acceptance:
- a CPU baker on the vendored Embree 4.4.1 (`thirdparty/embree/`, prebuilt x64 Windows DLL with TBB tasking, loaded at run time as `selftest` loads it);
- authored fixtures only, generated in code: no Painter data, no Assets3D file;
- fixed sampling and a fixed reduction order;
- identical output bytes at 1, 4 and N threads;
- rays that miss, hit a back face or hit their own triangle counted as classes, never filled;
- no parity claim.

`docs/architecture/06-baking.md` §1 already fixes the principle: Hammersley by texel index and sample id, a fixed reduction order and thread-independent tiles. The forks below are how. Panel (2026-10-19, `cx/gpt-5.6-sol`, `kimi/kimi-k3`, `xai/grok-4.5`): C1, C2, C3 and C6 agreed or partly agreed, C4 agreed, C5 partly agreed. Two risks they raised were fixed before this record:
- Embree keeps its error code per thread, so each worker now reads its own;
- the SSE floating-point state (FTZ, DAZ, rounding) is now pinned for the build and for every casting thread.

## Decision

### 1. Where threads are allowed
- **The BVH is built by one Embree thread.** The device config is `threads=1,isa=avx2,verbose=0`, so the BVH depends on the mesh and the build only.
- **Rays are cast by UzPainter's own worker pool.** Workers take fixed 16 x 16 tiles (row-major tile index) from an atomic counter. Each texel writes only its own output slots. Per-tile integer counts are summed in tile order after join. A failing tile is rethrown in tile order, whichever worker met it first. `rtcIntersect1` runs concurrently on the committed scene.
- **The calling thread is no exception.** At one worker, it casts the tiles itself, under the same pinned floating-point state.
- Measured: with an 8-thread BVH build, the 1.9k-triangle scene gives the same bytes. That is not proof, since small scenes may build serially anyway. The pin stays at 1 until large meshes are measured (`BakerConfig::embree_build_threads`).

### 2. Sample addressing
- Sample `s` of `N` for texel `t` (row-major index) is Hammersley's `(s / N, Φ2(s))`.
- It is rotated per texel (Cranley-Patterson) by `SplitMix64(t)`, split into two 32-bit fractions.
- Directions are cosine or uniform over the hemisphere around the interpolated high normal, using Duff et al.'s (2017) orthonormal basis.
- Everything is computed in double and cast to float only for the Embree ray (`src/bake/sampling.*`).

### 3. Primary ray and texel classes
**Texel centres.** A texel centre is `((x + 0.5) / W, 1 - (y + 0.5) / H)`, so row 0 is v = 1.
- It is matched to a low UV triangle with inclusive edges; either UV winding is accepted.
- Where islands overlap, the lowest triangle index wins.
- The matching is serial and in triangle order.

**The primary ray.** It starts at the low point plus `max_height` along the interpolated normal and casts down to `max_depth` below. This is the distance-based cage in absolute mesh units.

**Each texel gets exactly one class:**

| Class | Meaning | AO cast? |
|---|---|---|
| `Uncovered` | the centre is in no UV triangle | no |
| `StraightHit` | the first hit is a front face | yes |
| `BackFaceHit` | the first hit is a back face, by our own winding: `cross(p1 - p0, p2 - p0)`, not Embree's `Ng` | no; this is not `IgnoreBackface` |
| `CentreMiss` | no hit | no |

Only `StraightHit` texels carry a value. Every other texel holds 0 and is told apart by the class map. Nothing is dilated, filled or repaired.

**Cage modes.** `CageMode::Automatic` raises `CapabilityError`, naming the release gap of `06-baking.md` §3. `CustomFile` raises `NotYetSupported`, item 2.5.

### 4. AO reduction and ray classes
- The AO value is `round(65535 * escaped / N)` in integers. N is in [1, 65535].
- Every secondary hit occludes: a front face, a back face, or the ray's own origin triangle.
- Rejected: dropping back-face or self rays from the denominator. That is a silent repair.

**Each secondary ray gets exactly one class:**

| Class | Meaning |
|---|---|
| `escaped` | no hit in [`min_distance`, `max_distance`] |
| `front_hit` | the first hit is a front face |
| `back_face_hit` | the first hit is a back face |
| `self_hit` | the first hit has the same geometry and primitive as the ray's origin triangle |

**Where the classes are reported:**
- as bake totals;
- as per-texel uint16 evidence maps for back-face and self hits.

**What `self_hit` does not cover.** Near-zero hits on neighbouring or coincident triangles count as front or back hits. With `min_distance` 0, most rays self-hit (Embree accepts t = tnear). At 1e-4 on the smooth sphere, 5 of 3.7 M rays still do, all grazing.

### 5. Qualification
`caps().qualified` needs all of these:
- CPUID AVX2, FMA, BMI1, BMI2, LZCNT and F16C;
- the OS YMM state (OSXSAVE and XGETBV);
- `embree4.dll` loaded, reporting `RTC_DEVICE_PROPERTY_VERSION` 40401;
- back-face culling off (culling would hide the back-face class);
- triangle geometry supported.

Otherwise every `bake` raises `CapabilityError` before any work. Also refused before any work:
- unsupported usages, which name their owner task;
- `OutputSize` above 2^12.

Cross-machine bit identity is measured later, not promised (`06-baking.md` §1).

### 6. Scope of the slice
- **Synchronous `EmbreeBaker::bake(BakeRequest) -> BakeResult`.** `IBaker`, `JobHandle` and the `BakingParameters`/`Property` model stay with items 2.2 and 2.8.
- **One usage: AO.** Its parity status is `pending-evidence`, owned by `phase3.4_baker-ao`, never `supported`.
- **Nothing reaches the capability manifest.** The slice exposes no Python or MCP symbol.

## Alternatives Considered

- Letting Embree build the BVH with N threads: not yet. Determinism is unmeasured on large meshes.
- Texel-interleaved work instead of tiles: equivalent for determinism, worse locality.
- A float accumulation of AO: deterministic in sample order too. Integers make the reduction exact and order-free.
- Embree's `Ng` for front or back: rejected. Our own winding keeps the convention independent of the backend, for the later `GpuBaker`.

## Consequences

- `src/bake/` and `tests/bake/` are new, with the `bake-feasibility-tests` build step.
- Determinism scene (`SphereOnGround`, 256², 64 rays, `min_distance` 1e-4):
  - SHA-256 `11cdde9bacf602cf69f7fd1b1664c9dfa8b6e529451d27e8292d1602e8e1d0fa` at 1, 4 and 32 threads;
  - texels: 5704 uncovered, 58530 straight, 1302 back-face (the sphere's contact with the ground), 0 centre misses;
  - rays: 2905062 escaped, 839914 front, 939 back, 5 self.
- With `min_distance` 0 the hash is `bd5c28ff8169d5d9f14dacea4ed08d7ff5304b69e59021056b538b531d8b0771` at all three thread counts (2858049 self hits).
- These hashes hold on one build and machine. They are not goldens.
- Still open:
  - the BVH thread pin on large meshes;
  - an offset relative to scene scale (`MaxDistanceRelativeScale`);
  - `IgnoreBackface`, subsampling and dilation (items 2.4-2.7);
  - Tier 2b evidence.

## Amendment (2026-10-19, decision 306)

Supervisor review SUP-023 of this slice found three faults, fixed under decision 306:
- a worker spawn that throws could reach `std::terminate` (joinable threads destroyed): workers now live in a joining container;
- the scene constructor leaked the scene and its geometries on a failed acquisition: every Embree object is now owned from its first acquisition;
- §5 qualified every `embree_build_threads >= 1`, while §1 measured only the serial build: only `threads=1` is qualified now. Any other count is unqualified and bakes only on an explicit diagnostic path, its results marked `diagnostic_unqualified`.

The synchronous `bake` of §6 is replaced by `IBaker`/`JobHandle` (decision 306).
