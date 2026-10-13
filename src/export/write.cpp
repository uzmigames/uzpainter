#include "export/write.h"

#include "evaluator/height_to_normal.h"
#include "export/encode.h"
#include "export/padding.h"
#include "uzp_core/manifest/sha256.h"

#include <filesystem>
#include <fstream>
#include <map>
#include <optional>
#include <stdexcept>

#if defined(UZP_EXPORT_FAULT_HOOKS)
#include "export/fault.h"
#endif

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

render::Result<std::vector<EncodedFile>> EncodeExport(const core::Project& project, std::int64_t revision,
                                                      const ExportPlan& plan, const SourceInputs& inputs,
                                                      const evaluator::TemplateLibrary& templates,
                                                      evaluator::ITileStore& store, evaluator::TileCache& cache) {
    // 1. Every file's processing and padding, before any evaluation.
    std::map<core::Id, Coverage> coverages;
    for (const PlannedFile& file : plan.files) {
        const core::TextureSet* set = SetOf(project, file.textureSetId);
        if (set == nullptr) return ExportFail("the texture set of " + file.relativePath + " is not in the project");
        CheckProcessing(project, file);
        if (file.layout == FileLayout::Statistics) continue;
        if (!coverages.contains(set->id)) {
            std::optional<Coverage> coverage = CoverageOf(*set, inputs);
            if (!coverage) {
                return ExportFail("the padding of " + file.relativePath + " needs the UV coverage of the texture set \"" +
                                  set->name + "\", and no texturing mesh provides it");
            }
            coverages.emplace(set->id, std::move(*coverage));
        }
        const Coverage& coverage = coverages.at(set->id);
        if (!coverage.Complete() && ReadsCombinedNormal(file)) {
            render::Result<bool> flat =
                evaluator::FlatZeroHeight(project, set->id, file.stackId, templates, inputs.templateId);
            if (!flat) return render::Unexpected(flat.error());
            CheckIslandNormal(file, coverage, *flat);
        }
        CheckPadding(file, coverage);
    }
    // 2. Every file evaluated, padded and encoded in memory. Every check passed in step 1, so a
    // padding or an encoder that throws here is a failure of this export, returned as such: the
    // host keeps running (EXP-06).
    std::vector<EncodedFile> encoded;
    encoded.reserve(plan.files.size());
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        if (inputs.beforeFile && !inputs.beforeFile(i, plan.files.size())) {
            return ExportFail("stopped before " + file.relativePath);
        }
        render::Result<FileRaster> raster = EvaluateFileOn(project, revision, file, inputs, templates, store, cache);
        if (!raster) return render::Unexpected(raster.error());
        try {
#if defined(UZP_EXPORT_FAULT_HOOKS)
            if (fault::Fails(fault::Point::fail_encode, i)) throw std::runtime_error("injected encoder failure");
#endif
            const Coverage* coverage =
                file.layout != FileLayout::Statistics ? &coverages.at(file.textureSetId) : nullptr;
            EncodedImage image = EncodeFile(file, *raster, coverage);
            encoded.push_back({std::move(image.bytes), raster->normalTag, image.layout});
        } catch (const std::exception& e) {
            return ExportFail("encoding " + file.relativePath + " failed: " + e.what());
        }
    }
    return encoded;
}

render::Result<std::vector<WrittenFile>> WriteExport(const core::Project& project, std::int64_t revision,
                                                     const ExportPlan& plan, const SourceInputs& inputs,
                                                     const evaluator::TemplateLibrary& templates,
                                                     evaluator::ITileStore& store, evaluator::TileCache& cache) {
    render::Result<std::vector<EncodedFile>> encoded =
        EncodeExport(project, revision, plan, inputs, templates, store, cache);
    if (!encoded) return render::Unexpected(encoded.error());
    // 3. The files written.
    std::vector<WrittenFile> written;
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        const fs::path path = fs::path(plan.exportPath) / fs::path(file.relativePath);
        std::error_code error;
        fs::create_directories(path.parent_path(), error);
        if (error) return ExportFail("cannot create the folder of " + path.string() + ": " + error.message());
        std::ofstream stream(path, std::ios::binary | std::ios::trunc);
        const std::string& bytes = (*encoded)[i].bytes;
        stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        stream.close();
        if (!stream) return ExportFail("cannot write " + path.string());
        written.push_back(
            {file.rootPath, file.relativePath, path.generic_string(), bytes.size(), core::Sha256Hex(bytes)});
    }
    return written;
}

}  // namespace uzp::exporter
