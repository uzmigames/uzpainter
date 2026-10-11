## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store, phase0.8_tier0-goldens

## 2. Environment record
- [ ] 2.1 Define the environment record (Painter build string, GPU model, driver version, OS build, colour-configuration hash, recorder version; Iray: operator id) in the private-record and public-manifest schemas under `parity/schema/`, with validators and tests
- [ ] 2.2 The recorder captures the record at session start through documented sources only (Painter's documented API for the build and colour configuration; the OS and driver from the host) and writes it into every run
- [ ] 2.3 Back-fill existing goldens with the record of the environment they were recorded under where known, `unknown` per field otherwise; never rewrite a golden's outputs
- [ ] 2.4 Comparison rule in `tools/parity/verdict.py`: UzPainter-to-golden comparisons ignore the live environment; oracle re-recording and oracle-to-golden comparisons with a different envelope end in `out_of_envelope`, never `pass` or `fail`

## 3. Stability study
- [ ] 3.1 Recorder job that records every Tier 0 golden 5 times: 2 in the same session, 2 after save/reopen, 1 in a freshly started Painter process
- [ ] 3.2 Analysis: per-golden self-variance (max, mean, p99, differing values, per recording pair), with fresh-process instability classified apart from save/reopen instability (decision 032)
- [ ] 3.3 For fresh-process-unstable goldens: r1 stays the exact target; prepare their register entries with the evidence, left unapproved until the owner approves them (decision 017)
- [ ] 3.4 Run the study on the owner's machine and admit the runs to the private store

## 4. Canary
- [ ] 4.1 Fix the 10-golden canary subset (covering blends, quantisation, sRGB store, height-to-normal, resampling, a bake and an API readback) and its re-record-and-diff procedure
- [ ] 4.2 Any non-zero difference re-records the affected goldens under a new envelope, keeping the originals, their r1 targets and their 032 records; tested with a synthetic envelope change

## 5. Acceptance
- [ ] 5.1 Report `parity/reports/phase0/oracle-envelope.md` (numbers and hashes only); `parity/CONTRACT.md` §6 states the envelope and the `out_of_envelope` outcome
- [ ] 5.2 Acceptance (P0-ORACLE-ENVELOPE): envelope on every admitted golden; study published before any further calibration of `calibrated` fits; canary procedure tested

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
