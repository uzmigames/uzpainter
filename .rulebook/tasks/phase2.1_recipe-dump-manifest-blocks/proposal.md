# Proposal: phase2.1_recipe-dump-manifest-blocks

## Why
Child of `phase2.2_recipe-and-diagnostics` (P2-RECIPE in `docs/dag.md`), implementing the recipe dump of D3 (`docs/architecture/03-project-model.md` §5, §7; `docs/architecture/09-project-file-format.md` §6) and the manifest `exportacao` block of D7 (`docs/architecture/08-export.md` §5). The Assets3D pipeline records a machine-readable recipe with a deterministic digest next to every delivery and needs a project rebuilt from that recipe plus its resources to export identical maps; this is also the replay path of Painter migration (owner Q6, decision 020). Requirements: SAV-03, SAV-04, INT-20, INT-21, ARC-11, G-03 (`docs/prd.md`).

## What Changes
- `uzpainter.project.dump_recipe()`: the manifest subset that fully determines output (per node type, name, visibility, channels, per-channel blend and opacity, sources with values and colour spaces, resource hashes and aliases, projections and symmetry, effects and parameters, mask background and enable, geometry masks, procedural parameters and asset versions, effective defaults, `evaluator_profile`) plus a deterministic digest (SHA-256 of the canonical JSON); it is the `painter_recipe`-equivalent block of INT-20 with defaults, evaluator version and content identity, and carries `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}`.
- `uzpainter inspect <file.uzp>` prints the same recipe JSON without opening the project (no GPU, no project lock); the worker handler behind the MCP `project_recipe` tool and the `uzpainter://project/recipe` resource returns it.
- Rebuild path: a dump plus its referenced resources replayed through the native API into a new project (the same replay used for migration, `03-…` §7).
- Manifest `exportacao` block written with every export receipt: `fontes`, `saidas`, `momento`, `preset`, `mapas`, `comparacao`, `evidencias`, `pendencias` (INT-21).

## Dependencies
- Parent: `phase2.2_recipe-and-diagnostics`.
- Prerequisite: `phase1.25_pilot-wand` (DAG input of P2-RECIPE; document model, store with `inspect`, export receipts and the wand project exist).
- Sibling (independent): `phase2.1_recipe-diagnostic-views`.

## Acceptance
- Dump schema tests pass; the digest is identical across runs, sessions and save/reopen and changes only when output-determining state changes.
- `inspect` output equals `dump_recipe()` for the same revision without GPU or lock.
- Rebuilding a synthetic fixture from its dump gives identical exports.
- Every export receipt carries a schema-valid `exportacao` block.

## Impact
- Affected specs: `recipe` (dump, digest, rebuild, manifest blocks)
- Affected code: document-model serialisation, `inspect` CLI, worker command handlers, export receipt writer
- Breaking change: NO
- User benefit: deliveries carry a reproducible recipe that rebuilds the same maps
