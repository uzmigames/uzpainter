# Origin of stb image_write

| Field | Value |
|---|---|
| Upstream | https://github.com/nothings/stb |
| Release | `stb_image_write v1.16` |
| Tag commit | `003501f6d7a8668ce8b6d875e34dd97ad0d5d5b5` |
| Archive | https://codeload.github.com/nothings/stb/tar.gz/003501f6d7a8668ce8b6d875e34dd97ad0d5d5b5 |
| Archive SHA-256 | `a6c31950b3bdf05eb92258768ba2a11bd44449490574b1aac67028452288c40d` |
| Archive root | `stb-003501f6d7a8668ce8b6d875e34dd97ad0d5d5b5/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-23 |
| Importer | Rulebook task phase3.2_unreal-ue56-packed-preset, tools.vendoring.import_thirdparty |
| Version source | UzPainter selection: TGA8 writer, phase3.2_unreal-ue56-packed-preset item 2.5; upstream HEAD pinned on 2026-10-23 |
| Licence | MIT (chosen from upstream's MIT/public-domain dual licence) |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | shipped: compiled privately into the export TGA writer |
| Selected features | Memory-only TGA8 writer; STB_IMAGE_WRITE_STATIC and STBI_WRITE_NO_STDIO; no public stb globals |
| Include directories | `thirdparty/stb/` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (2)

- `LICENSE` (2,510 bytes)
- `stb_image_write.h` (71,221 bytes)

## Comparison with UzEngine's copy

Selected independently for UzPainter's TGA writer; no UzEngine source copied
