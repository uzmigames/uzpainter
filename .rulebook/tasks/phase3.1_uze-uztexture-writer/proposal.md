# Proposal: phase3.1_uze-uztexture-writer

## Why
OWN-06 and EXP-08 (`docs/prd.md`) require compressed UzEngine textures (`.uztexture` with BC7/BC5/BC4); EXP-10 requires explicit engine format metadata per map and signed normals kept at authoring precision. Owner decision 023 (Q10) fixes these formats; decision 021 (Q8) forbids linking or calling UzEngine code, so UzPainter writes `.uztexture` itself: only the vendored header `engine/asset/formats/uztexture_format.h` is kept, as the format definition, and its `WriteUzTexture`/`ReadUzTexture` declarations are not implemented in UzPainter's build (`docs/architecture/13-engine-integration.md` §2.1, §2.4). Mip generation and the `.uztexture` writer are UzPainter-owned code (`13-…` §4.1). Child of P3-UZE (`phase3.4_uzengine-preset`), implementing D7: `docs/architecture/08-export.md` §3 (DDS/BC row: etcpak behind an encoder adapter, CPU, deterministic) and §4 (UzEngine preset table and mip rules).

## What Changes
- **BC encoder adapter** (Exporter component): etcpak with its bundled bc7enc behind an adapter interface; BC1/BC3/BC4/BC5/BC7 including the sRGB variants; CPU only; fixed quality settings, fixed block order and output independent of thread count; bc7enc_rdo stays a replacement candidate behind the same interface (`08-export.md` §3). Dependency inventory, `NOTICE` and `LICENSES/` entries confirmed for etcpak (BSD-3-Clause) and bc7enc (MIT/Unlicense) per `docs/licensing-and-clean-room.md` §3 (LIC-02).
- **Mip generation**: full chains; sRGB-aware filtering for colour maps (decode, filter in linear, re-encode); renormalised normals; alpha-coverage-preserving mips for masked albedo (`08-export.md` §4).
- **`.uztexture` writer** from the constants and layout of the vendored format definition, carrying explicit format, colour space, binding and mip metadata per texture (EXP-10); height written as BC4 with explicit format metadata instead of the cooker's default BC7 sRGB rule.
- **Normal guard**: BC5 two-channel normals; texels with negative Z are detected before encoding and the export either fails or routes the map to an RGB format, as configured in the export plan and recorded in the receipt; Z is never silently reconstructed (`08-export.md` §4 normal row).
- **Test-only decoder**: BC block decoder and `.uztexture` reader used by tests and by the lossy-derivative comparison (`14-parity-testing.md` §4); never shipped as a UzEngine substitute.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Delivered upstream and used here: `phase1.18_export-engine` (plan compiler, receipts, generational publication), `phase0.5_vendor-render-core` (vendored `uztexture_format.h`).
- Parent: `phase3.4_uzengine-preset`. Next child: `phase3.2_uze-uzmat-preset`.
- Consumer outside the parent: `phase3.2_unreal-ue56-packed-preset` uses the BC encoder adapter for its optional DDS BC7/BC5 variant.

## Acceptance
Part of the P3-UZE gate ("preset loads and renders in the external UzEngine fixture; gaps listed"). This child is accepted when: BC encoding and mip generation are byte-identical across two runs and across thread counts; the mip rules hold on authored fixture images; written `.uztexture` files match the layout of the vendored format definition; negative-Z normals never encode silently; and the decoded compression error against the canonical map is reported as a separate lossy-derivative contract, never as authoring equality.

## Impact
- Affected specs: `export` (`.uztexture` writer, BC encoding, mips)
- Affected code: Exporter component (encoder adapter, mip generation, `.uztexture` writer, test decoder); `thirdparty/etcpak/` with its `ORIGIN.md` and licence files; `NOTICE`, `LICENSES/`
- Breaking change: NO
- User benefit: compressed, mip-mapped UzEngine textures with explicit metadata, reproducible byte for byte
