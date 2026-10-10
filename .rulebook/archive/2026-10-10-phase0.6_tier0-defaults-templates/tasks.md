## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [x] 2.1 Instruction sequence for baking defaults: fresh project, `BakingParameters.common()` and `baker(usage)` for the ten `MeshMapUsage` bakers, every key with value, name, short name, label, widget type, enum values, enum value and nested properties
- [x] 2.2 Instruction sequence for templates: enumerate the project templates shipped with Painter 12.1.0 that the documented project-creation API accepts; create a project per template on a UzmiGames synthetic mesh and read back each stack's channel set and `ChannelFormat` through the documented `textureset` API
- [x] 2.3 Record each capture at least twice (same session; after save/reopen; defaults also on a second fresh project) in the shape of `parity/schema/golden-private.json`
- [x] 2.4 Admit the captures with `uzpainter parity record` and write `parity/manifests/phase0/tier0-defaults-templates.json` with instruction sequences, template identifiers, Painter build id and hashes only

## 3. Tests
- [x] 3.1 Completeness test: the defaults capture contains every key returned by `common().keys()` and by `baker(usage).keys()` for all ten usages, and the template capture lists every enumerated template
- [x] 3.2 Manifest test: the public manifest validates against `parity/schema/golden-public.json` and contains no captured value
- [x] 3.3 Store test: `uzpainter parity verify` passes for every hash on the owner's machine
- [x] 3.4 Guard test: a captured defaults JSON staged for commit is rejected by the repository guard

## 4. Acceptance
- [x] 4.1 Child acceptance (contributes to P0-TIER0): baking defaults and template channel sets/formats captured ≥ 2× through the documented API; blobs private, hashes public; verify passes

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-10)

- Code: `tools/parity/recorder/defaults.py` (new; `record-defaults`, `list-templates` and `record-templates` commands in `__main__.py`). Recorder extensions: painter-side `baking_capture` and `shipped_templates`, `project.create` `template` argument (`painter_side.py`), baking capture calls in `job.py` and `vocabulary.py`, 27 documented symbols added to `documented_symbols.json`. `python -m tools.parity.recorder check --python-doc <objects.inv>` reports `provenance: ok` for these files. The fake Painter (`tests/parity/recorder/fake_painter.py`) gained baking parameters (authored stand-in keys), an application shelf and templates. Docs: `parity/RECORDER.md` §2 and §8.
- Manifest path: following the coordinator's instruction, the manifests live in the task folder `parity/manifests/tier0/defaults-templates/`. There are two, one per golden (`golden-public.json` describes one golden per file): `baking-defaults.json` (golden `tier0/defaults-templates/baking-defaults`) and `project-templates.json` (golden `tier0/defaults-templates/project-templates`, 26 template identifiers). They replace the single `parity/manifests/phase0/tier0-defaults-templates.json` named in item 2.4.
- Template enumeration, coordinator ruling (2026-10-10): the path comes from the documented `Shelves.application_shelf().path()`. Only `*.spt` file names are listed; no template is read, hashed or copied. Painter opens each template through the documented `project.create(..., template_file_path=...)`. File names and relative paths are public facts. Everything Painter reports from those projects is a private oracle record. Reading the python-doc HTML and `objects.inv` (A-PYDOC) was allowed by the coordinator ruling `pydoc-ruling.md`.
- Recording: Painter 12.1.0, build `12.1.0+js-api.1.1.20`, one session under the Assets3D Painter lock. The lock was acquired, Painter exited before the lock was released, and the release succeeded. Baking defaults: recordings r1 (`same_session`), r2 (`after_save_reopen`) and r3 (`same_session`, second fresh project) are identical. Templates: 26 shipped, 26 accepted, r1 (`same_session`) and r2 (`after_save_reopen`) are identical. Observed facts that the recorder now records instead of refusing: the Normal, WorldSpaceNormal and Opacity bakers expose no keys, and one `common()` Combobox has an empty `enum_values()`.
- Store: `python -m tools.parity.store record <manifest> --run <inbox run>` admitted both runs. Record hashes: baking `aa823e7adbd5bb5c8759ec2261977997d3779ca2ee50685e0487ce285b9d44ed` (116441 bytes), templates `d546c51c1697bc16a9874989696625588978902cb1902306205a93e17f42b0fd` (55772 bytes). `python -m tools.parity.store verify parity/manifests/tier0/defaults-templates` exits 0 (both `available`), and the whole-store `verify` reports ok and exits 0. `python -m tools.parity.guard parity/manifests/tier0/defaults-templates tools/parity/recorder tests/parity/recorder` (with the store-hash rule) checked 25 files and blocked 0.
- Tests: `tests/parity/recorder/test_defaults_templates.py` (24 passed). Items 3.1 to 3.4 are covered by: completeness against the fake's `keys()` for common and all ten bakers; enum labels with `enum_value`; a raising getter recorded; incomplete captures refused; every shipped template listed and captured twice; a job that does not name exactly the shipped templates refused before Painter is touched; identifiers outside the shelf refused; committed manifests valid with no captured value; store round trip and `verify` on the owner's store; the guard rejecting a captured defaults JSON staged for commit (store-hash, private-record and public-schema rules).
