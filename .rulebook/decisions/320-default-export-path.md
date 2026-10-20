# 320. The native default export folder stays under Documents/UzPainter; the facade returns Painter's observed application folder without using it, pending exact replay evidence

Date: 2026-10-20. Status: accepted (Claude and Codex, SUP-160/162/164; routine technical choice delegated by the owner).
Related: `phase1.24_python-api-facade` item 4.1, decision 319, decision 113, golden `tier0/api-probes/phase1-create-default-paths` (P21-B).

## Context

In both P21-B recordings, `get_default_export_path()` (s3) returns the recording host's Documents export folder of Painter. The value depends on the host and on Painter's own folder layout. UzPainter keeps its own folder and does not reuse that path. Until now the facade did not have the symbol (AttributeError), and P21-B s3 was an open item of 4.1.

## Original decision

1. **Value.** The private native call `uzpainter.export._default_export_path` returns `<Documents>/UzPainter/export` as an absolute UTF-8 path.
   - `<Documents>` comes from `SHGetKnownFolderPath(FOLDERID_Documents, KF_FLAG_DONT_VERIFY)`, so a redirected Documents folder is respected.
   - The call never checks that the folder exists and never creates it. The buffer is freed on every path.
   - If the shell call fails, it raises `RuntimeError`. There is no fallback path.
2. **Independence.** `Settings.export_path` does not change the getter, because P21-B shows the setting has no observable effect (decision 319). An export without an explicit `exportPath` still raises Painter's observed `ValueError("at /exportPath: Expected a string value")`. The default folder is never used silently.
3. **Comparison.** The P21-B replay checks that s3 returns a valid absolute path and records the host difference explicitly, naming this decision. It never asserts literal equality with Painter's path.
4. **Status.** The symbol moves from `release-gap` to `pending-evidence`, not to `supported`. An output that is compared only as a host difference proves no parity. 4.1 still names this seam.

## Consequences

- Scripts that read the default export folder get a stable UzPainter location. The location stays the same across create, save and reopen, and the call has no side effect on disk.
- The 18 P22-B recordings remain the other open part of 4.1.

## Amendment: facade compatibility, 2026-10-20

The owner delegated routine technical decisions to Claude and Codex and requested closure of the
remaining API tasks. Codex's root and delegated reviewer agreed on the following amendment after
reading both admitted P21-B s3 outputs and the public API documentation. This replaces the facade
behavior and comparison in the original decision; it does not change the native directory policy.

1. **Evidence.** `python-doc/substance_painter/export.html#get_default_export_path` says the
   application default is independent of the project. In both admitted P21-B recordings, s3 returns
   `<recording host Documents>/Adobe/Adobe Substance 3D Painter/export`, with forward slashes.
   The application directory names are observed interface data. No Adobe implementation source or
   resource is needed to reproduce this string.
2. **Facade only.** `substance_painter.export.get_default_export_path()` derives Documents from the
   existing private native getter's `<Documents>/UzPainter/export` result, appends
   `Adobe/Adobe Substance 3D Painter/export`, and returns the path with forward slashes. The user
   name is never a literal. Redirected Documents and Unicode components come from the Known Folder
   lookup. This is a path calculation: it does not inspect, create, open, read, or write an Adobe
   directory, query Painter, or use that directory for any export.
3. **Native unchanged.** `uzpainter.export._default_export_path()` still returns its own
   `<Documents>/UzPainter/export` location, with the same failure behavior and no filesystem side
   effects. `Settings.export_path` remains independent. Export without explicit `exportPath`
   continues to raise the recorded ValueError; no implicit destination is introduced.
4. **Exact comparison.** Remove s3 from the observed replay's exclusions. Compare its returned
   path literally with each golden output, without username substitution, slash normalization,
   or host-difference credit. The replay remains a recording-host test; equality on another
   machine is not presumed. Separate contract tests check both native and facade paths, lifecycle
   stability, no directory changes, and a redirected Unicode Documents path.
5. **Status.** Keep the capability `pending-evidence` until the non-excluded P21-B replay actually
   passes and its trace is validated. This amendment itself promotes no symbol and closes no gate.

Validation: the non-excluded P21-B replay passed against both recordings on 2026-10-20,
together with the native/facade path contracts (including redirected Unicode Documents and no
filesystem writes). Evidence is in `parity/reports/phase1/python-api-facade.md` section 9.
Trace/inventory reconciliation remains the coordinator's step before capability promotion.
