# 384. Tier 2b bake requests on the analytic fixtures: the C++ fixtures as generated OBJ files, one baker per golden at 512 px with no dilation, the swept values the baker tasks name, and no request where no documented call reads the map out

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase3.2_baker-normal, phase3.4_baker-ao, phase3.4_baker-curvature, phase3.4_baker-id, phase3.4_baker-position, phase3.4_baker-thickness, phase3.4_baker-world-space-normal, phase3.4_baker-height, phase3.4_baker-opacity, phase3.4_baker-bent-normals, phase3.5_embree-bakers

## Context

Front E of decision 367. Every baker task's Tier 2b item asks for Painter goldens "on plane, sphere and bevelled cube with highs" (`06-baking.md` §7). The batch inventory (`docs/analysis/painter-recording-backlog/01-inventory.md` §2) found three gaps: the fixtures existed only as C++ meshes (`tests/bake/bake_fixtures.h` and the `*_bake_cases.h`), no bake request generator existed, and no settings were declared. The recorder already replays bakes through the documented baking API (`BakingParameters.set`, `set_enabled_bakers`, `bake_async`, `BakingProcessEnded`; phase0.9_normal-convention-fixture). The task's rule: no invented semantics; what a task leaves open is listed, not chosen.

## Decision

### 1. Fixtures
`tools/parity/tier2b_bakes/fixtures.py` ports the C++ fixture functions line for line (constants, corner order, winding, double arithmetic cast to float32 where the C++ casts). It writes six public OBJ files under `parity/fixtures/tier2b-bakes/` (UzmiGames-authored, Apache-2.0, declared by the requests as CONTRACT.md §6.4 requires):

| Scene | Low | High | C++ source |
|---|---|---|---|
| plane | `plane-low.obj` (`low`) | `plane-high.obj` (`normal_high`, 0.005 above) | `CaseNormalPlane` |
| slab | `plane-low.obj` | `slab-high.obj` (`slab`, top 0.005, bottom -0.245) | `CaseThicknessPlane` |
| sphere | `sphere-on-ground.obj` | none: low as high | `SphereOnGround()` |
| bevelled cube | `bevelled-cube-low.obj` (`cube_low`, `knob_low`) | `bevelled-cube-high.obj` (`cube_high`, `knob_high_ignorebf`, `decoy_high`) | the `Bevel` fixture, `CaseMatchByName` |

- Coordinates are the C++ ones as authored (z up); one OBJ unit is one centimetre (OBJ states no unit; `12-mesh-import.md` §3), the C++ requests' `scale_to_internal` 1. The slab case authors its distances in inches; its geometry is unchanged.
- No native dump verb was added. `tests/parity/tier2b_bakes/test_fixtures.py` reads the C++ sources and fails when a constant, a call argument, the cube-face table or a request distance differs from the generator's; it also checks the committed bytes, the float32 read-back, the shapes (closed outward chamfered cube, triangle counts) and that every island edge lies on a texel boundary at 512 px.
- Residual drift risk: the sphere's `sin`/`cos` come from Python's C library, the C++ ones from the native toolchain's; a one-ulp double difference could flip a float32 rounding. No comparison measured this.

### 2. Settings shared by every request
- Project at 512 px, normal map format OpenGL, tangent space the project default; `OutputSize` (9, 9), so no export resamples a mesh map (the normal-convention fixture's 512 px precedent; Painter's texture-set resolution does not go down to the C++ cases' 64 px).
- `DilationWidth` 0 and export padding `passthrough`: the native bakers refuse a dilation above 0 and fill nothing (decisions 337 §2, 341 §1), so a golden holds Painter's raw texels. `SubSampling` stays at Painter's default, None.
- The scene's C++ request values: plane, slab and cube bake their highs at absolute distances (`RelativeScale` false; `MaxHeight`/`MaxDepth` 0.05/0.05, cube 0.05/0.04), because a relative distance is refused natively without a box size (`06-baking.md` §3). The cube uses `FilterMethod` By mesh name with the default suffixes. The sphere sets only `LowAsHigh`.
- Every other parameter stays at Painter's default, recorded by the admitted Tier 0 baking-defaults captures (`assets/defaults/baking.json`). The recorder reads back every parameter a request sets.
- One baker per golden, so each task's golden stands alone; Curvature FromNormalMap enables Normal too (task item 2.2: "from the baked Normal map of the same request").
- Each golden exports its maps twice, PNG 16 and OpenEXR 32f, so the channel format items (2.2 of WorldSpaceNormal, Opacity, the encodings) can be established without guessing Painter's storage. Recorded twice (r1; r2 after save and reopen). The bake backend is listed as uncontrolled.

### 3. The swept values (63 requests, `requests/tier2b/bakes/`)

| Task | Scenes | Variants (what the task item names) | Requests |
|---|---|---|---|
| phase3.2_baker-normal 3.2 | plane, sphere, cube | none | 3 |
| phase3.4_baker-world-space-normal 3.1 | plane, sphere, cube | none | 3 |
| phase3.4_baker-ao 3.1 | plane, sphere, cube | `GroundPlane` off / on | 6 |
| phase3.4_baker-curvature 3.1 | plane, sphere, cube | `CurvatureMethod` FromMesh / FromNormalMap | 6 |
| phase3.4_baker-position 3.1 (decision 337 §4) | plane, sphere, cube | All axis x `Normalization` x `NormalizationScale`; One axis x `Axis` | 27 |
| phase3.4_baker-id 3.1 (decision 337 §5) | plane, sphere, cube | `ColorSource` Mesh ID / Polygroup x each `ColorGenerator` | 9 |
| phase3.4_baker-thickness 3.1 (decision 341 §4) | slab, sphere, cube | each `MaximizeRange` | 9 |

The plane and the cube scenes are not cubic (the knob and decoy widen the cube scene's box), which is what decision 337 §4 asks of Position's normalisation goldens.

### 4. Recorder: `set_curvature_method`
`substance_painter.baking.BakingParameters.set_curvature_method` (documented on the python-doc baking page, `CurvatureMethod.FromMesh` / `FromNormalMap`) is a recorder state call: `{"method": ..., "texture_set"?}`, refused offline otherwise, required to precede the last `bake_async` like the other baking settings, read back with `get_curvature_method` in both recordings. Added to `documented_symbols.json`; `test_provenance.py` checks it against the installed `objects.inv`.

### 5. Panel (2026-11-02, `cx/gpt-6-astra`, `cx/gpt-6.1-sol`, frozen diff)
Neither raised a blocker on the bake requests. Their shared points, and what was done:
- **Literal checks do not prove the port.** The test now also pins the C++ structure: corner and index order, winding, loop order, casts and merge order. A full proof needs a native dump of the C++ meshes; that stays open (native lock, fronts A and B first).
- **`usemtl` without `mtllib`.** Kept: the admitted plane and normal-convention fixtures are written the same way, and their recordings named the texture set from `usemtl`. Each recording captures the texture sets it saw.
- **OBJ units, z-up orientation, name matching.** Painter's own reading is what the goldens record; the requests assume nothing about it. A native comparison must establish the import scale and frame first. The cube's knob, cover and decoy are exactly the evidence decision 306 §3 asks for.
- **Untouched defaults are not re-read.** They are the admitted 12.2.0 Tier 0 baking-defaults captures of this envelope (fresh projects, r1 = r2 = r3). The texture recorder refuses baking-defaults captures, so a request cannot re-read them; this stays a stated assumption.

### 6. Not requested, and what is missing
- **Height, Opacity, BentNormals.** Painter's documentation names no export map (`srcMapName`) for them (decision 110, P21-A reads them back only). No documented call reads their baked maps out, so no request records them. Missing: a documented read-out route, or a decision qualifying an indirect one (for example a fill sourced from the baked resource and exported as a document channel, which adds Painter's layer composition to the map).
- **Height** also lacks its two `Divisor` values and the inflated sphere (decision 341 §3).
- **ID** sources other than Mesh ID: the fixtures carry no vertex colours, materials or ID file. A cube split into more named meshes (more palette entries) is not authored.
- **AO** `IgnoreBackfaceSecondary`/`Attenuation` sweeps and the buried-face fixture (item 3.4): not named as Tier 2b variants.
- **Dilation and sub-sampling** goldens: none until the native bakers implement them.
- **Wand and Hat low/high/cage pairs** (each task's 3.2): their high and cage meshes are not pinned (inventory §2).

## Alternatives Considered

- **A native verb dumping the C++ fixtures.** Not taken: it needs the native lock and a build, and the C++ geometry is closed-form. The source-literal test catches a changed constant.
- **All bakers in one bake per scene.** Fewer sessions, but every task's golden would depend on the others' settings and a variant would re-bake all maps. Not taken.
- **Painter's default dilation (32).** Not taken: the native bakers cannot reproduce dilation yet, so the raw texels would be hidden under an unrecorded fill.
- **One export format per map.** Not taken: which format holds Painter's stored values exactly is what item 2.2 of several tasks has to establish.

## Consequences

- New: `tools/parity/tier2b_bakes/` (`fixtures.py`, `requests.py`, `__main__.py`), `parity/fixtures/tier2b-bakes/*.obj`, 63 requests, `tests/parity/tier2b_bakes/test_fixtures.py`.
- Changed: `tools/parity/recorder/{painter_side,job,vocabulary}.py`, `documented_symbols.json`, `tests/parity/recorder/{fake_painter,test_bake_recording}.py`; `batch.py` routes `tier2b/bakes` to the texture recorder.
- The batch compiler schedules the 63 requests in the Legacy session after the Wand probe. No timing exists for bakes; the estimate is about 30 s per golden, about 30 minutes in all, unmeasured.
- Authoring the Tier 2b manifests (items 2.x "Author the ... manifests") is done for these scenes once the recordings are admitted; parity stays `pending-evidence`.
