# Unreal Engine 5.6 consumer fixture on the pilots (phase3.2_unreal-ue56-packed-preset items 2.8, 3.2, 3.3, 3.5)

Date: 2026-11-10. Consumer-matrix row 8 (`docs/architecture/08-export.md` §5.1). Every hash below
is of UzPainter's own output; no Painter output is published here.

## Setup

- **UE.** Unreal Engine 5.6.1 (changelist 44394996, `++UE5+Release-5.6`) at `W:\UE_5.6`, pinned by
  `parity/manifests/consumers/unreal/wand-v1.json` (status `partial`).
- **Project.** The owner's fixture folder `W:\UE_Projects\UzPainterFixture`, created once by
  `tools/consumers/unreal.py ensure_project` and reused. It holds a content-only `.uproject`
  (Python Editor Script Plugin, Editor Scripting Utilities), its own derived-data cache graph
  `UzFixtureDDC` (`%GAMEDIR%DerivedDataCache`, Zen not launched) and `DirectoriesToAlwaysCook`
  `/Game/UzFixture`. Its `Saved`, `Intermediate` and `DerivedDataCache` stay there.
- **Import method.** UE's documented Python commandlet:
  `UnrealEditor-Cmd.exe <project> -run=pythonscript -script=tools/consumers/unreal_ue.py -nullrhi -unattended`.
  Each file goes through `unreal.AssetImportTask` (automated) and `AssetTools.import_asset_tasks`,
  so UE's default importer (Interchange) runs. The fixture then:
  - records the settings UE gave each texture;
  - applies the binding;
  - exports each texture's source through UE's own exporter;
  - builds one material.
- **Cook.** `-run=cook -targetplatform=Windows`.
- **Delivery.** Through the generation-pinning adapter (`08-export.md` §5):
  - `current.json` is read once;
  - the receipt and every file are verified by size and SHA-256;
  - only those bytes are staged into `Import/<fixture>/<variant>/<generation>/` and verified again.

## Results

### PNG 16 on the three pilots

`tests/parity/tier1/test_unreal_consumer_pilots.py` (`UZP_TIER1_PRODUCTION=1 UZP_UE_FIXTURE=1`) ran:
3 passed in 2158.8 s, ReleaseFast DX12.

Each pilot is first rebuilt and compared with Painter as item 3.1 does. In the same run every
covered BaseColor and ORM texel equals Painter's r1, and the Normal differs only on island-edge
texels (EXC-014). UE then imports the first rebuild's published generation.

| Pilot | Map | Published file (SHA-256) | Size | UE as imported | UE as bound | Source equals file |
| --- | --- | --- | --- | --- | --- | --- |
| Wand v1 | BaseColor | `7af73490c2552c781769993587ee7ace99fc3743c6320c2f34230b3af9d5add6` | 2048² | sRGB, TC_Default | sRGB, TC_Default | yes, 16-bit |
| Wand v1 | ORM | `435a032ab9d5c6e35c0e621f3ed1a7ad404c041c20b79fdc25c0d4947bb1d97e` | 2048² | sRGB, TC_Default | linear, TC_Masks | yes, 16-bit |
| Wand v1 | Normal | `f0a29aff8e269e752bb1717daef6609dbc4d85612e33545629c27ef4a6e161c5` | 2048² | linear, TC_Normalmap | linear, TC_Normalmap, green not flipped | yes, 16-bit |
| Sash v5 | BaseColor | `03834889a67b4de4f865926495ebea3f86c2d0ebe28e4ee751ec34f7cb2752a1` | 2048² | sRGB, TC_Default | sRGB, TC_Default | yes, 16-bit |
| Sash v5 | ORM | `56bb2e545b45b5bc9810145f5463e95005b952209f7e389dc72db20573bddb85` | 2048² | sRGB, TC_Default | linear, TC_Masks | yes, 16-bit |
| Sash v5 | Normal | `b478b4950c74af8859f19b8d937bab98a52b666e2465d0dc684bdab727edb489` | 2048² | linear, TC_Normalmap | linear, TC_Normalmap, green not flipped | yes, 16-bit |
| Tunic v10 | BaseColor | `53ee651b31d0aa6b9968874e353277625086165960a662091c864aeb41644327` | 4096² | sRGB, TC_Default | sRGB, TC_Default | yes, 16-bit |
| Tunic v10 | ORM | `48251232c94f7331d76986ca1e8babc3ee781049c7bc898bcb0e0c576e746d90` | 4096² | sRGB, TC_Default | linear, TC_Masks | yes, 16-bit |
| Tunic v10 | Normal | `78c7b62df0c6ee3239a64b91f8146cd7ac2fac39329054b586a3801b05927370` | 4096² | linear, TC_Normalmap | linear, TC_Normalmap, green not flipped | yes, 16-bit |

On every pilot, the material binds the maps as follows:

| Material input | Source | Sampler |
| --- | --- | --- |
| Base Color | BaseColor RGB | Color |
| Ambient Occlusion | ORM R | Masks |
| Roughness | ORM G | Masks |
| Metallic | ORM B | Masks |
| Normal | Normal RGB | Normal |

The links read back to their textures. No pilot has an Emissive, Opacity or SpecularWeight
channel, and every receipt lists `_Emissive` and `_SpecularWeight` as skipped.

### TGA 8 on Wand v1

A third build of the Wand exports the same configuration with `fileFormat: tga`, `bitDepth: 8`.
Its `dithering: false` is the pilot's own setting, which TGA 8 requires. UE imports its three
files with the same bindings:

| Map | Published file (SHA-256) |
| --- | --- |
| BaseColor | `dd990f863aaaafcb09f9c45605bd7016c8ae8005091da6f3c5429ae2d217635e` |
| ORM | `cf250baeced2758d982fb604fc5c734425ff07b592c8860591f3abd77b21e2fa` |
| Normal | `adbcc26317afe22e17c6fcc1ad0e63fff6b8709ef160350cd5b2bcfb1c3939e4` |

UE's source equals each file at 8 bits.

### The Windows cook

The cook of the fixture's content took 606.6 s: 0 errors, 0 warnings. It compiles both Wand
materials. Cooked pixel formats, PNG 16 and TGA 8 alike:

| Map | Cooked format |
| --- | --- |
| BaseColor | `PF_DXT1` |
| ORM | `PF_DXT1` |
| Normal | `PF_BC5` |

### The DDS variant (item 3.3): refused by UE 5.6

The same Wand build exports `unreal-engine-packed-dds`. Each canonical PNG 16 is byte-identical
to the compared PNG 16 above, and each DDS is a valid DX10 file. UE 5.6 imports none of them:

- Interchange imports nothing and gives no message.
- The legacy `TextureFactory`, run only to get the reason, logs:
  - `Error: DDS DXGIFormat not supported : 99 : BC7_UNORM_SRGB`
  - `Error: DDS DXGIFormat not supported : 98 : BC7_UNORM`
  - `Error: DDS DXGIFormat not supported : 83 : BC5_UNORM`

The authored set's four DDS files (BaseColor, Emissive, ORM, Normal) are refused the same way
(`tests/export/test_unreal_consumer.py::test_ue_56_refuses_the_bc7_and_bc5_dds_files`), and Pillow
decodes each of them.

A one-off probe with 64² DDS files gives the same result for the other formats:

| DDS format | UE 5.6 |
| --- | --- |
| DX10 BC1 (71), BC3 (77) | refused |
| DX9 FourCC `DXT1`, `DXT5`, `ATI2`, `BC5U` | refused |
| DX10 R8G8B8A8 (28), R16G16B16A16 (11) | imported |

**The `cook` gap, answered.** No block-compressed data enters UE 5.6. UE imports only
uncompressed sources and encodes the platform format itself when it cooks, so a BC7 or BC5 file
cannot pass through. As specified, the DDS variant cannot be consumed by UE 5.6 at all. Item 3.3
therefore does not hold, and neither does acceptance 4.1 ("loads both variants"). That outcome
is left to the decision it needs: nothing is relaxed here.

### Authored set and item 3.5

`tests/export/test_unreal_consumer.py` runs on the CPU and in UE, with each case run once:

- **CPU.** 7 cases pass on every lane.
- **UE.** 10 cases pass with `UZP_UE_FIXTURE=1`:
  - **PNG 8 and TGA 8.** The shipped preset on the authored set in AO_Mixed's scope imports with
    every binding, Emissive included.
    - Grey-valued BaseColor and Emissive are stored by UE as a G8 source ("Auto-detected
      grayscale"); each of R, G and B equals that grey.
    - The PNG 8 export's SpecularWeight file has no slot and stays the receipt's gap.
  - **DDS.** Refused, as above.
  - **Item 3.5.** For each of the six interruption points, a fixed-name copy of generation B is
    killed before or after the rename of each of its three files. UE imports at once through the
    pinning adapter and consumes exactly B's verified files, never the half-copied directory.
    A damaged selected generation fails before anything is staged or UE starts.

## Scope

This fixture covers UE's importer, its texture settings, its stored sources, the material
bindings and the Windows cook. There is no rendered-image or Painter-parity claim: output parity
is item 3.1.
