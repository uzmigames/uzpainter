# P3-PATHTRACER entry gate (P0-FEAS-RENDER acceptance) — gate record

Task `phase0.9_render-reference-capture` (`docs/dag.md` P0-FEAS-RENDER, D6; decision 033: the sole entry gate of P3-PATHTRACER, not a G0 join). Evaluated on 2026-10-11 on the owner's machine (Windows 11, NVIDIA GeForce RTX 4090, Painter `12.1.5+js-api.1.1.20`, Python 3.13) on the tree of commit `30d2c03` with this task's working-tree changes. Numbers and hashes only: every recorded Painter output stays in the private store. SHA-256 values are of the file bytes in that tree.

**Result: held open (decision 063).** Every acceptance clause of P0-FEAS-RENDER is evidenced below except one: term (c) of the qualification sphere (task item 3.2). The owner's signature is pending. P3-PATHTRACER does not start before both close; it also needs P1-CORE, P2-TUNIC and P3-VULKAN.

Owner signature: pending.

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
| Noise floor measured | `iray-noise-floor.md` §2-§3: (a), (b) and the prototype's (c) for the 22 fixtures of decision 046; the face-confined (a) final after decision 052's amendment (§9); the qualification sphere has (a) and (b) only | not met: the sphere's (c) (item 3.2) |
| Fixture values proposed to the owner for ratification | `iray-references.md` §2, labelled proposed; render settings fixed by the owner (decision 038) | met (proposal; ratification not required) |
| Reproducibility probe published (decision 033) | `iray-noise-floor.md` §9 "Reproducibility probe": `plane-mid-grey`, six S renders and the k*S render, 0 of 15 pairs pixel-identical, per-setting observability, variance | met |

## 3. Integration checks (task items 3.1-3.5)

- **3.1** All 69 references of the 23 admitted goldens name `capture.procedure` = `iray-capture/1` in their sheet, carry their sheet's SHA-256 (`settings_sheet_sha256`) on every reference output of their private record, are `current_frame_verified`, and list `random_seed` as `uncontrolled` (`tests/parity/test_render_entry_gate.py`, with the private store).
- **3.2** Open: the qualification sphere's term (c) needs its template-default material read back first (decision 063).
- **3.3** The fixture content is presented as a proposal in `iray-references.md` §2 and here; the owner has not answered, so it stays labelled proposed.
- **3.4** Decision 052's capture request: 18 S renders of nine stability goldens, none refused, all in the private store (`store verify` exit 0 on `manifests/phase0/iray-stability`); decision 052 amended (trigger confirmed in the tested conditions, two-set mechanism contradicted, rotation dependence recorded); decision 062.
- **3.5** Reproducibility probe: §2 above.

## 4. Open items handed on

| Item | Owner |
|---|---|
| Term (c) of the qualification sphere (template-default material read-back, then the prototype's measurement) | `phase0.9_render-reference-capture` item 3.2 |
| Mechanism of the zero-component class (rotation 360 test; y-zero and z-zero facets) | phase3.6 |
| The shipped tracer's term (c) | phase3.6 item 2.3 |
| Dielectric lobe and view-dependent diffuse residual | phase3.5 |

## 5. Owner actions

- Sign this record once item 3.2 is closed.
- Optionally ratify or amend the proposed fixture content (`iray-references.md` §2).

## 6. Evidence

| File | SHA-256 |
|---|---|
| `parity/reports/phase0/iray-capture-procedure.md` | `d71e29f084b5a585280c4470c6a7c4875fdd88aa7f908276d6f37211eae677dd` |
| `parity/reports/phase0/iray-references.md` | `625f90a18fabb1d460c1c3356889c77c68670a96e77d0ff672e21f993dd3ee02` |
| `parity/reports/phase0/iray-noise-floor.md` | `e4fb3cdf09a33ebc05c216cd0cf85e662a1edd8b33b2cab74fcb2b7490ca096f` |
| `parity/semantics/iray.json` | `6bb5ace3688de52c52bad6e4e520cefdc6d9b170f94dae200e9641d76b941198` |
| `parity/reports/phase0/toolchain-probes.md` | `4cedda0542eb3fb2dbeb30d09010be6b6a1f695f1ac30e8e37aecb166adf11a5` |
| `tools/parity/render_procedure/references.py` | `2cf6f3876a30068e99979bc815e7e9c0d7ceefe61074465b9e24b7c6c8ddcb71` |
| `tools/parity/render_fits/probe.py` | `c2ff2028f04ece4602eeaf1490fe8a14b3ce1c8f0cdb03c3fa9ec63ea03b0281` |
| `.rulebook/decisions/052-iray-s-run-to-run-difference-is-rounding-level-except-on-zero-component-facets-the-k-render-nests-the-s-render.md` | `2be6ad4b4e6fe629aa8adf28fc991629fedd823d820687020721f7c52dbf57e5` |
| `.rulebook/decisions/062-decision-052-s-capture-request-runs-as-a-stability-probe-the-zero-component-class-is-redrawn-per-render-and-the-plane-scene-is-the-reproducibility-probe.md` | `68729012931e3ef83fe2fa3ad6fb6609b25fc00eaad3c154d12cca59b67d2d6b` |
| `.rulebook/decisions/063-p0-feas-render-stays-open-until-the-qualification-sphere-has-its-term-c-and-the-owner-signs-the-path-tracer-entry-gate-record.md` | `0b201671ae31336befc337e79276e3a3048762f249993f62934c6d9c906faadc` |
