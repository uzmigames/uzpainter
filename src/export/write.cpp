#include "export/write.h"

#include "export/encode.h"
#include "export/padding.h"
#include "export/uztexture_writer.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

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

/// The `.uztexture` derivative of `file` from its PNG 16 samples (`EncodedUzTexture`), or the
/// negative-Z refusal of policy `fail`.
render::Result<EncodedUzTexture> CookNormalDerivative(const PlannedFile& file, const std::vector<uint16_t>& samples) {
    const UzTextureOutput& output = *file.uztexture;
    const size_t texels = size_t{file.width} * file.height;
    if (samples.size() != texels * 3) {
        return ExportFail("the samples of " + file.relativePath + " are not the RGB PNG 16 its derivative reads");
    }
    Rgba16Image canonical{file.width, file.height, {}};
    canonical.rgba.reserve(texels * 4);
    for (size_t t = 0; t < texels; ++t) {
        canonical.rgba.insert(canonical.rgba.end(), {samples[t * 3], samples[t * 3 + 1], samples[t * 3 + 2], 65535});
    }
    const NegativeZ negative = FindNegativeZ(canonical);
    if (negative.count != 0 && output.negativeZ == NegativeZPolicy::fail) {
        return ExportFail(std::string(NegativeZNormal(file.relativePath, negative).what()) +
                          "; the negative-Z policy is fail (decision 316): nothing is published");
    }
    EncodedUzTexture cooked;
    cooked.policy = output.negativeZ;
    cooked.negativeTexels = negative.count;
    if (negative.count != 0) cooked.firstNegative = std::array<uint32_t, 2>{negative.firstX, negative.firstY};
    cooked.routed = negative.count != 0;
    UzTextureSpec spec;
    spec.binding = "normal";
    spec.format = cooked.routed ? uz::TextureFormat::Uncompressed_RGBA8 : uz::TextureFormat::BC5;
    spec.srgb = false;
    spec.mips.mapClass = MipClass::Normal;
    const BcEncoder& encoder = EtcpakEncoder();
    UzTexture texture = CookUzTexture(encoder, canonical, spec, 0);
    cooked.bytes.assign(texture.bytes.begin(), texture.bytes.end());
    cooked.format = cooked.routed ? "RGBA8" : "BC5";
    cooked.mips = static_cast<uint32_t>(texture.metadata.mips.size());
    cooked.encoder = std::string(encoder.Name());
    return cooked;
}

}  // namespace

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

render::Result<std::vector<EncodedFile>> EncodeExport(const core::Project& project, std::int64_t revision,
                                                      const ExportPlan& plan, const SourceInputs& inputs,
                                                      const evaluator::TemplateLibrary& templates,
                                                      evaluator::ITileStore& store, evaluator::TileCache& cache,
                                                      const DiagnosticMeasure* diagnostic) {
    if (diagnostic != nullptr && !diagnostic->mesh) {
        return ExportFail("the diagnostic measure export (decision 286) needs the texturing mesh");
    }
    // 1. Every file's processing and padding, before any evaluation.
    std::map<core::Id, Coverage> coverages;
    std::vector<std::vector<std::string>> bypassed(plan.files.size());
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        const core::TextureSet* set = SetOf(project, file.textureSetId);
        if (set == nullptr) return ExportFail("the texture set of " + file.relativePath + " is not in the project");
        CheckProcessing(project, file);
        // A statistics file has no padding; one of a combined virtual normal reads its island-edge
        // texels, and without a texturing mesh there are no UV islands.
        const bool statistics = file.layout == FileLayout::Statistics;
        if (statistics && (!ReadsCombinedNormal(file) || !inputs.geometry)) continue;
        if (!coverages.contains(set->id)) {
            std::optional<Coverage> coverage = CoverageOf(*set, inputs);
            if (!coverage) {
                return ExportFail("the padding of " + file.relativePath + " needs the UV coverage of the texture set \"" +
                                  set->name + "\", and no texturing mesh provides it");
            }
            if (diagnostic != nullptr) IslandTriangles(*coverage, *diagnostic->mesh, set->material_id);
            coverages.emplace(set->id, std::move(*coverage));
        }
        const Coverage& coverage = coverages.at(set->id);
        if (diagnostic == nullptr) {
            CheckIslandNormal(file, coverage);
            CheckPadding(file, coverage);
            continue;
        }
        // The diagnostic measure export: production's two island refusals recorded, not thrown.
        const auto record = [&](const auto& check) {
            try {
                check();
            } catch (const core::NotYetSupported& refusal) {
                bypassed[i].emplace_back(refusal.what());
            }
        };
        record([&] { CheckIslandNormal(file, coverage); });
        record([&] { CheckPadding(file, coverage); });
        CheckPadding(file, coverage, InexactPadding::measure);
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
        // The diagnostic measure export computes a combined virtual normal on the file's islands as
        // Painter does (virtual_maps.h, decision 308).
        SourceInputs measured;
        if (diagnostic != nullptr && file.layout != FileLayout::Statistics) {
            measured = inputs;
            measured.islandNormal = &coverages.at(file.textureSetId);
        }
        render::Result<FileRaster> raster =
            EvaluateFileOn(project, revision, file, measured.islandNormal != nullptr ? measured : inputs, templates,
                           store, cache);
        if (!raster) return render::Unexpected(raster.error());
        try {
#if defined(UZP_EXPORT_FAULT_HOOKS)
            if (fault::Fails(fault::Point::fail_encode, i)) throw std::runtime_error("injected encoder failure");
#endif
            const Coverage* coverage =
                file.layout != FileLayout::Statistics ? &coverages.at(file.textureSetId) : nullptr;
            std::vector<uint16_t> samples;
            EncodedImage image = EncodeFile(file, *raster, coverage,
                                            diagnostic != nullptr ? InexactPadding::measure : InexactPadding::refuse,
                                            file.uztexture ? &samples : nullptr);
            std::optional<EncodedUzTexture> derivative;
            if (file.uztexture) {
                render::Result<EncodedUzTexture> cooked = CookNormalDerivative(file, samples);
                if (!cooked) return render::Unexpected(cooked.error());
                derivative = std::move(*cooked);
            }
            encoded.push_back({std::move(image.bytes), raster->normalTag, image.layout, diagnostic != nullptr,
                               std::move(bypassed[i]), raster->undecided, std::move(derivative)});
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
    const auto write = [&](const std::string& rootPath, const std::string& relativePath,
                           const std::string& bytes) -> render::Result<void> {
        const fs::path path = fs::path(plan.exportPath) / fs::path(relativePath);
        std::error_code error;
        fs::create_directories(path.parent_path(), error);
        if (error) return ExportFail("cannot create the folder of " + path.string() + ": " + error.message());
        std::ofstream stream(path, std::ios::binary | std::ios::trunc);
        stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        stream.close();
        if (!stream) return ExportFail("cannot write " + path.string());
        written.push_back({rootPath, relativePath, path.generic_string(), bytes.size(), core::Sha256Hex(bytes)});
        return {};
    };
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        render::Result<void> done = write(file.rootPath, file.relativePath, (*encoded)[i].bytes);
        if (done && (*encoded)[i].uztexture) {
            done = write(file.rootPath, file.uztexture->relativePath, (*encoded)[i].uztexture->bytes);
        }
        if (!done) return render::Unexpected(done.error());
    }
    return written;
}

}  // namespace uzp::exporter
