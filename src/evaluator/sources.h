#pragma once

// Fill sources (docs/architecture/04-layer-stack-and-compositing.md §1, §4; parity/semantics/
// colour-transfer.json): how uniform colours and bitmaps become channel values.
//
// Colour management: the rules below are those of Painter's legacy colour management, the mode
// every Tier 0 golden was recorded in (an unset mode is legacy). An OCIO project fails explicitly
// with `evaluator:unsupported_source` (no golden fits it yet).
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
// - sRGB bitmap (Painter's default for a colour bitmap on BaseColor): each code is decoded with
//   the sRGB transfer function, v = x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055)^2.4 with
//   x = float32(c / 65535), and stored on the sRGB8 channel (arith::Srgb8Store). Exact on every
//   texel of `virtual-maps-converted` (and its OpenEXR twin) s0-s1, `export-probes-config` and
//   `export-probes-naming` (r1 and r2); c / M misses 195 325 of 196 608 values there. On an sRGB8
//   channel the stored code does not depend on the decode's arithmetic: float32 orders of
//   operations, the GPU's pow and the double-precision decode give the same code for each of the
//   65 536 codes. Recorded only for a 16-bit colour bitmap sampled 1:1 (the bitmap the size of
//   the set, the identity transform) onto an sRGB8 channel; any other use (another channel
//   format or a mask, an 8-bit or grey bitmap, resampling) and the Working and Linear spaces
//   fail with `evaluator:unsupported_source` (support.h refuses the first and last before any
//   mutation).

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
/// NormalXYZLeft and the empty tag: c / M), `Srgb` (sRGB: decoded) or `Unrecorded` (any other
/// tag, Working and Linear included: no golden).
enum class BitmapColourSpace : uint8_t { Linear, Srgb, Unrecorded };
[[nodiscard]] BitmapColourSpace BitmapColourSpaceOf(std::string_view tag);

/// Fails with `evaluator:unsupported_source` unless `project` uses legacy colour management.
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
