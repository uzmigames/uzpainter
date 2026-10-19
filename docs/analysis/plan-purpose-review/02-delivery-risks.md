# 02. Delivery risks

## F-003 - Procedural certification does not explicitly separate fitting from generalisation

**Evidence:** `docs/architecture/05-procedural-content.md:52` specifies three meshes, three resolutions, a few parameter sets and two seeds. `.rulebook/tasks/phase3.2_proc-generator-families/tasks.md:9` calibrates the generators and `:13` tests that matrix; neither explicitly reserves independent holdouts or bounds the editable parameter domain exposed at architecture `:56`. Frozen snapshots already enforce exact signatures and prohibit extrapolation (`:40`).

**Impact:** High for editable replacement. A fit can match its calibration fixtures yet fail on new geometry, parameters or seeds. Specify a separate holdout protocol and the supported editable domain; distinguish exact migration snapshots from editable procedural claims. Keep unsupported domains refused, and route any permitted divergence through owner-approved exceptions.

**Confidence:** High that the reviewed plan lacks an explicit split; medium on the eventual numerical effect, which this review did not test.

## F-004 - Full technical feasibility remains research, visibly disclosed

**Evidence:** `parity/reports/phase0/procedural-feasibility.md:12`-`:15` marks Metal Edge Wear no-go (1/8 cases equal) and Leather Damaged no-go (0/2). `parity/reports/phase0/iray-noise-floor.md:5` says no fitted lobe is reproduced on held-out pixels; `:331` says the current references do not identify multi-bounce transport. OCIO working-value admission is a finite table of 256 codes plus 193 recorded components, with unrecorded values refused (`.rulebook/tasks/phase1.15_compositor-colour-fits/tasks.md:34`; `:36`).

**Impact:** High. These results justify targeted research, not a guarantee that arbitrary required states can be reproduced. Iray already has holdouts and honest safeguards; their existence is a strength, not a missing-validation defect. Treat unresolved families as explicit feasibility checkpoints before committing downstream capacity.

**Confidence:** High for the stated limits; future success or impossibility cannot be inferred from them.

## F-005 - Pilot acceptance needs original inputs and timely owner decisions

**Evidence:** Belt has no known copy of its approved inputs (`.rulebook/tasks/phase2.9_pilot-belt/tasks.md:28`). Tunic has stable recorded goldens, but its rebuild requires nine missing original masks (`.rulebook/tasks/phase2.10_pilot-tunic-recovery/tasks.md:34`; `:46`); padding and double-sided state are separate blockers (`:35`; `:36`). `docs/roadmap.md:30` allows replacement/exclusion only through an explicit owner scope decision, without a mandatory decision checkpoint.

**Impact:** High for G2 and cutover. More infrastructure cannot substitute for missing approved bytes. Preserve available inputs by hash and make recovery versus a new owner-approved fixture a scheduled decision at the next pilot checkpoint; a regenerated mask is a new reference, not the original v10.

**Confidence:** High for documented blockers; no claim that recovery outside the recorded search is impossible.

## F-006 - Duration and distribution remain conditional delivery assumptions

**Evidence:** `docs/roadmap.md:16`, `:20` and `:29` label durations as hypotheses and require reforecasting after Wand. Clean offline distribution is required (`docs/prd.md:25`) but its decisive check is in Phase 5 (`docs/roadmap.md:18`).

**Impact:** Medium to high. The 30-39-week total is not a measured forecast or guarantee. Reforecast from completed vertical slices and unresolved research; consider an early packaging smoke milestone to expose dependency/redistribution problems without claiming release qualification.

**Confidence:** High on the plan text; medium on schedule and packaging risk magnitude. No packaging defect was observed here.
