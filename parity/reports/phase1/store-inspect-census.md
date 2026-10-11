# Project store: inspection and the size census — `phase1.7_store-inspect-census`

Child of P1-STORE (`phase1.8_project-store`). Implements `docs/architecture/09-project-file-format.md`
§3 and §6 with owner answer Q11 (decision 024). Code and contract: `src/store/inspect.h`,
`bundle.h`, `bundle_codec.h`, `census.h`, `cli.h`, documented in `src/store/STORE.md` §10–§11.
The numbers are in `parity/reports/phase1/store-census.json` (`uzpainter/store-census/1`, numbers
and identifiers only; the repository guard has a rule for that path, `parity/GUARD.md` §2).

**Result: `inspect`, `inspect --verify`, `export-bundle` and the bundle import work and are tested;
the census ran on tunic v10, hat v8 and body v5/v6/v6b. On the dependency content measurable
today only tunic v10 is inside the 10 % candidate budget (6.2 %); the other four are above it
because the measured dependency files themselves are most of the project file. The budget stays a
candidate the owner ratifies with these numbers in hand (09 §3), and the full-content census is
`phase4.1_coverage-body-v6b`.**

## 1. Local run (owner's machine, 2026-10-11)

| Item | Value |
|---|---|
| Machine | Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090 (no GPU used: the store is CPU only) |
| Toolchain | Zig 0.15.2, Python 3.13 |
| Builds | `zig build painter` (Debug and ReleaseFast) and `zig build uzp-store uzp-store-tests uzp-store-save-tests uzp-store-inspect-tests`: exit 0, no warnings (`-Wall -Wextra -Werror` on UzPainter's own sources) |
| Tests | `python -m pytest tests/store` 63 passed; full suite, `mypy`, `ruff check`, `ruff format --check`, `python -m tools.parity.guard` green |
| Census command | `UzPainter.exe store-census --inputs src/store/census_inputs.json --assets-root E:/UzmiGames/Assets3D --work <temp> --out parity/reports/phase1/store-census.json --edits 20` |

## 2. Census numbers

Per project: a portable `.uzp` holding every measurable dependency, 1 fill layer, 20
one-parameter edits, a 4096×4096 sRGB8 paint plane and an edit inside one chunk, saved, reopened
and compacted (procedure in `STORE.md` §11). `.spp` sizes are file sizes only — no Painter file was
opened (decision 020, decision 002).

| Project | `.spp` bytes | Measured dependencies | Project bytes | Ratio | ≤ 10 % |
|---|---|---|---|---|---|
| tunic v10 | 408,723,056 | 2 files, 35,324,928 B | 25,464,832 | 0.062 | yes |
| hat v8 | 578,029,285 | 48 files, 307,122,093 B | 307,261,440 | 0.532 | no |
| body v5 | 879,248,615 | 4 files, 153,201,033 B | 153,677,824 | 0.175 | no |
| body v6 | 1,087,438,533 | 4 files, 156,016,983 B | 154,865,664 | 0.142 | no |
| body v6b | 1,190,431,812 | 4 files, 155,798,219 B | 154,648,576 | 0.130 | no |

The three body `.spp` sizes are the public facts of 09 §3; tunic v10 and hat v8 come from the same
filesystem metadata.

| Measurement | tunic v10 | hat v8 | body v5 | body v6 | body v6b |
|---|---|---|---|---|---|
| First save (s) | 7.41 | 58.22 | 27.06 | 28.29 | 24.22 |
| One-parameter edit, file growth (mean B) | 2,048 | 4,915 | 2,662 | 2,662 | 2,662 |
| One-parameter edit, bytes written (mean B) | 43,572 | 46,439 | 44,186 | 44,186 | 44,186 |
| One-parameter edit (mean s) | 0.0097 | 0.0205 | 0.0101 | 0.0139 | 0.0087 |
| Stored manifest per edit (mean B) | 1,246 | 4,230 | 1,583 | 1,591 | 1,589 |
| Plane create, stored chunk bytes | 188,829 | 188,829 | 188,829 | 188,829 | 188,829 |
| One-chunk plane edit, stored chunk bytes | 29,113 | 29,113 | 29,113 | 29,113 | 29,113 |
| Reopen (s) | 1.10 | 1.29 | 1.37 | 1.14 | 0.89 |
| Compaction (s) | 0.27 | 3.39 | 2.14 | 1.88 | 1.22 |
| Retained history (B) | 48,744 | 117,381 | 56,510 | 56,683 | 56,644 |

What the numbers say about the store itself: an edit costs what it changes (a one-parameter edit
grows the file by 2–12 KB and writes ~44 KB including the rollback journal, independent of the
project's size), a plane edit stores only the chunk it touched (29 KB against 189 KB for all 16
chunks), reopening a 25–307 MB project takes about a second, and 23 retained revisions cost
48–117 KB — so the file size is the dependency bytes plus a fraction of a percent. Nothing was
collapsed by `compact` here (23 revisions, under the 50-mutation window), so `file_bytes_before` =
`file_bytes_after`.

## 3. Why four ratios are above the budget, and what is not measured yet

The project file is essentially the embedded dependencies: lossless PNG mesh maps and masks, the
mesh, the high-poly mesh where it exists. UzPainter stores those original bytes once, unmodified
(09 §2), so the ratio to a matched `.spp` is decided by which dependency content each side holds —
not by store overhead. Hat v8 embeds the 48 lossless 4K mask PNGs of its stack (307 MB); the
bodies embed three 4K 16-bit normal maps (≈ 51 MB each).

The inputs (`src/store/census_inputs.json`) list the dependency files that exist today. What is
named `not_measured` per project is dependency content the corpus no longer keeps as files:

| Project | `not_measured` | Why |
|---|---|---|
| tunic v10 | `imported_masks_packed_in_blend`, `painter_baked_mesh_maps` | its seven masks live packed inside `18-Tunica-v10.blend`; the baked maps exist only inside the `.spp` |
| hat v8 | `high_poly_mesh`, `painter_baked_mesh_maps` | the high-poly source is not in the corpus tree |
| body v5/v6/v6b | `imported_masks`, `high_poly_mesh`, `painter_baked_mesh_maps` | the bone/teeth masks were produced in `_tmp` and removed; the high-poly meshes live inside the `.blend` files |

Both sides therefore hold different content, which is why these ratios are a measurement of the
content that exists now (as this task was scoped) and not the ratification evidence on their own.
Completing it needs the dependency content unpacked for one project with the Painter-side
inventory of the same content: `phase4.1_coverage-body-v6b` (09 §3, "linked bytes counted on both
sides"). Reading it the other way round, the measured dependency bytes are ≤ 10 % of the matched
`.spp` only for tunic v10, so the budget as a release gate will have to be stated against matched
content, not against the file as it is assembled from whatever files are at hand.

## 4. Inspection and the bundle

`uzpainter inspect <file.uzp> [--revision N] [--verify]` prints every field of 09 §6 (the recipe
digest reported as `{available: false, reason}` until `dump_recipe` exists in
`phase2.2_recipe-and-diagnostics`, never silently omitted), without a GPU and without taking the
project lock: a read-only connection inside one read transaction, and `--verify` works on a
consistent SQLite backup snapshot, so it runs while a worker holds the project (native case
`inspect_while_locked`). `sizes` lists the project file's parts and, separately,
`external_dependencies` (the locator targets of a non-portable project). `--verify` runs every
integrity rule of 09 §1 and exits 1 on a failure (native case `verify_failures`: a broken plane
binding, a missing resource blob, a missing chunk blob).

`uzpainter export-bundle <file.uzp> <dir|file.zip>` writes `manifest.json`, `res/`, `meshmaps/`
and `planes/` (PNG for 8/16-bit formats, uncompressed scanline OpenEXR for half/float, bit-exact)
plus a `bundle.json` index; `project.open` of the bundle directory rebuilds a `.uzp` with an equal
manifest digest and equal plane pixels (native case `bundle_round_trip`).
