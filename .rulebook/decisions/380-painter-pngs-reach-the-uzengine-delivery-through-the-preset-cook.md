# 380. Painter PNGs reach the UzEngine delivery through the preset's own cook

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase3.3_uze-png-cook-cli, phase3.2_uze-uzmat-preset, phase3.4_uzengine-preset

## Context

On 2026-11-02 the owner ordered, through the Assets3D session, that UzEngine's standard formats are `.uztexture` and `.uzmat`, with the texture organisation modelled on Path of Exile 2: packed channels and block compression. That is organisation only. GGG's formats are proprietary, and nothing of them is copied. UzPainter already writes both natively: the `.uztexture` writer (decision 315), the `.uzmat` writer, the BC encoder and mips, and the UzEngine preset (`phase3.2_uze-uzmat-preset`). The Assets3D pipeline still paints in Substance Painter, and it must produce the SAME files.

The Assets3D session added its input: Painter exports three 8-bit PNGs per set (BaseColor, Normal, an ORM already packed R = AO, G = roughness, B = metallic). A 16-bit master may exist. Emissive and height are optional, and the pilot is opaque, so BaseColor may have no alpha.

The panel (`cx/gpt-6-astra`, `cx/gpt-6.1-sol`, `xai/grok-4.6`, `kimi/kimi-k3`) agreed 4/4 on the conditions below.

## Decision

1. **One code path.** `UzPainter.exe cook-uzengine` cooks each texture with write.h `CookUzEngineDerivative`, and writes the `.uzmat` with `WriteUzEngineMaterial`. Both functions are extracted from `EncodeExport`, which now calls them too. The targets are read from the shipped `uzengine` preset: binding, format, colour space, mip class, negative-Z policy and file names. There is no second implementation.
2. **Equality.** Equality is defined on the decoded input pixels, the options and the encoder version. Each input becomes a 16-bit RGBA image: an 8-bit code becomes code * 257, grey becomes R = G = B, and a missing alpha becomes 1. Equal images give equal bytes. The receipt records each image's hash (`decoded_rgba16_sha256`) and each file's encoder, `etcpak 2.1`, with its fixed settings.
3. **Input contract.**
   - PNG 8 or 16 bits: grey, grey + alpha, RGB or RGBA. Palette, sub-8-bit and tRNS images are refused. Colour chunks are not applied.
   - BaseColor and emissive are sRGB-encoded. Every other map is linear.
   - The normal convention must be stated (`--normal-convention opengl|directx`). The preset stores `Normal_DirectX`, so an OpenGL green is mirrored (65535 - G). Dithering is off on the exporting side.
4. **Mip filters are the preset's.** sRGB-aware masked colour for the albedo (alpha coverage at its cutoff 0.5), linear per channel for ORM, height and SpecularWeight, renormalised normal, and sRGB colour for emissive.
5. **Opacity follows the preset.** It is the albedo alpha. No alpha, or an alpha of 1 everywhere, means opacity 1 and `Opaque`, and the receipt says which. Neither the blend nor two-sidedness is an option, because that would change the preset's semantics.
6. **Maps.**
   - The ORM comes either packed (`--orm`) or as three grey maps (`--ao`, `--roughness`, `--metallic`).
   - Without `--emissive`, the emissive texture is black, which is what the preset cooks for a black emissive channel. The `.uzmat` binds four textures. The receipt marks the emissive `synthesized`.
   - Height and SpecularWeight are optional, BC4, with the preset's gaps.
7. **Refusals, loud and before any write.**
   - a missing or invalid map;
   - mismatched sizes;
   - a side that is not a power of two, which the mip chain cannot tile;
   - a non-opaque alpha outside the albedo;
   - a non-grey map where grey is required;
   - a grey normal;
   - negative-Z normal texels (policy `fail`);
   - an unsafe set name. The name is one stem: no `/`, `\`, `:` or `..`. It is then checked as a delivery path by `WriteUzMaterial`, so the `.uzmat` holds only safe relative `/` paths.

## Consequences

The Assets3D pipeline can deliver UzEngine's standard files from its Painter exports. `tests/export/test_uze_png_cook.py` shows four things:
- a native export's canonical PNG 16 maps cook to its own `.uztexture` and `.uzmat` bytes;
- 8/16-bit, OpenGL/DirectX, opaque-alpha and separate-ORM forms of one decoded image give equal bytes;
- runs are deterministic;
- every refusal writes nothing.

A Painter 8-bit export is NOT the same input as UzPainter's 16-bit canonical maps, so it matches the native files only where the decoded images match. Whether UzEngine loads the files stays with `phase3.3_uze-consumer-fixture`. Decision numbers 381-383 stay reserved to front D.
