# 215. Painter batch G admits the Tunic v10 migration golden, stable in r1, r1-repeat and r2 under OCIO

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.10_pilot-tunic-recovery

## Context

Decisions 194 and 205 left one Painter recording open: the Tier 1 migration golden `phase2/tier1/tunic-v10` (RECORDER.md §9b). It opens the approved Tunic v10 Painter project and must be recorded under OCIO with Painter's substance configuration. Decision 194 named two risks it could not test without Painter:

- a Painter dialog when the existing `.spp` opens;
- the project opening in Legacy colour management instead of OCIO.

The recording ran on 2026-10-13 in Painter `12.1.5+js-api.1.1.20`:

- under the Assets3D Painter lock, through the documented API only;
- in Session O: `OCIO` set to Painter's `resources\ocio\substance\config.ocio`, no `PAINTER_ACE_CONFIG`. `envelope check` reported `other_environment`, as in decisions 180 and 198, because the colour configuration hash is part of the environment.

The recorder copied `18-Tunica-v10.spp` into its private work directory and checked the copy's SHA-256 against the pin (`c43db46a…`). It opened only that copy. The original was never opened or saved.

Painter ran from 01:21:36 to 01:22:56, about 1.5 minutes. The recording itself took 33 seconds (01:22:00-01:22:33). Painter was closed and the lock released at the end.

## What happened on the two risks

- **No dialog.** A watch on Painter's visible top-level windows, sampled every 2 seconds, saw only the main window. While the saved copy was being reopened, one more window titled `Adobe Substance 3D Painter` was visible for under 4 seconds (01:22:29-01:22:31). No recorder call waited on it or failed. Open, save-as, close and reopen all returned.
- **The project stayed OCIO.** The colour management read right after the open (`colour_management_after_open` in the record key) is `mode: ocio` with the substance configuration. It is the same as the session's.

## Decision

The run was admitted with `python -m tools.parity.store record --run` to `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase2/tier1/tunic-v10.json` (17 private records), and the request was deleted. `store verify` of the envelope's `phase2` manifests passes.

- golden-record SHA-256: `afa1309ace69d4a8…`.
- Export: five maps of texture set `DefaultMaterial`, each 4096 x 4096 RGB, 16-bit PNG. They are BaseColor (sRGB), Normal, Metallic, Roughness and Displacement.

Stability, per map, across `r1`, `r1-repeat` and `r2`:

| Map | SHA-256 (prefix) | Stability |
|---|---|---|
| `DefaultMaterial_BaseColor_sRGB` | `d821c2931f4b378b` | stable: byte-identical in all three |
| `DefaultMaterial_Normal_Raw` | `f372fdf3efbdddf2` | stable |
| `DefaultMaterial_Metallic_Raw` | `d915331ab8750d70` | stable |
| `DefaultMaterial_Roughness_Raw` | `b36eeb5698b23705` | stable |
| `DefaultMaterial_Displacement_Raw` | `73998cf028cee448` | stable |

The `migration/state` readback is equal between `r1` and `r2` once two things are ignored:

- the per-project resource counter (`project0` and `project1` in the resource contexts and URLs);
- the project's own `file_path`.

This is the same normalisation the stability study applies. The readback holds 75 nodes, a resolution of 4096 x 4096 and the mesh-map resources. The template capture is equal. The export result differs only in its output file paths.

`parity/reports/phase0/tier0-stability.md` was regenerated without fits. It covers Tier 0 only, so its counts are unchanged: 218 goldens, 137 stable.

## Unexpected

The project's `last_imported_mesh_path` is `_tmp/astra-tunica/normalized_low.obj` in Assets3D, and that file no longer exists. The rebuild fixture of decision 194 (`--pilot tunic-rebuild`) assumes the delivered `Export/18-Tunica-v10.fbx`, an assumption it said the readback would check. The readback contradicts the assumed path. It does not show whether the two meshes differ in geometry or UVs. The map comparison of phase2.10 item 3.1 will show that.

## Consequences

### Positive
- phase2.10 item 2.2 is done: the golden is recorded, with r1 and r2, and every map is stable.
- The two risks are settled for this project and build. No dialog blocked the open, and the project kept OCIO.

### Negative
- The rebuild's mesh input is not the mesh the project was last imported from.

## Follow-ups
- phase2.10 owner: settle the rebuild mesh. Either show that `Export/18-Tunica-v10.fbx` matches the mesh the project was imported from, or recover `normalized_low.obj` into the private store by hash and pin it in `--pilot tunic-rebuild`.
- No Painter recording is queued after this one.
