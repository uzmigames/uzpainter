## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [x] 2.1 Author the unit sphere and bevelled cube fixtures with their mesh maps and the public manifest `parity/manifests/phase0/procedural-feasibility.json`
- [x] 2.2 Select the two mesh-map generators from the `05-procedural-content.md` §3 family list and the evaluated subset of the §6 matrix; record both choices in the report
- [x] 2.3 Discover the parameter names, ranges and labels of the selected assets through the documented `Property`/`SourceSubstance` API (private readback)
- [x] 2.4 Record the private oracles (both generators and Leather Damaged on both fixtures) through the recorder, twice each, and admit them to the store
- [x] 2.5 Write the feasibility prototypes of the two generators from the public sources of 05 §3, with a provenance note per formula
- [x] 2.6 Write the Leather Damaged feasibility prototype from the families it needs; the observed preset structure stays private
- [x] 2.7 Fit prototype parameters black-box to the oracles; record fits, public sources and residuals in `parity/semantics/procedural-feasibility.json`
- [x] 2.8 Write `parity/reports/phase0/procedural-feasibility.md`: per case max/mean/p99 |Δ| and affected-texel counts, oracle stability, and a go/no-go per family for P3-PROC

## 3. Tests
- [x] 3.1 Comparison run on the owner's machine: each prototype output compared with both oracle recordings at native depth; numbers in the report match the comparison output
- [x] 3.2 Guard run: no oracle output, readback or observed preset structure is in the repository

## 4. Acceptance
- [x] 4.1 Acceptance gate (P0-FEAS-PROC): residuals published; go/no-go for Phase 3 scope

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-10, owner's machine)
- Painter 12.1.0 (`12.1.0+js-api.1.1.20`) under the Assets3D Painter lock, one session: 16 goldens (Position 6, Metal Edge Wear 8, Leather Damaged 2) recorded twice each (same session; after save/reopen) with `python -m tools.parity.recorder record`, admitted with `python -m tools.parity.store record --run`; `python -m tools.parity.store verify parity/manifests/phase0/procedural-feasibility` all available.
- Oracle stability over the comparison domain (UV-covered texels eroded by one): max |Δ| 0 for every golden and map (r1/r2 differ only in `passthrough` padding texels).
- `python -m tools.parity.feasibility run` wrote `parity/semantics/procedural-feasibility.json` and `parity/reports/phase0/procedural-feasibility.md`; `python -m tools.parity.feasibility check` reproduces every published number (also `tests/parity/feasibility/test_publication.py`, local).
- Verdicts: Position go (6/6 equal); Metal Edge Wear no-go (1/8 equal); Leather Damaged no-go (0/2 equal; metalness and normal equal, base colour/roughness/height not).
- Gate: `python -m mypy` (107 files) clean, `python -m ruff check .` clean, `python -m pytest` 624 passed; `python -m tools.parity.guard` 1485 files, 0 blocked (store-hash rule against the local store).
