# UzPainter private oracle store

Work package P0-STORE (`docs/dag.md`), task `phase0.3_oracle-store-cli`. Implements `parity/CONTRACT.md` §3 (`oracle_unavailable`) and §6.4, and `docs/architecture/14-parity-testing.md` §6–§7, under decisions 002 (clean room), 022 (platform) and 028 (hosted CPU-only CI; oracle checks run locally on the owner's machine). Code: `tools/parity/store/`; tests: `tests/parity/test_store.py`; hosted CI: `.github/workflows/parity.yml`.

## 1. Rules

- Every recorded Painter output lives only in the store, on the owner's machine. The store is never uploaded to a hosted service and never shipped; backups are the owner's private copies.
- The store root, a fetch destination and an inbox are always **outside the repository**; the tools refuse a path inside it.
- Records are **write-once** per Painter build. A new Painter build gets its own corpus directory; old corpora are kept.
- A blob that is missing, unreadable, of the wrong size or failing its SHA-256 is **`oracle_unavailable`**, never a pass and never compared.

## 2. Location and layout

Root: `UZP_PARITY_STORE` when set, else `%LOCALAPPDATA%\UzPainter\parity-store`. A folder without `store.json` is not a store: a machine without one (every hosted CI machine) has no oracle.

| Path under the root | Content |
|---|---|
| `store.json` | Layout marker `{"schema": "uzpainter/parity/store/1", "hash": "sha256"}` |
| `index.json` | `{"schema": "uzpainter/parity/store-index/1", "sha256": [...]}`: the sorted SHA-256 of every stored blob. The repository guard (`phase0.4_oracle-store-guard`) matches files against it; it is the only part of the store a hosted job may ever receive |
| `blobs/<aa>/<sha256>` | The bytes, named by their SHA-256 (`<aa>` = its first two hex digits), read-only |
| `corpora/<Painter build id>/<golden id>/<record id>.json` | Write-once entry `{"schema": "uzpainter/parity/store-entry/1", painter_build_id, golden_id, record_id, kind, sha256, size_bytes, file_name}`, read-only |

The Painter build id is the manifest's `software.painter.build_id` and must match `^[A-Za-z0-9][A-Za-z0-9._+-]*$` to name a directory. A record id is unique per (Painter build, golden).

## 3. Commands

Phase 0 prototype of `uzpainter parity`: run `python -m tools.parity.store [--store PATH] <command>` from the repository root. Exit status 0 when every blob resolves, 1 when any is `oracle_unavailable` or an operation is refused, 2 on usage errors.

| Command | Does |
|---|---|
| `init` | Creates the layout at the store root (owner's machine, once; idempotent; refuses a non-empty folder that is not a store) |
| `record <manifest> --record-id ID --kind KIND --file FILE` | Owner's machine only. Stores one recorded file and appends `{record_id, kind, sha256, size_bytes}` to the manifest's `private_records` (`golden-public.json`). A `private_oracle_record` file must pass `record_problems` and belong to the manifest's golden and Painter build |
| `record <manifest> --run DIR` | Owner's machine only. Ingests one recorder run from the oracle inbox (§4); creates the manifest from the run's, or merges its `private_records` into the existing one |
| `fetch <manifest> --out DIR` | Copies every blob the manifest names to `DIR/<record id><suffix>` and re-hashes the copy |
| `verify [PATH ...]` | Re-hashes in the store every blob the given manifests (or every `*.json` under a directory) name. Without a path: whole-store integrity (index, blobs and entries agree; every blob hashes to its name) |

Refusals, all checked before anything is written: a different blob under an existing record id (in the manifest or in the store), an invalid manifest or private record, a path inside the repository, a run without `READY`.

Comparisons obtain oracle bytes with `tools.parity.store.store.load_oracle(locate(), ref)`; it returns `None` for an unavailable oracle, and `tools.parity.verdict.evaluate` turns a comparison whose oracle is `None` into `oracle_unavailable`.

## 4. Recorder hand-off (oracle inbox)

The Painter recorder (`phase0.3_painter-oracle-recorder`) writes each recording run outside the repository to `<inbox>/<golden id with / as __>/<run stamp>/` (inbox: `UZP_ORACLE_INBOX`, else `%LOCALAPPDATA%\UzPainter\oracle-inbox`):

- `record.json`: the private record (`golden-private.json`);
- `blobs/<sha256>`: every blob the record names, named by its SHA-256;
- `manifest.json`: the public manifest with `private_records` filled (the record as `private_oracle_record`, every blob with its output kind);
- `READY`: an empty marker written last.

`record --run` requires `READY`, matches every `private_records` entry to a file of the run by SHA-256 and size, checks that each blob file is named by its hash and that the manifest names every blob the record names, then stores everything. Fetched blobs take their extension from the record's `media_type`. The run is never deleted by the store.

## 5. Hosted CI and the local oracle run

Decision 028: there is no GPU CI on GitHub and no self-hosted runner. `.github/workflows/parity.yml` (`14-parity-testing.md` §7) runs only hosted, CPU-only work:

| Where | Runs on | Does |
|---|---|---|
| Hosted CI (`hosted` job) | `windows-latest`, no GPU, no store, no `UZP_PARITY_STORE` | Type-check, lint, full test suite (GPU and oracle tests skip with an explicit reason); then checks that `verify` of the sample manifests reports `oracle_unavailable` |
| Local oracle run | The owner's machine only, started by hand (§5.1) | Whole-store integrity, then `verify parity/manifests`. Later comparisons against recorded Painter values run the same way, locally, and nowhere else |

The local run report is the gate evidence for every check that needs the store or Painter; a hosted run never stands in for it.

### 5.1 Local oracle run procedure (owner's machine)

1. Prerequisites on the machine: the GPU with DXR Tier 1.1 and Vulkan ray query, licensed Adobe Substance 3D Painter 12.1.0, Python 3.13 with `jsonschema` on `PATH`, and the store: `python -m tools.parity.store --store <root> init` with `<root>` outside the repository (once). Set `UZP_PARITY_STORE=<root>`, or leave it unset when the store is at the default `%LOCALAPPDATA%\UzPainter\parity-store`.
2. From the repository root, on a clean checkout of the commit under test: `python -m tools.parity.store verify` (whole-store integrity), then `python -m tools.parity.store verify parity/manifests` when that folder exists. Both must exit 0.
3. Write the run report: the commands, machine name, GPU and driver version, build hash (the commit), Painter build, and each command's exit status and output. It holds statuses and hashes only, never a recorded output, and is recorded as the evidence of the task that needs it.

## 6. Tests

`tests/parity/test_store.py` (every test uses a temporary store): round trip record → delete the local copy → fetch → hash (single file and recorder run), missing/unreadable/mismatched blob → `oracle_unavailable` (CLI, API and verdict), write-once refusal and idempotent re-record, per-build corpora, store and fetch paths inside the repository refused, the hosted lane without a store (subprocess without `UZP_PARITY_STORE`), and the workflow's lane rules.
