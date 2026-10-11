# 65. Normals carry an EXP-09 tag with a content relief round, the method is a per-texture-set document field, and unrecorded normal inputs are requested

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.12_compositor-height-normal

## Context

EXP-09 asks that authored relief is applied exactly once: every exported or previewed normal is tagged `geometry_only` or `combined` with the relief round it contains (Assets3D: an older combined normal plus a newer Height was relief applied twice). The term "relief round" is not defined in the architecture. Decision 047 made the height-to-normal method a per-texture-set setting with no documented API. Decision 064 leaves inputs unrecorded: a Normal mesh map, other resolutions, SignedAddition on Height, Normal-channel partial coverage, DirectX projects. The same panel run as decision 064 ruled on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| Tag {combined, relief round = (revision, Height read-out subtree hash, method)}; geometry-only pass-through = the mesh map's codes, green inverted across conventions, refused without a mesh map | PARTLY x3: the hash must cover every effective Height dependency (it does: profile, channel, format, base, resolution, layers, sources, masks); the pass-through needs matching resolution and encoding, and is itself unobserved. |
| GPU = CPU via a raw float32 read-out blend and a 3x3-tile kernel | DISAGREE x1, PARTLY x2: equal source is not enough; mirror explicit float32 rounding, use the same tables, test halo reads across tile seams and set borders. |
| Recording requests for the open cases | AGREE x3; add 8- and 16-bit Normal imports in a DirectX project, a reopen variant, and other resolutions. |
| Method as an optional manifest field, absent = Sharp, no format bump | AGREE x1, PARTLY x2: acceptable when no older reader can render the field's meaning silently wrong. |

## Decision

1. Every virtual normal result carries `NormalTag {role, relief}`: `combined` with `ReliefRound {revision, heightHash = hex SHA-256 of the Height read-out subtree, method}`; the geometry-only pass-through carries `geometry_only` and no relief round. The relief round changes with the Height content or the method and not with other channels.
2. The geometry-only pass-through is the bound Normal mesh map at the set resolution, 8 or 16 bits, its codes as UNORM operands, green inverted (max - g) when the requested convention differs from the map's (imported: its declared convention; baked: the project's). Without a Normal mesh map it fails with `missing_resource`; any other size or encoding with `unsupported_source`.
3. GPU = CPU is proven by the `height-normal-gpu-vs-cpu` case: the kernel over a 3 x 3 grid of tiles (halo reads across every tile edge and the set border), the raw read-out on every channel format, whole evaluations, bit for bit.
4. `TextureSet::height_to_normal_method` (`Sharp` | `SmoothSobel`) is an optional manifest key, absent = `Sharp` (a new Painter project's default), written always, no format-version bump: no earlier UzPainter evaluates virtual normal maps, so no older reader can render it wrongly.
5. Items 3.1 (SignedAddition on Height) and 3.3 (mesh normal map with both conventions) stay open on recordings, whose exact specification is in `parity/reports/phase1/compositor-height-normal.md` §5 and the task report.

## Alternatives Considered

- A relief round as a counter of Height edits (rejected: a content hash identifies the relief across sessions and copies).
- Bump the manifest format to 1.1.0 (rejected: an additive optional key, preserved verbatim by any reader, read by the only code that uses it).

## Consequences

Export and adapters (phase1.15, phase1.17, phase3.2) receive the tag with each normal and can refuse to add Height to a `combined` normal. The open items wait for the recording task; nothing unrecorded is evaluated silently.
