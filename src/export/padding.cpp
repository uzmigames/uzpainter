#include "export/padding.h"

#include "export/encode.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <stdexcept>
#include <string>

namespace uzp::exporter {

namespace {

[[noreturn]] void Unfitted(const PlannedFile& file, const std::string& what) {
    throw core::NotYetSupported("export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
                                "): " + what + " (" + std::string(kProcessingRecording) + ")");
}

}  // namespace

bool Coverage::Complete() const {
    return std::all_of(covered.begin(), covered.end(), [](uint8_t c) { return c != 0; });
}

void CheckPadding(const PlannedFile& file, const Coverage& coverage) {
    if (file.layout == FileLayout::Statistics) return;
    if (coverage.width != file.width || coverage.height != file.height ||
        coverage.covered.size() != size_t{coverage.width} * coverage.height) {
        throw std::invalid_argument("export: the coverage of " + file.relativePath + " does not have its size");
    }
    if (coverage.Complete()) return;
    const std::string_view padding = PaddingName(file.parameters->paddingAlgorithm);
    if (file.parameters->paddingAlgorithm != Padding::passthrough) {
        Unfitted(file, "the padding \"" + std::string(padding) +
                           "\" on a texture set whose UV islands do not cover the whole tile is not fitted: Painter's "
                           "gutter is not the nearest covered texel, and its ring around each island blends across "
                           "the UV seams");
    }
    if (file.layout == FileLayout::LA || file.layout == FileLayout::RGBA) {
        Unfitted(file, "an alpha layout (L+A, RGB+A) on a texture set whose UV islands do not cover the whole tile "
                       "is recorded under infinite and transparent padding only, and not fitted");
    }
    for (const PlannedChannel& channel : file.channels) {
        const SourceType type = channel.source.type;
        if (type == SourceType::meshMap || type == SourceType::virtualMap) {
            Unfitted(file, "the padding \"passthrough\" of a " + std::string(SourceTypeName(type)) +
                               " source outside the UV islands is not recorded");
        }
    }
}

void ApplyPadding(const PlannedFile& file, FileRaster& raster, const Coverage& coverage) {
    CheckPadding(file, coverage);
    if (raster.width != coverage.width || raster.height != coverage.height) {
        throw std::invalid_argument("export: the raster of " + file.relativePath + " does not have its size");
    }
    // Every admitted case keeps the evaluated values: complete coverage, or `passthrough`.
}

}  // namespace uzp::exporter
