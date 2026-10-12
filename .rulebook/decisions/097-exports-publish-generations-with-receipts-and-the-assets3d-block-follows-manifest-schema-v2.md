# 97. Exports publish generations with receipts, and the Assets3D block follows manifest schema v2

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.17_export-publication-receipts, phase1.18_export-engine, phase1.23_pyapi-pipeline-adapter

## Context

Task `phase1.17_export-publication-receipts` implements `docs/architecture/08-export.md` §5 (EXP-06, EXP-09, ARC-11, INT-21, QG-03). Measured facts:

- `WriteExport` (phase1.16) writes the flat layout Painter writes, `exportPath/<relativePath>`. The Tier 0 parity tests compare that layout byte for byte with Painter's files.
- The architecture doc and the task name the manifest block `exportacao`, with the keys of Assets3D manifest schema v1 (`fontes`, `saidas`, `momento`, `preset`, `mapas`, `comparacao`, `evidencias`, `pendencias`). On 2026-10-11, Assets3D commit `b14511b` replaced v1 with `Pipeline/manifest/manifest-schema-v2.json`. Its `$defs/export` uses English keys (`sources`, `outputs`, `moment`, `preset`, `maps`, `comparison`, `evidence`, `open_items`). `sources` and `outputs` are keys of the manifest's `files`, and the comparison results are now `identical-bytes`, `identical-pixels`, `visual-equivalence`, `different` and `pending`. v1 is no longer in the Assets3D tree.
- No application version or build id exists in the code base. A project records the `app_version` of the app that wrote it.
- The evaluator names every bitmap, mesh map and the texturing mesh by SHA-256. `ReceiptInvalidated` (phase1.10) marks a receipt stale when one of its `resource_hashes` is a replaced mesh or an invalidated mesh-map binding.
- No template defines a base value for SpecularWeight, so a SpecularWeight map cannot be evaluated by this build yet.

The model panel was consulted once under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5). Grok answered HTTP 503, so the verdicts are from GPT and Kimi.

| Claim | Verdicts |
|---|---|
| C1: the v2 `export` block under `manifest_export`, with the v2 definitions copied into the receipt schema; keys derived from paths; paths relative to the generation; rebasing is the adapter's | AGREE x1, PARTLY x1: add the `files` entries the keys name, and keep the keys valid. Adopted: `manifest_files` |
| C2: the generation layout, flush and verify, then a durable pointer rename | AGREE x1, PARTLY x1: completeness must also check the plan against the plan hash. Adopted |
| C3: recovery rolls a complete newer generation forward and removes incomplete ones | PARTLY x2: publish the newest complete one, handle a missing pointer, never delete the selected generation. Adopted. A pointer that does not read fails recovery and changes nothing (Kimi proposed quarantine; refused, because a pointer is only ever replaced by rename and a bad one means outside damage) |
| C4: the pinning adapter, the journalled copy and the locked reader | AGREE x1, PARTLY x1: roll forward only from the generation the journal names. This was already the design |
| C5: app version and build supplied by the caller; resource hashes are the resources the files read | AGREE x1, PARTLY x1: GPT asked for a verifiable build hash. Refused: no build identity exists yet |

## Decision

1. **Generations** (`src/export/publish.h`). Every export goes to `exportPath/generations/<NNNNNN>/` with `files/<relativePath>`, `plan.json` and `receipt.json`. The steps, all under the publication lock:
   - encode every file in memory;
   - claim the next generation number with create-if-absent;
   - write, flush and re-read every file, then the plan and the receipt;
   - verify the generation;
   - write `current.json.uzp-staging`, flush it and rename it over `current.json` (`MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH`).

   A generation is complete when:
   - its receipt reads as a receipt of that generation;
   - its `plan.json` hashes to the receipt's plan hash;
   - every listed file has the recorded size and SHA-256.

   A failure before the rename removes the new generation, keeps the previous one selected and returns an `export:` failure. Encoder exceptions are caught there, so the host stays alive. `WriteExport` keeps the flat layout for the parity tests.
2. **Recovery** (`UzPainter.exe export --recover <exportPath> [--fixed-names <dir>]...`), under the lock:
   - the newest complete generation newer than the selected one, or any complete one when nothing is selected, is published;
   - other incomplete generations are removed;
   - complete generations and the selected one are never removed: a damaged selected generation is reported (exit 1);
   - a pointer that does not read fails the recovery before anything changes.
3. **Fixed names** (`src/export/fixed_names.h`). A fixed-name consumer reads through one of two routes:
   - **The pinning adapter.** It returns the selected generation's immutable `files/` directory after verifying every file.
   - **A fixed-name copy read under the publication lock.** The copy is journalled in its directory as `{generation, files, copied, obsolete}`. Each copy is written to `<name>.uzp-staging` and renamed, and only then recorded. A reader (`LockedFixedNames`) rolls an interrupted copy forward from the journal's generation, verifies every fixed name, and holds the lock for the whole read. When that generation does not verify, it fails before consumption.

   A copy into `exportPath` itself refuses the publication's own names.
4. **Receipt** (`src/export/receipt.h`, `src/export/schema/receipt.schema.json`, schema `uzpainter/export-receipt/1`).
   - **Header.** The ARC-11 header plus `build`, `generation`, `moment`, `plan` and `plan_hash`.
   - **Per file.** Path, bytes, SHA-256, format, bit depth, colour space, size, preset, layout, channel mapping, the EXP-09 normal tag (`combined` with its relief round, or `geometry_only`) and its consumer gaps.
   - **`skipped`.** The maps the plan does not write.
   - **`manifest_export`.** The Assets3D v2 `export` block, with `manifest_files` holding the entries its keys name. Its paths are relative to the generation, and rebasing them under the Assets3D root belongs to `phase1.23_pyapi-pipeline-adapter`. `comparison` is `pending`. The block is null when no file is written, because v2 needs an output. The v2 definitions are copied unchanged into the receipt schema from commit `b14511b`.
   - **Colour space.** Every image file written today is `linear`. The sRGB encoding is refused, decision 090.
   - **Consumer gaps.** A SpecularWeight map carries the consumer gap of `08-export.md` §4.
5. **ARC-11 inputs.**
   - `app_version` and `build` are required inputs of the publication request, supplied by the caller.
   - `resource_hashes` are the resources the planned files read:
     - the bitmaps of each read channel DAG (fills, effects, masks, groups);
     - a diagnostic material's masks;
     - the mesh maps read;
     - the texturing mesh whose coverage drives the padding.
6. **Fault hooks** (`src/export/fault.h`). They kill the process or fail a step between every publication step and around every fixed-name copy. They are compiled with `UZP_EXPORT_FAULT_HOOKS` into `uzp-export-tests.exe` only.

## Alternatives Considered

- **Emitting the v1 `exportacao` block.** Rejected: Assets3D retired v1, and its tools validate v2.
- **Writing the flat layout as the publication.** Rejected: separate copies into a fixed-name directory are not atomic (EXP-06). The flat layout remains a journalled fixed-name copy.
- **Listing every resource of the project.** Rejected: unrelated resources would make `ReceiptInvalidated` mark receipts stale.

## Consequences

- `08-export.md` §5 and `src/export/EXPORT.md` §6 describe the publication. The PRD's INT-21 row still names `exportacao`, and this decision maps it to the v2 block.
- `phase1.23_pyapi-pipeline-adapter` chooses each consumer's route (pinned directory or locked fixed names), rebases `manifest_files` paths under the Assets3D root, and supplies the app version and build.
- Complete generations accumulate, because no retention policy is specified. Pruning old generations is not part of this task.
- No Painter recording is needed: publication and receipts are UzPainter's own behaviour.
