# UzPainter parity contract

Work package P0-CONTRACT (`docs/dag.md`), task `phase0.2_parity-contract`. Binding for every parity comparison, recorder, store, comparison tool and report. Implements D13 as refined by the owner's answers of 2026-10-10: exact equality with an exception register (Q1, decision 017), Painter's Iray as the render reference (Q2, decision 018), migration through the documented API (Q6, decision 020), the owner's machine as holder of the private store (Q9b, decision 022), where GPU and oracle checks run locally with no GPU CI (decision 028). Acceptance premise: decision 001; clean room: decision 002. Architecture: `docs/architecture/14-parity-testing.md` and `docs/architecture/07-preview-and-render-parity.md` §2 and §4. Where this contract and those documents differ, the documents' owner decisions win and this file is corrected.

## 1. Acceptance sentence

> Default acceptance is equal native decoded texture values and the agreed reference render output. Every divergence is a failure unless an owner-approved, versioned exception explicitly covers that domain and metric. Explained differences are still failures without that exception. Diagnostic metrics do not grant an exception.

- **Exact equality** is the rule in every comparison domain: native decoded texture values, API readbacks, encoded bytes where a contract names them, and reference renders.
- **There are no preset tolerances.** No bound exists anywhere in the suite unless an entry of the exception register (§5) states it. Proposed numbers in earlier analyses are not tolerances.
- **The register is the only way a non-zero difference passes.** An explanation, a root-cause note or a small diagnostic value is not an exception.
- **Diagnostics never grant an exception.** Mean, p99, FLIP and every other statistic of §8 are reported to understand a difference, never to accept one.

## 2. Three results, always reported separately

| Result | Question | Compared |
|---|---|---|
| **Oracle stability** | Does Painter reproduce itself? | Painter recording against Painter recording of the same golden (§6.2) |
| **UzPainter repeatability** | Same build, same inputs: same bytes? | UzPainter run against UzPainter run |
| **Equality to Painter** | Does UzPainter equal the oracle? | UzPainter output against the Painter golden |

A report never merges them into one number. Equality to Painter compares against every admitted recording of the golden; with a stable oracle they are identical. An unstable oracle is reported as such and makes the equality result `blocked`, never `pass`, unless an in-force register entry whose evidence is the measured oracle instability covers it, or in Tier 3 an entry derived from the noise floor, which includes Iray's run-to-run difference (§3.3, §4.1, §5).

## 3. Comparison rules

1. **Decoded pixels at native depth.** Maps are decoded to their stored sample values (8-bit or 16-bit integer code values, half or float values) and compared value for value. Nothing passes through an 8-bit viewer or an image library that truncates 16-bit data. Integer formats compare code values. Float formats compare values as numbers: a NaN matches only a NaN, and the counts of non-finite values are reported (§8.1).
2. **Channels are classified by their measured storage format** (container, sample type, bits per channel, channel count, encoding) as recorded in the private record, never by map or channel name. No half-float epsilon or any other allowance is applied by name.
3. **Outcomes.** Every comparison ends in exactly one outcome:

   | Outcome | When |
   |---|---|
   | `pass` | Tiers 0–2b with a stable oracle: all compared values are equal. Otherwise only when an in-force register entry whose tier and domain match and whose every bound holds covers the comparison (the report lists the entries relied on); against an unstable oracle that entry's evidence must be the oracle instability (Tier 3: or the noise floor) |
   | `fail` | Tiers 0–2b: any difference without a covering entry; any tier: a structural difference (shape, missing map or channel, wrong binding) |
   | `blocked` | Tier 3 without a covering entry (even when the values happen to be equal); an unstable oracle without a covering instability entry; a gate fixture marked `not_migratable` without an owner scope decision (§6.3) |
   | `oracle_unavailable` | The private blob a public manifest names is missing from the store or fails its hash. **Never a pass.** Nothing is compared |

4. **Backends.** Once the Vulkan backend is qualified, Tier 0–2 outputs on Vulkan must equal those on DX12 byte for byte; any difference passes only through §5 (domain kind `backend_pair`). DXR and Vulkan path-tracer outputs of the same fixture are compared and every difference is reported.
5. **Not a tier.** The realtime viewport (`painter_viewport`) has UzPainter-against-UzPainter regression goldens (repeatability checks); they are never parity evidence.

The reference implementation of rules 3.1 and 3.3 for one compared quantity is `tools/parity/verdict.py` (`evaluate`), tested in `tests/parity/test_verdict.py`.

## 4. Tiers

| Tier | Corpus | Compared quantities | Gate |
|---|---|---|---|
| **0 Semantics** | Synthetic meshes (plane, sphere, bevelled cube) × blend modes × value/opacity sweeps; mask operations; projections; per-template channel sets and formats; base values; uniform colour spaces; height→normal methods and strength; normal blends; mixed ambient occlusion; export padding, dithering, resize and bit depth; triangulation of quads; API probes (set→get readback, mask `None` rules, insertion rules, active-channel reset, event order); current baking defaults and property metadata | Decoded maps; API readbacks | Exact |
| **1 Recipes** | Assets3D stacks rebuilt from the same JSON and resources in both tools with identical external mesh maps: Wand v1, Belt v5, Tunic v10, Staff v10, Bracer r9, Hat v8, Body v6b | Every exported map per texture set; save/reopen; dump-and-rebuild | Exact |
| **2a Procedurals** | Each certified procedural asset × 3 meshes × {1024, 2048, 4096} × parameter sets × seeds | Asset outputs | Exact, or a register entry per asset |
| **2b Bakes** | Analytic fixtures and the wand/hat low/high/cage pairs, ten bakers, Painter's CPU backend recorded; repeated across thread counts and instruction sets | Hit/coverage evidence first, then maps | Exact, or a register entry per map |
| **3 Renders** | `painter_iray` (DX12 and Vulkan) against converged Painter Iray references: analytic fixtures and the production-project profiles of the certified assets | Converged images in the reference's own encoding, per material region, next to the noise floor | Passes only through a register entry; otherwise **blocked** |

### 4.1 Tier 3

- **Reference.** A converged Iray image captured by the qualified procedure of `07-…` §2.2: Min Sample = Max Sample = S with Max Time well above the time S takes; captured only when Status reads Done, Iterations equals S and Rendering time is below Max Time; current-frame verification passed. Each reference is recorded twice in separate Painter sessions plus once at k·S samples.
- **Encoding.** If the reference is linear float, linear buffers are compared; if it is display-referred 8-bit, UzPainter's linear buffer goes through the same display transform and quantisation first.
- **Noise floor.** Measured per fixture: (a) Iray run-to-run difference between the two session-separated references (the oracle-stability result); (b) Iray's own Monte-Carlo error at S, from S against k·S; (c) UzPainter's error at S, from several seeds against its own k·S render. (b) and (c) form the noise floor.
- **Why the register is the only route.** Iray is stochastic and its seed is not exposed, so pixel-exact equality between `painter_iray` and an Iray reference is not achievable; this contract does not claim it. A Tier 3 comparison passes only through an owner-approved register entry whose bounds derive from the measured noise floor; without one it is **blocked**, never passed.
- **Limits.** A Tier 3 entry never relaxes Tiers 0–2 (entries match on their own tier only) and never covers a structural difference: a wrong material binding, a missing map, or a wrong geometry, camera or environment fails regardless of any metric.
- **Scope.** Tier 3 covers the fixtures and configurations its report lists; any other configuration is a capability gap, not a pass.

## 5. Exception register

`parity/exceptions.json`, schema `parity/schema/exceptions.json`. Public: numbers and the SHA-256 of private evidence only. An entry is proposed with, and the schema requires:

| Field | Content |
|---|---|
| `exception_id`, `version` | Stable id `EXC-NNN` and a version; a change is a new version, and only the highest version of an id is in force |
| `tier`, `domain` | The tier and the domain covered: `channel`, `asset_map`, `procedural_asset`, `bake_map` (Tiers 0–2b), `render_fixture_class` (Tier 3), `backend_pair` (any); `selector` equals the `domain` of the covered public manifests |
| `bounds` | One or more `{metric, scope, max}`: a metric of §8.2, over the `whole` comparison or `each_region`, with an inclusive upper bound; every bound must hold |
| `evidence` | `basis` (`oracle_instability` or `irreducible_difference`; `noise_floor` for a render fixture class, with the measured `noise_floor` per metric), a summary, the SHA-256 of the private evidence, and every `uncontrolled` setting of the references relied on (empty list when none) |
| `defect_detection_test` | The test showing the bounds still catch intentional errors (texture tiers: defects chosen for the domain, e.g. sparse seams, alpha defects, one wrong texel region; Tier 3 must include a missing channel, a wrong lobe, a roughness offset and a wrong environment rotation), and the outcome `every_injected_defect_fails` |
| `decision_id`, `approved_by`, `approved_on` | The owner decision recorded under `.rulebook/decisions/`; `approved_by` is always `owner` |

`tools.parity.schemas.register_problems` adds the two rules a schema cannot state: each (`exception_id`, `version`) appears once, and each `decision_id` names a recorded decision. Every report lists the entries it relied on (§8.4).

## 6. Oracle, goldens and storage

### 6.1 Oracle

Adobe Substance 3D Painter 12.1.0, including Iray, on the owner's machine, driven by UzmiGames recorder scripts through Painter's **documented** Python API for state and a qualified, permitted capture procedure for pixels (documented texture export; the Iray procedure of §4.1). The community MCP bridge is never used, and no private interface is inferred. Observing Painter this way is the only permitted way to learn undocumented semantics; every recorded output is private.

### 6.2 Golden shape and the two-recording rule

A golden is `{inputs, instruction sequence, effective defaults, Painter build, project settings, resource hashes, bake backend, render state} → {outputs}`. Outputs are exported maps (16-bit or float), API readbacks (JSON included), effective-default and template captures, and converged Iray references with their settings sheet, operator-recorded settings and settings-panel evidence. Every golden is recorded at least twice: Tiers 0–2b once in the session that built the state and once after save/reopen; Tier 3 twice in separate Painter sessions plus once at k·S samples. Oracle stability is measured before a golden is admitted. Goldens are immutable per Painter build.

### 6.3 `not_migratable`

Tier 1 fixtures are rebuilt through Painter's documented API and proven by output equality (no `.spp` reader). A fixture that cannot be rebuilt that way is recorded `not_migratable` with its reason in the public manifest and keeps its gate **blocked**. Only an explicit owner scope decision (`owner_scope_decision`, recorded in the capability manifest and the gate report) excludes or replaces it; reporting the limitation never closes the gate, even when every other fixture passes.

### 6.4 Public and private

- **Public repository** (independently authored or public data only): manifests `parity/manifests/**/*.json` (schema `golden-public.json`), fitted formulas `parity/semantics/*.json`, the register, comparison reports (numbers only).
- **Private store only** (`UZP_PARITY_STORE`, content-addressed by SHA-256, on the owner's machine, never uploaded, never shipped): every recorded Painter output (schema `golden-private.json`): exported maps, Iray references, API readbacks (JSON included), effective-default and template captures, operator-recorded render settings and settings-panel evidence, asset recipes extracted or dumped from Painter projects; and anything derived pixel for pixel from one (difference maps, crops). Public templates and default tables are independently authored from documented semantics with provenance.
- A missing or hash-mismatched blob yields `oracle_unavailable` (§3).
- Store layout, the `uzpainter parity init|record|fetch|verify` prototype, the recorder hand-off, hosted CI and the local oracle run: `parity/STORE.md`.

## 7. Schemas

All schemas are JSON Schema draft 2020-12 under `parity/schema/`; `tools/parity/schemas.py` validates against them.

| Schema | Describes | Separation rule |
|---|---|---|
| `golden-public.json` | Public manifest: authored inputs with provenance (`uzmigames_authored` or `cc0_public`), the UzmiGames instruction sequence over documented `substance_painter` calls, applied settings with who applies them, names of `uncontrolled` settings, public-documentation-derived expectations (each citing an approved public source of `docs/approved-sources.md` with a locator; `A-OBSERVE` is refused), software identities (Painter 12.1.0 build id, UzPainter build hash), SHA-256 and size of every private record, optional `not_migratable` | `record_class` is `public_manifest`; every object is closed (`additionalProperties: false`); value slots (instruction arguments, applied settings, expectations) take only short scalars or lists of at most 16 short scalars, and free text is bounded. No recorded output, readback object, capture or record fits any slot, and a relabelled private record is still rejected by its content. A single recorded number cannot be told apart from an authored one by shape, so expectations must cite public-source provenance and the P0-STORE guard also matches store hashes |
| `golden-private.json` | Private record: the golden key, at least two recordings (rule of §6.2), each output typed as exported map (with measured storage format), API readback, effective-default capture, template capture, Iray reference (convergence `Done`, capture route, settings-sheet hash, current-frame verification), operator-recorded settings or settings-panel evidence. `tools.parity.schemas.record_problems` adds the cross-field rules: ISO 8601 timestamps with offset, Iterations = S and Rendering time below Max Time, distinct sessions for the two Tier 3 references, k·S samples (k > 1) for the third. The record links to its manifest by `golden_id` only: the manifest names the record by SHA-256, so the record never hashes the manifest | `record_class` is `private_oracle_record` |
| `exceptions.json` | The register (§5) | — |
| `comparison-report.json` | The comparison-tool output (§8) | Numbers and hashes only |

Samples under `parity/schema/samples/` are synthetic (invented values and hashes; nothing recorded from Painter): `public/` (valid manifests), `private/` (private-shaped records: exported map, JSON readback, default and template capture, Iray reference), `exceptions/` (register entries), `reports/` (a report). The repository guard of P0-STORE must accept `samples/private/` only as these synthetic test inputs. Tests: `tests/parity/test_schemas.py`.

## 8. Comparison-tool specification

The comparison tool decodes both sides at native depth (§3), computes the diagnostics below for each of the three results of §2, applies §3.3 and writes a report valid against `comparison-report.json`.

### 8.1 Diagnostics reported with every comparison

Per map (and per material region when the golden defines regions):

- **Absolute difference** in native decoded units: max |Δ|, mean |Δ| and p99 |Δ| (nearest-rank 99th percentile of the sorted |Δ| over all compared values).
- **Differing values**: count, percentage and total compared.
- **Per-region breakdown** by the asset's material masks: the same statistics per region.
- **Normals**: angular max and mean (degrees), non-finite and unnormalised counts.
- **IDs and opacity**: exact label and alpha equality, differing count and edge-coverage differences.
- **Renders (Tier 3)**, per fixture and per material region, from the diagnostic ID captures: the statistics above, mean signed Δ with its standard error from the noise-floor measurements (a bias test: noise averages out, a wrong lobe does not), the same statistics after 2×, 4× and 8× box downsampling, next to the noise floor (Iray at S, UzPainter at S, Iray run to run) and UzPainter's own re-render statistics.
- **Lossy derivatives** (BC, mips): decoded compression error against the canonical map, a separate contract from authoring equality.
- **FLIP** (below).

**Never a mean alone.** A mean or percentile is always reported with the maximum and the differing count next to it; the report schema makes `max`, `mean`, `p99` one object and `count`, `percent`, `total` its required sibling.

### 8.2 Metric names

The names exception bounds use (`exceptions.json`): `max_abs_diff`, `mean_abs_diff`, `p99_abs_diff`, `differing_count`, `differing_percent`, each also with `_down2`, `_down4`, `_down8` (after box downsampling); `normal_angular_max_deg`, `normal_angular_mean_deg`, `normal_non_finite_count`, `normal_unnormalised_count`; `id_label_differing_count`, `alpha_differing_count`, `edge_coverage_differing_count` (never in a Tier 3 entry); `abs_mean_signed_diff_in_se` (|mean signed Δ| divided by its standard error); `compression_max_abs_diff`. The `_downN` names are Tier 3 only, and the keys of a Tier 3 `noise_floor` are names from this list. FLIP is deliberately absent: it can never bound an exception.

### 8.3 FLIP

Computed with NVIDIA's reference implementation (`NVlabs/flip`, BSD-3-Clause; approved source N-FLIP), pinned by version and SHA-256 in the comparison tool and listed with its notice in the dependency inventory (`docs/licensing-and-clean-room.md` §3). A report carrying a FLIP value carries the pinned identity (`flip_tool`). FLIP is a diagnostic only, never a gate and never exception evidence.

### 8.4 Report rules

- Every report carries hardware, driver, backend, UzPainter build hash, Painter build id, resource hashes and the exception entries relied on (id and version).
- `pass` without a relied-on entry requires every compared map and region to have max |Δ| 0 and differing count 0 and every exact check to be equal; a Tier 3 `pass` and a `pass` against an unstable oracle always list an entry; `oracle_unavailable` compares nothing.
- Tier 3 evidence comes from the DX12 or Vulkan GPU backends only, never from WARP or a CPU path.
- **Difference maps and region crops are derived from oracle pixels and stay in the private store**; a public report carries numbers and, at most, the SHA-256 of a private difference map.

## 9. Review

| Reviewer | Date | Scope | Result |
|---|---|---|---|
| Review subagent (Claude Fable 5.1) | 2026-10-10 | `parity/CONTRACT.md`, the four schemas under `parity/schema/`, the samples, `tools/parity/verdict.py`, `tools/parity/schemas.py`, `tests/parity/`; checked against `14-parity-testing.md` §1–§6 and §9, `07-preview-and-render-parity.md` §2 and §4, decisions 017, 018, 020 and 022 | First pass: 4 blocking findings (open instruction arguments, circular manifest/record hashes, Tier 3 equality without an entry, unstable oracle) and 7 non-blocking, all fixed. Second pass: 1 blocking regression (Tier 3 noise-floor entries could not cover an unstable Iray oracle), fixed. Approved |