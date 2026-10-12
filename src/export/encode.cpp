#include "export/encode.h"

#include "evaluator/arith.h"
#include "export/exr_writer.h"
#include "export/png_writer.h"
#include "uzp_core/types/errors.h"

#include <stdexcept>

namespace uzp::exporter {

namespace {

[[noreturn]] void Unrecorded(const PlannedFile& file, const std::string& what) {
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + what + " is not recorded (" + std::string(kProcessingRecording) + ")");
}

uint32_t ComponentsOf(FileLayout layout) { return layout == FileLayout::L ? 1 : 3; }

}  // namespace

void CheckProcessing(const PlannedFile& file, uint32_t setWidth, uint32_t setHeight) {
    if (file.layout == FileLayout::Statistics) return;
    const ResolvedParameters& p = *file.parameters;
    if (file.layout != FileLayout::L && file.layout != FileLayout::RGB) {
        Unrecorded(file, "the " + std::string(FileLayoutName(file.layout)) + " layout (an alpha channel)");
    }
    if (p.fileFormat == FileFormat::png && p.bitDepth != BitDepth::u16) {
        Unrecorded(file, "PNG at " + std::string(BitDepthName(p.bitDepth)) + " bits");
    }
    if (p.fileFormat == FileFormat::exr && p.bitDepth != BitDepth::f32) {
        Unrecorded(file, "OpenEXR at " + std::string(BitDepthName(p.bitDepth)));
    }
    if (p.dithering) Unrecorded(file, "dithering");
    if (file.width != setWidth || file.height != setHeight) {
        Unrecorded(file, "resizing " + std::to_string(setWidth) + "x" + std::to_string(setHeight) + " to " +
                             std::to_string(file.width) + "x" + std::to_string(file.height) + " (sizeLog2)");
    }
    if (p.paddingAlgorithm != Padding::infinite && p.paddingAlgorithm != Padding::passthrough) {
        Unrecorded(file, "the padding \"" + std::string(PaddingName(p.paddingAlgorithm)) + "\" with dilationDistance");
    }
}

std::string EncodeFile(const PlannedFile& file, const FileRaster& raster) {
    if (file.layout == FileLayout::Statistics) {
        if (!raster.statistics) throw std::invalid_argument("export: a statistics file without statistics");
        return *raster.statistics;
    }
    const uint32_t components = ComponentsOf(file.layout);
    if (raster.width != file.width || raster.height != file.height || raster.channels != components ||
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
