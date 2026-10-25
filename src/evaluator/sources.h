#pragma once

// Fill sources (docs/architecture/04-layer-stack-and-compositing.md §1, §4; parity/semantics/
// colour-transfer.json): how uniform colours and bitmaps become channel values.
//
// Colour management: the rules below are those of Painter's legacy colour management (an unset
// mode is legacy). OCIO with Painter's substance config (`kPainterOcioConfigSha256`, the
// configuration of Session O: `export-ocio-encode`, decision 190) stores the same codes for every
// recorded source but one: an 8-bit colour bitmap in Raw on an sRGB8 channel reads each code as
// float32(c / 255) rounded toward zero to a binary16 (`OcioRawDecoded`, evaluate.cpp; c / 255
// itself stores one code higher for c = 176, 245, 247 and 254). Under OCIO only what Session O
// records evaluates: uniform colours (sRGB, unset and Raw), an 8-bit colour bitmap in sRGB or Raw
// on an sRGB8 channel at 1:1, and a 16-bit grey bitmap in a linear space as a mask source at 1:1;
// every other bitmap use, and any other OCIO configuration, fails with
// `evaluator:unsupported_source`, and the support check refuses such a bitmap use before mutation
// from the PNG header (`OcioBitmapRecorded`, support.h; decision 240).
//
// - Uniform colour: each component (the mean of the three on a grey channel) is taken as a linear
//   value and stored with the channel's write rule (dag.h `UniformOperand`): RGB16 codes are
//   round(v 65535), sRGB8 codes the recording GPU's float-to-sRGB8 conversion (arith.h
//   `Srgb8Store`). The colour spaces sRGB, Working and Raw give the same codes (all three
//   observed on the Tier 0 ramps). Every API and MCP setter stores Painter's working value of the
//   colour given, tagged Working (`python::WorkingColour`, decision 240), so the tag is a record
//   only.
// - Bitmap: bound by the SHA-256 of its bytes (LAY-13: two nodes binding different bytes under
//   one alias each read their own), decoded once per resource (`DecodeBitmap`, 8- or 16-bit PNG),
//   sampled by the node's projection (projection_uv.h) and stored with the channel's write rule.
//   Under the colour spaces Raw, Data, DataSigned and NormalXYZLeft (and an untagged source) the
//   codes are linear values c / M: observed for 16-bit bitmaps on RGB16, sRGB8, RGB8 and L16
//   channels (Tier 0 `blend-inputs`, every 16-bit code; Painter reports them Data), on Height
//   (DataSigned) and Normal (NormalXYZLeft), and for field A on BaseColor set to Raw
//   (`export-probes-channels`); 8-bit bitmaps follow the same rule without a golden yet. A grey
//   bitmap feeds every channel of a colour channel; alpha planes are not read.
// - Bitmap on the Normal channel (decision 226: P20-A, the 8-bit checker and the 8-bit grey
//   half-left image magnified 16 times under NormalMapDetail): Painter samples a 16-bit UNORM
//   texture and writes the filter's result as a 16-bit code before the channel stores it half
//   toward zero (evaluate.cpp `NormalTexture`, `DecodedImage::unorm16Target`). A colour image has
//   its green codes inverted, and an 8-bit blue code below 127 (the flat normal's) raised to 127;
//   a grey image feeds its value to the three components, neither inverted nor raised (only the
//   direction NormalMapDetail decodes is seen, decision 249). Exact on all 65 536 texels of the
//   Normal map, r1 and r2. The clamp at 1/2 or 128/255, no clamp, the
//   decode clamped and normalised per texel, and the float32 or binary16 filter result each miss
//   texels. A 1:1 sample keeps its code (the recorded imports stay exact). A 16-bit grey image is
//   not recorded and fails with `evaluator:unsupported_source`.
//   Only the recorded uses evaluate (decision 249, evaluate.cpp `CheckNormalTexture`): a colour
//   image at 1:1 or under Nearest whose import raises no blue code, in any channel format and
//   convention (decision 226 changes none of these samples: normal-a, normal-b and normal-a-8bit
//   at 1:1; normal-a under Nearest at 2x and 4x, `export-resize` s0, exact), and an 8-bit colour
//   image magnified as P20-A records it, on an RGB16F Normal channel in an OpenGL project (a
//   bilinear filter, Repeat, scale 1, rotation 0, offset 0, an image 16 times smaller than the
//   set). A grey image is refused at every sampling: P20-A sees it only through NormalMapDetail,
//   whose decode normalises it, so neither its value nor the 16-bit code of its filtered result is
//   recorded (a plain fill stores 0.71875 or 0.71826171875 at a weight of 184 / 256, and the
//   decoded normals of the two differ by one float32 step at 33 of the 257 weights); P20-A's
//   Normal map is therefore refused. A 16-bit image resampled by a bilinear filter misses
//   `export-resize` s3 under this rule (normal-a magnified 2 and 4 times by BilinearHQ, seen
//   through the virtual normal maps: 2 048 of 262 144 texels at 512, 6 880 of 1 048 576 at 1024,
//   up to 32 PNG 16 codes; 21 888 at 512 before it, decision 103). Those, any bilinear
//   minification, another magnification, transform, channel format or convention, and a raised
//   blue code at 1:1 or under Nearest fail with `evaluator:unsupported_source`.
// - Colour bitmap read by a one-channel tile (decision 218: P20-A, `phase1-fill-channel-defaults`,
//   the 8-bit checker magnified 16 times on L8, on L16F Height and as a mask source): Painter
//   samples an R16F texture. Each texel is the mean ((r + g) + b) / 3 of its float32(c / 255)
//   components (2 m - 1 on Height), rounded toward zero to a binary16, and the bilinear filter's
//   result is rounded to a binary16, to nearest with ties away from zero (evaluate.cpp
//   `GreyTexture`): exact on BaseMetalness, SpecularRoughness, Height and the mask, r1 and r2. The
//   red component, BT.709 and Rec. 601 weights, an 8-bit grey and a float32 mean each miss codes.
//   An 8-bit colour bitmap magnified or at 1:1 by a bilinear filter on L8, L16F or in a mask
//   evaluates; on any other one-channel format, at 16 bits, under Nearest or minified it fails with
//   `evaluator:unsupported_source` (not recorded).
// - sRGB bitmap (Painter's default for a colour bitmap on BaseColor; the tags `sRGB` and
//   `LegacyColorSpace.sRGB`, which give the same codes: `srgb-bitmap-variants-v2` s8): each texel
//   is decoded to a float32 linear value before the projection samples it, then stored on the
//   sRGB8 channel (arith::Srgb8Store). An 8-bit code c decodes as the recording GPU's sRGB8 texel
//   (arith::Srgb8Operand: Painter samples an sRGB8 texture); a 16-bit code as the GPU's float32
//   shader decode of x = float32(c / 65535), x float32(1 / 12.92) up to 0.04045 and above it
//   pow(fma(x, r, float32(0.055) r), 2.4), r = float32(1 / 1.055), with the GPU's pow (hw::Pow).
//   Only filtered texels tell the decodes apart: at 1:1 every decode stores the same code (the
//   double-precision decode, float32 orders of operations and the GPU's pow agree on each of the
//   65 536 16-bit codes, and an 8-bit code is its own sRGB8 code). The 16-bit decode is the one
//   form exact on both field A at 1:1 (s8) and BilinearHQ-magnified (s2), where one texel's
//   filtered value lies on an sRGB8 threshold: the uncontracted product, a division, the
//   double-precision decode and a correctly rounded pow each miss at least one; decoding after
//   the filter misses 67 values of s2 and the 8-bit decode in a shader 1 536 of s2's 8-bit ramp.
//   A grey bitmap feeds the three channels. Exact, every texel, PNG 16, PNG 8 and OpenEXR 32f, r1
//   and r2: 16-bit colour at 1:1 (`virtual-maps-converted` and its OpenEXR twin s0-s1,
//   `export-probes-config`, `export-probes-naming`, c / M misses 195 325 of 196 608 values there),
//   8-bit colour at 1:1 (`export-ocio-encode-legacy` s3), 16-bit grey at 1:1 (`export-bit-depth`
//   s4, s5, s7), 8-bit grey at 1:1 (`srgb-bitmap-variants-v2` s0), 16- and 8-bit colour magnified
//   by BilinearHQ (s2, scale 0.5) and under Nearest at scale 2 (s3), and 16-bit colour minified
//   by BilinearHQ and BilinearSharp at scales 2 and 4 (`srgb-bitmap-minification` s4-s7): the
//   texture unit samples the decoded float32 mip chain (`BitmapChain`, decision 203). An 8-bit
//   sRGB bitmap minified by a bilinear filter is an sRGB8 texture: the texture unit sums its
//   probes with the sRGB8 arithmetic (texture_unit.h, steps 5' and 6', decision 219), exact for
//   8-bit colour at scale 2 under BilinearHQ and BilinearSharp (`srgb-bitmap-minification` s0,
//   s2), where only level 0 is read. A footprint that reads a mip level fails with
//   `evaluator:unsupported_source` (`ReadsMipLevels`): Painter's sRGB8 mip levels hold sRGB8
//   codes, but how it filters them is not separated by any recording (decision 219). Magnified
//   or at 1:1 by a bilinear filter, an 8-bit sRGB bitmap's four taps are one probe of the same
//   sRGB8 sums (`tu::Srgb8Probe`, decision 209's single-probe rule; decision 224): exact on
//   P20-A's BaseColor (the 8-bit sRGB checker magnified 16 times, `phase1-fill-channel-defaults`,
//   r1 and r2), where the float32 filter missed 8 264 texels, and on s2's 8-bit ramp.
// - sRGB bitmap on an L8 BaseColor, Specular or Emissive (`SrgbL8MaterialChannel`, decision 208:
//   `export-l8-material` s0 and s1, bitmaps left in Painter's default space): a grey bitmap at 1:1 is read
//   decoded and stored with the L8 write rule. A 16-bit code decodes as on an sRGB8 channel (the
//   GPU's float32 shader decode above). An 8-bit code takes the same float32 shader decode of
//   x = float32(c / 255), rounded toward zero to a binary16 (the binary16 texel of decision 190),
//   not the sRGB8 texel: exact on all 256 codes of the 8-bit ramp and of grey A (`257 c`), every
//   channel, r1 and r2. The IEC decode rounded to nearest stores one code higher for 13 of the
//   256 8-bit codes (7, 18, 72, 82, 123, 148, 167, 170, 178, 194, 209, 220, 243) and for 10 of
//   grey A's (the same but 194, 209, 243); the sRGB8 texel misses 30, the float32 decode
//   without the binary16 3 (194, 209, 243). A colour bitmap there, any resampling, any other
//   format of these channels and OCIO are not recorded and fail with
//   `evaluator:unsupported_source`.
// - Working and `LegacyColorSpace.Linear` read the codes as Raw does (s6, s7). Painter offers
//   sRGB on a user channel only in sRGB8: in every other format (RGB8, L8, RGB16, L16, RGB16F and
//   RGB32F recorded) and on a mask's mono source it refuses the space and the bitmap stays Data
//   (s4, s5; decision 174), so an sRGB tag there fails with `evaluator:unsupported_source`
//   (support.h before any mutation). On any other channel that is neither sRGB8 nor the L8
//   material channels above, sRGB is not recorded and fails the same way, as does any other tag.

#include "evaluator/projection_uv.h"
#include "evaluator/resources.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <set>
#include <string>
#include <string_view>

#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// How a bitmap source's colour-space tag (`core::BitmapSource::color_space`) turns its codes
/// into channel values under legacy colour management (above): `Linear` (Raw, Data, DataSigned,
/// NormalXYZLeft, Working, LegacyColorSpace.Linear and the empty tag: c / M), `Srgb` (sRGB and
/// LegacyColorSpace.sRGB: decoded) or `Unrecorded` (any other tag: no golden).
enum class BitmapColourSpace : uint8_t { Linear, Srgb, Unrecorded };
[[nodiscard]] BitmapColourSpace BitmapColourSpaceOf(std::string_view tag);
/// The colour space of `tag` in `project`: `BitmapColourSpaceOf`, plus the one qualified OCIO tag
/// "OcioColorSpace.sRGB" (the configuration space "sRGB" Painter reports as a string; the
/// tier0/api-probes/source-bitmap-defaults-unreal-* probes, phase3.2_unreal-ue56-packed-preset §16). Under the pinned OCIO profile (`PainterOcio`) it is exactly the plain "sRGB" tag's
/// space; in any other project, and for any other "OcioColorSpace.*" name, it is `Unrecorded`.
[[nodiscard]] BitmapColourSpace BitmapColourSpaceIn(const core::Project& project, std::string_view tag);

/// True for BaseColor, Specular and Emissive in L8, where Painter reads an sRGB bitmap decoded
/// (above, decision 208).
[[nodiscard]] bool SrgbL8MaterialChannel(core::ChannelType channel, core::ChannelFormat format);

/// SHA-256 of Painter 12.1.5's `resources/ocio/substance/config.ocio`, the configuration Session O
/// recorded (decision 134 pins the same file for the display transform; the file is never read).
inline constexpr std::string_view kPainterOcioConfigSha256 =
    "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4";

/// True when `project` uses OCIO with Painter's substance config (`kPainterOcioConfigSha256`).
[[nodiscard]] bool PainterOcio(const core::Project& project);

/// Painter's working value of an sRGB uniform colour component under OCIO with its substance
/// config: the measured float32 readback by the float32 bits of the component (decision 202), the
/// table of `python/uzpainter_facade/ocio_srgb.py` as generated into `ocio_srgb_table.inc` by
/// `tools/parity/ocio_srgb_table.py`: the 256 codes c / 255 and the 193 other recorded components.
/// Empty for a component it does not record: no analytic decode reproduces it.
[[nodiscard]] std::optional<float> PainterOcioSrgbDecode(float component);

/// Painter's working value of an sRGB uniform colour component under legacy colour management
/// (decision 214), in float32 with x = float32(component): x * (1.0f / 12.92f) up to 0.04045f,
/// else ((x + 0.055f) * (1.0f / 1.055f)) ^ 2.4f, each reciprocal the float32 quotient of 1 by the
/// float32 constant and the power of the float32 operands rounded once to float32 (P20-B,
/// `phase1-srgb-uniform-decode-part1..4`: all 448 recorded components, both recordings).
/// `python::WorkingColour` (python/edits.h) is its one caller: every path that stores a uniform
/// colour, the facade's included, decodes through it (decision 240).
[[nodiscard]] float PainterLegacySrgbDecode(float component);

/// Fails with `evaluator:unsupported_source` unless `project` uses legacy colour management or
/// OCIO with Painter's substance config (`PainterOcio`).
[[nodiscard]] render::Result<void> CheckColourManagement(const core::Project& project,
                                                         core::Id node);

/// The shape `DecodeBitmap` gives a PNG, read from its header alone: its size, one channel for a
/// grey file (with or without alpha) and three otherwise, 16-bit codes for a 16-bit file and 8-bit
/// codes otherwise.
struct BitmapShape {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 0;
    render::TexelEncoding encoding = render::TexelEncoding::Unorm8;
};

/// The shape of the PNG `bytes` (`BitmapShape`), or nullopt when its header does not decode.
[[nodiscard]] std::optional<BitmapShape> BitmapShapeOf(std::string_view bytes);

/// Whether a bitmap of `shape` sampled by `projection` on a `width` x `height` texture set is a use
/// Session O records under OCIO with Painter's substance config (above; decision 190): a 16-bit
/// grey image as a mask source (`mask`), an 8-bit colour image on an sRGB8 channel otherwise, each
/// at 1:1 (the image is the set's size and the projection is the identity). The evaluation
/// (evaluate.cpp `CheckOcioBitmap`) and the support check before mutation (support.h) share it.
[[nodiscard]] bool OcioBitmapRecorded(bool mask, const UvProjection& projection, uint32_t width,
                                      uint32_t height, const BitmapShape& shape);

/// The samples of a PNG: 16-bit files as 16-bit codes, files of 8 bits or fewer as 8-bit codes;
/// grey (with or without alpha) as one channel, RGB, RGBA and palette images as three; rows top
/// first. Fails with `evaluator:unsupported_source` when the bytes are not a decodable PNG.
[[nodiscard]] render::Result<DecodedImage> DecodeBitmap(std::string_view bytes);

/// A provider over resource bytes: `fetch` returns the bytes stored under a hash (or nothing);
/// each resource is decoded once, after its bytes are checked against the hash, and kept in a RAM
/// cache keyed by hash (its decoded form has one format, the file's bit depth). A resource whose
/// bytes are absent, do not hash to their key or do not decode is unavailable (null).
class DecodingResourceProvider final : public IResourceProvider {
public:
    using FetchBytes = std::function<std::optional<std::string>(std::string_view sha256)>;

    explicit DecodingResourceProvider(FetchBytes fetch) : m_fetch(std::move(fetch)) {}

    std::shared_ptr<const DecodedImage> Fetch(std::string_view sha256) const override;
    /// The bytes are stored and hash to `sha256`, checked once, without decoding them: bytes
    /// that hash to the key of a stored result decoded when it was computed.
    bool Available(std::string_view sha256) const override;

    /// Decodes performed so far (cache misses that produced an image).
    [[nodiscard]] size_t Decodes() const;

private:
    FetchBytes m_fetch;
    mutable std::mutex m_mutex;
    mutable std::map<std::string, std::shared_ptr<const DecodedImage>, std::less<>> m_cache;
    mutable std::set<std::string, std::less<>> m_available;
    mutable size_t m_decodes = 0;
};

}  // namespace uzp::evaluator
