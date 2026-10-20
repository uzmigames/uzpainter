# Authored BC decoder: sources and numerical contract

This is the source and algorithm record for UzPainter's own test-only BC1,
BC3, BC4, BC5 and BC7 UNORM decoder. Implementation and validation are separate:
this document records no passing test, completed task or GPU parity result.
BC2, BC6H and signed RGTC decoding are outside this slice.

## Approved inputs and attribution

The approved-source index entries S-BC-MS, S-BC-KHR and X-BC-TEST-REFERENCE
cover the sources below. All were consulted on 2026-10-20. The Khronos registry
host returned HTTP 403 for S3TC and RGTC, so the official KhronosGroup repository
was used, not an unofficial implementation. Raw downloaded bytes and a retrieval
manifest are kept in `tmp/scratch/bc-decoder-sources/` (untracked).

The implementation is authored here, but is not represented as independent of
all open-source implementations: the existing bcdec CPU formulas were inspected
to preserve the measurement contract. bcdec remains a test oracle only; the new
decoder must not invoke it. BC7 partition and anchor constants are reused from
Richard Geldreich, Jr.'s bc7enc.cpp under MIT, pinned with etcpak 2.1 commit
`7f15da4739cc5f8562311bdbb800436986d268ca`. NOTICE attributes that reuse; the
complete licence and exact file hashes remain in `thirdparty/etcpak/`.

The oracle has one recorded local fix: initialise BC7 endpoint storage before
RGB-only modes shift the otherwise unread alpha component. The authored random
corpus exposed this undefined read in ReleaseSafe; the same case passes with
initialisation and with sanitizers still enabled. `tools/vendoring/thirdparty.py`
records the reproducible patch, and the generated ORIGIN and manifest retain it.

## BC1, BC3, BC4 and BC5

Blocks address a 4 by 4 texel region, with little-endian endpoints and packed
indices. BC1 uses RGB565 endpoints and two-bit selectors. Endpoint ordering
selects four colors or the three-color/transparent case. BC3 uses an independent
alpha palette and always uses the four-color RGB palette. BC4 decodes one scalar
palette; BC5 decodes two independent scalar palettes, red first, then green.

The public specifications describe weighted interpolation. They do not make the
following byte-level CPU convention a claim about every GPU implementation:

- Expand a 5- or 6-bit endpoint component by nearest integer to
  `value * 255 / ((1 << bits) - 1)`.
- RGB thirds use integer `(2*a + b + 1) / 3` and `(a + 2*b + 1) / 3`;
  the half uses `(a + b + 1) / 2`.
- The interpolated alpha/scalar entries use weighted endpoint sums with a
  numerator bias of 1 before division by 7 or 5, matching the existing bcdec
  byte-output convention. This is not general round-to-nearest for those
  denominators. The short palette also has explicit zero and 255 entries.

These rules preserve the prior CPU metrics contract; compatibility must be
checked against the pinned bcdec oracle and authored edge cases. S3TC specifies
component-wise thirds and halves; RGTC specifies endpoint-index palettes.
RGTC issue 12 explicitly leaves texture-filtering precision unspecified. That
statement concerns filtering, and must not be misquoted as a numeric decoder
error bound. No numeric BC1-5 hardware tolerance was established from these
consulted pages. No exact GPU decoding equivalence is claimed.

## BC7, all eight modes

Modes 0 through 7 are required, including partitioned RGB modes and modes with
alpha. The authored implementation reads the unary mode prefix, mode-specific
endpoint fields, partition identifiers, shared or per-endpoint P-bits, and
indices with omitted anchor MSBs. It expands endpoint precision by bit
replication, selects each texel's subset, handles the separate index streams
in modes 4/5 and the index selector in mode 4, and applies channel rotation
after interpolation.
Modes without explicit alpha produce 255 alpha.

Microsoft's BC7 specification gives weights:

- Two-bit indices: `0, 21, 43, 64`.
- Three-bit indices: `0, 9, 18, 27, 37, 46, 55, 64`.
- Four-bit indices: `0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64`.

Each interpolated byte is `((64-w)*e0 + w*e1 + 32) >> 6`.
The mode-reference page determines field widths and subset counts; reused
partition/anchor tables supply format constants, not the decoding algorithm.
Validation must exercise all eight modes, both relevant endpoint orderings for
older formats, and malformed/edge blocks according to the wrapper contract.
Random-block agreement alone does not replace structured mode coverage.

## Retrieval record

SHA-256 values identify the bytes actually consulted, including HTML for
Microsoft pages; mutable upstream URLs alone are not revision pins.

| Source | Retrieved URL | SHA-256 |
|---|---|---|
| bc1 | https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression | `c1f3cc37233d7cb51052859db32a1bfb0c0aa6a155fa3021646edfde3dae6045` |
| bc7 | https://learn.microsoft.com/en-us/windows/win32/direct3d11/bc7-format | `7b4aaa85f9dda6de068ba1e0920800ee5009c57d999e5d2d304adb05026fa175` |
| bc7modes | https://learn.microsoft.com/en-us/windows/win32/direct3d11/bc7-format-mode-reference | `0ead94d512254b49afe80cc442aaf1a913eef518d49fee4c7b3194528b2a015b` |
| s3tc | https://raw.githubusercontent.com/KhronosGroup/OpenGL-Registry/main/extensions/EXT/EXT_texture_compression_s3tc.txt | `4b8064e3032ebef0f2afdef6c38f2d758d1911f759eeeceac904b0d81f301c4c` |
| rgtc | https://raw.githubusercontent.com/KhronosGroup/OpenGL-Registry/main/extensions/ARB/ARB_texture_compression_rgtc.txt | `50c88794181bf2f6f589de7ce135f42efbfc442fd44149a0684b9f26c9314922` |
| bptc | https://raw.githubusercontent.com/KhronosGroup/OpenGL-Registry/main/extensions/ARB/ARB_texture_compression_bptc.txt | `ab85a0e9b885a0fa1d23e18606b4bad1ab1eacc2bc18011806ea43d9c51bf666` |
