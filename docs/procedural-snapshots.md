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
and the actual mesh resource hash come from that document. A hash of the import
report, excluding source-file metadata, also pins external glTF buffers and mesh
derivation settings. Older signatures lacking that hash do not match projects
with an effective import report and require a new capture; their stored rasters
remain intact. The native command
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

## Explicit fill evaluation and export

An explicit native `ProceduralRef` can bind the recorded asset pin, every effective
parameter and a singleton output mapping to a User channel. The current evaluator
admits only User L32F on the authored full-UV 128-square plane, tile 1001, with the
recorded Legacy settings and identity UV projection. It never selects a snapshot
implicitly, guesses an output, resizes its raster or invokes a procedural family.
The public `SourceSubstance` facade is not enabled by this path.

The signature seed comes from the effective `$randomseed` integer parameter;
absence means zero. Signed int64 values retain the same uint64 bit representation
used by snapshot ingestion. A different seed changes the signature, and floating
or boolean seed values are refused before mutation or evaluation.

The provider loads the authoritative project-private plane and uploads its float32
bits directly. Signature, raster digest and plane provenance participate in DAG
hashes. Memory and persistent cache reads recheck the authoritative plane;
missing, corrupt or foreign data cannot be served by a previously cached result.
Mutations reject unsupported final states atomically. Native transactions may
temporarily resize or rebind a source, provided their final state is supported.
An unrelated edit remains possible when the project already contains an
unsupported reference.

Scalar EXR32f passthrough export retains the recorded values after original-project
reopen and bundle import. Export receipts list `procedural_snapshots` with signature,
project UUID, plane/version ids, chunk root and raster SHA-256; a plane is not
misreported as an imported resource hash. Recipe rebuild explicitly refuses these
project-private dependencies because recipes do not transport their planes. Reopen
the original project or import its bundle instead.

CPU integration evidence: `tests/python/test_snapshot_source_export.py` drives
`tests/export/snapshot_source_test.cpp`, compares every exported float32 bit and
checks receipt schema, transaction rollback, persistent hits, corrupted retained
inputs and a foreign store UUID. This synthetic transport test establishes no new
Painter parity or certified editable procedural domain.
