#include "export/write.h"

#include "export/encode.h"
#include "export/padding.h"
#include "uzp_core/manifest/sha256.h"

#include <filesystem>
#include <fstream>
#include <map>
#include <optional>

namespace uzp::exporter {

namespace {

namespace fs = std::filesystem;

render::Unexpected ExportFail(std::string reason) {
    return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "export: " + std::move(reason));
}

const core::TextureSet* SetOf(const core::Project& project, core::Id id) {
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.id == id) return &set;
    }
    return nullptr;
}

/// The texel-centre coverage of every object of `set`'s material, or nullopt without a mesh.
std::optional<Coverage> CoverageOf(const core::TextureSet& set, const SourceInputs& inputs) {
    if (!inputs.geometry) return std::nullopt;
    evaluator::GeometryMaskQuery query;
    query.material = set.material_id;
    query.inclusionList = false;
    query.width = static_cast<uint32_t>(set.resolution.width);
    query.height = static_cast<uint32_t>(set.resolution.height);
    const std::shared_ptr<const evaluator::DecodedImage> mask = inputs.geometry->Coverage(query);
    if (!mask) return std::nullopt;
    Coverage coverage{mask->width, mask->height, {}};
    coverage.covered.reserve(size_t{mask->width} * mask->height);
    for (size_t t = 0; t < size_t{mask->width} * mask->height; ++t) {
        coverage.covered.push_back(mask->values[t * mask->channels] != 0 ? 1 : 0);
    }
    return coverage;
}

}  // namespace

render::Result<std::vector<WrittenFile>> WriteExport(const core::Project& project, std::int64_t revision,
                                                     const ExportPlan& plan, const SourceInputs& inputs,
                                                     const evaluator::TemplateLibrary& templates,
                                                     evaluator::ITileStore& store, evaluator::TileCache& cache) {
    // 1. Every file's processing and padding, before any evaluation.
    std::map<core::Id, Coverage> coverages;
    for (const PlannedFile& file : plan.files) {
        const core::TextureSet* set = SetOf(project, file.textureSetId);
        if (set == nullptr) return ExportFail("the texture set of " + file.relativePath + " is not in the project");
        CheckProcessing(file, static_cast<uint32_t>(set->resolution.width),
                        static_cast<uint32_t>(set->resolution.height));
        if (file.layout == FileLayout::Statistics) continue;
        if (!coverages.contains(set->id)) {
            std::optional<Coverage> coverage = CoverageOf(*set, inputs);
            if (!coverage) {
                return ExportFail("the padding of " + file.relativePath + " needs the UV coverage of the texture set \"" +
                                  set->name + "\", and no texturing mesh provides it");
            }
            coverages.emplace(set->id, std::move(*coverage));
        }
        CheckPadding(file, coverages.at(set->id));
    }
    // 2. Every file evaluated, padded and encoded in memory.
    std::vector<std::string> encoded;
    encoded.reserve(plan.files.size());
    for (const PlannedFile& file : plan.files) {
        render::Result<FileRaster> raster = EvaluateFileOn(project, revision, file, inputs, templates, store, cache);
        if (!raster) return render::Unexpected(raster.error());
        if (file.layout != FileLayout::Statistics) ApplyPadding(file, *raster, coverages.at(file.textureSetId));
        encoded.push_back(EncodeFile(file, *raster));
    }
    // 3. The files written.
    std::vector<WrittenFile> written;
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        const fs::path path = fs::path(plan.exportPath) / fs::path(file.relativePath);
        std::error_code error;
        fs::create_directories(path.parent_path(), error);
        if (error) return ExportFail("cannot create the folder of " + path.string() + ": " + error.message());
        std::ofstream stream(path, std::ios::binary | std::ios::trunc);
        stream.write(encoded[i].data(), static_cast<std::streamsize>(encoded[i].size()));
        stream.close();
        if (!stream) return ExportFail("cannot write " + path.string());
        written.push_back({file.rootPath, file.relativePath, path.generic_string(), encoded[i].size(),
                           core::Sha256Hex(encoded[i])});
    }
    return written;
}

}  // namespace uzp::exporter
