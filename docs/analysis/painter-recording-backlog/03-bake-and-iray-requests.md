# Painter recording backlog: bake and Iray requests

Decision 367, front E, 2026-11-02. This closes two rows of `01-inventory.md`: the bake goldens of
§2 and the 32 stale Tier 3 references of §1. `02-batch-plan.json` was regenerated afterwards
(`plan --assets-root E:\UzmiGames\Assets3D --store`).

## 1. What is now requested

| Family | Requests | Generator | Decision |
|---|---:|---|---|
| `tier2b/bakes/` | 63 | `python -m tools.parity.tier2b_bakes write` | 384 |
| `phase0/iray-references/`, `phase0/iray-stability/`, `tier3/render-procedure/` | 32 | `python -m tools.parity.render_procedure references` | 385 |

Bake requests by task (fixtures `parity/fixtures/tier2b-bakes/`, generated from
`tests/bake/bake_fixtures.h`):

| Task item | Requests |
|---|---|
| `phase3.2_baker-normal` 3.2 | `normal-{plane,sphere,bevelled-cube}` |
| `phase3.4_baker-world-space-normal` 3.1 | `world-space-normal-{plane,sphere,bevelled-cube}` |
| `phase3.4_baker-ao` 3.1 | `ao-<scene>-{no-ground-plane,ground-plane}` (6) |
| `phase3.4_baker-curvature` 3.1 | `curvature-<scene>-{from-mesh,from-normal-map}` (6) |
| `phase3.4_baker-position` 3.1 | `position-<scene>-all-axis-<normalization>-<scale>` and `-one-axis-{x,y,z}` (27) |
| `phase3.4_baker-id` 3.1 | `id-<scene>-mesh-id-{random,hue-shift,grayscale}` (9) |
| `phase3.4_baker-thickness` 3.1 | `thickness-{slab,sphere,bevelled-cube}-<maximize range>` (9) |

The recorder gained one documented call for them, `BakingParameters.set_curvature_method`
(decision 384 §4).

## 2. Next slot after this change

| Session | Items | Estimate |
|---|---:|---|
| 1, Legacy | 65: the Wand kernel probe (G1), 63 bakes, `srgb-bitmap-minification-random` | about 35 minutes |
| 2, OCIO operator series | 32 Tier 3 (about 87 Iray renders, one fresh Painter each) | several hours of operator time |

The recorder keeps no timings, and none is documented for bakes or Iray, so both figures are
estimates. Session 1's figure assumes about 30 s per bake golden (two recordings of a small mesh at
512 px with two exports each) plus the 105 s session overhead and the Wand probe. Session 2 is not
part of a short slot (inventory §1).

## 3. Still underspecified (no request authored)

| Task | Missing |
|---|---|
| `phase3.4_baker-height`, `-opacity`, `-bent-normals` (all Tier 2b items) | No documented export map name: no documented call reads their baked maps out (decision 110, P21-A). Needs a documented route or a decision qualifying an indirect one |
| `phase3.4_baker-height` 3.1 | The two `Divisor` values and the inflated sphere of decision 341 §3 |
| `phase3.4_baker-id` 3.1 | Vertex color, Material color, File ID and Submesh sources: no fixture carries their inputs; a cube split into more named meshes is not authored |
| `phase3.4_baker-ao` 3.4 | The buried-face fixture as a Painter golden; no `Attenuation` or `IgnoreBackfaceSecondary` sweep is named |
| every baker's 3.2 | The Wand and Hat high and cage meshes are not pinned |
| every baker | Dilation and sub-sampling goldens wait on native support (decisions 337, 341) |
| fixtures | A native dump of the C++ meshes, to prove the Python port beyond the source checks |

## 4. Open risks

- **Studio White Soft.** The v2 Iray requests name the environment by a resource URL whose
  `version` hash was read under 12.1.5. If Painter 12.2.0 ships another version, those steps fail
  at record time.
- **Import frame and unit.** The bake goldens record Painter's reading of z-up OBJ files with no
  unit. A native comparison must first establish the import scale and frame.
- **Sphere rounding.** The sphere uses Python's `sin`/`cos`; a one-ulp difference from the native
  toolchain's could change a float32 vertex. No native dump has compared them.
