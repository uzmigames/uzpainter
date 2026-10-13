# P3-PATHTRACER entry gate (P0-FEAS-RENDER acceptance) — gate record

Task `phase0.9_render-reference-capture` (`docs/dag.md` P0-FEAS-RENDER, D6; decision 033: the sole entry gate of P3-PATHTRACER, not a G0 join). Evaluated on 2026-10-11 on the owner's machine (Windows 11, NVIDIA GeForce RTX 4090, Painter `12.1.5+js-api.1.1.20`, Python 3.13) on the tree of commit `cf48a54` with this task's working-tree changes. Numbers and hashes only: every recorded Painter output stays in the private store. SHA-256 values are of the file bytes in that tree.

**Result: evidence complete; signed by the owner on 2026-10-13 (decisions 063, 068).** Every acceptance clause of P0-FEAS-RENDER is evidenced below, checked clause by clause. The signature is the gate act: it records the owner's outcome and is not implied by this evidence. P3-PATHTRACER does not start before it; it also needs P1-CORE, P2-TUNIC and P3-VULKAN.

Owner signature: signed 2026-10-13. The owner, André, ordered in the coordinator session, in his own words, "termina e arquiva phase0.9_render-reference-capture" (finish and archive the task) while viewing its task file. That order is the gate act of item 4.1. The fixture content stays a proposal: the order neither ratified nor amended it.

## 1. Prerequisites and children

| Task | Role | State |
|---|---|---|
| `phase0.3_painter-oracle-recorder` | prerequisite (P0-RECORDER) | archived 2026-10-10 |
| `phase0.5_private-oracle-store` | prerequisite (P0-STORE) | archived 2026-10-10 |
| `phase0.6_render-reference-procedure` | child: every 07 §2.1 row answered for the fixed pipeline; procedure `iray-capture/1` qualified (decisions 038, 039) | archived 2026-10-11 |
| `phase0.7_render-reference-captures` | child: 23 goldens, 69 references admitted; terms (a), (b); fixture content proposed (decision 046) | archived 2026-10-11 |
| `phase0.8_render-reference-fits` | child: prototype term (c), lobe fits, noise-floor report, GPU probes (decisions 050-052) | archived 2026-10-11 |

## 2. Acceptance clauses (`docs/dag.md` P0-FEAS-RENDER)

| Clause | Evidence | Verdict |
|---|---|---|
| Procedure qualified | `iray-capture-procedure.md`: 14 rows answered (`documented`, `confirmed_by_probe`, `not_required` for the fixed pipeline, `random_seed` `uncontrolled`); qualification run and current-frame refusals recorded | met |
| References admitted | `iray-references.md` §3: 23 goldens, each two `separate_session` and one `k_times_samples` reference (69), all in the private store; item 3.1 below | met |
| Noise floor measured | `iray-noise-floor.md` §2-§3: (a), (b) and the prototype's (c) for the 22 fixtures of decision 046 and the qualification sphere, whose template-default material was read back under OCIO (`iray-references.md` §5.1, decision 068); the face-confined (a) final after decision 052's amendment (§9) | met |
| Fixture values proposed to the owner for ratification | `iray-references.md` §2, labelled proposed; render settings fixed by the owner (decision 038) | met (proposal; ratification not required) |
| Reproducibility probe published (decision 033) | `iray-noise-floor.md` §9 "Reproducibility probe": `plane-mid-grey`, six S renders and the k*S render, 0 of 15 pairs pixel-identical, per-setting observability, variance | met |

## 3. Integration checks (task items 3.1-3.5)

- **3.1** All 69 references of the 23 admitted goldens name `capture.procedure` = `iray-capture/1` in their sheet, carry their sheet's SHA-256 (`settings_sheet_sha256`) on every reference output of their private record, are `current_frame_verified`, and list `random_seed` as `uncontrolled` (`tests/parity/test_render_entry_gate.py`, with the private store).
- **3.2** The noise-floor table covers all 23 admitted analytic fixtures. The qualification sphere's material is the read-back golden `phase0/template-default-material/ocio-sphere` (one OCIO session, r1 = r2 on all five maps, private record `f6ac6f70c43d0df1d0051ad16e7a6805ce4f98b1143852c7b113b9d3f4faa2bb`): BaseColor linear 0.799986 (off the sRGB8 lattice), metalness 0, roughness L8 code 76, Normal (127/255, 127/255, 1), Height 0. Its (c): interior mean |delta| 402 codes at seed 1 and 511 at seed 2 against Iray's (b) of 140; edge 196 against 170 (decision 068).
- **3.3** The fixture content is presented as a proposal in `iray-references.md` §2 and here; the owner has not answered, so it stays labelled proposed.
- **3.4** Decision 052's capture request: 18 S renders of nine stability goldens, none refused, all in the private store (`store verify` exit 0 on `manifests/phase0/iray-stability`); decision 052 amended (trigger confirmed in the tested conditions, two-set mechanism contradicted, rotation dependence recorded); decision 062.
- **3.5** Reproducibility probe: §2 above.

## 4. Open items handed on

| Item | Owner |
|---|---|
| Mechanism of the zero-component class (rotation 360 test; y-zero and z-zero facets) | phase3.6 |
| The shipped tracer's term (c) | phase3.6 item 2.3 |
| Dielectric lobe and view-dependent diffuse residual | phase3.5 |
| Whether Iray shades the empty stack with 0.8 or the sRGB8 code 231, and whether it tilts the empty Normal's decoded 127/255 | phase3.5 (decision 068) |

## 5. Owner actions

- ~~Sign this record (the gate act; task item 4.1).~~ Done 2026-10-13; the task is archived.
- Optionally ratify or amend the proposed fixture content (`iray-references.md` §2).

## 6. Evidence

| File | SHA-256 |
|---|---|
| `parity/reports/phase0/iray-capture-procedure.md` | `d71e29f084b5a585280c4470c6a7c4875fdd88aa7f908276d6f37211eae677dd` |
| `parity/reports/phase0/iray-references.md` | `2970bc6123fa3c1a80fecd00a17506961dc761010c0c4de36ae50d3bd644e39d` |
| `parity/reports/phase0/iray-noise-floor.md` | `c4d8494aa7863427d05b4b8e2f0a36abac7d66e2e12a7a6c935c6302bcc267c7` |
| `parity/semantics/iray.json` | `6bb5ace3688de52c52bad6e4e520cefdc6d9b170f94dae200e9641d76b941198` |
| `parity/reports/phase0/toolchain-probes.md` | `4cedda0542eb3fb2dbeb30d09010be6b6a1f695f1ac30e8e37aecb166adf11a5` |
| `tools/parity/render_procedure/references.py` | `d561fa1b19083609458838179901e4e5daa3d5368779eeeb65f15005fc8cfe8b` |
| `tools/parity/render_fits/probe.py` | `c2ff2028f04ece4602eeaf1490fe8a14b3ce1c8f0cdb03c3fa9ec63ea03b0281` |
| `tools/parity/render_fits/pipeline.py` | `09147e031907f93edfc75fd1941946e28c8157f6e0bb2a2b01b4088f985e2e22` |
| `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase0/template-default-material/ocio-sphere.json` | `b18891cc5b636e25dc4a139420f7b66c73b4c816cfdac4ae9068e15bcc96f8ba` |
| `.rulebook/decisions/052-iray-s-run-to-run-difference-is-rounding-level-except-on-zero-component-facets-the-k-render-nests-the-s-render.md` | `2be6ad4b4e6fe629aa8adf28fc991629fedd823d820687020721f7c52dbf57e5` |
| `.rulebook/decisions/062-decision-052-s-capture-request-runs-as-a-stability-probe-the-zero-component-class-is-redrawn-per-render-and-the-plane-scene-is-the-reproducibility-probe.md` | `68729012931e3ef83fe2fa3ad6fb6609b25fc00eaad3c154d12cca59b67d2d6b` |
| `.rulebook/decisions/063-p0-feas-render-stays-open-until-the-qualification-sphere-has-its-term-c-and-the-owner-signs-the-path-tracer-entry-gate-record.md` | `0b201671ae31336befc337e79276e3a3048762f249993f62934c6d9c906faadc` |
| `.rulebook/decisions/068-the-qualification-sphere-s-template-default-material-is-read-back-under-ocio-and-its-term-c-is-measured-item-3-2-closes.md` | `170a2d1d72dccbca63d98d2c628646403056750c64d1ef432e2d298cbd34c46b` |
