# 320. `export.get_default_export_path` returns UzPainter's own export folder under the user's Documents Known Folder; it is a host policy, not Painter-path parity, and the symbol stays pending evidence

Date: 2026-10-20. Status: accepted (Claude and Codex, SUP-160/162/164; routine technical choice delegated by the owner).
Related: `phase1.24_python-api-facade` item 4.1, decision 319, decision 113, golden `tier0/api-probes/phase1-create-default-paths` (P21-B).

## Context

In both P21-B recordings, `get_default_export_path()` (s3) returns the recording host's Documents export folder of Painter. The value depends on the host and on Painter's own folder layout. UzPainter keeps its own folder and does not reuse that path. Until now the facade did not have the symbol (AttributeError), and P21-B s3 was an open item of 4.1.

## Decision

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
