#include "export/guards.h"

#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "export/encode.h"
#include "export/resize.h"
#include "export/write.h"
#include "mesh/reload.h"
#include "mesh/texturing_mesh.h"

#include <algorithm>
#include <map>
#include <regex>
#include <stdexcept>

namespace uzp::exporter {

namespace {

/// Recorded by R-090 and not fitted (decision 103); the owners of the remaining fits.
constexpr std::string_view kSrgb8NotRecorded =
    "recording R-090 P10 records BaseColor, Specular and Emissive only; decision 126";
constexpr std::string_view kL8MaterialNotRecorded =
    "tier0/semantics/export-l8-material records RGB and L files of one L8 channel under Legacy; decision 204";
constexpr std::string_view kDitherNotFitted =
    "recording R-090 P3, decisions 103 and 349; owner phase3.2_unreal-ue56-packed-preset item 2.9";
constexpr std::string_view kResizeNotFitted =
    "recording R-090 P4, decisions 103 and 349; owner phase3.2_unreal-ue56-packed-preset item 2.9";
constexpr std::string_view kPaddingNotFitted =
    "recording R-090 P5 and P9, decision 103; owner phase3.2_unreal-ue56-packed-preset";

/// The message of a refusal of `file`: `what`, then its owner.
std::string Refused(const PlannedFile& file, const std::string& what, std::string_view owner) {
    return "export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath + "): " + what + " (" +
           std::string(owner) + ")";
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

/// The stack channel of `source` when it is an L8 documentMap channel of `file`'s stack.
std::optional<core::ChannelType> L8Channel(const core::TextureSet& set, const PlannedFile& file,
                                           const PlannedSource& source) {
    if (source.type != SourceType::documentMap || !source.channel) return std::nullopt;
    for (const core::Stack& stack : set.stacks) {
        if (stack.id != file.stackId) continue;
        const auto it = stack.channels.find(*source.channel);
        if (it != stack.channels.end() && it->second.format == core::ChannelFormat::L8) return *source.channel;
    }
    return std::nullopt;
}

/// The stack channel format a channel of `file` reads one component of (a documentMap source,
/// not its luma), or nothing.
std::optional<core::ChannelFormat> DocumentFormat(const core::TextureSet& set, const PlannedFile& file,
                                                  const PlannedChannel& channel) {
    if (channel.luma || channel.source.type != SourceType::documentMap || !channel.source.channel) {
        return std::nullopt;
    }
    for (const core::Stack& stack : set.stacks) {
        if (stack.id != file.stackId) continue;
        const auto it = stack.channels.find(*channel.source.channel);
        if (it != stack.channels.end()) return it->second.format;
    }
    return std::nullopt;
}

bool IsUserChannel(core::ChannelType type) { return core::ToString(type).starts_with("User"); }

/// True when `file` is laid out as export-l8-material records an L8 material channel: an RGB file
/// whose R, G and B, or an L file whose L, each read that letter of one documentMap source.
bool RecordedL8Mapping(const PlannedFile& file) {
    const size_t letters = file.layout == FileLayout::RGB ? 3 : file.layout == FileLayout::L ? 1 : 0;
    if (letters == 0 || file.channels.size() != letters) return false;
    return std::all_of(file.channels.begin(), file.channels.end(), [&](const PlannedChannel& c) {
        return c.src == c.dest && c.source.type == file.channels[0].source.type &&
               c.source.name == file.channels[0].source.name;
    });
}

/// The tasks, recordings and decisions `reason` names, in order of appearance, each once.
core::json::Array References(const std::string& reason) {
    static const std::regex kReference(R"(phase\d+\.\d+_[a-z0-9-]+|R-\d+|decisions? \d+(?:(?:, | and | to )\d+)*)");
    static const std::regex kNumber(R"(\d+)");
    core::json::Array references;
    std::vector<std::string> seen;
    const auto add = [&](std::string reference) {
        if (std::ranges::find(seen, reference) != seen.end()) return;
        seen.push_back(reference);
        references.emplace_back(std::move(reference));
    };
    for (auto it = std::sregex_iterator(reason.begin(), reason.end(), kReference); it != std::sregex_iterator(); ++it) {
        const std::string match = it->str();
        if (!match.starts_with("decision")) {
            add(match);
            continue;
        }
        for (auto n = std::sregex_iterator(match.begin(), match.end(), kNumber); n != std::sregex_iterator(); ++n) {
            add("decision " + n->str());
        }
    }
    return references;
}

}  // namespace

std::optional<std::string> ProcessingRefusal(const core::Project& project, const PlannedFile& file) {
    if (file.layout == FileLayout::Statistics) return std::nullopt;
    const core::TextureSet& set = SetOf(project, file);
    const ResolvedParameters& p = *file.parameters;
    const auto width = static_cast<uint32_t>(set.resolution.width);
    const auto height = static_cast<uint32_t>(set.resolution.height);
    const Resize resize = ResizeOf(width, height, file);
    if (p.dithering) {
        // Dithering changes nothing at PNG 16 (recording R-090 P3: on equals off on every map); at
        // PNG 8 it changes nothing on an RGB16 channel and an sRGB8 BaseColor (decision 349), and
        // changes a float channel or a virtual normal deterministically, unfitted; in OpenEXR no
        // recording compares it with off; with a resize it is not recorded.
        if (p.fileFormat == FileFormat::exr) {
            return Refused(file, "dithering in OpenEXR is not compared with dithering off by any recording",
                           kDitherNotFitted);
        }
        if (resize != Resize::none) {
            return Refused(file, "dithering with a resize is not recorded", kDitherNotFitted);
        }
        if (p.bitDepth == BitDepth::u8) {
            for (const PlannedChannel& channel : file.channels) {
                const std::optional<core::ChannelFormat> format = DocumentFormat(set, file, channel);
                const bool unchanged = format == core::ChannelFormat::RGB16 ||
                                       (format == core::ChannelFormat::sRGB8 &&
                                        channel.source.channel == core::ChannelType::BaseColor);
                if (unchanged) continue;
                return Refused(file,
                               "dithering at PNG 8 bits of a source other than an RGB16 channel or an sRGB8 "
                               "BaseColor (a float channel, a virtual or mesh map, a luma, a constant) is recorded "
                               "(deterministic) but not fitted",
                               kDitherNotFitted);
            }
        }
    }
    if (resize != Resize::none) {
        const std::string what = "resizing " + std::to_string(width) + "x" + std::to_string(height) + " to " +
                                 std::to_string(file.width) + "x" + std::to_string(file.height) + " (sizeLog2)";
        if (std::min(file.width, file.height) < 128) {
            return Refused(file,
                           what + ": Painter writes no side below 128 (sizeLog2 6 on a 256 set is written at 128), "
                                  "and the plan does not reproduce it",
                           kResizeNotFitted);
        }
        if (resize == Resize::other) {
            return Refused(file, what + " is not recorded: only halving sides or enlarging them by powers of two is",
                           kResizeNotFitted);
        }
        const bool upscale = resize == Resize::upscale;
        const bool recordedFormat = (p.fileFormat == FileFormat::png && p.bitDepth == BitDepth::u16) ||
                                    (p.fileFormat == FileFormat::exr && p.bitDepth == BitDepth::f32) ||
                                    (!upscale && p.fileFormat == FileFormat::png && p.bitDepth == BitDepth::u8);
        if (!recordedFormat) {
            return Refused(file, what + " is recorded at PNG 16 and OpenEXR 32f, and downscaled at PNG 8, only",
                           kResizeNotFitted);
        }
        for (const PlannedChannel& channel : file.channels) {
            const std::optional<core::ChannelFormat> format = DocumentFormat(set, file, channel);
            bool admitted = format == core::ChannelFormat::RGB16 || format == core::ChannelFormat::L16F;
            if (upscale) {
                const std::optional<VirtualMap> map = channel.source.virtualMap;
                admitted = admitted ||
                           (format == core::ChannelFormat::sRGB8 &&
                            channel.source.channel == core::ChannelType::BaseColor) ||
                           (channel.source.type == SourceType::virtualMap &&
                            (map == VirtualMap::Normal_OpenGL || map == VirtualMap::Normal_DirectX));
            }
            if (admitted) continue;
            return Refused(file,
                           what + (upscale ? " is exact for RGB16 and L16F channels, an sRGB8 BaseColor and the "
                                             "Normal_OpenGL and Normal_DirectX virtual maps only"
                                           : " is exact for RGB16 and L16F channels only (an sRGB8 channel and a "
                                             "virtual normal after a downscale are not reproduced)"),
                           kResizeNotFitted);
        }
    }
    if (p.paddingAlgorithm != Padding::infinite && p.paddingAlgorithm != Padding::passthrough) {
        return Refused(file,
                       "the padding \"" + std::string(PaddingName(p.paddingAlgorithm)) +
                           "\" with dilationDistance is recorded but not fitted",
                       kPaddingNotFitted);
    }
    for (const PlannedChannel& channel : file.channels) {
        const std::optional<core::ChannelType> srgb8 = Srgb8Channel(set, file, channel.source);
        if (!srgb8 || IsUserChannel(*srgb8) || SrgbEncodedOnExport(*srgb8)) continue;
        return Refused(file,
                       "the export encoding of the sRGB8 channel " + std::string(core::ToString(*srgb8)) +
                           " (linear like a User channel, or sRGB-encoded like BaseColor) is not recorded",
                       kSrgb8NotRecorded);
    }
    if (p.fileFormat != FileFormat::png) return std::nullopt;
    for (const PlannedChannel& channel : file.channels) {
        // An L8 BaseColor, Specular or Emissive is written as the sRGB encode of its linear value
        // in srcChannel R, B and L and as the linear value in G (export-l8-material, decision 204),
        // recorded for the RGB and L files of one L8 channel under Legacy.
        const std::optional<core::ChannelType> l8 = L8Channel(set, file, channel.source);
        if (!l8 || !SrgbEncodedOnExport(*l8)) continue;
        const std::string what = "the PNG encoding of the L8 channel " + std::string(core::ToString(*l8));
        if (evaluator::PainterOcio(project)) {
            return Refused(file, what + " under OCIO is not recorded", kL8MaterialNotRecorded);
        }
        if (!RecordedL8Mapping(file)) {
            return Refused(file,
                           what + " in a file laid out " + std::string(FileLayoutName(file.layout)) +
                               " other than the channel's own R, G and B, or its L, alone is not recorded",
                           kL8MaterialNotRecorded);
        }
    }
    return std::nullopt;
}

std::optional<std::string> IslandNormalFileRefusal(const PlannedFile& file, const Coverage& coverage) {
    if (coverage.Complete()) return std::nullopt;
    const auto normal = std::find_if(file.channels.begin(), file.channels.end(),
                                     [](const PlannedChannel& channel) { return ReadsCombinedNormal(channel.source); });
    if (normal == file.channels.end()) return std::nullopt;
    return "export: " + file.rootPath + " map \"" + file.fileName + "\" (" + file.relativePath +
           "): " + IslandNormalRefusal(normal->source);
}

std::optional<std::string> PaddingRefusal(const PlannedFile& file, const Coverage& coverage, InexactPadding inexact) {
    if (file.layout == FileLayout::Statistics) return std::nullopt;
    if (coverage.width != file.width || coverage.height != file.height ||
        coverage.covered.size() != size_t{coverage.width} * coverage.height) {
        throw std::invalid_argument("export: the coverage of " + file.relativePath + " does not have its size");
    }
    if (coverage.Complete()) return std::nullopt;
    const Padding padding = file.parameters->paddingAlgorithm;
    if (padding == Padding::infinite) {
        if (inexact == InexactPadding::measure) return std::nullopt;
        return Refused(file,
                       "the padding \"infinite\" on a texture set whose UV islands do not cover the whole tile is not "
                       "exact: Painter's ring across UV seams, at seam corners and at poles is not identified, and the "
                       "best-known rule misses Painter's padding texels by up to 59150 PNG 16 codes (decision 220)",
                       std::string(kIslandsOwner) + ", " + std::string(kProcessingRecording) + ", decision 259");
    }
    if (padding != Padding::passthrough) {
        return Refused(file,
                       "the padding \"" + std::string(PaddingName(padding)) +
                           "\" on a texture set whose UV islands do not cover the whole tile is not fitted",
                       kProcessingRecording);
    }
    if (file.layout == FileLayout::LA || file.layout == FileLayout::RGBA) {
        return Refused(file,
                       "an alpha layout (L+A, RGB+A) on a texture set whose UV islands do not cover the whole tile "
                       "is recorded under infinite and transparent padding only, and not fitted",
                       kProcessingRecording);
    }
    for (const PlannedChannel& channel : file.channels) {
        const SourceType type = channel.source.type;
        if (type == SourceType::meshMap || type == SourceType::virtualMap) {
            return Refused(file,
                           "the padding \"passthrough\" of a " + std::string(SourceTypeName(type)) +
                               " source outside the UV islands is not recorded (R-090 records it for a virtual "
                               "normal from layers without a mesh map only, where Painter's values there differ "
                               "between recordings)",
                           std::string(kIslandsOwner) + ", " + std::string(kProcessingRecording) + ", decision 245");
        }
    }
    return std::nullopt;
}

std::string_view PreflightStatusName(PreflightStatus status) {
    switch (status) {
        case PreflightStatus::blocked: return "blocked";
        case PreflightStatus::needs_evaluation: return "needs_evaluation";
        case PreflightStatus::no_known_blocker: return "no_known_blocker";
    }
    return "";
}

PreflightCoverage CoverageForPreflight(const core::Project& project,
                                       const std::function<std::string(const std::string&)>& read) {
    PreflightCoverage coverage;
    if (!project.mesh) {
        coverage.gap = {true, "the project has no texturing mesh"};
        return coverage;
    }
    try {
        mesh::ImportResult imported = mesh::RederiveMesh(project, read);
        coverage.inputs.geometry = std::make_shared<evaluator::MeshGeometryMasks>(
            std::make_shared<const mesh::TexturingMesh>(std::move(imported.mesh)));
    } catch (const std::exception& error) {
        coverage.gap = {false, std::string("the texturing mesh does not re-derive: ") + error.what()};
    }
    return coverage;
}

ExportPreflight PreflightExport(const core::Project& project, const ExportPlan& plan, const SourceInputs& inputs,
                                const CoverageGap& gap) {
    ExportPreflight preflight;
    std::map<core::Id, std::optional<Coverage>> coverages;
    for (const PlannedFile& file : plan.files) {
        FilePreflight& entry = preflight.files.emplace_back();
        entry.rootPath = file.rootPath;
        entry.fileName = file.fileName;
        entry.relativePath = file.relativePath;
        const auto blocked = [&](std::optional<std::string> refusal) {
            if (!refusal) return false;
            entry.status = PreflightStatus::blocked;
            entry.reason = std::move(*refusal);
            return true;
        };
        if (blocked(ProcessingRefusal(project, file))) continue;
        // As `EncodeExport` step 1: a statistics file needs the coverage only for a combined
        // virtual normal, and only when there is a texturing mesh. A mesh whose coverage could
        // not be obtained is not an absent one: its island checks are unknown.
        if (file.layout == FileLayout::Statistics &&
            (!ReadsCombinedNormal(file) || (!inputs.geometry && gap.meshAbsent))) {
            continue;
        }
        const core::TextureSet& set = SetOf(project, file);
        if (!coverages.contains(file.textureSetId)) coverages.emplace(file.textureSetId, CoverageOf(set, inputs));
        const std::optional<Coverage>& coverage = coverages.at(file.textureSetId);
        if (!coverage) {
            const std::string why =
                inputs.geometry ? "the texturing mesh gives no coverage of the material \"" + set.material_id + "\""
                                : gap.reason;
            entry.status = PreflightStatus::needs_evaluation;
            entry.reason = "the UV coverage of the texture set \"" + file.textureSet + "\" is not available (" + why +
                           "): the island normal and padding checks (decisions 245, 259) did not run";
            continue;
        }
        const Coverage* checked = &*coverage;
        std::optional<Coverage> target;
        if (ResizeOf(static_cast<uint32_t>(set.resolution.width), static_cast<uint32_t>(set.resolution.height),
                     file) != Resize::none) {
            // A resized file: its coverage at its own size (resize.h, decision 349).
            target = CoverageAt(set, inputs, file.width, file.height);
            if (!target) {
                entry.status = PreflightStatus::needs_evaluation;
                entry.reason = "the UV coverage of the texture set \"" + file.textureSet + "\" at " +
                               std::to_string(file.width) + "x" + std::to_string(file.height) +
                               " is not available: the island normal and padding checks did not run";
                continue;
            }
            if (blocked(ResizeCoverageRefusal(file, *coverage, *target))) continue;
            checked = &*target;
        }
        if (blocked(IslandNormalFileRefusal(file, *checked))) continue;
        blocked(PaddingRefusal(file, *checked));
    }
    for (const FilePreflight& file : preflight.files) {
        if (file.status == PreflightStatus::blocked) {
            preflight.status = PreflightStatus::blocked;
            break;
        }
        if (file.status == PreflightStatus::needs_evaluation) preflight.status = PreflightStatus::needs_evaluation;
    }
    return preflight;
}

core::json::Object PreflightJson(const ExportPreflight& preflight) {
    core::json::Array files;
    for (const FilePreflight& file : preflight.files) {
        core::json::Object entry{{"root_path", file.rootPath},
                                 {"map", file.fileName},
                                 {"relative_path", file.relativePath},
                                 {"status", std::string(PreflightStatusName(file.status))}};
        if (file.status == PreflightStatus::blocked) {
            entry["type"] = "NotYetSupported";
            entry["references"] = References(file.reason);
        }
        if (!file.reason.empty()) entry["reason"] = file.reason;
        files.push_back(std::move(entry));
    }
    return {{"status", std::string(PreflightStatusName(preflight.status))},
            {"note", "static checks of the plan only: the export is all or nothing, so one blocked file refuses every "
                     "file and nothing is written; no_known_blocker is no guarantee, the evaluation may still refuse "
                     "(decision 091)"},
            {"files", std::move(files)}};
}

}  // namespace uzp::exporter
