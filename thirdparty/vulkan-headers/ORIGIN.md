# Origin of Vulkan-Headers

| Field | Value |
|---|---|
| Upstream | https://github.com/KhronosGroup/Vulkan-Headers |
| Release | `v1.4.342` |
| Tag commit | `3cfca3829608e778cf59b0dab55d77f4f6c79bee` |
| Archive | https://github.com/KhronosGroup/Vulkan-Headers/archive/refs/tags/v1.4.342.tar.gz |
| Archive SHA-256 | `71ec294f7499d02ba3e8b5a37b72a036ceea458f55bcc8f4dda05fec3234a1b9` |
| Archive root | `Vulkan-Headers-1.4.342/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (1.4.342); `scripts/setup.ps1` clones tag `v1.4.342` |
| Licence | Apache-2.0: every selected header carries `SPDX-License-Identifier: Apache-2.0` (repository statement `LICENSE.md`, texts `LICENSES/`) |
| Licence files | `LICENSE.md`, `LICENSES/Apache-2.0.txt`, `LICENSES/MIT.txt` (verbatim) |
| Distribution role | build-only: headers, nothing of it is compiled on its own or shipped |
| Selected features | C headers only (`include/vulkan/*.h`, `include/vk_video/*.h`); the C++ bindings (`*.hpp`, `*.cppm`) and the registry are not vendored |
| Include directories | `thirdparty/vulkan-headers/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)
- The tag has no `NOTICE` file, so Apache-2.0 §4(d) adds no attribution text.

## Selected files (36)

- `LICENSE.md` (458 bytes)
- `LICENSES/Apache-2.0.txt` (11,358 bytes)
- `LICENSES/MIT.txt` (1,084 bytes)
- `include/vk_video/vulkan_video_codec_av1std.h` (16,687 bytes)
- `include/vk_video/vulkan_video_codec_av1std_decode.h` (4,250 bytes)
- `include/vk_video/vulkan_video_codec_av1std_encode.h` (5,979 bytes)
- `include/vk_video/vulkan_video_codec_h264std.h` (13,861 bytes)
- `include/vk_video/vulkan_video_codec_h264std_decode.h` (2,723 bytes)
- `include/vk_video/vulkan_video_codec_h264std_encode.h` (6,878 bytes)
- `include/vk_video/vulkan_video_codec_h265std.h` (23,439 bytes)
- `include/vk_video/vulkan_video_codec_h265std_decode.h` (2,429 bytes)
- `include/vk_video/vulkan_video_codec_h265std_encode.h` (7,462 bytes)
- `include/vk_video/vulkan_video_codec_vp9std.h` (5,384 bytes)
- `include/vk_video/vulkan_video_codec_vp9std_decode.h` (2,371 bytes)
- `include/vk_video/vulkan_video_codecs_common.h` (660 bytes)
- `include/vulkan/vk_icd.h` (8,224 bytes)
- `include/vulkan/vk_layer.h` (7,178 bytes)
- `include/vulkan/vk_platform.h` (2,828 bytes)
- `include/vulkan/vulkan.h` (1,616 bytes)
- `include/vulkan/vulkan_android.h` (6,330 bytes)
- `include/vulkan/vulkan_beta.h` (17,412 bytes)
- `include/vulkan/vulkan_core.h` (1,265,883 bytes)
- `include/vulkan/vulkan_directfb.h` (1,952 bytes)
- `include/vulkan/vulkan_fuchsia.h` (12,900 bytes)
- `include/vulkan/vulkan_ggp.h` (1,939 bytes)
- `include/vulkan/vulkan_ios.h` (1,352 bytes)
- `include/vulkan/vulkan_macos.h` (1,384 bytes)
- `include/vulkan/vulkan_metal.h` (8,066 bytes)
- `include/vulkan/vulkan_ohos.h` (4,106 bytes)
- `include/vulkan/vulkan_screen.h` (4,193 bytes)
- `include/vulkan/vulkan_vi.h` (1,325 bytes)
- `include/vulkan/vulkan_wayland.h` (1,952 bytes)
- `include/vulkan/vulkan_win32.h` (15,757 bytes)
- `include/vulkan/vulkan_xcb.h` (1,966 bytes)
- `include/vulkan/vulkan_xlib.h` (1,947 bytes)
- `include/vulkan/vulkan_xlib_xrandr.h` (1,497 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/vulkan_headers` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 74 |
| line-endings | 0 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Identical files:

- `.reuse/dep5`
- `BUILD.gn`
- `BUILD.md`
- `CMakeLists.txt`
- `CODE_OF_CONDUCT.adoc`
- `LICENSE.md`
- `LICENSES/Apache-2.0.txt`
- `LICENSES/MIT.txt`
- `Makefile.release`
- `README.md`
- `include/vk_video/vulkan_video_codec_av1std.h`
- `include/vk_video/vulkan_video_codec_av1std_decode.h`
- `include/vk_video/vulkan_video_codec_av1std_encode.h`
- `include/vk_video/vulkan_video_codec_h264std.h`
- `include/vk_video/vulkan_video_codec_h264std_decode.h`
- `include/vk_video/vulkan_video_codec_h264std_encode.h`
- `include/vk_video/vulkan_video_codec_h265std.h`
- `include/vk_video/vulkan_video_codec_h265std_decode.h`
- `include/vk_video/vulkan_video_codec_h265std_encode.h`
- `include/vk_video/vulkan_video_codec_vp9std.h`
- `include/vk_video/vulkan_video_codec_vp9std_decode.h`
- `include/vk_video/vulkan_video_codecs_common.h`
- `include/vulkan/vk_icd.h`
- `include/vulkan/vk_layer.h`
- `include/vulkan/vk_platform.h`
- `include/vulkan/vulkan.cppm`
- `include/vulkan/vulkan.h`
- `include/vulkan/vulkan.hpp`
- `include/vulkan/vulkan_android.h`
- `include/vulkan/vulkan_beta.h`
- `include/vulkan/vulkan_core.h`
- `include/vulkan/vulkan_directfb.h`
- `include/vulkan/vulkan_enums.hpp`
- `include/vulkan/vulkan_extension_inspection.hpp`
- `include/vulkan/vulkan_format_traits.hpp`
- `include/vulkan/vulkan_fuchsia.h`
- `include/vulkan/vulkan_funcs.hpp`
- `include/vulkan/vulkan_ggp.h`
- `include/vulkan/vulkan_handles.hpp`
- `include/vulkan/vulkan_hash.hpp`
- `include/vulkan/vulkan_hpp_macros.hpp`
- `include/vulkan/vulkan_ios.h`
- `include/vulkan/vulkan_macos.h`
- `include/vulkan/vulkan_metal.h`
- `include/vulkan/vulkan_ohos.h`
- `include/vulkan/vulkan_raii.hpp`
- `include/vulkan/vulkan_screen.h`
- `include/vulkan/vulkan_shared.hpp`
- `include/vulkan/vulkan_static_assertions.hpp`
- `include/vulkan/vulkan_structs.hpp`
- `include/vulkan/vulkan_to_string.hpp`
- `include/vulkan/vulkan_vi.h`
- `include/vulkan/vulkan_video.cppm`
- `include/vulkan/vulkan_video.hpp`
- `include/vulkan/vulkan_wayland.h`
- `include/vulkan/vulkan_win32.h`
- `include/vulkan/vulkan_xcb.h`
- `include/vulkan/vulkan_xlib.h`
- `include/vulkan/vulkan_xlib_xrandr.h`
- `registry/apiconventions.py`
- `registry/base_generator.py`
- `registry/cgenerator.py`
- `registry/generator.py`
- `registry/parse_dependency.py`
- `registry/profiles/VP_KHR_roadmap.json`
- `registry/reg.py`
- `registry/spec_tools/conventions.py`
- `registry/spec_tools/util.py`
- `registry/stripAPI.py`
- `registry/validusage.json`
- `registry/video.xml`
- `registry/vk.xml`
- `registry/vkconventions.py`
- `registry/vulkan_object.py`

UzEngine patches: none under this library at the commit.
