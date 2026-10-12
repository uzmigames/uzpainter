#include "export/padding.h"

#include "export/encode.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <stdexcept>
#include <string>

namespace uzp::exporter {

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
    throw core::NotYetSupported(
        "export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath + "): the padding \"" +
        std::string(PaddingName(file.parameters->paddingAlgorithm)) +
        "\" on a texture set whose UV islands do not cover the whole tile is not fitted: Painter's padding follows "
        "the mesh across UV seams (" +
        std::string(kProcessingRecording) + ")");
}

void ApplyPadding(const PlannedFile& file, FileRaster& raster, const Coverage& coverage) {
    CheckPadding(file, coverage);
    if (raster.width != coverage.width || raster.height != coverage.height) {
        throw std::invalid_argument("export: the raster of " + file.relativePath + " does not have its size");
    }
    // Complete coverage: every texel holds its evaluated value, for `infinite` and `passthrough`.
}

}  // namespace uzp::exporter
