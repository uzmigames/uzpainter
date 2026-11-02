# Painter recording backlog: inventory

Decision 367, front C, 2026-11-02. This file lists what the next Painter slot can record, and which
open rulebook items wait on a Painter recording that has no request yet. The batch compiler
`tools/parity/recorder/batch.py` builds the slot's plan:

```powershell
python -m tools.parity.recorder.batch plan --assets-root E:\UzmiGames\Assets3D --store --out <plan.json>
python -m tools.parity.recorder.batch status --assets-root E:\UzmiGames\Assets3D --store --next
```

The plan is regenerated from the repository each time, so it is never stale. `02-batch-plan.json`
is the snapshot taken when this inventory was written. Envelope:
`painter-12.2.0+js-api.1.1.20-env-a981b586eae7`.

## 1. Queue for the next slot

The current envelope has 52 request files outside `requests/admitted/`. 40 of them already have an
admitted manifest. The other 12 are:

| Request | State | Why |
|---|---|---|
| `tier0/assets3d/export-padding-kernel-wand-2048` | **scheduled, 1st (G1)** | Decision 266's kernel-code probe on the Wand v1 low mesh at 2048 px (`phase1.25_pilot-wand` item 2.7). Its mesh is no longer under Assets3D `_tmp/claude/varinha11-v1/`. The private store holds a blob of the pinned hash, so the job is valid only with `--store` |
| `tier0/semantics/srgb-bitmap-minification-random` | scheduled, 2nd | Decision 225. It cites `phase1.15_compositor-colour-fits`, which is archived |
| `tier0/api-probes/ocio16-raw-readout-*` (10 files, v1 and v2) | not scheduled: superseded | Each `-v3` with the same state is admitted, and the runners refuse the earlier recipes (phase3.2_unreal-ue56-packed-preset §20) |

Both scheduled goldens run in **one Legacy session**. The recorder keeps no timings. Decision 266's
batch gives about 8 s for each kernel probe and about 105 s of session overhead. The slot is
therefore about **2–5 minutes** of Painter time; that figure is an estimate, not a measurement. The
Wand mesh (2048 px, four EXR32f exports of eight maps) is heavier than the probes it is compared
with. `srgb-bitmap-minification-random` has no documented timing.

Front A may add more Wand padding probes. Every request under `requests/` is scheduled on the next
run of the compiler: Wand ones first, then the rest by the open items of the tasks they cite.

### Goldens that need a request first

- **32 Tier 3 Iray references** (the drift report's `stale_tier3`: 22 under
  `phase0/iray-references/`, 9 under `phase0/iray-stability/`, plus
  `tier3/render-procedure/qualification-sphere`). They were recorded under 12.1.5, and CONTRACT.md
  §5 bars any whole-product parity claim while they are stale. Their generator,
  `tools/parity/render_procedure/references.py` (`manifest`, `write_manifests`), still pins the
  old Painter identity and writes into the old manifest directory. Nothing defines how Tier 3
  requests are staged under a promoted envelope. Missing: that decision and the generator change.
  They are operator sessions (`iray --launch --operator ui`, one fresh Painter per reference, three
  conditions each), not part of a short slot.
- No request of the superseded 12.1.5 envelope is missing from the current one.

## 2. Open items that wait on a recording without a request (phases 1–3)

Sources: every open `- [ ]` item of `.rulebook/tasks/*/tasks.md`, the current `requests/` and
`manifests/` trees, and RECORDER.md §11. Items whose only blocker is native work or a fit to
recordings that are already admitted are left out. So are owner signatures, docs, and gate or
acceptance items that only join other items.

| Task (items) | Recording needed | What is missing before a request can be authored |
|---|---|---|
| `phase2.9_pilot-belt` (2.2, then 3.1, 3.3, 4.1) | Sash v5 Tier 1 golden (r1, r1-repeat, r2) | The generator exists (`script_run manifest --pilot sash`). 22 Assets3D inputs are lost: 2 arguments files, 19 masks and `T_sash`. The mesh, normal and AO bindings are unresolved, and the owner's baseline choice (item 2.8) is pending |
| `phase2.10_pilot-tunic-recovery` (2.1, 2.3–2.5) | Painter export of the 9 lost masks from the stored `.spp` (decision 300 §7), or a `tunic-v10-current` golden | The Export-resource route is not qualified (result `RE_ENCODED`). `normalized_low.obj` is missing. The changed baseline waits on the owner |
| `phase3.2_baker-normal` (2.4, 3.2, 3.3), `phase3.4_baker-ao`, `-curvature`, `-height`, `-thickness`, `-id`, `-position`, `-world-space-normal`, `-bent-normals`, `-opacity` (items 2.x manifests, 3.1, 3.2 each) | Tier 2b bake goldens on the analytic fixtures with highs, and on the Wand and Hat low/high/cage pairs | The analytic high/low fixtures exist only as C++ meshes (`tests/bake/bake_fixtures.h`). There are no OBJ inputs and no bake request generator. Bake settings, resolution and format are not declared. Authoring the manifests is itself each task's item. The Height `Divisor` values and the ID cube and Position non-cubic meshes of decision 337 are not chosen or authored. The Wand and Hat high and cage meshes are not pinned |
| `phase3.2_proc-filter-families`, `-generator-families`, `-grunge-families`, `-material-families` (calibration 2.4/2.5, 3.1; grunge 3.3 seeds; material 3.2 physical size), then `phase3.3_procedural-families` 3.1 | Tier 2a goldens: 3 meshes × {1024, 2048, 4096} × parameter sets × seeds | The certified domain is not declared (items 2.6/2.7), so calibration may not start. Parameter discovery and parameter sets are not done. The Hat v6 low mesh is not in the repository. The two-unit-scale meshes are not authored |
| `phase3.4_smart-projections` (2.2, 3.1–3.5) | Tier 0 projection goldens and API probes | The meshes exist. The hardness, scale, rotation, crop, culling and symmetry sweeps and the multi-unit meshes are not chosen. There is no generator |
| `phase3.4_smart-mask-recipes` (2.5, 3.1), `phase3.5_smart-material-recipes` (2.7, 3.1, 3.5) | A Painter rebuild of each recipe | The recipes are not authored (items 2.1/2.2) |
| `phase3.1_unreal-gltf-pbr-preset` 3.1, `phase3.2_unreal-ue56-packed-preset` 3.1, `phase3.3_unreal-gltf-presets` 3.2 | Painter exports of each preset on the pilots | There is no pilot preset-export generator (R-314 and R-322 used an authored bevelled cube). The Belt and Tunic inputs are missing |
| `phase3.2_unreal-ue56-packed-preset` 2.1, 2.3 | Unreal Packed observed outputs | R-322 is admitted, but its own-defaults configuration fails inside Painter and the dry-run readbacks are unstable after reopen. No decision says what to re-record |
| `phase3.5_path-tracer-materials` 2.4 | OpenPBR default-instance readback and the Tunic "Double sided" readback, on an OCIO project | The probe steps are not authored |
| `phase3.5_path-tracer-materials` 3.3, `phase3.6_path-tracer-tier3-report` 2.2, 3.1 | Iray references: analytic ones re-captured, plus production ones | Analytic: see §1. Production: the settings sheets and cameras (item 2.1) are not written, and the Belt inputs are lost |
| `phase3.7_fixtures-bracers-hat5` (2.1, 2.5, 2.6, 3.x) | Bracer r9 and Hat v5 Tier 1 and Tier 2b goldens | There is no generator (`script_run` pilots: wand, belt, sash). The Hat v5 classification (item 2.4) is open |

Waiting only on the Sash golden above: `phase3.1_vulkan-compute-parity` 3.6,
`phase3.3_vulkan-backend-ray-tracing` 3.2, `phase3.1_assets3d-cutover` 3.1/3.5 and G2
(`phase2.11` 2.5, 4.1).

**No request was authored here.** No phase 1–3 recording passes the bar "fully defined by its task
or decisions": every row above lacks an input, a parameter choice, a fixture or a decision that
would otherwise have to be invented.

### Already recorded: the task text lags

- `phase3.2_unreal-ue56-packed-preset` 2.10 (AO_Mixed, decision 131): `ao-mixed-grid*`,
  `ao-mixed-mesh-float-product` and `ao-mixed-precomposed-*` are admitted. What remains is the fit
  (native). `phase3.2_uze-uzmat-preset` waits on that fit and on Wand padding, not on Painter.
- `phase3.3_unreal-gltf-presets` 3.5 (R-095): `export-presets-legacy` and `-ocio` are admitted.
- `parity/RECORDER.md` §11.4 still calls `ao-mixed-grid` "authored only; not recorded". It is
  admitted.
- `phase1.25_pilot-wand` item 2.7 does not yet cite the committed
  `export-padding-kernel-wand-2048` request.

## 3. Phases 4–5 (approximate keyword count of recording-blocked items)

phase4.1: coverage-body-v6b 3, hat8-sharpen-filter 4, hat8-specular-weight-export 1,
nodes-instances-anchors 7, nodes-mask-effects 6, nodes-paint-layers 6, nodes-projections 7,
nodes-vector-font-sources 6. phase4.2: coverage-hat-v8 3, dxr-dx12-rt 2, dxr-vulkan-rt 2,
remaining-nodes 3. phase4.3: dxr-baker 2, tiles-workflow 6. phase4.4: tiles-export-filters 4,
tiles-per-tile-resolution 4. phase4.5_uv-tiles 2, phase4.6_gate-g4 1,
phase5.2_parity-report-tiers 5. None of them has a request, and none is due before G3.
