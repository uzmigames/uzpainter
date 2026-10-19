# 303. The procedural certification harness: calibration and held-out sets pinned in separate roots, a fence that refuses fitters any access to held-out data, bit-exact cases, and a held-out set spent on the first candidate it is revealed to

**Status**: accepted
**Date**: 2026-10-19
**Related Tasks**: phase3.1_proc-backend-seam

## Context

Decision 222 requires a held-out set that is reserved before calibration and never used for fitting. A held-out case that was looked at to change a fit is spent. An asset is `exact` only when both sets are exact. Item 2.7 of `phase3.1_proc-backend-seam` needs a harness that enforces those rules.

The Codex supervisor's SUP-014 allows this work early as a permitted slice, while Painter is busy. The slice runs on CPU only and is built and tested on synthetic families with authored formulas. It does not accept the task, and it certifies no Painter asset.

Building it raised six design forks. The model panel ran one round on them; its log is `E:/tmp/uzp-scratch/proc-harness/panel.log`.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1. An in-process audit-hook fence (PEP 578) is enough isolation at this stage | DISAGREE (monitoring, not isolation; wants OS-isolated workers) | AGREE (acceptable now; weaker than a subprocess) | PARTLY (keep the hooks as an extra layer; wants a subprocess) |
| C2. Pin each case list by SHA-256, in separate directories | AGREE | AGREE | AGREE |
| C3. Key the report by the held-out pin and spend the set on the first candidate's fingerprint | PARTLY (bind the fingerprint to the code; reserve the set before the reveal) | PARTLY (a declared identity binds weakly) | AGREE |
| C4. The four case outcomes, no conversion of the output, and residual or fail beating unavailable | PARTLY (pooled statistics must not hide per-case outcomes) | PARTLY (say how `calibrated` relates to `fail`) | AGREE |
| C5. The independence checks | DISAGREE (a fresh seed is not always possible; check the resolution) | PARTLY (canonical number form in the signature) | PARTLY (the signature must cover the whole evaluation key) |
| C6. Reports hold hashes and integer statistics only, in canonical JSON | PARTLY (keep case outcomes and reasons) | AGREE | AGREE |

## Decision

Code: `tools/parity/proc_cert/` (`batch.py`, `fence.py`, `raster.py`, `harness.py`). Tests: `tests/parity/proc_cert/test_proc_cert_harness.py`.

1. **Separate roots, pinned by hash.**
   - A batch is `batch.json` plus two case lists, each in its own directory under the batch directory. Neither directory is inside the other, and `batch.json` is outside the held-out one.
   - `batch.json` pins each list by the SHA-256 of its bytes. A list whose bytes differ from its pin does not load. The pins are checked again when certification starts.
   - The lists name the oracles and image inputs by hash only. The bytes stay in the private store.
2. **The fence.**
   - `fit` loads the calibration oracles and inputs into read-only arrays. It then calls the fitter with a `CalibrationAccess`, which holds the domain and the calibration set and nothing else.
   - The fitter runs inside a process-wide audit-hook fence. The fence refuses every file-system event on a path under the private store, the held-out root or the reports directory. It also refuses starting a process, `ctypes.dlopen` and clearing the audit hooks.
   - The fence's error is not an `OSError`, so code that treats an `OSError` as "unavailable" cannot swallow it. Every refused event is recorded, so a fitter that catches the error is refused anyway.
   - The candidate's evaluation of every case runs inside the same fence. Oracles are loaded only after the fence comes down.
   - The panel's dissent, an OS-isolated worker, is open risk 1 below and is not built in this slice.
3. **The held-out set is spent.**
   - The report file is keyed by `asset@version` and the first 16 hex digits of the held-out pin. It records the candidate's fingerprint.
   - The fingerprint is the SHA-256 of three things: the candidate's declared identity, its class name, and the bytes of the source file that defines the class.
   - Before any oracle is loaded, `certify` creates the report file exclusively, as a reservation. A run that stops after that point still leaves the set spent. Of two runs racing for one set, the second is refused.
   - A different candidate against a spent set raises `HeldOutSpent`. The same candidate may run again and gets identical bytes. A fingerprint that changes between fit and certify raises `CandidateChanged`.
4. **Bit-exact outcomes.**
   - Each case is one of:
     - `exact`: every channel of every texel is equal;
     - `residual`: any non-zero |Δ|;
     - `fail`: the output is not the declared unsigned dtype and shape (nothing is converted), or the candidate raised;
     - `oracle_unavailable`: the oracle or a pinned input is missing, unreadable or fails its hash, or there is no store.
   - The asset is `exact` only when every case of both sets is exact. Any `residual` or `fail` makes it `fail`. Otherwise it is `oracle_unavailable`.
   - `parity_status` uses §3's vocabulary. `calibrated{max, mean, p99, corpus ids}` is pooled over the cases that were compared, and it is a candidate exception for the owner, never a pass. Per-case outcomes, residuals, reasons and per-set counts are always reported with it.
5. **Independence, checked before anything is fitted.**
   - Every case lies inside the declared domain.
   - Case ids are unique across both sets.
   - No held-out oracle blob is also a calibration blob.
   - No held-out case has the evaluation signature of a calibration case. The signature covers the mesh, every parameter (numbers compared by value, so `1` equals `1.0`), the seed, the output spec, and each input's spec and hash.
   - The held-out set has at least one mesh outside the calibration set.
   - It has at least one seed outside the calibration set, unless the domain lists a single seed.
   - It has, for each ranged parameter, a value strictly inside the range that calibration does not use.
   - Decision 222's "one resolution" is read as adding no further check: every held-out case already has a resolution inside the domain. This is an assumption. A later amendment may require a resolution that calibration does not use.
6. **Reports.**
   - A report holds hashes only: of the batch, the domain, the case lists, the oracle blobs, the candidate's outputs and the candidate.
   - It also holds integer residual statistics from a histogram of |Δ|: max, exact sum, value count, mean, nearest-rank p99, and affected and total texels.
   - It is written as canonical JSON with no timestamp and no path.
   - It states that sampled cases are evidence for the domain, not a proof over it. It certifies no Painter asset.

## Alternatives Considered

- **A subprocess or an OS-ACL sandbox for the fitter.** This is the panel's amendment to C1. It was deferred, not rejected. A child process that runs the same fence stops the fitter from seeing the parent's state, but code inside the child can still clear the fence's state. Only OS-level isolation would stop a hostile fitter. This slice guards against accidental reads by fitters written in good faith, which is decision 222's methodological risk.
- **Fencing nothing and relying on the API alone.** Rejected. Nothing would stop a fitter that opens the store directly.
- **A declared fingerprint alone.** Rejected, following the panel. A lookalike class with the same declaration would get the same fingerprint and pass as the same candidate.

## Consequences and open risks

1. Native code that is already loaded can reach the files without an audit event. Python code inside the process can also clear the fence's state. The fence detects careless reads, not deliberate fraud. Before Phase 3 families use it with agent-written fitters, an OS-isolated worker should be considered.
2. The fingerprint binds only the source file of the candidate's class, not the modules that file imports.
3. The spend record is the report file. Deleting it, or certifying against another reports directory, removes the protection. Committing reports under `parity/reports/phase3/` is what makes the record durable.
4. Raster formats are `u8` and `u16` (raw little-endian or PNG). Float (EXR) oracles and the §6 matrix check (3 meshes × 3 resolutions × parameter sets × seeds) are not built yet. Both stay open in item 2.7.
