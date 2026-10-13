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
// `evaluator:unsupported_source`.
//
// - Uniform colour: each component (the mean of the three on a grey channel) is taken as a linear
//   value and stored with the channel's write rule (dag.h `UniformOperand`): RGB16 codes are
//   round(v 65535), sRGB8 codes the recording GPU's float-to-sRGB8 conversion (arith.h
//   `Srgb8Store`). The colour spaces sRGB, Working and Raw give the same codes (all three
//   observed on the Tier 0 ramps).
// - Bitmap: bound by the SHA-256 of its bytes (LAY-13: two nodes binding different bytes under
//   one alias each read their own), decoded once per resource (`DecodeBitmap`, 8- or 16-bit PNG),
//   sampled by the node's projection (projection_uv.h) and stored with the channel's write rule.
//   Under the colour spaces Raw, Data, DataSigned and NormalXYZLeft (and an untagged source) the
//   codes are linear values c / M: observed for 16-bit bitmaps on RGB16, sRGB8, RGB8 and L16
//   channels (Tier 0 `blend-inputs`, every 16-bit code; Painter reports them Data), on Height
//   (DataSigned) and Normal (NormalXYZLeft), and for field A on BaseColor set to Raw
//   (`export-probes-channels`); 8-bit bitmaps follow the same rule without a golden yet. A grey
//   bitmap feeds every channel of a colour channel; a grey channel reads the first channel of a
//   colour bitmap; alpha planes are not read.
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
//   by BilinearHQ (s2, scale 0.5) and under Nearest at scale 2 (s3). Bilinear minification of an
//   sRGB bitmap is not recorded and fails with `evaluator:unsupported_source` (its mip chain is
//   unmeasured; s1 minifies at 30 degrees, refused for every bitmap).
// - Working and `LegacyColorSpace.Linear` read the codes as Raw does (s6, s7). Painter offers
//   sRGB on sRGB8 channels only: on every other channel format (RGB8, L8, RGB16, L16, RGB16F and
//   RGB32F recorded) and on a mask's mono source it refuses the space and the bitmap stays Data
//   (s4, s5; decision 174), so an sRGB tag there fails with `evaluator:unsupported_source`
//   (support.h before any mutation). Any other tag is not recorded and fails the same way.

#include "evaluator/resources.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
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

/// SHA-256 of Painter 12.1.5's `resources/ocio/substance/config.ocio`, the configuration Session O
/// recorded (decision 134 pins the same file for the display transform; the file is never read).
inline constexpr std::string_view kPainterOcioConfigSha256 =
    "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4";

/// True when `project` uses OCIO with Painter's substance config (`kPainterOcioConfigSha256`).
[[nodiscard]] bool PainterOcio(const core::Project& project);

/// Fails with `evaluator:unsupported_source` unless `project` uses legacy colour management or
/// OCIO with Painter's substance config (`PainterOcio`).
[[nodiscard]] render::Result<void> CheckColourManagement(const core::Project& project,
                                                         core::Id node);

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

    /// Decodes performed so far (cache misses that produced an image).
    [[nodiscard]] size_t Decodes() const;

private:
    FetchBytes m_fetch;
    mutable std::mutex m_mutex;
    mutable std::map<std::string, std::shared_ptr<const DecodedImage>, std::less<>> m_cache;
    mutable size_t m_decodes = 0;
};

}  // namespace uzp::evaluator
