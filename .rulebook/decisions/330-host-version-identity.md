# 330. The application version UzPainter reports is its own, not Painter's; P22-B host replays record it as an explicit host difference

Date: 2026-10-20. Status: accepted (Claude and Codex; routine technical choice delegated by the owner).
Related: phase1.24_python-api-facade item 4.1, decisions 297, 319 and 320, docs/architecture/10-python-api.md §4 (Versions row).

## Context

`p22b-host-application` records Painter's version in three places: `application.version()` (s3), `version_info()` (s4) and the JavaScript `alg.version.painter` (s20). They return 12.1.5. UzPainter reports its own version, 0.0.0 today. Reporting 12.1.5 would claim to be a Painter build UzPainter is not. Scripts that branch on the version would then take Painter-specific paths without the behaviour behind them.

## Decision

1. **The version is UzPainter's own.** `application.version()`, `version_info()` and `alg.version.painter` return UzPainter's version, as 10-python-api.md §4 says.
2. **Replays record a host difference, not an exclusion.** The host replay compares s3, s4 and s20 as a host difference that names this decision. They are not literal parity, and no symbol is credited from them.
3. **Two items stay open seams of phase1.24 item 4.1:**
   - `TextureStateEvent` emission. Painter delivers its UPDATE dispatches, and UzPainter emits none yet. The replay drops only those dispatches and fails if the facade ever emits one or the golden loses them. The UPDATE also lands in different steps in Painter's two recordings (s8 and s7), so its timing is unstable in Painter itself.
   - The reload outputs of `p22b-host-resources` (s24, and r2 s20), marked BLOCKED with no credit. They wait on the replay harness's REWRITE_ARGS copy and on a native shared-bytes rule (`CheckResources`: entries with one SHA-256 but different mimes).

## Consequences

- Item 4.1 keeps these named seams. Nothing here claims Painter's version.
