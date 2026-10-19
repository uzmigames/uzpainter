# 306. CPU baker request model: IBaker and JobHandle with refusals before any job, a result published whole or not at all, SUP-023/SUP-031 fixes, name matching and IgnoreBackface through a primary-ray filter, an in-memory custom cage, CageHit and Hidden classes, SubSampling as coverage accumulation, dilation into uncovered texels only, and a parameter model that answers only what admitted sources state; parity pending-evidence

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_baker-request-model, phase3.4_baker-ao, phase3.5_embree-bakers

## Context

This is a second permitted slice of `phase3.1_baker-request-model` (SUP-014), after decision 302, and it is not acceptance. The coordinator asked for the request-model items slice 1 left open:
- `IBaker` and `JobHandle`;
- the `Property` parameter model;
- `IgnoreBackface` and mesh name matching;
- `SubSampling` and dilation;
- the cage-hit and hidden classes;
- the bevelled-cube fixture.

Every new path keeps decision 302's contract: equal bytes at 1, 4 and N threads, miss classes kept, refusals explicit. Supervisor reviews SUP-023 (on e9a3152) and SUP-031 (on this slice in progress) added fixes, recorded in §2.

Admitted sources for Painter facts:
- Painter's public Python API pages (`baking.html`, `properties.html`);
- Adobe's public mesh-map settings page (A-HELP-BAKING);
- the key list of `docs/architecture/06-baking.md` §2.

Neither page states a widget type, an enum integer, a range or a default. Behaviour beyond what the pages say is UzPainter's own reading, written behind `pending-evidence`.

**Panel** (2026-10-19, `cx/gpt-5.6-sol`, `kimi/kimi-k3`, `xai/grok-4.5`):

| Claim | Votes |
|---|---|
| C1 job model | 1 agree, 2 partly |
| C2 RAII and seams | 2 agree, 1 partly |
| C3 serial-only qualification | 3 agree |
| C4 name matching, C5 `IgnoreBackface`, C6 custom cage | 2 partly, 1 disagree each |
| C7 hidden mask | 2 agree, 1 partly |
| C8 sub-sampling, C9 dilation | 1 agree, 1 partly, 1 disagree each |
| C10 parameter model | 2 agree, 1 partly |

GPT disagreed with C4-C9 as a whole: without evidence, each should be `NotYetSupported`. That was not adopted, for three reasons:
- the coordinator asked for these paths;
- like slice 1's AO, they are UzPainter's own deterministic semantics, never claimed equal to Painter;
- nothing is exposed (no Python or MCP symbol), so no user can mistake them for parity.

Each reading is listed below with what would settle it. Adopted from the panel:
- C10: types that only a key's meaning suggests are pending (GPT and Kimi);
- C4: a name that is only a suffix is refused (Kimi);
- C3: a test that the diagnostic flag changes nothing on a qualified build (Kimi);
- C8 and C9: the class precedence and the serial, whole-texture dilation are recorded as fixed (Grok and Kimi).

The C1 race the panel named is closed by design: cancel and publication share one lock.

## Decision

### 1. `IBaker` and `JobHandle` (`06-baking.md` §1, §6)
- **The interface.** `IBaker { Capabilities caps() const; JobHandle bake(const BakeRequest&); }`. `EmbreeBaker` implements it.
- **Refusals throw.** `bake` throws every refusal before any job exists: `CapabilityError`, `NotYetSupported` and `ValueError`, including the copy of the request.
- **Otherwise the job runs alone.** `bake` copies the request and its meshes into the job, so the caller's meshes may go away. It then starts one job thread, which runs the slice-1 cast with its worker pool.
- **The handle.** `JobHandle` is move-only. It carries an id, `progress()` (tiles done / total), `cancel()`, `wait()`, `status()` (`Running | Success | Cancel | Fail`, Painter's `BakingStatus` plus `Running`), `result()` and `error_message()`.
- **Publication.** It is one locked step at the end. When a stop was requested before it, the status is `Cancel` and the result is discarded. Otherwise the whole result is stored and the status is `Success`.
- **What `cancel()` promises.** It takes the same lock. It returns true only while the job is `Running`, which then always ends in `Cancel`; a stop also wins over a later failure. After publication it returns false, and the result stays published.
- **Reading the result.** Workers check the stop flag before each tile. `result()` raises `JobCancelled` on `Cancel`, rethrows the job's error on `Fail`, and raises `std::logic_error` while the job is running.
- **Dropping a handle.** Dropping the handle of a running job cancels it and joins it.
- **What is left alone.** The baker's device and API are shared with running jobs by ownership, so a job may outlive its baker. The canonical bytes, the tile partition and the sample addressing are decision 302's.

### 2. Supervisor fixes (amending decision 302)
- **SUP-023.1, worker spawn.** The workers live in a joining container, declared after everything they use. When spawning worker *i* throws, an `abandon` flag stops the workers already started, the container joins them during unwinding, and the job ends in `Fail`. One worker needs no spawn: the job thread casts the tiles itself.
- **SUP-023.2, Embree objects.** The scene and every geometry are owned by a handle from their first acquisition. A failure at any acquisition releases everything acquired before it, constructor failure included. `live_embree_objects()` counts the scenes and geometries the baker holds.
- **SUP-023.3, test seams.** `BakerConfig::faults` makes the Nth worker spawn throw `std::system_error`, or the Nth Embree acquisition return null. The acquisitions, in order, are `rtcNewScene`, then for each high mesh `rtcNewGeometry` and its vertex and index buffers. Tests drive every acquisition of a two-mesh scene and spawn failures at workers 0, 1, 3 and 7. In each case the job fails, and the live count returns to 0. No real OS resource is exhausted.
- **SUP-023.4, qualification.** Only `embree_build_threads == 1`, the serial BVH build decision 302 measured, is qualified.
  - Any other count leaves `caps().qualified` false, with `diagnostic_build_threads` set.
  - `bake` refuses such a configuration, unless `allow_unqualified_build_threads_diagnostic` is set. Then every result carries `diagnostic_unqualified`, which is not part of the canonical bytes.
  - The flag never lifts another reason (ISA, Embree version, culling, filter support).
  - Filter-function support (`RTC_DEVICE_PROPERTY_FILTER_FUNCTION_SUPPORTED`) is now required, for §3.
- **SUP-031, tile callback.** An exception from the `on_tile_done` test callback is caught inside the worker. It takes the tile's error slot, so the first error in tile order fails the job at any worker count, and nothing escapes a `std::thread`. Cancellation and joining are unchanged.

### 3. Name matching and `IgnoreBackface` (item 2.4)
The public page states only "Match: Always / By mesh name", a low suffix and a high suffix that pair meshes, and a toggle that ignores back faces. The rest is our reading.

**Pairing by name** (`FilterMethod::ByMeshName`):
- A low part's base is its name minus a trailing low suffix (default `_low`).
- A high mesh's name first loses a trailing `_ignorebf` (`BackfaceCullingSuffix`). That suffix makes its back faces pass-through for primary rays. The name then loses a trailing high suffix (default `_high`).
- A high mesh is a primary-ray candidate for a low part exactly when the two bases are equal: case-sensitive, and the suffix is optional.
- A name that is only a suffix (an empty base) is refused with `NotYetSupported`.
- With `LowAsHigh`, each low part is its own only candidate.
- **Settles it:** Tier 2b evidence on named highs (`phase3.3_baker-evidence-publication`).

**`FilterMethod::Always`.** Every high mesh is a candidate, and the three suffixes are not read.

**`IgnoreBackface`.** Primary rays pass through the back faces of every high mesh, by our winding (decision 302 §3). AO secondary rays are unaffected: Painter's AO has its own `IgnoreBackfaceSecondary`, which is not modelled.

**Unmatched highs.** They stay in the scene: AO secondary rays see the whole scene, as before.

**The mechanism.**
- Both rules run in one Embree argument filter on the primary ray.
- The scene flag `RTC_SCENE_FLAG_FILTER_FUNCTION_IN_ARGUMENTS` is set before commit, and only when some part needs the filter. A part's rays carry the filter only when that part needs it.
- So a request without matching or ignoring builds and casts exactly as slice 1. Measured: the sphere scene's RAW AO, class and ray maps are byte-identical to e9a3152's.

### 4. Custom cage and the `CageHit` class (items 2.5, 2.6)
- **The cage.** `CageMode::CustomFile` takes in-memory cage meshes, one per low part, each with that part's vertex count and identical indices (checked before any work). Loading a cage from a file stays `NotYetSupported` (item 2.5).
- **The ray.** It starts at the cage point with the sub-sample's barycentrics and aims at the low point. It searches to `max_depth` beyond the low point; `max_height` is unused. A hit anywhere on that segment counts.
- **The class.** A front hit is `CageHit`; a distance-based front hit stays `StraightHit`.
- **Degenerate cages.** A cage point on the low point fails the job (`ValueError`, found while casting).
- **Settles it:** a custom-cage recording.

### 5. The `Hidden` class (item 2.6)
- It comes only from the request's per-texel `hidden_mask`, whose size is checked before any work. `06-baking.md` §4 says hidden texels exist only with a hidden mask.
- A covered texel under the mask is `Hidden`: no ray is cast, and its covered sub-samples count as hidden.
- An uncovered texel stays `Uncovered`.

### 6. `SubSampling` as coverage accumulation (item 2.6)
- **Sub-samples.** k is 1, 2, 4 or 8. Sub-sample (i, j) of texel (x, y) sits at ((x + (i + 0.5) / k) / W, 1 - (y + (j + 0.5) / k) / H).
- **Finding the triangle.** Each sub-sample finds its own low triangle: the lowest part, then the lowest triangle index. The search uses per-texel candidate lists, built serially in (part, triangle) order.
- **Rays.** Each covered sub-sample casts its own primary ray. On a hit it casts N secondary rays, with sample id `sub * N + s` of `k² N` in one Hammersley set per texel. `N k² <= 65535` is checked.
- **Evidence maps.** `coverage` holds the covered sub-samples per texel, and `subsample_hits` the hit ones.
- **The value.** `round(65535 * escaped / (hits * N))` over the hit sub-samples only: non-hit sub-samples are counted as classes and never dilute the value.
- **The texel class** (fixed precedence):
  1. `Uncovered` when no sub-sample is covered;
  2. otherwise `Hidden` when masked;
  3. otherwise `StraightHit` or `CageHit` when any sub-sample hits;
  4. otherwise `BackFaceHit` when any sub-sample hit a back face;
  5. otherwise `CentreMiss`.
- **k = 1** is bit-identical to slice 1's centre sampling (tested).
- **Settles it:** Tier 2b evidence on `SubSampling`.

### 7. `DilationWidth` (item 2.7)
- **The passes.** There are `w` passes, Jacobi-style: a pass reads only the previous pass. In each pass, every `Uncovered` texel with at least one valued 8-neighbour takes the rounded integer mean of those neighbours. A valued texel is a hit texel or one dilated in an earlier pass.
- **What is never touched.** Texels of the used surface without a hit (centre misses, back-face hits, hidden texels) are never written and never spread.
- **Serial and last.** Dilation runs serially over the whole texture after the cast, so it is independent of the thread count. It writes `ao`; `ao_raw` is kept unchanged.
- **`ApplyDiffusion = true`.** Refused with `NotYetSupported` (item 2.7): its behaviour is not documented.
- **Settles it:** Painter's dilation, compared on the used-surface boundary.

### 8. The parameter model (item 2.8)
- **The API shape.** `BakingParameters(texture_set)` with `common()` (the common and detail keys), `baker(usage)` and a static `set({Property: value})`, mirroring Painter's documented shape.
  - The keys are `06-baking.md` §2's short names: 19 common and detail keys, and 11 AO keys.
  - `baker(usage)` for any usage other than AO raises `NotYetSupported`, naming its owner task (`phase3.2_baker-normal`, `phase3.4_baker-*`).
- **What a `Property` answers:**
  - `short_name()`;
  - `label()`, only where the public page states it;
  - the documented option labels, marked complete or partial (`Distribution` documents only `Cosine`, in the API page's example);
  - its type;
  - an own-words description;
  - `value()`.
- **Where a type comes from.** Only from the page's widget (a checkbox is `Bool`, a dropdown `Enum`) or from the task's listing (the `OutputSize` log2 pair, `DilationWidth` in texels, the `HipolyMesh` URL list, the suffix strings). A type that only a key's meaning suggests (a ray count, a distance, an angle) is `Pending`, so no `Float` key exists yet.
- **Defaults.** The only ones are the three suffixes `06-baking.md` §2 lists. Every other `value()` raises `NotYetSupported` (item 2.9) until it is set.
- **What waits for Tier 0.** `name()`, `widget_type()`, `enum_values()`, `enum_value()`, `properties()` and every unlabelled label raise `NotYetSupported`, naming the Tier 0 discovery capture (items 2.8 and 3.1).
- **`set()` is one transaction.** It checks the whole batch first: types, option labels, and no duplicates. A pending type or an undocumented option raises `NotYetSupported`. Only then does it write. One failure leaves every texture set in the batch unchanged.
- Linked groups (item 2.10) are not started.

### 9. Scope
- AO stays the only usage, `pending-evidence`, owned by `phase3.4_baker-ao`, never `supported`.
- No Python or MCP symbol is exposed, so the capability manifest is unchanged.

## Alternatives Considered

- **Refusing every undocumented behaviour (GPT).** Not adopted: these are internal, deterministic and `pending-evidence`, as slice 1's AO is (Context).
- **Returning refusals as `Fail` jobs.** Rejected: "refused before any work" means no job exists, and callers can tell a refusal from a casting failure.
- **Attaching the filter to every ray.** Rejected: it would change slice 1's scene configuration for requests that need no filter. Per-part attachment keeps the old bytes.
- **Averaging over covered sub-samples, counting misses as 0.** Rejected: that is a silent fill of misses.
- **Gauss-Seidel dilation.** Rejected: it is scan-order dependent; Jacobi is not.
- **Float types for distances by meaning.** Rejected, on the panel's advice: they stay pending until the capture.

## Consequences

**Files.**
- New: `src/bake/baker.{h,cpp}` and `src/bake/baking_parameters.{h,cpp}`.
- Changed: `bake_request.*`, `embree_baker.*`, `tests/bake/*`, and two new sources in the `bake-feasibility-tests` step.
- Canonical bytes are now `UZPBAKE2`, adding the baked map, coverage, sub-sample hits, the new class counts and the dilated count.

**Measured on one build and machine** (32 threads). These are not goldens:

| Scene | SHA-256 | Notes |
|---|---|---|
| Bevelled cube with highs (name matching, `_ignorebf`, 4 x 4 sub-samples, dilation 8, a hidden band) | `0034cd97fbb920d362f034af1ca593264fafa4696ead63a20028d6e2ecd2f3ed` | identical at 1, 4 and 32 threads |
| Sphere scene in `UZPBAKE2` | `4002682cddd0fd4c77fcf8a1ebe351c6d499aeee6b50e34fe83622439ac3f7ce` | identical at 1, 4 and 32 threads; its RAW, class and ray maps equal e9a3152's `11cdde9b...` bytes |

**Tests.** `python -m pytest tests/bake/test_bake_feasibility.py`: 31 passed, comprising 26 native cases and the cross-process thread-count, diagnostic and miss-class tests.

**Still open:**
- relative (bounding-box) distances and units (items 2.5, 2.7);
- `ApplyDiffusion`;
- cage files;
- linked groups;
- defaults and Tier 0 metadata;
- the `_ignorebf` and matching rules against evidence;
- two jobs building scenes at once on one serial device: their bytes matched in the test, but this is not proven for large meshes;
- Tier 2b evidence.
