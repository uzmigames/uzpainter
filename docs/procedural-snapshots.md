# Project-private procedural snapshots

`UzPainter.exe assets snapshot <project.uzp> --request <request.json>` records a
frozen raster through the owner's locally running, licensed Painter. Start Painter
with its documented `--enable-remote-scripting` option and close its current project
before running the command. The destination `.uzp` must also be closed in other
UzPainter processes. No external Python installation is required: the command uses
UzPainter's isolated embedded CPython and its shipped recording bridge.

The request has exactly two fields:

```json
{
  "resource": "resource://<shelf>/<resource>?version=<exact-version>",
  "parameters": {}
}
```

Use the exact `Resource.identifier().url()` of a documented `PROCEDURAL` Substance
resource. `parameters` supplies finite scalar overrides; an empty object keeps the
source's effective defaults. The recorder reads all resulting parameters back.
Unversioned resources, image inputs, multiple outputs, vectors and colours are
outside this initial recording domain and are refused. No substitute asset or
compatibility alias is selected.

## Supported capture domain

The destination must contain the exact authored mesh installed at
`assets/snapshot/plane.obj`, including its original byte identity. Project settings
must use the default workflow, Legacy colour management (the native empty mode
also denotes Legacy), OpenGL normals, PerVertex tangents and mesh scale 1, with no
colour configuration, working-space override or I/O rules. Painter must use its
documented Legacy environment selection: neither `OCIO` nor `PAINTER_ACE_CONFIG`.

The recorder creates its own disposable project with a 128 by 128 texture set. It
removes that new project's initial layers and creates one visible fill layer with
User0 L32F and User1 RGB32F. Both sources have identical effective parameters and
the same singleton output, no image inputs, Auto resolution with zero offset,
identity UV projection, nearest filtering, no wrapping, Normal blending and opacity
1. Auto resolution follows the fill's texture set, as documented by A-PYDOC.

Before and after exporting, readbacks verify the full root-layer list, absence of
content effects and masks, layer visibility, channel formats, projection, source
state, texture-set resolution and absence of UV-tile workflow. Each mutating or
capture operation checks the owning Painter process and unique imported mesh path.
A different open project is never closed. Shelf crawling must finish before the
exact resource lookup; project readiness alone does not imply resource readiness.

Two exports of each channel use EXR float32 with passthrough padding and no
dithering. Every scalar texel must match each RGB component and its repeat at the
float32 bit level. No conversion, resampling, tolerance or extrapolation is applied.
These controls establish this narrowly defined full-coverage capture recipe. They
do not certify a procedural implementation or generalize to arbitrary meshes,
projections, material outputs or parameter families.

## Storage and result

The destination stays locked during recording. UUID, revision, evaluation settings
and the actual mesh resource hash come from that document. The native command
checks returned identity, signatures and file hashes, decodes the exports at their
native precision, and writes one store transaction. It then saves, closes, reopens
and checks `SnapshotBackend.Stored` against the decoded capture before reporting
success. Preflight and capture refusals do not submit a transaction.

The private asset pin is `uzasset://snapshot/<sha256>@1`, where the digest names the
complete observed, versioned ResourceID. This is a snapshot identity, not an asset
library alias or a certification. The full signature, including effective defaults,
is available in the receipt. A different signature is unavailable; capturing a
snapshot does not make its parameters editable.

The command prints one `UZP_JSON:` result with the asset pin, signature hash,
committed revision, `verified_after_reopen` and receipt path. Errors return exit
code 3; malformed command-line usage returns 2. Private requests, readbacks, exported
pixels, recorder hashes and receipts remain under
`%LOCALAPPDATA%/UzPainter/snapshot-recordings/`. They are never installed as assets
or committed to the repository. The raster itself is embedded in its destination
`.uzp`; copying a reference into another project does not copy the snapshot.

Run `UzPainter.exe inspect <project.uzp> --verify` to inspect the stored entry and
project integrity. The recording command requires no local GPU evaluation by
UzPainter; Painter alone computes the captured source.
