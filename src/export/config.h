#pragma once

// Painter's export configuration dictionary, parsed verbatim (docs/architecture/08-export.md §1;
// task phase1.15_export-plan-compiler, decision 085). The dictionary is the `json_config` of the
// documented `export.export_project_textures` and `export.list_project_textures` (Painter's
// public Python API documentation, export.html, "Full json_config dict possibilities"):
//
//   exportPath, exportShaderParams, defaultExportPreset (an inline preset name or a
//   `resource://` URL), exportPresets[].{name, maps[].{fileName, channels[].{destChannel,
//   srcChannel, srcMapType, srcMapName, srcPath}, parameters}}, exportList[].{rootPath,
//   filter.{outputMaps, uvTiles}, exportPreset}, exportParameters[].{filter.{dataPaths,
//   outputMaps, uvTiles}, parameters.{fileFormat, bitDepth, dithering, sizeLog2,
//   paddingAlgorithm, dilationDistance}}.
//
// Parsing checks the shape and every identifier that does not depend on the project: keys,
// channel letters, `srcMapType`, `srcMapName` (the documented names of each type, decision 076's
// `diagnosticMap` grammar), file formats, bit depths and padding algorithms. An ill-formed
// configuration throws `core::ValueError` whose message starts with the JSON path and lists the
// valid alternatives, nearest first (`Mixed_AO` names `AO_Mixed` first). A well-formed request
// for something this build does not write (a later-package or excluded file format, shader
// parameters, a shelf preset) throws `core::NotYetSupported` naming its owner task. Both happen
// before any evaluation or write.

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"

namespace uzp::exporter {

/// The documented `srcMapType` values plus UzPainter's `diagnosticMap` (decision 076).
enum class SourceType : uint8_t { documentMap, meshMap, virtualMap, defaultMap, diagnosticMap };
[[nodiscard]] std::string_view SourceTypeName(SourceType type);

/// A `destChannel` / `srcChannel` letter.
enum class ChannelLetter : uint8_t { L, R, G, B, A };
[[nodiscard]] std::string_view ChannelLetterName(ChannelLetter letter);

/// The `fileFormat` values this build knows. `png` and `exr` are written in Phase 1; the others
/// are refused at parse time (NotYetSupported, `FormatOwner`).
enum class FileFormat : uint8_t { png, exr, tga, bmp, jpeg, dds, tiff, psd, webp, jp2, pgm, jng, sbsar };
/// The file extension (and canonical `fileFormat` spelling) of a format.
[[nodiscard]] std::string_view FileFormatName(FileFormat format);

/// `bitDepth`: "8", "16", "16f", "32f".
enum class BitDepth : uint8_t { u8, u16, f16, f32 };
[[nodiscard]] std::string_view BitDepthName(BitDepth depth);

/// `paddingAlgorithm`.
enum class Padding : uint8_t { passthrough, color, transparent, diffusion, infinite };
[[nodiscard]] std::string_view PaddingName(Padding padding);
/// The padding algorithms that need `dilationDistance` (transparent, color, diffusion).
[[nodiscard]] bool NeedsDilation(Padding padding);

/// `sizeLog2`: one integer (the larger side, aspect kept) or [width, height] (aspect ignored).
using SizeLog2 = std::variant<int, std::array<int, 2>>;

/// One `parameters` block: every field optional (a preset map's, or a rule's).
struct Parameters {
    std::optional<FileFormat> fileFormat;
    std::optional<BitDepth> bitDepth;
    std::optional<bool> dithering;
    std::optional<SizeLog2> sizeLog2;
    std::optional<Padding> paddingAlgorithm;
    std::optional<int> dilationDistance;

    friend bool operator==(const Parameters&, const Parameters&) = default;
};

struct ChannelSpec {
    ChannelLetter dest = ChannelLetter::L;
    ChannelLetter src = ChannelLetter::L;
    SourceType type = SourceType::documentMap;
    /// `srcMapName` as given.
    std::string name;

    friend bool operator==(const ChannelSpec&, const ChannelSpec&) = default;
};

struct MapSpec {
    /// `fileName`, wildcards and `( … )` groups unexpanded.
    std::string fileName;
    std::vector<ChannelSpec> channels;
    Parameters parameters;

    friend bool operator==(const MapSpec&, const MapSpec&) = default;
};

struct PresetSpec {
    std::string name;
    std::vector<MapSpec> maps;

    friend bool operator==(const PresetSpec&, const PresetSpec&) = default;
};

/// A UV tile coordinate `[u, v]` (UDIM 1001 + u + 10 v).
using UvTile = std::array<int, 2>;

/// `exportList[].filter` (outputMaps, uvTiles) and `exportParameters[].filter` (dataPaths too).
/// An absent member selects everything; a present empty list selects nothing.
struct Filter {
    std::optional<std::vector<std::string>> dataPaths;
    std::optional<std::vector<std::string>> outputMaps;
    std::optional<std::vector<UvTile>> uvTiles;

    friend bool operator==(const Filter&, const Filter&) = default;
};

struct ExportListEntry {
    /// "<texture set>" or "<texture set>/<stack>".
    std::string rootPath;
    std::optional<Filter> filter;
    /// An inline preset name; absent: `defaultExportPreset`.
    std::optional<std::string> exportPreset;

    friend bool operator==(const ExportListEntry&, const ExportListEntry&) = default;
};

struct ParameterRule {
    std::optional<Filter> filter;
    Parameters parameters;

    friend bool operator==(const ParameterRule&, const ParameterRule&) = default;
};

struct ExportConfig {
    std::string exportPath;
    std::optional<std::string> defaultExportPreset;
    std::vector<PresetSpec> exportPresets;
    std::vector<ExportListEntry> exportList;
    std::vector<ParameterRule> exportParameters;

    friend bool operator==(const ExportConfig&, const ExportConfig&) = default;
};

/// Parses the JSON text of a configuration (throws `core::ValueError` for a JSON syntax error
/// too, with its byte offset).
[[nodiscard]] ExportConfig ParseConfig(std::string_view jsonText);
/// Parses a configuration already read as JSON.
[[nodiscard]] ExportConfig ParseConfig(const core::json::Value& config);

/// The documented `srcMapName`s of a source type, in documentation order (documentMap: the
/// documented list, then the other `ChannelType` members lower-cased; diagnosticMap: the kinds
/// of decision 076's grammar).
[[nodiscard]] std::vector<std::string> SourceNames(SourceType type);

/// The `ChannelType` member a documentMap name names: the member whose lower-cased name equals
/// the name compared case-insensitively (the documentation spells both `basecolor` and
/// `baseColor`), `ambientOcclusion` for `AO`; nullopt for any other name.
[[nodiscard]] std::optional<core::ChannelType> DocumentMapMember(std::string_view name);

/// The OpenPBR member a legacy alias member reads when the stack lacks the alias itself, for the
/// pairings Painter 12.1.5 was observed to export: Roughness → SpecularRoughness, Metallic →
/// BaseMetalness, Emissive → EmissionColor, Anisotropylevel → SpecularRoughnessAnisotropy,
/// Scattering → SubsurfaceRadiusScale (decision 085, the Tier 0 goldens); CoatOpacity →
/// CoatWeight, SheenColor → FuzzColor, SheenRoughness → FuzzRoughness, SheenOpacity → FuzzWeight,
/// Translucency → SubsurfaceWeight, ScatteringColor → SubsurfaceColor (probe P13, decision 091:
/// byte-equal to the paired channel's own export). nullopt for any other member.
[[nodiscard]] std::optional<core::ChannelType> RecordedAliasTarget(core::ChannelType member);
/// The legacy names whose export raises ValueError when the stack has neither the name's channel
/// nor its pairing (probe P13, decision 091), unlike every other documentMap, whose map is then
/// absent: the six P13 pairings above, and AbsorptionColor and SpecularEdgeColor, which have no
/// pairing on any recorded template.
[[nodiscard]] bool RaisesWhenAbsent(core::ChannelType member);

/// The mesh map a meshMap name names (`ambient_occlusion` AO, `id` ID, `curvature` Curvature,
/// `normal_base` Normal, `world_space_normals` WorldSpaceNormal, `position` Position,
/// `thickness` Thickness); nullopt for any other name.
[[nodiscard]] std::optional<core::MeshMapUsage> MeshMapOf(std::string_view name);

/// The constant of a defaultMap name (`black` 0, `white` 1); nullopt for any other name.
[[nodiscard]] std::optional<float> DefaultMapValue(std::string_view name);

/// `candidates` ordered nearest to `name` first: shared `_`-separated words (case-insensitive),
/// then edit distance on lower-cased text, then the given order.
[[nodiscard]] std::vector<std::string> Nearest(std::string_view name, std::vector<std::string> candidates);

/// "a, b, c" of `items`.
[[nodiscard]] std::string JoinNames(const std::vector<std::string>& items);

}  // namespace uzp::exporter
