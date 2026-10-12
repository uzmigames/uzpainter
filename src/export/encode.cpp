#include "export/encode.h"

#include "evaluator/arith.h"
#include "export/exr_writer.h"
#include "export/png_writer.h"
#include "uzp_core/types/errors.h"

#include <stdexcept>

namespace uzp::exporter {

namespace {

constexpr std::string_view kNotFitted = "phase1.16_export-processing-encoders, decision 090";

[[noreturn]] void Refuse(const PlannedFile& file, const std::string& what, std::string_view owner) {
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + what + " (" + std::string(owner) + ")");
}

[[noreturn]] void Unrecorded(const PlannedFile& file, const std::string& what) {
    Refuse(file, what + " is not recorded", kProcessingRecording);
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
    if (file.layout == FileLayout::LA) Unrecorded(file, "the L+A layout (grey and alpha)");
    if (file.layout == FileLayout::RGBA) {
        Refuse(file,
               "the RGB+A layout is recorded (R-085 P6, P7: an alpha of 1 everywhere is dropped) but its alpha "
               "sources are not resolved by the plan yet",
               kNotFitted);
    }
    if (p.fileFormat == FileFormat::png && p.bitDepth != BitDepth::u16) {
        Unrecorded(file, "PNG at " + std::string(BitDepthName(p.bitDepth)) + " bits");
    }
    if (p.fileFormat == FileFormat::exr && p.bitDepth != BitDepth::f32) {
        Unrecorded(file, "OpenEXR at " + std::string(BitDepthName(p.bitDepth)));
    }
    if (p.dithering) Unrecorded(file, "dithering");
    const auto width = static_cast<uint32_t>(set.resolution.width);
    const auto height = static_cast<uint32_t>(set.resolution.height);
    if (file.width != width || file.height != height) {
        Unrecorded(file, "resizing " + std::to_string(width) + "x" + std::to_string(height) + " to " +
                             std::to_string(file.width) + "x" + std::to_string(file.height) + " (sizeLog2)");
    }
    if (p.paddingAlgorithm != Padding::infinite && p.paddingAlgorithm != Padding::passthrough) {
        Unrecorded(file, "the padding \"" + std::string(PaddingName(p.paddingAlgorithm)) + "\" with dilationDistance");
    }
    for (const PlannedChannel& channel : file.channels) {
        const std::optional<core::ChannelType> srgb8 = Srgb8Channel(set, file, channel.source);
        if (!srgb8) continue;
        const std::string name(core::ToString(*srgb8));
        if (p.fileFormat == FileFormat::exr) Unrecorded(file, "the sRGB8 channel " + name + " in OpenEXR");
        if (!IsUserChannel(*srgb8)) {
            Refuse(file,
                   "the export encoding of the sRGB8 channel " + name +
                       " (sRGB-encoded samples, export-valued template constants) is recorded but not fitted",
                   kNotFitted);
        }
    }
}

std::string EncodeFile(const PlannedFile& file, const FileRaster& raster) {
    if (file.layout == FileLayout::Statistics) {
        if (!raster.statistics) throw std::invalid_argument("export: a statistics file without statistics");
        return *raster.statistics;
    }
    const uint32_t components = file.layout == FileLayout::L ? 1 : 3;
    if ((file.layout != FileLayout::L && file.layout != FileLayout::RGB) || raster.width != file.width ||
        raster.height != file.height || raster.channels != components ||
        raster.values.size() != size_t{raster.width} * raster.height * components) {
        throw std::invalid_argument("export: the raster of " + file.relativePath + " does not match its size and layout");
    }
    if (file.parameters->fileFormat == FileFormat::exr) {
        return EncodeExr(ExrImage{raster.width, raster.height, components, raster.values});
    }
    PngImage image{raster.width, raster.height, components, 16, {}};
    image.samples.reserve(raster.values.size());
    for (const float v : raster.values) image.samples.push_back(static_cast<uint16_t>(evaluator::arith::WriteUnorm(v, 16)));
    return EncodePng(image);
}

}  // namespace uzp::exporter
