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

Code: `tools/parity/proc_cert/` (`batch.py`, `fence.py`, `fingerprint.py`, `ledger.py`, `raster.py`, `harness.py`, and the command line in `cli.py`). Tests: `tests/parity/proc_cert/test_proc_cert_harness.py`.

**Threat model.** The fitters and candidates are reviewed code that the project writes. The harness guards against their ordinary mistakes: an accidental read, a reused buffer, an incomplete identity. It does not defend against hostile code. Hostile native code, and Python code written to defeat the fence, are out of scope. No OS-level sandbox is built for them (restricted tokens, AppContainer or similar). See open risk 1.

1. **Separate roots, pinned by hash.**
   - A batch is `batch.json` plus two case lists, each in its own directory under the batch directory. Neither directory is inside the other, and `batch.json` is outside the held-out one. `batch.json` also declares the §6 matrix (point 7).
   - `batch.json` pins each list by the SHA-256 of its bytes. A list whose bytes differ from its pin does not load. The pins are checked again when certification starts.
   - The lists name the oracles and image inputs by hash only. The bytes stay in the private store.
2. **The fence.**
   - `fit` loads the calibration oracles and inputs into read-only arrays. It then calls the fitter with a `CalibrationAccess`, which holds the domain and the calibration set and nothing else.
   - The fitter runs inside a process-wide audit-hook fence. The fence refuses every file-system event on a path under the private store, the held-out root, the reports directory or the ledger (point 3). It also refuses starting a process, `ctypes.dlopen` and clearing the audit hooks.
   - Every call into candidate code runs behind the fence, not only the fitter: the candidate's `fingerprint` at fit and again at certify, every `evaluate`, and the import of a fitter named on the command line.
   - The fence's error is not an `OSError`, so code that treats an `OSError` as "unavailable" cannot swallow it. Every refused event is recorded, so a fitter that catches the error is refused anyway.
   - The candidate's evaluation of every case runs inside the same fence. Oracles are loaded only after the fence comes down.
   - Each evaluated output is copied into an owned, read-only array before the next call into the candidate. A candidate that reuses one buffer for several cases is scored on what it returned for each case.
   - The panel's dissent, an OS-isolated worker, is not built (see the threat model above and open risk 1).
3. **The held-out set is spent.**
   - The durable record is the held-out ledger, `parity/reports/phase3/held-out-ledger.json`. It is committed, holds hashes only, and is written in one canonical form (sorted keys, two-space indent, LF). It maps each held-out pin to the fingerprint of the one candidate the set was revealed to. Deleting a local report, or certifying into another reports directory, does not reset it. Updates take an exclusive lock file and replace the ledger atomically. The repository guard checks the file's schema.
   - The local report file is keyed by `asset@version` and the first 16 hex digits of the held-out pin. It records the candidate's fingerprint.
   - The fingerprint is the SHA-256 of three things: the candidate's declared identity, its class name, and the bytes of every project module in the import closure of the modules that define the class and its bases. The closure is read from the source with `ast`, imports inside functions included, without importing anything. Modules outside the project tree are not hashed.
   - The declared identity must name every piece of fitted state that changes the candidate's outputs. The harness cannot see state that the declaration leaves out. The spend guarantee is therefore only as complete as that declaration.
   - Before any oracle is loaded, `certify` spends the set in the ledger, then creates the report file exclusively as a reservation. A run that stops after that point still leaves the set spent. Of two runs racing for one set, the second is refused.
   - A different candidate against a spent set raises `HeldOutSpent`, whether the ledger or the report records the spend. The same candidate may run again and gets identical bytes. A fingerprint that changes between fit and certify raises `CandidateChanged`. So does one that changes while the candidate evaluates the cases. It is checked again under the evaluation's fence after the last `evaluate`, before the set is spent or any held-out oracle is loaded. State that evaluation changes, such as a scratch cache, must stay out of the declared identity.
4. **Bit-exact outcomes.**
   - Each case is one of:
     - `exact`: every channel of every texel is equal;
     - `residual`: any non-zero |Δ|;
     - `fail`: the output is not the declared dtype and shape (nothing is converted), or the candidate raised;
     - `oracle_unavailable`: the oracle or a pinned input is missing, unreadable or fails its hash, or there is no store.
   - The asset is `exact` only when every case of both sets is exact. Any `residual` or `fail` makes it `fail`. Otherwise it is `oracle_unavailable`.
   - `parity_status` uses §3's vocabulary. `calibrated{max, mean, p99, corpus ids}` is pooled over the cases that were compared, one entry per residual unit (decision 305), and it is a candidate exception for the owner, never a pass. Per-case outcomes, residuals, reasons and per-set counts are always reported with it.
5. **Independence, checked before anything is fitted.**
   - Every case lies inside the declared domain.
   - Case ids are unique across both sets.
   - No held-out oracle blob is any blob a fitter is given: a calibration oracle or a calibration input.
   - No held-out case has the evaluation signature of a calibration case. The signature covers the mesh, every parameter (numbers compared by value, so `1` equals `1.0`), the seed, the output spec, and each input's spec and hash.
   - The held-out set has at least one mesh outside the calibration set.
   - It has at least one seed outside the calibration set, unless the domain lists a single seed.
   - It has, for each ranged parameter, a value strictly inside the range that calibration does not use.
   - Decision 222's "one resolution" is read as adding no further check: every held-out case already has a resolution inside the domain. This is an assumption. A later amendment may require a resolution that calibration does not use.
6. **Reports.**
   - A report holds hashes only: of the batch, the domain, the case lists, the oracle blobs, the candidate's outputs and the candidate.
   - It also holds integer residual statistics from a histogram of per-value distances: code values for integer formats, ULPs for float formats (decision 305). They are max, exact sum, value count, mean, nearest-rank p99, and affected and total texels.
   - It is written as canonical JSON with no timestamp and no path.
   - It states that sampled cases are evidence for the domain, not a proof over it. It certifies no Painter asset.
7. **The §6 matrix, with decision 222's counts.**
   - `batch.json` declares the matrix: 3 meshes × 3 resolutions × parameter sets × 2 seeds.
   - The parameter sets are exactly one `defaults` set, at least one `recipe` set and exactly two `boundary` sets. Each set lies inside the domain, and no two sets have the same values.
   - Each boundary set puts at least one ranged parameter at an end of its range.
   - A domain that lists a single seed needs one matrix seed.
   - Every matrix resolution is one of the domain's output resolutions. The check counts distinct values and does not require the literal {1024, 2048, 4096}, so the tests run at 4, 8 and 16 texels a side. The batch's matrix is pinned by its hash and summarised in the report.
   - The calibration set must hold a case for every cell. A missing cell refuses the batch before anything is fitted.
8. **The command line.** `python -m tools.parity.proc_cert` has four commands:
   - `validate` loads and checks a batch;
   - `fit` fits behind the fence and prints the candidate's fingerprint without spending the set;
   - `certify` fits and certifies, spending the set and writing the report;
   - `report` prints a batch's report and its ledger entry. A stored report is admitted only when its whole identity is the current batch's: asset, version, batch, domain, matrix and both case lists. The committed ledger must also record its held-out set as spent on the report's candidate. Any mismatch, or a report that is only a reservation, is refused (`StaleReport`). It is never shown as certified.

   Output is JSON. The exit code is 0 when done (for `certify`, when the asset is exact), 1 when there is no exact asset or no report, and 2 when refused.

## Alternatives Considered

- **A subprocess or an OS-ACL sandbox for the fitter.** This is the panel's amendment to C1. It was deferred, not rejected. A child process that runs the same fence stops the fitter from seeing the parent's state, but code inside the child can still clear the fence's state. Only OS-level isolation would stop a hostile fitter. This slice guards against accidental reads by fitters written in good faith, which is decision 222's methodological risk.
- **Fencing nothing and relying on the API alone.** Rejected. Nothing would stop a fitter that opens the store directly.
- **A declared fingerprint alone.** Rejected, following the panel. A lookalike class with the same declaration would get the same fingerprint and pass as the same candidate.

## Consequences and open risks

1. Hostile code is out of scope (see the threat model). Native code that is already loaded can reach the files without an audit event. Python code inside the process can clear the fence's state. Such code can also hide fitted state from its declared identity. The fence catches careless reads by reviewed, project-written fitters, not deliberate fraud. Running fitters that are not reviewed would need OS-level isolation, which this harness does not provide.
2. The fingerprint covers project modules reached by `import` statements. It does not cover modules loaded through `importlib.import_module` or `__import__` with a computed name, installed packages, or data files the code reads.
3. The ledger is the durable spend record. A spend is durable only once the ledger change is committed. Deleting the file, or pointing `--ledger` at another file, removes the protection. Such a change shows in the repository's history.
4. Float (EXR) oracles follow decision 305. Real batches under `parity/manifests/phase3/` still wait on Painter recordings. Local reports have no guard rule, so they are not committed under `parity/`.
5. The held-out oracle check compares blob hashes. The same values stored in another encoding (raw against PNG, say) hash differently and are not caught.
