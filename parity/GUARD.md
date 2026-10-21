# UzPainter repository guard

Work package P0-STORE (`docs/dag.md`), task `phase0.4_oracle-store-guard`. Implements the guard of `docs/architecture/14-parity-testing.md` §6 for `parity/CONTRACT.md` §6.4 and §7, under decisions 002 (clean room), 028 (no GPU CI; the store never leaves the owner's machine) and 200 (the hosted parity CI was removed; the local full gate runs the guard, §5). Code: `tools/parity/guard/`; hook: `.githooks/pre-commit`; tests: `tests/parity/test_guard.py`.

## 1. What it blocks

No recorded Painter output may enter the repository in any form. The guard judges the bytes of each file, never only its name, extension or signature. A file is blocked by any of five rules:

| Rule | Blocks | Needs |
|---|---|---|
| `store-hash` | A file whose SHA-256 is in the private store index (`parity/STORE.md` §2). Text is also hashed after CRLF→LF and LF→CRLF conversion, so a copy whose line endings git or an editor changed still matches | The index of the owner's store (`UZP_PARITY_STORE`, else `%LOCALAPPDATA%\UzPainter\parity-store`) or `--index FILE`. A machine with neither skips this rule, saying so |
| `private-record` | A JSON file anywhere in the repository that holds a private oracle record at any depth (`record_class` `private_oracle_record`, or a `uzpainter/parity/golden-private/` schema id) | Nothing |
| `public-schema` | A JSON data file under `parity/` that fails the public schema its path assigns (§2), or that no rule covers. A file counts as JSON by its `.json` name (it must then parse as UTF-8 JSON) or by its content (starts with `{` or `[` and parses), so a readback renamed to `.txt` is still judged | Nothing |
| `procedural-snapshot` | A frozen procedural snapshot anywhere (decision 327): a JSON document holding a `procedural_snapshots` member at any depth (a project or export-bundle manifest, `inspect` output); a `.uzp` project (an SQLite database, by its header) whose `plane` table holds a project-level plane (set, stack and channel absent: a snapshot's raster); a ZIP archive whose JSON members hold such an entry | Nothing |
| `observed-structure` | An observed Painter preset tree, parameter collection or serialised readback anywhere, in JSON or in a ZIP archive's JSON members, in the shapes the recorder's serialisers give: a layer-stack node (`name` with a `node_type` or `type` of the documented `layerstack.NodeType`), a property read (`value` with `widget_type`), a substance source read (`substance_properties`, or `resource_url` with `properties`, `presets`, `image_inputs` or `image_outputs`), or levels parameters (a `class` of the documented `substance_painter.levels`). UzPainter's recipes name node kinds in lower case (`kind`) and its default tables hold `default`, not a read `value` | Nothing |

A re-serialised readback no longer matches the index, so it is caught by its content: it never validates against the public manifest schema, and as a private record it also trips `private-record`. A snapshot's raster or a recorded image outside a project database or bundle manifest, re-encoded or cropped, matches nothing and is not detected by content; such files are prevented by the recording procedure (blobs go only to the store and the oracle inbox outside the repository, `parity/STORE.md` §1 and §4), and the guard's hash rule catches the unmodified bytes on the owner's machine.

## 2. Schema of each JSON path under `parity/`

First match wins; any other JSON under `parity/` is blocked until a rule for its area is added to `PATH_RULES` in `tools/parity/guard/guard.py` together with its schema.

| Path | Must be |
|---|---|
| `parity/schema/<name>.json` | One of the schemas of `tools.parity.schemas.Schema`, declaring JSON Schema draft 2020-12 and valid as one |
| `parity/schema/samples/public/*.json` | Valid `golden-public.json` |
| `parity/schema/samples/private/*.json` | Synthetic private-shaped samples only (CONTRACT.md §7): a valid private record (`record_problems`) whose `note` starts with `Synthetic sample`, whose `golden_id` is under `samples/` and whose Painter `build_id` is `synthetic-sample-build`. They deliberately fail the public schema; any other file here is blocked |
| `parity/schema/samples/exceptions/*.json` | One valid `exceptions.json` entry |
| `parity/schema/samples/reports/*.json` | Valid `comparison-report.json` |
| `parity/exceptions.json` | The register: valid `exceptions.json` and `register_problems` (decisions recorded under `.rulebook/decisions/`) |
| `parity/manifests/**` | Valid `golden-public.json` |
| `parity/envelopes/registry.json` | The oracle envelope registry: valid `envelope-registry.json` and its cross-field rules (`tools.parity.envelope.registry.registry_problems`: one current envelope, a candidate that refreshes it; decision 037) |
| `parity/envelopes/<envelope id>/manifests/**` | Valid `golden-public.json` (a promoted envelope's manifests) |
| `parity/envelopes/<envelope id>/requests/**` | Valid `golden-public.json` with `private_records` empty: a requested golden, prepared before the Painter session that records it and admitted under `manifests/` (`parity/RECORDER.md` §11) |
| `parity/reports/<phase>/oracle-envelope*.json` | Valid `oracle-envelope.json` (stability study, drift, prepared register entries); a prepared entry must be a valid `exceptions.json` entry once the owner's approval fields are added, and must not carry them |
| `parity/reports/<phase>/tier<tier>-*.json` | Valid `comparison-report.json`: a golden's comparison report (numbers and hashes only; Tier 1 pilots, `parity/RECORDER.md` §11) |
| `parity/semantics/*.json` | Valid `semantics.json` (fitted formulas: public sources, constants, residuals as numbers) |
| `parity/fixtures/**` | An authored input (fixture description, authored recipe) that a valid manifest under `parity/manifests/`, under an envelope's `parity/envelopes/<envelope id>/manifests/` or among its requested goldens (`requests/`) declares by this path and SHA-256 (decision 087) |
| `parity/reports/<phase>/recipe-rebuild-*.json` | Valid `recipe-rebuild-report.json`: a rebuild-from-dump report (`phase2.2_recipe-and-diagnostics`): recipe digests, file names, SHA-256 and sizes, the outcome; no oracle data |
| `parity/reports/<phase>/store-census.json` | The project store's size census (`src/store/census.h`, `phase1.7_store-inspect-census`): `schema` `uzpainter/store-census/1`, a non-empty `projects` list of objects with an `id`, numbers everywhere else; text only in `schema`, `task`, `date`, `id`, `format`, `raster_plane_format` and the `not_measured` lists, each an identifier (no paths) |
| `parity/reports/<phase>/supervisor-settling.json` | The supervisor's settling report (`tools/parity/settling/report.py`, `phase2.4_supervisor-worker`, decision 150): numbers, booleans, identifiers, dates and SHA-256 digests only |
| `parity/reports/<phase>/preview-settling.json` | The preview's settling report (`tools/parity/settling/preview.py`, `phase2.3_realtime-preview`, decision 162): numbers, enums, identifiers, dates and SHA-256 digests only; no oracle data |
| `parity/reports/<phase>/mcp-contract.json` | The MCP contract report (`tools/parity/settling/mcp_contract.py`, `phase2.8_mcp-server`, decision 186): numbers, enums, identifiers, dates and SHA-256 digests only; no oracle data |
| `parity/reports/<phase>/<pilot>-mcp-round.json` | A pilot's MCP-only round report (`tools/parity/tier1/mcp_round.py`, `phase2.9_pilot-belt`, decision 192): the call log, the outcome and each exported map's SHA-256 beside the Tier 1 run's; both sides are UzPainter's, no oracle data |
| `parity/reports/<phase>/held-out-ledger.json` | The procedural held-out ledger (`tools/parity/proc_cert/ledger.py`, `phase3.1_proc-backend-seam`, decision 303): `schema` `uzpainter/parity/proc-cert-ledger/1` and `spent`, an object mapping each held-out pin (SHA-256) to the SHA-256 of the one candidate it was revealed to; nothing else |

## 3. Running it

From the repository: `python -m tools.parity.guard [--staged] [--index FILE | --no-store] [PATH ...]`.

- Without `--staged`: the working tree (tracked and untracked, not ignored, files); `PATH`s narrow the check. This is the full-gate step (§5).
- `--staged`: the files the next commit would record, read from the index (pre-commit hook). Manifests that declare fixtures are read from the index too.
- `--index FILE`: match hashes against a store `index.json` (`uzpainter/parity/store-index/1`; hashes only, never blobs). `--no-store`: do not look for this machine's store.

Output: one `BLOCKED <path>: [<rule>] <reason>` line per finding and a summary. Exit status 0 when nothing is blocked, 1 when a file is blocked, 2 when the guard cannot run (git failure, unreadable index, a store configured inside the repository).

## 4. Pre-commit hook

The hook lives in the repository at `.githooks/pre-commit` (LF endings, `.gitattributes`) and runs `python -m tools.parity.guard --staged`. Enable it once per clone, from the repository root:

```
git config core.hooksPath .githooks
```

`python` (3.13 with `jsonschema`) must be on `PATH` in the shell git uses for hooks. On the owner's machine the hook finds the store and applies all three rules; elsewhere it applies the content and schema rules and says the hash rule was skipped. A blocked commit is fixed by removing the file from the commit, never by bypassing the hook.

## 5. Local full gate

The hosted parity CI was removed (decision 200). `python -m tools.parity.guard` runs locally on the commit under test, in the coordinator's full gate before the owner pushes, besides the pre-commit hook. On a machine without the store it applies the `private-record` and `public-schema` rules and says the hash rule was skipped; a blocked file exits 1. The `store-hash` rule runs on the owner's machine (hook and local runs).

## 6. Tests

`tests/parity/test_guard.py`: stand-ins for a recorded PNG and a recorded JSON readback are written outside the repository and recorded into a temporary store; each case runs in a throwaway git repository. Covered: the PNG blocked by hash when staged (API, CLI with the local store, and `git commit` through the committed hook); the readback blocked by hash, after line-ending conversion, and re-serialised under `parity/` (manifest, fixture, uncovered and schema paths, `.txt` name), outside `parity/`, and relabelled as a synthetic sample; the authored fixture image and expectation JSON (`tests/parity/guard_data/`) pass staged and in the working tree; declared and undeclared JSON fixtures; the repository's own `parity/schema` and register pass, synthetic private samples included; the report rules of §2 and the envelope registry, manifests and requests; the guard command, run without a store, fails on a commit carrying a blocked file. Snapshots and observed structures (`phase3.2_proc-snapshot-backend` 3.4, `phase3.4_smart-mask-recipes` 2.4 and 3.4): a snapshot entry in JSON at any path, a stand-in `.uzp` with a snapshot plane (a paint and mask plane passes), export-bundle ZIPs judged by their JSON members, each observed shape outside `parity/`, and a recorded smart-mask readback blocked by hash and content while an authored recipe passes.
