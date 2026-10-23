#include "export/resize.h"

#include "evaluator/arith.h"
#include "evaluator/error.h"
#include "evaluator/geometry_mask.h"

#include <array>
#include <bit>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace uzp::exporter {

namespace {

/// The resize of one side: `to` from `from`.
Resize SideResize(uint32_t from, uint32_t to) {
    if (to == from) return Resize::none;
    if (from % 2 == 0 && to == from / 2) return Resize::downscale;
    if (to > from && to % from == 0 && std::has_single_bit(to / from)) return Resize::upscale;
    return Resize::other;
}

/// The nearest binary16 value of `mean`, ties away from zero (arith::HalfNearestAway's rounding,
/// decided in double: `mean` is the exact mean of 2 or 4 halves, which float32 need not hold).
float HalfNearestAwayOf(double mean) {
    if (std::isnan(mean)) return std::numeric_limits<float>::quiet_NaN();
    const uint16_t guess = evaluator::arith::HalfNearestAway(static_cast<float>(mean));
    float best = evaluator::arith::HalfToFloat(guess);
    // The guess's neighbours (same sign; NaN and infinity are not reached: the mean of finite
    // halves is finite and within their range).
    const uint16_t sign = guess & 0x8000u;
    const int magnitude = guess & 0x7FFF;
    for (const int next : {magnitude - 1, magnitude + 1}) {
        if (next < 0 || next >= 0x7C00) continue;
        const float candidate = evaluator::arith::HalfToFloat(static_cast<uint16_t>(sign | next));
        const double d = std::abs(static_cast<double>(candidate) - mean);
        const double b = std::abs(static_cast<double>(best) - mean);
        if (d < b || (d == b && std::abs(candidate) > std::abs(best))) best = candidate;
    }
    return best;
}

}  // namespace

Resize ResizeOf(uint32_t setWidth, uint32_t setHeight, const PlannedFile& file) {
    const Resize x = SideResize(setWidth, file.width);
    const Resize y = SideResize(setHeight, file.height);
    if (x == Resize::other || y == Resize::other) return Resize::other;
    if (x == Resize::none) return y;
    if (y == Resize::none || y == x) return x;
    return Resize::other;  // one side halved, the other enlarged
}

core::Project AtFileSize(const core::Project& project, const PlannedFile& file) {
    core::Project resized = project;
    for (core::TextureSet& set : resized.texture_sets) {
        if (set.id != file.textureSetId) continue;
        set.resolution.width = static_cast<int>(file.width);
        set.resolution.height = static_cast<int>(file.height);
        return resized;
    }
    throw std::invalid_argument("export: the texture set of " + file.relativePath + " is not in the project");
}

std::optional<Coverage> CoverageAt(const core::TextureSet& set, const SourceInputs& inputs, uint32_t width,
                                   uint32_t height) {
    if (!inputs.geometry) return std::nullopt;
    evaluator::GeometryMaskQuery query;
    query.material = set.material_id;
    query.inclusionList = false;
    query.width = width;
    query.height = height;
    const std::shared_ptr<const evaluator::DecodedImage> mask = inputs.geometry->Coverage(query);
    if (!mask) return std::nullopt;
    Coverage coverage{mask->width, mask->height, {}};
    coverage.covered.reserve(size_t{mask->width} * mask->height);
    for (size_t t = 0; t < size_t{mask->width} * mask->height; ++t) {
        coverage.covered.push_back(mask->values[t * mask->channels] != 0 ? 1 : 0);
    }
    return coverage;
}

std::optional<std::string> ResizeCoverageRefusal(const PlannedFile& file, const Coverage& native,
                                                 const Coverage& target) {
    if (native.Complete() && target.Complete()) return std::nullopt;
    return "export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
           "): resizing a texture set whose UV islands do not cover the whole tile is not recorded (Painter's "
           "padding around the resize; export-resize records sets that cover it) (owner "
           "phase3.2_unreal-ue56-packed-preset item 2.9, decision 349; phase1.25_pilot-wand item 2.7)";
}

render::Result<FileRaster> Downscale(const PlannedFile& file, const FileRaster& native) {
    const bool halveX = native.width != file.width;
    const bool halveY = native.height != file.height;
    if ((halveX && native.width != file.width * 2) || (halveY && native.height != file.height * 2) ||
        (!halveX && !halveY) || native.statistics || native.channels != file.channels.size() ||
        native.documentFormat.size() != native.channels ||
        native.values.size() != size_t{native.width} * native.height * native.channels) {
        throw std::invalid_argument("export: the raster of " + file.relativePath + " is not its downscale's source");
    }
    FileRaster out = native;
    out.width = file.width;
    out.height = file.height;
    out.values.assign(size_t{out.width} * out.height * out.channels, 0.0f);
    const uint32_t taps = (halveX ? 2u : 1u) * (halveY ? 2u : 1u);
    for (uint32_t c = 0; c < native.channels; ++c) {
        const std::optional<core::ChannelFormat> format = native.documentFormat[c];
        if (format != core::ChannelFormat::RGB16 && format != core::ChannelFormat::L16F) {
            throw std::invalid_argument("export: channel " + std::to_string(c) + " of " + file.relativePath +
                                        " is not an RGB16 or L16F documentMap component");
        }
        for (uint32_t y = 0; y < out.height; ++y) {
            for (uint32_t x = 0; x < out.width; ++x) {
                std::array<float, 4> v{};
                uint32_t n = 0;
                for (uint32_t dy = 0; dy < (halveY ? 2u : 1u); ++dy) {
                    for (uint32_t dx = 0; dx < (halveX ? 2u : 1u); ++dx) {
                        const size_t sx = halveX ? size_t{x} * 2 + dx : x;
                        const size_t sy = halveY ? size_t{y} * 2 + dy : y;
                        v[n++] = native.values[(sy * native.width + sx) * native.channels + c];
                    }
                }
                float result = 0.0f;
                if (format == core::ChannelFormat::RGB16) {
                    // The texels are UNORM16 operands; their codes are exact.
                    uint32_t sum = 0;
                    for (uint32_t i = 0; i < taps; ++i) sum += evaluator::arith::WriteUnorm(v[i], 16);
                    if (taps == 4 && sum % 4 == 2) {
                        return evaluator::EvalFail(
                            evaluator::EvalErrorKind::UnsupportedSource,
                            "the downscale of " + file.relativePath + " has a 2 x 2 RGB16 mean halfway between two "
                            "16-bit codes, whose rounding export-resize does not record (phase3.2_unreal-ue56-"
                            "packed-preset item 2.9, decision 349)");
                    }
                    result = evaluator::arith::UnormOperand((sum + taps / 2) / taps, 16);
                } else {
                    double sum = 0.0;
                    for (uint32_t i = 0; i < taps; ++i) sum += static_cast<double>(v[i]);
                    result = HalfNearestAwayOf(sum / taps);
                }
                out.values[(size_t{y} * out.width + x) * out.channels + c] = result;
            }
        }
    }
    return out;
}

}  // namespace uzp::exporter
