# P1-DOCMODEL gate — `phase1.3_document-model`

Task `phase1.3_document-model`, the parent and acceptance task of P1-DOCMODEL (`docs/dag.md`: "Round-trip tests; digest stable"). Children, all archived on 2026-10-10: `phase1.1_docmodel-types-manifest`, `phase1.2_docmodel-transactions`, `phase1.2_docmodel-capability-manifest`; prerequisite `phase0.2_parity-contract` archived. Decision 028: the digest must be the same on the hosted CPU lane and in a local run on the owner's machine. This report is the evidence for the G1 gate record.

**Result: P1-DOCMODEL gate met. Round-trip tests green and digests identical across processes, builds and two machines (the owner's machine and the hosted CPU lane, Parity run `38088050428` on `1e90914`).**

## Integration added by this task

| Item | Change |
|---|---|
| 2.4 library | `zig build uzp-core` builds `zig-out/lib/uzp_core.lib` from `src/uzp_core/` alone (only `src/` on the include path, libc and libc++, no render core, render layer, system library or GPU API), `-Wall -Wextra -Werror`. `uzp-core-tests.exe` and `uzp-core-transaction-tests.exe` now link this library instead of compiling the sources themselves. `test_uzp_core_includes_no_render_or_gpu_header` checks that every `#include` of `src/uzp_core/` is a `uzp_core/` header or a C++ standard header. The capability manifest generator stays the `zig build capabilities` step. |
| 3.1 integrated round trip | Native case `integrated_round_trip` (`tests/uzp_core/transaction_test.cpp`): a document built only through committed transactions (resource import; fill layer with uniform and bitmap sources and blending; composite attach of a group with a child; levels and anchor content effects; a mask with fill and compare-mask effects; a native multi-call `Transaction` adding a paint layer, an instance layer and hiding the paint layer; a named insert, its repeat (a no-op) and a second same-named layer; metadata), checkpoint marked. Serialised, reloaded: equal `Project`, equal bytes, equal digest (`ManifestDigest` = SHA-256 of the bytes); a second document built the same way gives the same bytes; reopened with its revision, checkpoints and operation records, a retry of a committed key returns the stored outcome without executing and the next new id is `next_id`. |
| 3.2 digest stability | `uzp-core-transaction-tests integrated-manifest` prints that manifest. `test_integrated_manifest_digest_stable` runs it in two processes (equal bytes), checks Python's reload and `canonical_json` re-serialisation give the same bytes, validates against `manifest.schema.json` and asserts the pinned digest below. The every-kind fixture of `phase1.1` keeps its pinned digest (`test_digest_identical_across_processes_and_languages`). Both pinned values are asserted by `python -m pytest` on the hosted lane and locally. |

## Owner's machine run (2026-10-10)

| Item | Value |
|---|---|
| Machine | Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090 (no GPU used by these tests) |
| Toolchain | Zig 0.15.2 (Debug), Python 3.13.9 |
| Tree | commit `a6f9cfa` plus the working-tree changes of this task |
| Build | `zig build painter uzp-core uzp-core-tests uzp-core-transaction-tests capabilities`: exit 0, no warnings |

| Fixture document | Digest (SHA-256 of the canonical manifest) | Processes |
|---|---|---|
| `tests/uzp_core/fixtures/every-kind.manifest.json` (every node, effect and source kind) | `dc572509c528d6e520230df4d226099fd7711267cd9f53480594d954b21f1db3` | 2 native processes and Python: identical, equal to the pinned value |
| Document built through transactions (`integrated-manifest`) | `c2f28a5f8c7296319b31e5d9286acb85257aac5022d091aed9fdc7fcb803e0c2` | 2 native processes, two separate builds (scratch prefix and `zig-out`) and Python: identical, equal to the pinned value |

Tests: `python -m pytest tests/uzp_core tests/capabilities`: 70 passed, also with `UZP_NO_GPU=1` (the hosted-lane setting). Native: `uzp-core-tests.exe run` 11 cases, `uzp-core-transaction-tests.exe run` 11 cases, all PASS. Full gate: `python -m mypy` (161 files, no issues), `ruff check .`, `ruff format --check .`, `python -m pytest` (945 passed), `python -m tools.parity.guard` (0 blocked).

## Hosted CPU lane

The hosted lane (`.github/workflows/parity.yml`, `UZP_NO_GPU=1`, step "Tests") runs the same two pinned-digest tests on a GitHub-hosted `windows-latest` runner without a GPU.

| Item | Value |
|---|---|
| Run | Parity run `38088050428` (https://github.com/uzmigames/uzpainter/actions/runs/38088050428), job "Hosted CPU lane (no GPU, no oracle store)" `114318601978`, 31m28s, conclusion `success` |
| Commit | `1e90914`, which contains this task (`tests/uzp_core/test_transactions.py` pins `INTEGRATED_DIGEST = c2f28a5f…e0c2`) |
| Tests step | 884 passed, 72 skipped; `tests/uzp_core/test_document_model.py` 28 passed, `test_transactions.py` 18 passed, `test_channel_types.py` 2 passed, none skipped |

Both pinned digests (`dc572509…1db3` and `c2f28a5f…e0c2`) held on the hosted lane as on the owner's machine: item 3.2 is met.

## Reproduce

```
zig build uzp-core uzp-core-tests uzp-core-transaction-tests
python -m pytest tests/uzp_core tests/capabilities
zig-out\bin\uzp-core-transaction-tests.exe integrated-manifest
zig-out\bin\uzp-core-tests.exe digest tests\uzp_core\fixtures\every-kind.manifest.json
```
