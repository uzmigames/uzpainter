#include "export/encode.h"

#include "evaluator/arith.h"
#include "export/exr_writer.h"
#include "export/png_writer.h"
#include "uzp_core/types/errors.h"

#include <stdexcept>

namespace uzp::exporter {

namespace {

/// Recorded by R-090 and not fitted (decision 103); the owners of the remaining fits.
constexpr std::string_view kSrgb8NotFitted =
    "recording R-090 P10: PNG 8 fitted, PNG 16 not, and the evaluator's linear read-out of export-valued "
    "constants; decision 103";
constexpr std::string_view kDitherNotFitted = "recording R-090 P3, decision 103";
constexpr std::string_view kResizeNotFitted = "recording R-090 P4, decision 103";
constexpr std::string_view kPaddingNotFitted = "recording R-090 P5 and P9, decision 103";

[[noreturn]] void Refuse(const PlannedFile& file, const std::string& what, std::string_view owner) {
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + what + " (" + std::string(owner) + ")");
}

const core::TextureSet& SetOf(const core::Project& project, const PlannedFile& file) {
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.id == file.textureSetId) return set;
    }
    throw std::invalid_argument("export: the texture set of " + file.relativePath + " is not in the project");
}

/// The stack channel of `source` when it is an sRGB8 documentMap channel of `file`'s stack.
std::optional<core::ChannelType> Srgb8Channel(const core::TextureSet& set, const PlannedFile& file,
                                              const PlannedSource& source) {
    if (source.type != SourceType::documentMap || !source.channel) return std::nullopt;
    for (const core::Stack& stack : set.stacks) {
        if (stack.id != file.stackId) continue;
        const auto it = stack.channels.find(*source.channel);
        if (it != stack.channels.end() && it->second.format == core::ChannelFormat::sRGB8) return *source.channel;
    }
    return std::nullopt;
}

bool IsUserChannel(core::ChannelType type) { return core::ToString(type).starts_with("User"); }

}  // namespace

void CheckProcessing(const core::Project& project, const PlannedFile& file) {
    if (file.layout == FileLayout::Statistics) return;
    const core::TextureSet& set = SetOf(project, file);
    const ResolvedParameters& p = *file.parameters;
    if (p.dithering) {
        // Dithering changes nothing at PNG 16 (recording R-090 P3: on equals off on every map); at
        // PNG 8 it is deterministic but not fitted; in OpenEXR no recording compares it with off.
        if (p.fileFormat == FileFormat::png && p.bitDepth == BitDepth::u8) {
            Refuse(file, "dithering at PNG 8 bits is recorded (deterministic) but not fitted", kDitherNotFitted);
        }
        if (p.fileFormat == FileFormat::exr) {
            Refuse(file, "dithering in OpenEXR is not compared with dithering off by any recording", kDitherNotFitted);
        }
    }
    const auto width = static_cast<uint32_t>(set.resolution.width);
    const auto height = static_cast<uint32_t>(set.resolution.height);
    if (file.width != width || file.height != height) {
        Refuse(file,
               "resizing " + std::to_string(width) + "x" + std::to_string(height) + " to " + std::to_string(file.width) +
                   "x" + std::to_string(file.height) + " (sizeLog2) is recorded but only partly fitted",
               kResizeNotFitted);
    }
    if (p.paddingAlgorithm != Padding::infinite && p.paddingAlgorithm != Padding::passthrough) {
        Refuse(file,
               "the padding \"" + std::string(PaddingName(p.paddingAlgorithm)) +
                   "\" with dilationDistance is recorded but not fitted",
               kPaddingNotFitted);
    }
    for (const PlannedChannel& channel : file.channels) {
        const std::optional<core::ChannelType> srgb8 = Srgb8Channel(set, file, channel.source);
        if (!srgb8 || IsUserChannel(*srgb8)) continue;
        Refuse(file,
               "the export encoding of the sRGB8 channel " + std::string(core::ToString(*srgb8)) +
                   " (sRGB-encoded samples, export-valued template constants) is recorded but not fitted",
               kSrgb8NotFitted);
    }
}

namespace {

/// The value a PNG writes for `v` of `channel`: a Height channel is written signed, v * 0.5 + 0.5
/// (recording R-090 P1: exact at 8 and 16 bits, decision 103).
float PngValue(const PlannedChannel& channel, float v) {
    const PlannedSource& s = channel.source;
    if (s.type == SourceType::documentMap && s.channel == core::ChannelType::Height) return v * 0.5f + 0.5f;
    return v;
}

/// True when every alpha (last component) of `raster` is 1.
bool OpaqueAlpha(const FileRaster& raster) {
    const size_t texels = size_t{raster.width} * raster.height;
    for (size_t t = 0; t < texels; ++t) {
        if (raster.values[t * raster.channels + raster.channels - 1] != 1.0f) return false;
    }
    return true;
}

}  // namespace

EncodedImage EncodeFile(const PlannedFile& file, const FileRaster& raster) {
    if (file.layout == FileLayout::Statistics) {
        if (!raster.statistics) throw std::invalid_argument("export: a statistics file without statistics");
        return {*raster.statistics, FileLayout::Statistics};
    }
    const uint32_t components = file.layout == FileLayout::L    ? 1
                                : file.layout == FileLayout::LA ? 2
                                : file.layout == FileLayout::RGB ? 3
                                                                 : 4;
    if (raster.width != file.width || raster.height != file.height || raster.channels != components ||
        raster.values.size() != size_t{raster.width} * raster.height * components) {
        throw std::invalid_argument("export: the raster of " + file.relativePath + " does not match its size and layout");
    }
    // An alpha of 1 everywhere is dropped (recordings R-085 P6/P7 for RGB+A, R-090 P6 for L+A).
    const bool alpha = file.layout == FileLayout::LA || file.layout == FileLayout::RGBA;
    const bool drop = alpha && OpaqueAlpha(raster);
    const uint32_t written = drop ? components - 1 : components;
    const FileLayout layout = !drop ? file.layout : file.layout == FileLayout::LA ? FileLayout::L : FileLayout::RGB;
    const size_t texels = size_t{raster.width} * raster.height;
    const ResolvedParameters& p = *file.parameters;
    if (p.fileFormat == FileFormat::exr) {
        // OpenEXR 32f: the float unchanged; 16f: the half rounded toward zero (R-090 P2).
        const bool half = p.bitDepth == BitDepth::f16;
        ExrImage image{raster.width, raster.height, written, {}, half};
        image.values.reserve(texels * written);
        for (size_t t = 0; t < texels; ++t) {
            for (uint32_t c = 0; c < written; ++c) {
                const float v = raster.values[t * components + c];
                image.values.push_back(half ? evaluator::arith::HalfToFloat(evaluator::arith::HalfTowardZero(v)) : v);
            }
        }
        return {EncodeExr(image), layout};
    }
    // PNG 8 and 16: the UNORM write rule at the file's depth (R-090 P1).
    const uint32_t bits = p.bitDepth == BitDepth::u8 ? 8 : 16;
    PngImage image{raster.width, raster.height, written, bits, {}};
    image.samples.reserve(texels * written);
    for (size_t t = 0; t < texels; ++t) {
        for (uint32_t c = 0; c < written; ++c) {
            const float v = PngValue(file.channels[c], raster.values[t * components + c]);
            image.samples.push_back(static_cast<uint16_t>(evaluator::arith::WriteUnorm(v, bits)));
        }
    }
    return {EncodePng(image), layout};
}

}  // namespace uzp::exporter
