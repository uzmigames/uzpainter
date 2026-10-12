# UzPainter repository guard

Work package P0-STORE (`docs/dag.md`), task `phase0.4_oracle-store-guard`. Implements the guard of `docs/architecture/14-parity-testing.md` §6 for `parity/CONTRACT.md` §6.4 and §7, under decisions 002 (clean room) and 028 (hosted CPU-only CI; the store never leaves the owner's machine). Code: `tools/parity/guard/`; hook: `.githooks/pre-commit`; tests: `tests/parity/test_guard.py`; hosted CI: `.github/workflows/parity.yml`.

## 1. What it blocks

No recorded Painter output may enter the repository in any form. The guard judges the bytes of each file, never only its name, extension or signature. A file is blocked by any of three rules:

| Rule | Blocks | Needs |
|---|---|---|
| `store-hash` | A file whose SHA-256 is in the private store index (`parity/STORE.md` §2). Text is also hashed after CRLF→LF and LF→CRLF conversion, so a copy whose line endings git or an editor changed still matches | The index of the owner's store (`UZP_PARITY_STORE`, else `%LOCALAPPDATA%\UzPainter\parity-store`) or `--index FILE`. Hosted CI has neither and skips this rule, saying so |
| `private-record` | A JSON file anywhere in the repository that holds a private oracle record at any depth (`record_class` `private_oracle_record`, or a `uzpainter/parity/golden-private/` schema id) | Nothing |
| `public-schema` | A JSON data file under `parity/` that fails the public schema its path assigns (§2), or that no rule covers. A file counts as JSON by its `.json` name (it must then parse as UTF-8 JSON) or by its content (starts with `{` or `[` and parses), so a readback renamed to `.txt` is still judged | Nothing |

A re-serialised readback no longer matches the index, so it is caught by its content: it never validates against the public manifest schema, and as a private record it also trips `private-record`. A recorded image that is re-encoded or cropped matches nothing and is not detected by content; such files are prevented by the recording procedure (blobs go only to the store and the oracle inbox outside the repository, `parity/STORE.md` §1 and §4), and the guard's hash rule catches the unmodified bytes on the owner's machine.

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

## 3. Running it

From the repository: `python -m tools.parity.guard [--staged] [--index FILE | --no-store] [PATH ...]`.

- Without `--staged`: the working tree (tracked and untracked, not ignored, files); `PATH`s narrow the check. This is the hosted CI step.
- `--staged`: the files the next commit would record, read from the index (pre-commit hook). Manifests that declare fixtures are read from the index too.
- `--index FILE`: match hashes against a store `index.json` (`uzpainter/parity/store-index/1`; hashes only, never blobs). `--no-store`: do not look for this machine's store.

Output: one `BLOCKED <path>: [<rule>] <reason>` line per finding and a summary. Exit status 0 when nothing is blocked, 1 when a file is blocked, 2 when the guard cannot run (git failure, unreadable index, a store configured inside the repository).

## 4. Pre-commit hook

The hook lives in the repository at `.githooks/pre-commit` (LF endings, `.gitattributes`) and runs `python -m tools.parity.guard --staged`. Enable it once per clone, from the repository root:

```
git config core.hooksPath .githooks
```

`python` (3.13 with `jsonschema`) must be on `PATH` in the shell git uses for hooks. On the owner's machine the hook finds the store and applies all three rules; elsewhere it applies the content and schema rules and says the hash rule was skipped. A blocked commit is fixed by removing the file from the commit, never by bypassing the hook.

## 5. Hosted CI

The `hosted` job of `.github/workflows/parity.yml` runs `python -m tools.parity.guard` on the checked-out commit of every push and pull request to `main`. Decision 028: the job has no store and receives no index, so it applies the `private-record` and `public-schema` rules; a blocked file fails the job. The `store-hash` rule runs on the owner's machine (hook and local runs).

## 6. Tests

`tests/parity/test_guard.py`: stand-ins for a recorded PNG and a recorded JSON readback are written outside the repository and recorded into a temporary store; each case runs in a throwaway git repository. Covered: the PNG blocked by hash when staged (API, CLI with the local store, and `git commit` through the committed hook); the readback blocked by hash, after line-ending conversion, and re-serialised under `parity/` (manifest, fixture, uncovered and schema paths, `.txt` name), outside `parity/`, and relabelled as a synthetic sample; the authored fixture image and expectation JSON (`tests/parity/guard_data/`) pass staged and in the working tree; declared and undeclared JSON fixtures; the repository's own `parity/schema` and register pass, synthetic private samples included; the CI step exists and the CI command fails on a commit carrying a blocked file.
