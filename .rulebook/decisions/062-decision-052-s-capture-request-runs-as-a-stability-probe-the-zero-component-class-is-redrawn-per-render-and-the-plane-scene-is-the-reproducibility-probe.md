# 62. Decision 052's capture request runs as a stability probe; the zero-component class is redrawn per render; the plane scene is the reproducibility probe

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.9_render-reference-capture, phase0.8_render-reference-fits, phase3.6_path-tracer-tier3-report

## Context

Decision 052 left the face-confined run-to-run difference of three Iray goldens open: on facets whose normal has an x component of exactly zero (the tilted plane, the bevelled cube's top face), two sessions differ broadly; elsewhere only at the binary16 rounding level. Its capture request asked for 18 S renders (procedure `iray-capture/1`, S = 256, no k*S): the plane and the cube turned by +-1 degree about +Y, `plane-mid-grey` twice more in separate sessions and twice in one session, `cube-saturated--ref-match-180` twice more, and the plane under `ref_match` at rotations 0 and 180. Decision 033 adds to P0-FEAS-RENDER's acceptance a reproducibility probe: "one trivial Iray scene captured repeatedly, with pixel equality, per-setting observability and the measured variance published". The store admits a Tier 3 golden only with two separate-session renders and one k*S render; the recorder refused a second reference of a golden in one Painter session.

The model panel was consulted twice under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5).

Design, before capture:

| Claim | Verdicts |
|---|---|
| C1 Nine stability goldens under `phase0/iray-stability/`, never admitted as goldens; repeats keep the parent's instruction sequence and golden key | PARTLY x3: mark them non-admitted explicitly; state the key rule (the nudge of the same-session pair is a recorder condition, not part of the sequence) |
| C2 Renders, panel images and environment records into the store under the stability manifests; staged recording JSON private, hashed in the report | AGREE x2, PARTLY x1 (store-verify coverage must be shown) |
| C3 Turned meshes: one more +-1 degree turn about world +Y, committed | AGREE x2, PARTLY x1 (verify that no facet normal keeps a zero x component) |
| C4 Same-session pair: one project, field-of-view nudge and restore through the documented API, read-back state must equal the first | AGREE x1, PARTLY x2 (it separates per render from per session only; a second project is a different test) |
| C5 Classification thresholds 5% / 0.75 / 50% | DISAGREE x1, PARTLY x2: 0.75 excludes a measured rounding facet (0.73); identical pairs are rounding-compatible; add `indeterminate`; publish the full pair matrix |
| C6 Verdict rule | DISAGREE x1, PARTLY x2: say "consistent", not "supported"; three outcomes; two classes need two observed classes |
| C7 The same captures serve decision 033's probe | PARTLY x2, DISAGREE x1: publish it as its own section; separate per-capture read-back from the phase0.6 row statuses; define every term |

Results, after capture:

| Claim | Verdicts |
|---|---|
| R1 An exactly-zero normal component is necessary | PARTLY x3: necessary in the tested conditions (rotation-0 environments, +-1 degree), not sufficient; finer turns are untested |
| R2 The two-set mechanism is contradicted; the component is redrawn per render | AGREE x1, PARTLY x2: the redrawn share is rms(a)^2 / 2 rms(b)^2 = 0.08-0.15 (not 4-7%), under a stated model; other per-render mechanisms remain |
| R3 Rotation matters, asymmetry does not explain it; record the sin(pi) hypothesis and defer the 360-degree test | AGREE x1, PARTLY x2: record both predicted outcomes; 360 may fold to 0 |
| R5 The plane scene satisfies decision 033's probe | AGREE x1, PARTLY x2: map each requirement; cite independent evidence that no denoiser acts |

## Decision

1. **Stability goldens.** `references.STABILITY_FIXTURES` adds nine goldens `phase0/iray-stability/<name>` with their manifests: `plane-mid-grey--yaw-p1/m1`, `cube-mid-grey--yaw-p1/m1` (committed meshes turned +-1 degree about +Y after their own transforms; no facet normal keeps a zero x component), `plane-mid-grey--repeat`, `plane-mid-grey--same-session`, `cube-saturated--ref-match-180--repeat`, `plane-mid-grey--ref-match-000/180`. Each holds two S renders and no k*S render; they are stability evidence and are never admitted as goldens. The repeats have their parent's instruction sequence, and their golden keys equal the parents' (checked).
2. **Same-session condition.** The recorder's `--condition same_session` records two S renders of one project in one Painter process: after the first Save Render it nudges the field of view by one degree and restores it through the documented API, requires the read-back render state to equal the first, waits for Done and saves again (`s-<session>-1`, `-2`).
3. **Storage.** `python -m tools.parity.render_procedure stability-admit` stores every blob of the staged captures under the stability manifests (`<recording>-render-reference`, `-panel-<panel>`, `-oracle-environment`); `store verify` re-hashes them. The staged recording JSON stays in the private work folder; its SHA-256 is in `iray-noise-floor.md` §9.
4. **Classification.** Per facet: `identical`; `rounding` (under 5% of pixels differ, at least 70% of differing samples by one binary16 step); `decorrelated` (over 50%); else `indeterminate`. A pair takes its worst facet; renders joined by rounding or identical pairs form a class; the full pair matrix is published.
5. **Results** (18 renders, none refused; numbers in `iray-noise-floor.md` §9): all four turned fixtures are `rounding` on all 14 facets; the six `plane-mid-grey` renders give 15 `decorrelated` pairs and six classes, the same-session pair included; `cube-saturated--ref-match-180` stays `rounding` in four renders; the plane under `ref_match` is `decorrelated` at rotation 0 and `rounding` at 180; environment-asymmetry metrics do not separate the two rotations. Decision 052 is amended with the verdict.
6. **Reproducibility probe (decision 033).** The `plane-mid-grey` scene is the probe: six S renders and the admitted k*S render, with provenance, byte and pixel equality per pair (0 of 15), per-setting observability (how each setting is set and read back on every capture, captures confirming, the procedure row's status), and variance (high-pass sigma, (a), (b)). It is published as its own subsection with a per-requirement mapping; it requires no pixel equality and does not alone open P3-PATHTRACER.

## Alternatives Considered

- Admit the stability captures as Tier 3 goldens by relaxing the k*S rule (rejected: the admission rule stays; they are evidence, not references).
- A second project in the same process for the same-session pair (not adopted: the request asked for repeated Save Render in one session; it tests scene reloading, which the separate sessions already cover).
- Capture rotation 360 now to test the refined hypothesis (deferred: outside the pipeline's 0/180, no Phase-0 deliverable depends on it; phase3.6).

## Consequences

The recorder, `render_procedure` and `render_fits` gain the stability probe; `iray-noise-floor.md` §9 holds its numbers and the reproducibility probe. Phase3.6 owns the mechanism test and the y- and z-zero facets.
