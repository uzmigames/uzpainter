## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0_owner-decisions, phase0.1_approved-source-index

## 2. Implementation
- [ ] 2.1 Write `parity/CONTRACT.md`: acceptance sentence, three separately reported results, exact-equality rule with no preset tolerances (Q1), tiers 0/1/2a/2b/3 with corpus, compared quantities and gate
- [ ] 2.2 Contract rules for comparison: decoded pixels at native depth, channel class from measured storage format, `oracle_unavailable` never a pass, `not_migratable` keeps its gate blocked without an owner scope decision
- [ ] 2.3 Contract section for Tier 3: comparison against converged Iray references, noise floor, pass only through an owner-approved register entry, never relaxes Tiers 0–2 or covers a structural difference
- [ ] 2.4 Comparison-tool specification in `parity/CONTRACT.md`: diagnostics of `14-parity-testing.md` §4 and `07-preview-and-render-parity.md` §4, FLIP pinned by version and hash as diagnostic only, difference maps and crops private
- [ ] 2.5 Write `parity/schema/golden-public.json` (authored inputs, instruction sequences, applied settings, public-documentation-derived expectations, software identities, SHA-256 of private records)
- [ ] 2.6 Write `parity/schema/golden-private.json` (golden shape inputs → outputs; exported maps, API readbacks, default/template captures, Iray references with settings sheet and operator-recorded settings; two recordings per golden)
- [ ] 2.7 Write `parity/schema/exceptions.json` and an empty `parity/exceptions.json` register (domain, metric, bound, evidence, `uncontrolled` settings, defect-detection test, decision id, version)
- [ ] 2.8 Author the samples under `parity/schema/samples/`: valid public manifests, a synthetic private-shaped record, an exception entry

## 3. Tests
- [ ] 3.1 Schema test: every public sample validates against `golden-public.json` and every private-shaped sample validates against `golden-private.json`
- [ ] 3.2 Separation test: no private-shaped sample (exported map record, JSON readback, default capture, Iray reference) validates against `golden-public.json`
- [ ] 3.3 Register test: the sample exception entry validates; an entry without evidence, defect-detection test or decision id is rejected
- [ ] 3.4 Contract review recorded (reviewer and date in `parity/CONTRACT.md`)

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-CONTRACT): reviewed; schemas validate samples; no recorded output fits the public schema

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
