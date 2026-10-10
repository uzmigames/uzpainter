# Proposal: phase3.6_path-tracer-tier3-report

## Why
VIS-06, ARC-06 and ARC-10 (`docs/prd.md`) require `painter_iray` to be compared with converged Iray references next to the oracle's measured noise floor, with every residual passing only through an owner-approved exception; G-04 requires renders to be compared separately from textures. Because Iray is stochastic, the Tier 3 report and its exception proposals are the deliverable that lets the owner decide (decisions 017 and 018). This child of P3-PATHTRACER (`phase3.7_path-tracer`) implements `docs/architecture/07-preview-and-render-parity.md` §2.2–§2.3 (production references) and §4, and Tier 3 of `docs/architecture/14-parity-testing.md` §3–§5 (D6, D13).

## What Changes
- Production-project Iray references of the pilot assets (Wand v1, Belt v5, Tunic v10) captured per `07-…` §2.2 with the production-project profile of §2.3: recorder settings readback, operator panel sheet, convergence check, Save Render, current-frame verification, two session-separated captures plus one at k·S; blobs in `UZP_PARITY_STORE`, hashes and authored fixture descriptions in `parity/manifests/`.
- Noise measurement per fixture (`07-…` §4 step 1): Iray run-to-run difference, Iray Monte-Carlo error at S (S vs k·S), UzPainter error at S (several seeds vs its own k·S).
- Comparison in the reference's own encoding, per fixture and per material region from the diagnostic ID captures: max/mean/p99 |Δ|, differing-pixel count, mean signed Δ with its standard error, the same after 2×/4×/8× box downsampling, and FLIP from `NVlabs/flip` pinned by version and hash (diagnostic only, listed with its BSD-3 notice).
- DXR-versus-Vulkan cross-backend report on the same fixtures, every difference reported.
- Exception proposals for `parity/exceptions.json` (with a decision draft for `.rulebook/decisions/`): fixture class, metrics, bounds derived from the measured noise floor, every `uncontrolled` setting relied on, and a defect-detection test proving the bounds still fail a missing channel, a wrong lobe, a roughness offset and a wrong environment rotation.
- Tier 3 report under `parity/reports/phase3/` (numbers only): structural differences (wrong binding, missing map, wrong geometry, camera or environment) fail regardless of any metric; every comparison without an approved entry is `blocked`.

## Dependencies
- Prerequisites: `phase3.4_path-tracer-transport`, `phase3.5_path-tracer-materials` (and through the parent `phase0.9_render-reference-capture` for the analytic references and noise-floor method).
- Parent: `phase3.7_path-tracer`.

## Acceptance
Tier 3 report produced with the noise floor, per-region statistics and the cross-backend report; exception proposals with defect-detection tests submitted to the owner; any Tier 3 pass or cross-backend bound exists only as an approved register entry, otherwise reported `blocked`.

## Impact
- Affected specs: path-tracer
- Affected code: recorder production-profile capture sheets, Tier 3 comparison tool, FLIP pin, `parity/manifests/`, `parity/reports/phase3/`, exception proposals
- Breaking change: NO
- User benefit: an evidence-backed render-parity decision for the owner instead of an unprovable equality claim
