## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [ ] 2.1 Author the unit sphere and bevelled cube fixtures with their mesh maps and the public manifest `parity/manifests/phase0/procedural-feasibility.json`
- [ ] 2.2 Select the two mesh-map generators from the `05-procedural-content.md` §3 family list and the evaluated subset of the §6 matrix; record both choices in the report
- [ ] 2.3 Discover the parameter names, ranges and labels of the selected assets through the documented `Property`/`SourceSubstance` API (private readback)
- [ ] 2.4 Record the private oracles (both generators and Leather Damaged on both fixtures) through the recorder, twice each, and admit them to the store
- [ ] 2.5 Write the feasibility prototypes of the two generators from the public sources of 05 §3, with a provenance note per formula
- [ ] 2.6 Write the Leather Damaged feasibility prototype from the families it needs; the observed preset structure stays private
- [ ] 2.7 Fit prototype parameters black-box to the oracles; record fits, public sources and residuals in `parity/semantics/procedural-feasibility.json`
- [ ] 2.8 Write `parity/reports/phase0/procedural-feasibility.md`: per case max/mean/p99 |Δ| and affected-texel counts, oracle stability, and a go/no-go per family for P3-PROC

## 3. Tests
- [ ] 3.1 Comparison run on the owner's machine: each prototype output compared with both oracle recordings at native depth; numbers in the report match the comparison output
- [ ] 3.2 Guard run: no oracle output, readback or observed preset structure is in the repository

## 4. Acceptance
- [ ] 4.1 Acceptance gate (P0-FEAS-PROC): residuals published; go/no-go for Phase 3 scope

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
