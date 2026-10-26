# UzPainter private oracle store

Work package P0-STORE (`docs/dag.md`), task `phase0.3_oracle-store-cli`. Implements `parity/CONTRACT.md` §3 (`oracle_unavailable`) and §6.4, and `docs/architecture/14-parity-testing.md` §6–§7, under decisions 002 (clean room), 022 (platform), 028 (no GPU CI; oracle checks run locally on the owner's machine) and 200 (the hosted parity CI was removed; the local full gate replaces it, §5). Code: `tools/parity/store/`; tests: `tests/parity/test_store.py`.

## 1. Rules

- Every recorded Painter output lives only in the store, on the owner's machine. The store is never uploaded to a hosted service and never shipped; backups are the owner's private copies.
- The store root, a fetch destination and an inbox are always **outside the repository**; the tools refuse a path inside it.
- Records are **write-once** per Painter build. A new Painter build gets its own corpus directory; old corpora are kept.
- A blob that is missing, unreadable, of the wrong size or failing its SHA-256 is **`oracle_unavailable`**, never a pass and never compared.

## 2. Location and layout

Root: `UZP_PARITY_STORE` when set, else `%LOCALAPPDATA%\UzPainter\parity-store`. A folder without `store.json` is not a store: a machine without one has no oracle.

| Path under the root | Content |
|---|---|
| `store.json` | Layout marker `{"schema": "uzpainter/parity/store/1", "hash": "sha256"}` |
| `index.json` | `{"schema": "uzpainter/parity/store-index/1", "sha256": [...]}`: the sorted SHA-256 of every stored blob. The repository guard (`phase0.4_oracle-store-guard`, `parity/GUARD.md`) matches files against it; it is the only part of the store a hosted job may ever receive |
| `blobs/<aa>/<sha256>` | The bytes, named by their SHA-256 (`<aa>` = its first two hex digits), read-only |
| `corpora/<Painter build id>/<golden id>/<record id>.json` | Write-once entry `{"schema": "uzpainter/parity/store-entry/1", painter_build_id, golden_id, record_id, kind, sha256, size_bytes, file_name}`, read-only |
| `inputs/<sha256>.json` | Write-once entry `{"schema": "uzpainter/parity/store-input/1", sha256, size_bytes, path}` of an authored input a public manifest pins by hash (its bytes in `blobs/`), read-only. A pipeline-script job resolves an input here when its file at the pinned path is gone or changed (decision 144) |
| `snapshot-captures/<capture_id>/<policy_sha256>.json` | Complete immutable `uzpainter/parity/snapshot-capture-admission/1` document, published last after fresh native validation and verified blob storage |
| `snapshot-producer-policies/<sha256>.json` | Exact pinned public producer policy bytes retained for offline admission resolution; not an observed-output blob and not added to the private blob index |
| `.staging-<id>.partial` | Preserved incomplete or competing publication files in the store root; never admission authority |
| `.index.lock` | Persistent OS lock file serializing every blob-index update; process exit releases the lock without deleting the file |

The Painter build id is the manifest's `software.painter.build_id` and must match `^[A-Za-z0-9][A-Za-z0-9._+-]*$` to name a directory. A record id is unique per (Painter build, golden).

## 3. Commands

Phase 0 prototype of `uzpainter parity`: run `python -m tools.parity.store [--store PATH] <command>` from the repository root. Exit status 0 when every blob resolves, 1 when any is `oracle_unavailable` or an operation is refused, 2 on usage errors.

| Command | Does |
|---|---|
| `init` | Creates the layout at the store root (owner's machine, once; idempotent; refuses a non-empty folder that is not a store) |
| `record <manifest> --record-id ID --kind KIND --file FILE` | Owner's machine only. Stores one recorded file and appends `{record_id, kind, sha256, size_bytes}` to the manifest's `private_records` (`golden-public.json`). A `private_oracle_record` file must pass `record_problems` and belong to the manifest's golden and Painter build |
| `record <manifest> --run DIR` | Owner's machine only. Ingests one recorder run from the oracle inbox (§4); creates the manifest from the run's, or merges its `private_records` into the existing one |
| `input FILE --path PATH` | Owner's machine only. Stores an authored input under its SHA-256, with an entry naming the path a manifest pins it at (`PATH`, e.g. its `assets3d_path`) |
| `fetch <manifest> --out DIR` | Copies every blob the manifest names to `DIR/<record id><suffix>` and re-hashes the copy |
| `verify [PATH ...]` | Re-hashes in the store every blob the given manifests (or every `*.json` under a directory) name. Without a path: whole-store integrity (index, blobs and entries agree; every blob hashes to its name) |
| `admit-snapshot-capture WORK --producer-policy FILE --approved-policy-sha256 SHA --approved-policy-revision N --validator-binary ABSOLUTE_EXE --approved-binary-sha256 SHA --approved-code-sha256 SHA` | Fresh invocation of the coordinator-approved native diagnostic, then private immutable snapshot admission. Approval pins are trusted coordinator inputs, never inferred from the capture or a submitted report |

Refusals, all checked before anything is written: a different blob under an existing record id (in the manifest or in the store), an invalid manifest or private record, a path inside the repository, a run without `READY`.

Comparisons obtain oracle bytes with `tools.parity.store.store.load_oracle(locate(), ref)`; it returns `None` for an unavailable oracle, and `tools.parity.verdict.evaluate` turns a comparison whose oracle is `None` into `oracle_unavailable`.

### 3.1 Snapshot admission

Generic `record`, recorder-run merging and `add_record` reserve every `snapshot_*` kind before
storing bytes. These kinds are not added to the public manifest enum. The dedicated command
always invokes `validate_snapshot_capture`, including retries; it never accepts a caller report,
cached success flag or a bare blob as evidence of admission.

The six role/round slots retain their identities even when exports share a hash. The native
report pins the exact opened receipt, request and export bytes. Admission copies and hashes
those bytes again; a changed source refuses. Publication uses no-overwrite Windows rename or
POSIX hard links, with complete admission written last. Failed and competing staging files are
preserved, and orphan blobs confer no membership. POSIX successful hard-link publication also
retains its staging link. Unsupported no-overwrite publication fails closed. No automatic
cleanup deletes private evidence.

`resolve_snapshot_capture` requires explicitly approved policy SHA and revision, validates the
closed document and its path identity, checks its retained policy and producer pair, and
re-hashes every member blob with its size. `resolve_snapshot_artifact` additionally requires an
exact role/round/hash/size member. Missing or corrupt admission, policy or any member yields
`oracle_unavailable`; generic blob availability cannot substitute for membership. Whole-store
`verify` includes this namespace and retained policy integrity, but does not authorize policies
merely because they exist on disk.

An existing `(capture_id, policy_sha256)` must still resolve and match freshly validated artifact
roles, policy, signature, context and raster. A matching retry returns the original timestamp
and validator identity; revalidation never rewrites prior provenance. A different approved
validator may confirm the same semantics without replacing that original identity. Conflicts
and corrupt winners refuse. Owner-local submission remains the provenance basis, with no
historical execution attestation.

## 4. Recorder hand-off (oracle inbox)

The Painter recorder (`phase0.3_painter-oracle-recorder`) writes each recording run outside the repository to `<inbox>/<golden id with / as __>/<run stamp>/` (inbox: `UZP_ORACLE_INBOX`, else `%LOCALAPPDATA%\UzPainter\oracle-inbox`):

- `record.json`: the private record (`golden-private.json`);
- `blobs/<sha256>`: every blob the record names, named by its SHA-256;
- `manifest.json`: the public manifest with `private_records` filled (the record as `private_oracle_record`, every blob with its output kind);
- `READY`: an empty marker written last.

`record --run` requires `READY`, matches every `private_records` entry to a file of the run by SHA-256 and size, checks that each blob file is named by its hash and that the manifest names every blob the record names, then stores everything. Fetched blobs take their extension from the record's `media_type`. The run is never deleted by the store.

## 5. Local full gate and the local oracle run

Decision 028: there is no GPU CI on GitHub and no self-hosted runner. Decision 200: the owner removed the hosted parity CI as well; only codespell still runs on GitHub. Every check runs locally (`14-parity-testing.md` §7):

| Where | Runs on | Does |
|---|---|---|
| Local full gate | The coordinator's run before the owner pushes | Type-check, lint, full test suite (GPU and oracle tests skip with an explicit reason where the GPU or store is missing), the guard (`python -m tools.parity.guard`), the vendoring check (`python -m tools.vendoring.vendor_check`) and the selftest (`zig build painter` with `UzPainter.exe selftest`); `python -m tools.parity.store verify parity/schema/samples/public` on a machine without the store exits 1 and reports `oracle_unavailable` |
| Local oracle run | The owner's machine only, started by hand (§5.1) | Whole-store integrity, then `verify parity/manifests`. Later comparisons against recorded Painter values run the same way, locally, and nowhere else |

The local run report is the gate evidence for every check that needs the store or Painter.

### 5.1 Local oracle run procedure (owner's machine)

1. Prerequisites on the machine: the GPU with DXR Tier 1.1 and Vulkan ray query, licensed Adobe Substance 3D Painter at the current envelope's build (`parity/CONTRACT.md` §6.5, decision 037), Python 3.13 with `jsonschema` on `PATH`, and the store: `python -m tools.parity.store --store <root> init` with `<root>` outside the repository (once). Set `UZP_PARITY_STORE=<root>`, or leave it unset when the store is at the default `%LOCALAPPDATA%\UzPainter\parity-store`.
2. From the repository root, on a clean checkout of the commit under test: `python -m tools.parity.store verify` (whole-store integrity), then `python -m tools.parity.store verify parity/manifests` when that folder exists. Both must exit 0.
3. Write the run report: the commands, machine name, GPU and driver version, build hash (the commit), Painter build, and each command's exit status and output. It holds statuses and hashes only, never a recorded output, and is recorded as the evidence of the task that needs it.

The first run (P0-STORE acceptance, 2026-10-10) initialised the store at the default location, made the record → delete → fetch → verify round trip with authored stand-ins under the Painter build id `local-run-authored` (golden `local-run/store-gate`), and ran the committed pre-commit hook against that store in a throwaway repository; its report is the Evidence section of `.rulebook/archive/*-phase0.5_private-oracle-store/tasks.md`.

## 6. Tests

`tests/parity/test_store.py` (every test uses a temporary store): round trip record → delete the local copy → fetch → hash (single file and recorder run), missing/unreadable/mismatched blob → `oracle_unavailable` (CLI, API and verdict), write-once refusal and idempotent re-record, per-build corpora, store and fetch paths inside the repository refused, a machine without a store (subprocess without `UZP_PARITY_STORE`).

`tests/parity/test_store_integration.py` is the P0-STORE gate on one commit: with one temporary store it makes the round trip of an authored sample, checks that a machine without the store gets `oracle_unavailable` for the same manifest, records stand-ins for a recorded PNG and a JSON readback with `record`, and in a throwaway repository the committed pre-commit hook accepts the authored fixture image and expectation JSON and rejects both stand-ins by their store hash.
