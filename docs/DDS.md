# DDS writer and cook

`src/export/dds.h` writes one 2D texture with the DDS DX10 header.
`src/export/cook_dds.h` cooks canonical RGBA16 samples through the existing
`GenerateMipChain`, `QuantizeTo8` and `EncodeBc` policies. Both are CPU libraries.
Owner: `phase3.2_unreal-ue56-packed-preset`, item 2.6.

| Input format | DXGI format | Stored channels |
|---|---|---|
| `BcFormat::Bc5` | `BC5_UNORM` (83) | R, G |
| `BcFormat::Bc7` | `BC7_UNORM` (98) | R, G, B, A |
| `BcFormat::Bc7Srgb` | `BC7_UNORM_SRGB` (99) | sRGB R/G/B, linear A |

`WriteDdsFile` takes encoded mip blobs, largest first. It accepts positive
dimensions and partial chains up to the complete chain length, including
non-power-of-two sizes. Each level occupies exactly
`ceil(width / 4) * ceil(height / 4) * 16` bytes. Dimensions halve with a minimum
of one. Invalid format, mip count, blob size or integer/buffer limit is refused.

The first payload byte is at offset 148: magic, 124-byte DDS header, then
20-byte DX10 extension. Header fields are written explicitly in little endian;
no host structure layout is serialized. One array element, 2D resource, no
cube/volume flags, unknown alpha mode. Mip flags and complex-surface capability
are set only for multiple levels. Metadata records each mip's dimensions,
offset and size. Callers hash the complete returned byte buffer for receipts.

`CookDds` requires power-of-two sides and emits every level through 1x1.
Colour and masked-colour mips require sRGB BC7; linear data and normals require
linear storage. Inputs retain their supplied green convention. BC5 normals
with negative Z are refused before compression; BC7 can preserve the B channel.
Normal renormalization, sRGB filtering, alpha coverage, 16-to-8-bit rounding,
block padding and encoder settings come from the existing mip/BC components.

## Native export opt-in

`RequestDds(plan, project, relativePath, format, mipClass)` attaches a DDS
companion to an already planned PNG16 file and recomputes the plan hash.
The canonical file stays byte-for-byte unchanged. Normal companions require
RGB from `Normal_DirectX`; data/colour companions must match their stored
transfer and mip class. Windows path collisions, including case and
file-versus-directory conflicts, reject the request without changing the plan.

Encoding cooks every requested companion before writing any files. Direct
writing, dry-run lists, generational publication and fixed-name delivery all
include the DDS immediately after its canonical file (after an optional
`.uztexture`, before a material). `kill_after_dds` tests an interruption before
the new generation is committed.

Each receipt includes the DDS's complete-file hash, canonical source path,
format, sRGB flag, mip count, encoder/settings, stored channels and `lossy: true`.
Its `layout`/`channels` describe the canonical mapping; `dds.stored_channels`
states RG for BC5 or RGBA for BC7. The canonical file has its own receipt/hash.

This is an explicit native C++ API, separate from Painter's JSON configuration.
It does not ship the Unreal preset or establish UE 5.6 consumer acceptance.
Item 2.6 also requires the DDS preset variant, whose observed-output and
provenance prerequisites remain open.

## Sources

`S-DDS-MS` in `docs/approved-sources.md` clears Microsoft's public DDS header,
pixel-format, DX10 extension, programming guide and DXGI format definitions,
retrieved 2026-10-20. The writer is authored from those format definitions.
No third-party DDS implementation is copied.

## Validation

`zig build uzp-dds-tests` builds the native driver;
`python -m pytest tests/export/test_dds_writer.py` exercises it and opens
generated BC5/BC7 files with Pillow's independent DDS decoder. The tests cover
headers, mip payloads, refusal paths, cook semantics and thread determinism.
Pillow is a development-only decoder on the owner's machine.

`tests/export/test_dds_publication.py` checks native opt-in planning, direct
writing, publication, fixed-name delivery, receipts, interruption and refusal
using authored fixtures. The task's evidence sections record the measured
build modes and preserve the distinction between these checks and UE/Painter
acceptance.
