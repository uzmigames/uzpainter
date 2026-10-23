#include "export/write.h"

#include "export/encode.h"
#include "export/cook_dds.h"
#include "export/padding.h"
#include "export/resize.h"
#include "export/uzmat_writer.h"
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

/// The 16-bit samples of a canonical file as written, and their layout.
struct CanonicalSamples {
    FileLayout layout = FileLayout::RGB;
    std::vector<uint16_t> samples;
};

EncodedDds CookDdsDerivative(const PlannedFile& file, const CanonicalSamples& canonical) {
    const DdsOutput& output = *file.dds;
    const size_t texels = size_t{file.width} * file.height;
    const size_t channels = canonical.layout == FileLayout::L ? 1 : canonical.layout == FileLayout::LA ? 2
                           : canonical.layout == FileLayout::RGB ? 3 : 4;
    if (canonical.samples.size() != texels * channels) {
        throw std::invalid_argument("DDS canonical samples do not match their PNG16 layout");
    }
    Rgba16Image image{file.width, file.height, {}};
    image.rgba.reserve(texels * 4);
    for (size_t t = 0; t < texels; ++t) {
        const uint16_t* v = &canonical.samples[t * channels];
        switch (channels) {
            case 1: image.rgba.insert(image.rgba.end(), {v[0], v[0], v[0], 65535}); break;
            case 2: image.rgba.insert(image.rgba.end(), {v[0], v[0], v[0], v[1]}); break;
            case 3: image.rgba.insert(image.rgba.end(), {v[0], v[1], v[2], 65535}); break;
            default: image.rgba.insert(image.rgba.end(), {v[0], v[1], v[2], v[3]}); break;
        }
    }
    DdsSpec spec;
    spec.format = output.format;
    switch (output.mips) {
        case DerivativeMips::linear: spec.mips.mapClass = MipClass::Linear; break;
        case DerivativeMips::normal: spec.mips.mapClass = MipClass::Normal; break;
        case DerivativeMips::colour: spec.mips.mapClass = MipClass::Colour; break;
        case DerivativeMips::masked_colour: spec.mips.mapClass = MipClass::MaskedColour; break;
        default: throw std::invalid_argument("DDS has an invalid mip class");
    }
    const BcEncoder& encoder = EtcpakEncoder();
    const Dds texture = CookDds(encoder, image, spec, 0);
    EncodedDds cooked;
    cooked.bytes.assign(texture.bytes.begin(), texture.bytes.end());
    cooked.format = std::string(BcFormatName(output.format));
    cooked.layout = canonical.layout;
    cooked.mips = static_cast<uint32_t>(texture.metadata.mips.size());
    cooked.encoder = std::string(encoder.Name());
    cooked.settings = std::string(encoder.Settings(output.format));
    return cooked;
}

/// The `.uztexture` derivative of `file` from its canonical file's PNG 16 samples
/// (`EncodedUzTexture`), or the negative-Z refusal of policy `fail`.
render::Result<EncodedUzTexture> CookDerivative(const PlannedFile& file, const PlannedFile& canonicalFile,
                                                const CanonicalSamples& canonical) {
    const UzTextureOutput& output = *file.uztexture;
    const size_t texels = size_t{canonicalFile.width} * canonicalFile.height;
    const size_t channels = canonical.layout == FileLayout::L    ? 1
                            : canonical.layout == FileLayout::LA  ? 2
                            : canonical.layout == FileLayout::RGB ? 3
                                                                  : 4;
    if (canonical.samples.size() != texels * channels) {
        return ExportFail("the samples of " + canonicalFile.relativePath + " are not the PNG 16 the derivative of " +
                          file.relativePath + " reads");
    }
    Rgba16Image image{canonicalFile.width, canonicalFile.height, {}};
    image.rgba.reserve(texels * 4);
    for (size_t t = 0; t < texels; ++t) {
        const uint16_t* v = &canonical.samples[t * channels];
        switch (channels) {
            case 1: image.rgba.insert(image.rgba.end(), {v[0], v[0], v[0], 65535}); break;
            case 2: image.rgba.insert(image.rgba.end(), {v[0], v[0], v[0], v[1]}); break;
            case 3: image.rgba.insert(image.rgba.end(), {v[0], v[1], v[2], 65535}); break;
            default: image.rgba.insert(image.rgba.end(), {v[0], v[1], v[2], v[3]}); break;
        }
    }
    EncodedUzTexture cooked;
    cooked.layout = canonical.layout;
    cooked.policy = output.negativeZ;
    UzTextureSpec spec;
    spec.binding = output.binding;
    spec.srgb = output.srgb;
    switch (output.mips) {
        case DerivativeMips::linear: spec.mips.mapClass = MipClass::Linear; break;
        case DerivativeMips::colour: spec.mips.mapClass = MipClass::Colour; break;
        case DerivativeMips::normal: spec.mips.mapClass = MipClass::Normal; break;
        case DerivativeMips::masked_colour: spec.mips.mapClass = MipClass::MaskedColour; break;
    }
    switch (output.format) {
        case UzTextureStorage::BC4: spec.format = uz::TextureFormat::BC4; break;
        case UzTextureStorage::BC5: spec.format = uz::TextureFormat::BC5; break;
        case UzTextureStorage::BC7: spec.format = uz::TextureFormat::BC7; break;
        case UzTextureStorage::RGBA8: spec.format = uz::TextureFormat::Uncompressed_RGBA8; break;
    }
    UzTextureStorage stored = output.format;
    if (output.mips == DerivativeMips::normal) {
        const NegativeZ negative = FindNegativeZ(image);
        if (negative.count != 0 && output.negativeZ == NegativeZPolicy::fail) {
            return ExportFail(std::string(NegativeZNormal(canonicalFile.relativePath, negative).what()) +
                              "; the negative-Z policy is fail (decision 316): nothing is published");
        }
        cooked.negativeTexels = negative.count;
        if (negative.count != 0) cooked.firstNegative = std::array<uint32_t, 2>{negative.firstX, negative.firstY};
        cooked.routed = negative.count != 0 && output.format == UzTextureStorage::BC5;
        if (cooked.routed) {
            spec.format = uz::TextureFormat::Uncompressed_RGBA8;
            stored = UzTextureStorage::RGBA8;
        }
    }
    const BcEncoder& encoder = EtcpakEncoder();
    UzTexture texture = CookUzTexture(encoder, image, spec, 0);
    cooked.bytes.assign(texture.bytes.begin(), texture.bytes.end());
    cooked.format = std::string(UzTextureStorageName(stored));
    cooked.mips = static_cast<uint32_t>(texture.metadata.mips.size());
    cooked.encoder = std::string(encoder.Name());
    return cooked;
}

/// The `.uzmat` `index` of `plan` over the cooked derivatives of its files.
EncodedUzMaterial WriteMaterial(const ExportPlan& plan, size_t index, const std::vector<EncodedFile>& encoded) {
    const UzMaterialOutput& material = plan.materials[index];
    bool alpha = false;
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        if (file.uztexture && file.uztexture->relativePath == material.albedo && encoded[i].uztexture) {
            const FileLayout layout = encoded[i].uztexture->layout;
            alpha = layout == FileLayout::RGBA || layout == FileLayout::LA;
        }
    }
    UzMaterialSpec spec;
    spec.name = material.relativePath.substr(0, material.relativePath.size() - std::string_view(".uzmat").size());
    spec.materialPath = material.relativePath;
    spec.albedo = material.albedo;
    spec.normal = material.normal;
    spec.orm = material.orm;
    spec.emissive = material.emissive;
    spec.height = material.height;
    spec.blend = alpha ? UzMaterialBlend::Masked : UzMaterialBlend::Opaque;
    UzMaterial written = WriteUzMaterial(spec);
    EncodedUzMaterial out;
    out.index = index;
    out.bytes = std::move(written.bytes);
    out.inlineMaterial = std::move(written.inlineMaterial);
    out.blend = alpha ? "Masked" : "Opaque";
    for (UzMaterialGap& gap : written.gaps) {
        out.gaps.push_back({std::move(gap.binding), std::move(gap.path), std::move(gap.reason)});
    }
    return out;
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
    // A resized file's coverage at its own size, by file index (resize.h, decision 349).
    std::map<size_t, Coverage> resizedCoverages;
    std::vector<Resize> resizes(plan.files.size(), Resize::none);
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
        resizes[i] = ResizeOf(static_cast<uint32_t>(set->resolution.width),
                              static_cast<uint32_t>(set->resolution.height), file);
        if (resizes[i] != Resize::none) {
            std::optional<Coverage> target = CoverageAt(*set, inputs, file.width, file.height);
            if (!target) {
                return ExportFail("the padding of " + file.relativePath + " needs the UV coverage of the texture set \"" +
                                  set->name + "\" at its size, and no texturing mesh provides it");
            }
            if (std::optional<std::string> refusal = ResizeCoverageRefusal(file, coverages.at(set->id), *target)) {
                throw core::NotYetSupported(*refusal);
            }
            resizedCoverages.emplace(i, std::move(*target));
        }
        const Coverage& coverage =
            resizes[i] != Resize::none ? resizedCoverages.at(i) : coverages.at(set->id);
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
    // The canonical files whose samples a derivative is cooked from.
    std::map<std::string, size_t> canonicalIndex;
    for (size_t i = 0; i < plan.files.size(); ++i) canonicalIndex.emplace(plan.files[i].relativePath, i);
    std::map<size_t, CanonicalSamples> canonicals;
    for (const PlannedFile& file : plan.files) {
        if (file.dds) {
            const auto it = canonicalIndex.find(file.dds->canonical);
            if (it == canonicalIndex.end() || file.dds->canonical != file.relativePath) {
                return ExportFail("DDS must retain its own canonical PNG16 file in the plan");
            }
            canonicals.emplace(it->second, CanonicalSamples{});
        }
        if (!file.uztexture) continue;
        const auto it = canonicalIndex.find(file.uztexture->canonical);
        if (it == canonicalIndex.end()) {
            return ExportFail("the canonical map " + file.uztexture->canonical + " of " + file.uztexture->relativePath +
                              " is not in the plan");
        }
        canonicals.emplace(it->second, CanonicalSamples{});
    }
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        if (inputs.beforeFile && !inputs.beforeFile(i, plan.files.size())) {
            return ExportFail("stopped before " + file.relativePath);
        }
        // The diagnostic measure export computes a combined virtual normal on the file's islands as
        // Painter does (virtual_maps.h, decision 308).
        SourceInputs measured;
        measured.procedurals = inputs.procedurals;
        if (diagnostic != nullptr && file.layout != FileLayout::Statistics) {
            measured = inputs;
            measured.islandNormal =
                resizes[i] != Resize::none ? &resizedCoverages.at(i) : &coverages.at(file.textureSetId);
        }
        const SourceInputs& sourceInputs = measured.islandNormal != nullptr ? measured : inputs;
        // An upscaled file is its texture set evaluated at the file's size; a downscaled one the
        // mean of the set's evaluation (resize.h, decision 349).
        render::Result<FileRaster> raster =
            resizes[i] == Resize::upscale
                ? EvaluateFileOn(AtFileSize(project, file), revision, file, sourceInputs, templates, store, cache)
                : EvaluateFileOn(project, revision, file, sourceInputs, templates, store, cache);
        if (raster && resizes[i] == Resize::downscale) raster = Downscale(file, *raster);
        if (!raster) return render::Unexpected(raster.error());
        try {
#if defined(UZP_EXPORT_FAULT_HOOKS)
            if (fault::Fails(fault::Point::fail_encode, i)) throw std::runtime_error("injected encoder failure");
#endif
            const Coverage* coverage = file.layout == FileLayout::Statistics ? nullptr
                                       : resizes[i] != Resize::none   ? &resizedCoverages.at(i)
                                                                      : &coverages.at(file.textureSetId);
            const auto canonical = canonicals.find(i);
            EncodedImage image = EncodeFile(file, *raster, coverage,
                                            diagnostic != nullptr ? InexactPadding::measure : InexactPadding::refuse,
                                            canonical != canonicals.end() ? &canonical->second.samples : nullptr);
            if (canonical != canonicals.end()) canonical->second.layout = image.layout;
            encoded.push_back({std::move(image.bytes), raster->normalTag, image.layout, diagnostic != nullptr,
                               std::move(bypassed[i]), raster->undecided, std::nullopt});
        } catch (const std::exception& e) {
            return ExportFail("encoding " + file.relativePath + " failed: " + e.what());
        }
    }
    // The derivatives, each from its canonical file's samples, then the materials that bind them.
    for (size_t i = 0; i < plan.files.size(); ++i) {
        const PlannedFile& file = plan.files[i];
        if (file.dds) {
            try {
                encoded[i].dds = CookDdsDerivative(file, canonicals.at(i));
            } catch (const std::exception& e) {
                return ExportFail("cooking " + file.dds->relativePath + " failed: " + e.what());
            }
        }
        if (!file.uztexture) continue;
        const size_t c = canonicalIndex.at(file.uztexture->canonical);
        try {
            render::Result<EncodedUzTexture> cooked = CookDerivative(file, plan.files[c], canonicals.at(c));
            if (!cooked) return render::Unexpected(cooked.error());
            encoded[i].uztexture = std::move(*cooked);
        } catch (const std::exception& e) {
            return ExportFail("cooking " + file.uztexture->relativePath + " failed: " + e.what());
        }
    }
    for (size_t m = 0; m < plan.materials.size(); ++m) {
        try {
            encoded[plan.materials[m].after].material = WriteMaterial(plan, m, encoded);
        } catch (const std::exception& e) {
            return ExportFail("writing " + plan.materials[m].relativePath + " failed: " + e.what());
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
        if (done && (*encoded)[i].dds) {
            done = write(file.rootPath, file.dds->relativePath, (*encoded)[i].dds->bytes);
        }
        if (done && (*encoded)[i].material) {
            const UzMaterialOutput& material = plan.materials[(*encoded)[i].material->index];
            done = write(material.rootPath, material.relativePath, (*encoded)[i].material->bytes);
        }
        if (!done) return render::Unexpected(done.error());
    }
    return written;
}

}  // namespace uzp::exporter
