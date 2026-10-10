## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0_owner-decisions, phase0.1_approved-source-index

## 2. Implementation
- [x] 2.1 Write `parity/CONTRACT.md`: acceptance sentence, three separately reported results, exact-equality rule with no preset tolerances (Q1), tiers 0/1/2a/2b/3 with corpus, compared quantities and gate
- [x] 2.2 Contract rules for comparison: decoded pixels at native depth, channel class from measured storage format, `oracle_unavailable` never a pass, `not_migratable` keeps its gate blocked without an owner scope decision
- [x] 2.3 Contract section for Tier 3: comparison against converged Iray references, noise floor, pass only through an owner-approved register entry, never relaxes Tiers 0–2 or covers a structural difference
- [x] 2.4 Comparison-tool specification in `parity/CONTRACT.md`: diagnostics of `14-parity-testing.md` §4 and `07-preview-and-render-parity.md` §4, FLIP pinned by version and hash as diagnostic only, difference maps and crops private
- [x] 2.5 Write `parity/schema/golden-public.json` (authored inputs, instruction sequences, applied settings, public-documentation-derived expectations, software identities, SHA-256 of private records)
- [x] 2.6 Write `parity/schema/golden-private.json` (golden shape inputs → outputs; exported maps, API readbacks, default/template captures, Iray references with settings sheet and operator-recorded settings; two recordings per golden)
- [x] 2.7 Write `parity/schema/exceptions.json` and an empty `parity/exceptions.json` register (domain, metric, bound, evidence, `uncontrolled` settings, defect-detection test, decision id, version)
- [x] 2.8 Author the samples under `parity/schema/samples/`: valid public manifests, a synthetic private-shaped record, an exception entry

## 3. Tests
- [x] 3.1 Schema test: every public sample validates against `golden-public.json` and every private-shaped sample validates against `golden-private.json`
- [x] 3.2 Separation test: no private-shaped sample (exported map record, JSON readback, default capture, Iray reference) validates against `golden-public.json`
- [x] 3.3 Register test: the sample exception entry validates; an entry without evidence, defect-detection test or decision id is rejected
- [x] 3.4 Contract review recorded (reviewer and date in `parity/CONTRACT.md`)

## 4. Acceptance
- [x] 4.1 Acceptance gate (P0-CONTRACT): reviewed; schemas validate samples; no recorded output fits the public schema

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Run notes (2026-10-10)
- Gate: `python -m mypy tools` and `python -m mypy` clean; `python -m ruff check .` clean; `python -m ruff format --check .` clean; `python -m pytest -q --deselect tests/vendoring/test_vendored_core.py::test_byte_equality` 205 passed (tests/parity: 92 passed).
- Deselected `tests/vendoring/test_vendored_core.py::test_byte_equality` on the coordinator's instruction: `phase0.3_vendor-modifications` is editing vendored files in parallel and updates their manifest at the end of that task; the committed tree is green. No vendoring file was touched by this task.
- Review: two passes by a review subagent (Claude Fable 5.1); every finding fixed; recorded in `parity/CONTRACT.md` §9.
