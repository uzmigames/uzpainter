#include "export/config.h"

#include <algorithm>
#include <cctype>
#include <set>
#include <utility>

#include "evaluator/diagnostics.h"
#include "export/preset_aliases.h"
#include "export/virtual_maps.h"
#include "uzp_core/types/errors.h"

namespace uzp::exporter {

namespace json = core::json;

namespace {

constexpr std::array<std::string_view, 5> kSourceTypes{"documentMap", "meshMap", "virtualMap", "defaultMap",
                                                       "diagnosticMap"};
constexpr std::array<std::string_view, 5> kLetters{"L", "R", "G", "B", "A"};
constexpr std::array<std::string_view, 13> kFormats{"png", "exr",  "tga",  "bmp", "jpeg", "dds",  "tiff",
                                                    "psd", "webp", "jp2", "pgm", "jng",  "sbsar"};
constexpr std::array<std::string_view, 4> kDepths{"8", "16", "16f", "32f"};
constexpr std::array<std::string_view, 5> kPaddings{"passthrough", "color", "transparent", "diffusion", "infinite"};

/// The documented documentMap names (export.html), in documentation order.
constexpr std::array<std::string_view, 28> kDocumentedDocumentMaps{
    "basecolor",  "height",        "specular",     "opacity",      "emissive",   "displacement", "glossiness",
    "roughness",  "anisotropylevel", "anisotropyangle", "transmissive", "scattering", "reflection",   "ior",
    "metallic",   "normal",        "ambientOcclusion", "diffuse",  "specularlevel", "blendingmask", "user0",
    "user1",      "user2",         "user3",        "user4",        "user5",      "user6",        "user7",
};
/// The documented meshMap names and their mesh maps.
constexpr std::array<std::pair<std::string_view, core::MeshMapUsage>, 7> kMeshMaps{{
    {"ambient_occlusion", core::MeshMapUsage::AO},
    {"id", core::MeshMapUsage::ID},
    {"curvature", core::MeshMapUsage::Curvature},
    {"normal_base", core::MeshMapUsage::Normal},
    {"world_space_normals", core::MeshMapUsage::WorldSpaceNormal},
    {"position", core::MeshMapUsage::Position},
    {"thickness", core::MeshMapUsage::Thickness},
}};
constexpr std::array<std::string_view, 6> kDiagnosticKinds{"isolated",     "contribution",  "materialMask",
                                                           "materialView", "materialLeaks", "regionStats"};

std::string Lower(std::string_view text) {
    std::string out(text);
    for (char& c : out) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return out;
}

template <size_t N>
std::vector<std::string> Strings(const std::array<std::string_view, N>& names) {
    return {names.begin(), names.end()};
}

template <size_t N>
std::optional<size_t> IndexOf(const std::array<std::string_view, N>& names, std::string_view name) {
    for (size_t i = 0; i < N; ++i) {
        if (names[i] == name) return i;
    }
    return std::nullopt;
}

[[noreturn]] void Invalid(const std::string& path, const std::string& problem) {
    throw core::ValueError("export: " + path + ": " + problem);
}

[[noreturn]] void Unknown(const std::string& path, std::string_view what, std::string_view name,
                          std::vector<std::string> valid) {
    Invalid(path, "unknown " + std::string(what) + " \"" + std::string(name) +
                      "\"; valid: " + JoinNames(Nearest(name, std::move(valid))));
}

std::string_view TypeName(const json::Value& value) {
    if (value.IsNull()) return "null";
    if (value.IsBool()) return "a boolean";
    if (value.IsNumber()) return "a number";
    if (value.IsString()) return "a string";
    if (value.IsArray()) return "an array";
    return "an object";
}

const json::Object& AsObject(const json::Value& value, const std::string& path) {
    if (!value.IsObject()) Invalid(path, "expected an object, got " + std::string(TypeName(value)));
    return std::get<json::Object>(value.data);
}

const json::Array& AsArray(const json::Value& value, const std::string& path) {
    if (!value.IsArray()) Invalid(path, "expected an array, got " + std::string(TypeName(value)));
    return std::get<json::Array>(value.data);
}

const std::string& AsString(const json::Value& value, const std::string& path) {
    if (!value.IsString()) Invalid(path, "expected a string, got " + std::string(TypeName(value)));
    return std::get<std::string>(value.data);
}

bool AsBool(const json::Value& value, const std::string& path) {
    if (!value.IsBool()) Invalid(path, "expected a boolean, got " + std::string(TypeName(value)));
    return std::get<bool>(value.data);
}

int AsInt(const json::Value& value, const std::string& path) {
    if (value.IsInt()) {
        const std::int64_t v = std::get<std::int64_t>(value.data);
        if (v >= -(1 << 30) && v <= (1 << 30)) return static_cast<int>(v);
    }
    Invalid(path, "expected an integer, got " + std::string(TypeName(value)));
}

/// Refuses every key of `object` outside the documented `allowed` ones where what Painter does with
/// an undocumented key is not recorded (decision 085). Painter ignores undocumented keys at the
/// configuration's root and in a preset map (probe P10, decision 091); those two objects are not
/// checked.
void CheckKeys(const json::Object& object, const std::string& path, std::vector<std::string> allowed) {
    for (const auto& [key, _] : object) {
        if (std::find(allowed.begin(), allowed.end(), key) == allowed.end()) {
            throw core::NotYetSupported("export: " + path + ": the key \"" + key +
                                        "\" is not documented and its effect in Painter is not recorded; "
                                        "documented keys: " + JoinNames(Nearest(key, std::move(allowed))) +
                                        " (export-semantics recording R-091, decision 091)");
        }
    }
}

const json::Value* Member(const json::Object& object, std::string_view key) {
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &it->second;
}

const json::Value& Required(const json::Object& object, std::string_view key, const std::string& path) {
    const json::Value* value = Member(object, key);
    if (value == nullptr) Invalid(path, "missing required key \"" + std::string(key) + "\"");
    return *value;
}

std::string Index(const std::string& path, size_t i) { return path + "[" + std::to_string(i) + "]"; }

std::string FormatOwner(FileFormat format) {
    switch (format) {
        case FileFormat::png:
        case FileFormat::exr: return {};
        case FileFormat::tga:
            return "phase3.2_unreal-ue56-packed-preset item 2.5 (native quantized TGA8 writer exists; "
                   "Painter's TGA processing and files still require recording R-322, decision 322)";
        case FileFormat::bmp:
        case FileFormat::jpeg: return "phase3.2_unreal-ue56-packed-preset (BMP and JPEG writers)";
        case FileFormat::dds:
            return "phase3.2_unreal-ue56-packed-preset (Painter's DDS files are not recorded; UzPainter's DDS "
                   "companions of PNG 16 maps: the shipped preset unreal-engine-packed-dds, decision 322)";
        case FileFormat::tiff:
        case FileFormat::psd:
        case FileFormat::webp:
        case FileFormat::jp2:
        case FileFormat::pgm:
        case FileFormat::jng:
        case FileFormat::sbsar:
            return "not in v1 (08-export.md §3: a release gap of the capability manifest)";
    }
    return {};
}

FileFormat ParseFormat(const json::Value& value, const std::string& path) {
    const std::string name = Lower(AsString(value, path));
    std::optional<size_t> index = IndexOf(kFormats, name);
    if (!index) {
        if (name == "jpg") index = static_cast<size_t>(FileFormat::jpeg);
        else if (name == "tif") index = static_cast<size_t>(FileFormat::tiff);
        else if (name == "j2k") index = static_cast<size_t>(FileFormat::jp2);
        else Unknown(path, "file format", AsString(value, path), Strings(kFormats));
    }
    const FileFormat format = static_cast<FileFormat>(*index);
    if (const std::string owner = FormatOwner(format); !owner.empty()) {
        throw core::NotYetSupported("export: " + path + ": the file format \"" + AsString(value, path) +
                                    "\" is not written by this build: " + owner);
    }
    return format;
}

BitDepth ParseDepth(const json::Value& value, const std::string& path) {
    // Painter raises "Expected a string value" for an integer (probe P11, decision 091).
    if (value.IsInt()) Invalid(path, "Expected a string value; valid: \"8\", \"16\", \"16f\", \"32f\"");
    const std::string& name = AsString(value, path);
    const std::optional<size_t> index = IndexOf(kDepths, name);
    if (!index) Unknown(path, "bit depth", name, Strings(kDepths));
    return static_cast<BitDepth>(*index);
}

Padding ParsePadding(const json::Value& value, const std::string& path) {
    const std::string& name = AsString(value, path);
    const std::optional<size_t> index = IndexOf(kPaddings, name);
    if (!index) Unknown(path, "padding algorithm", name, Strings(kPaddings));
    return static_cast<Padding>(*index);
}

/// The texture-set resolutions of the document model (128 to 8192): the sizes an export writes.
constexpr int kMinSizeLog2 = 7;
constexpr int kMaxSizeLog2 = 13;

int ParseLog2(const json::Value& value, const std::string& path) {
    const int v = AsInt(value, path);
    if (v < kMinSizeLog2 || v > kMaxSizeLog2) {
        throw core::NotYetSupported("export: " + path + ": sizeLog2 " + std::to_string(v) +
                                    " is outside the recorded texture sizes 2^7..2^13 (export-processing recording R-090 (decision 090))");
    }
    return v;
}

SizeLog2 ParseSize(const json::Value& value, const std::string& path) {
    if (value.IsArray()) {
        const json::Array& pair = AsArray(value, path);
        if (pair.size() != 2) Invalid(path, "expected an integer or an array of two integers");
        return std::array<int, 2>{ParseLog2(pair[0], Index(path, 0)), ParseLog2(pair[1], Index(path, 1))};
    }
    return ParseLog2(value, path);
}

Parameters ParseParameters(const json::Value& value, const std::string& path) {
    const json::Object& object = AsObject(value, path);
    CheckKeys(object, path,
              {"fileFormat", "bitDepth", "dithering", "sizeLog2", "paddingAlgorithm", "dilationDistance"});
    Parameters p;
    if (const json::Value* v = Member(object, "fileFormat")) p.fileFormat = ParseFormat(*v, path + ".fileFormat");
    if (const json::Value* v = Member(object, "bitDepth")) p.bitDepth = ParseDepth(*v, path + ".bitDepth");
    if (const json::Value* v = Member(object, "dithering")) p.dithering = AsBool(*v, path + ".dithering");
    if (const json::Value* v = Member(object, "sizeLog2")) p.sizeLog2 = ParseSize(*v, path + ".sizeLog2");
    if (const json::Value* v = Member(object, "paddingAlgorithm")) {
        p.paddingAlgorithm = ParsePadding(*v, path + ".paddingAlgorithm");
    }
    if (const json::Value* v = Member(object, "dilationDistance")) {
        const int distance = AsInt(*v, path + ".dilationDistance");
        if (distance < 0) Invalid(path + ".dilationDistance", "must not be negative");
        p.dilationDistance = distance;
    }
    return p;
}

ChannelLetter ParseLetter(const json::Value& value, const std::string& path) {
    const std::string& name = AsString(value, path);
    const std::optional<size_t> index = IndexOf(kLetters, name);
    if (!index) Unknown(path, "channel", name, Strings(kLetters));
    return static_cast<ChannelLetter>(*index);
}

/// The documentMap spellings of `member` that are documented or recorded: the lower-cased member
/// name (`ambientOcclusion` for AO), and `baseColor`, the documentation's own example.
std::vector<std::string> RecordedSpellings(core::ChannelType member) {
    if (member == core::ChannelType::AO) return {"ambientOcclusion"};
    if (member == core::ChannelType::BaseColor) return {"basecolor", "baseColor"};
    return {Lower(core::ToString(member))};
}

/// Checks `name` against the vocabulary of `type` (the project-independent part of resolution).
void CheckSourceName(SourceType type, const std::string& name, const std::string& path) {
    switch (type) {
        case SourceType::documentMap: {
            const std::optional<core::ChannelType> member = DocumentMapMember(name);
            if (!member) Unknown(path, "documentMap", name, SourceNames(type));
            const std::vector<std::string> spellings = RecordedSpellings(*member);
            if (std::find(spellings.begin(), spellings.end(), name) == spellings.end()) {
                throw core::NotYetSupported("export: " + path + ": the documentMap spelling \"" + name +
                                            "\" is not recorded (decision 085); recorded: " + JoinNames(spellings));
            }
            return;
        }
        case SourceType::meshMap:
            if (!MeshMapOf(name)) Unknown(path, "meshMap", name, SourceNames(type));
            return;
        case SourceType::virtualMap:
            if (!ParseVirtualMap(name)) Unknown(path, "virtualMap", name, SourceNames(type));
            return;
        case SourceType::defaultMap:
            if (!DefaultMapValue(name)) Unknown(path, "defaultMap", name, SourceNames(type));
            return;
        case SourceType::diagnosticMap:
            if (!evaluator::ParseSourceName(name)) {
                Invalid(path, "malformed diagnosticMap \"" + name +
                                  "\"; valid: isolated/<map>/<node>, contribution/<map>/<node>, "
                                  "materialMask/<material>, materialView/<view>/<material>, "
                                  "materialLeaks/<view>/<material>, regionStats/<map>/<material> (decision 076)");
            }
            return;
    }
}

ChannelSpec ParseChannel(const json::Value& value, const std::string& path) {
    const json::Object& object = AsObject(value, path);
    CheckKeys(object, path, {"destChannel", "srcChannel", "srcMapType", "srcMapName", "srcPath"});
    ChannelSpec channel;
    channel.dest = ParseLetter(Required(object, "destChannel", path), path + ".destChannel");
    channel.src = ParseLetter(Required(object, "srcChannel", path), path + ".srcChannel");
    const std::string& type = AsString(Required(object, "srcMapType", path), path + ".srcMapType");
    const std::optional<size_t> typeIndex = IndexOf(kSourceTypes, type);
    if (!typeIndex) Unknown(path + ".srcMapType", "srcMapType", type, Strings(kSourceTypes));
    channel.type = static_cast<SourceType>(*typeIndex);
    channel.name = AsString(Required(object, "srcMapName", path), path + ".srcMapName");
    CheckSourceName(channel.type, channel.name, path + ".srcMapName");
    if (const json::Value* srcPath = Member(object, "srcPath")) {
        // Painter's own list_output_maps() output carries `srcPath: ''`; its meaning is not
        // documented, so only the empty value is accepted.
        if (!AsString(*srcPath, path + ".srcPath").empty()) {
            Invalid(path + ".srcPath", "only the empty srcPath is supported (its meaning is not documented)");
        }
    }
    return channel;
}

/// The documented destination sets: L, L+A, R+G+B, R+G+B+A, each letter once.
void CheckDestinations(const std::vector<ChannelSpec>& channels, const std::string& path) {
    std::set<ChannelLetter> letters;
    for (const ChannelSpec& c : channels) {
        if (!letters.insert(c.dest).second) {
            Invalid(path, "destChannel " + std::string(ChannelLetterName(c.dest)) + " is written twice");
        }
    }
    using enum ChannelLetter;
    const std::set<ChannelLetter> l{L}, la{L, A}, rgb{R, G, B}, rgba{R, G, B, A};
    if (letters != l && letters != la && letters != rgb && letters != rgba) {
        Invalid(path, "destChannels must be L, L+A, R+G+B or R+G+B+A (in addition to alpha, either R+G+B or L only)");
    }
}

MapSpec ParseMap(const json::Value& value, const std::string& path) {
    const json::Object& object = AsObject(value, path);
    MapSpec map;
    map.fileName = AsString(Required(object, "fileName", path), path + ".fileName");
    if (map.fileName.empty()) Invalid(path + ".fileName", "must not be empty");
    const json::Array& channels = AsArray(Required(object, "channels", path), path + ".channels");
    if (channels.empty()) Invalid(path + ".channels", "must not be empty");
    for (size_t i = 0; i < channels.size(); ++i) {
        map.channels.push_back(ParseChannel(channels[i], Index(path + ".channels", i)));
    }
    CheckDestinations(map.channels, path + ".channels");
    if (const json::Value* p = Member(object, "parameters")) map.parameters = ParseParameters(*p, path + ".parameters");
    return map;
}

std::vector<std::string> StringList(const json::Value& value, const std::string& path) {
    std::vector<std::string> out;
    const json::Array& items = AsArray(value, path);
    for (size_t i = 0; i < items.size(); ++i) out.push_back(AsString(items[i], Index(path, i)));
    return out;
}

Filter ParseFilter(const json::Value& value, const std::string& path, bool dataPaths) {
    const json::Object& object = AsObject(value, path);
    if (dataPaths) CheckKeys(object, path, {"dataPaths", "outputMaps", "uvTiles"});
    else CheckKeys(object, path, {"outputMaps", "uvTiles"});
    Filter filter;
    if (const json::Value* v = Member(object, "dataPaths")) filter.dataPaths = StringList(*v, path + ".dataPaths");
    if (const json::Value* v = Member(object, "outputMaps")) filter.outputMaps = StringList(*v, path + ".outputMaps");
    if (const json::Value* v = Member(object, "uvTiles")) {
        const json::Array& tiles = AsArray(*v, path + ".uvTiles");
        std::vector<UvTile> out;
        for (size_t i = 0; i < tiles.size(); ++i) {
            const std::string at = Index(path + ".uvTiles", i);
            const json::Array& pair = AsArray(tiles[i], at);
            if (pair.size() != 2) Invalid(at, "a UV tile is [u, v]");
            const int u = AsInt(pair[0], Index(at, 0));
            const int w = AsInt(pair[1], Index(at, 1));
            if (u < 0 || u > 9 || w < 0) Invalid(at, "a UV tile has 0 <= u <= 9 and v >= 0");
            out.push_back({u, w});
        }
        filter.uvTiles = std::move(out);
    }
    return filter;
}


size_t EditDistance(std::string_view a, std::string_view b) {
    std::vector<size_t> row(b.size() + 1);
    for (size_t j = 0; j <= b.size(); ++j) row[j] = j;
    for (size_t i = 1; i <= a.size(); ++i) {
        size_t diagonal = row[0];
        row[0] = i;
        for (size_t j = 1; j <= b.size(); ++j) {
            const size_t above = row[j];
            row[j] = std::min({row[j] + 1, row[j - 1] + 1, diagonal + (a[i - 1] == b[j - 1] ? 0 : 1)});
            diagonal = above;
        }
    }
    return row[b.size()];
}

std::set<std::string> Words(std::string_view text) {
    std::set<std::string> words;
    std::string word;
    for (char c : Lower(text)) {
        if (std::isalnum(static_cast<unsigned char>(c))) word.push_back(c);
        else if (!word.empty()) words.insert(std::exchange(word, {}));
    }
    if (!word.empty()) words.insert(word);
    return words;
}

}  // namespace

std::string_view SourceTypeName(SourceType type) { return kSourceTypes[static_cast<size_t>(type)]; }
std::string_view ChannelLetterName(ChannelLetter letter) { return kLetters[static_cast<size_t>(letter)]; }
std::string_view FileFormatName(FileFormat format) { return kFormats[static_cast<size_t>(format)]; }
std::string_view BitDepthName(BitDepth depth) { return kDepths[static_cast<size_t>(depth)]; }
std::string_view PaddingName(Padding padding) { return kPaddings[static_cast<size_t>(padding)]; }

std::string_view UzTextureStorageName(UzTextureStorage storage) {
    static constexpr std::array<std::string_view, 4> names{"BC4", "BC5", "BC7", "RGBA8"};
    return names[static_cast<size_t>(storage)];
}

std::string_view DerivativeMipsName(DerivativeMips mips) {
    static constexpr std::array<std::string_view, 4> names{"linear", "colour", "normal", "masked_colour"};
    return names[static_cast<size_t>(mips)];
}

bool NeedsDilation(Padding padding) {
    return padding == Padding::transparent || padding == Padding::color || padding == Padding::diffusion;
}

std::string JoinNames(const std::vector<std::string>& items) {
    std::string out;
    for (const std::string& item : items) {
        if (!out.empty()) out += ", ";
        out += item;
    }
    return out;
}

std::vector<std::string> Nearest(std::string_view name, std::vector<std::string> candidates) {
    const std::set<std::string> words = Words(name);
    const std::string lowered = Lower(name);
    struct Ranked {
        size_t shared;
        size_t distance;
        size_t order;
        std::string name;
    };
    std::vector<Ranked> ranked;
    for (size_t i = 0; i < candidates.size(); ++i) {
        const std::set<std::string> theirs = Words(candidates[i]);
        size_t shared = 0;
        for (const std::string& w : theirs) shared += words.contains(w) ? 1 : 0;
        ranked.push_back({shared, EditDistance(lowered, Lower(candidates[i])), i, std::move(candidates[i])});
    }
    std::stable_sort(ranked.begin(), ranked.end(), [](const Ranked& a, const Ranked& b) {
        if (a.shared != b.shared) return a.shared > b.shared;
        if (a.distance != b.distance) return a.distance < b.distance;
        return a.order < b.order;
    });
    std::vector<std::string> out;
    for (Ranked& r : ranked) out.push_back(std::move(r.name));
    return out;
}

std::vector<std::string> SourceNames(SourceType type) {
    switch (type) {
        case SourceType::documentMap: {
            std::vector<std::string> names = Strings(kDocumentedDocumentMaps);
            for (std::string_view member : core::EnumTable<core::ChannelType>::names) {
                std::string lowered = Lower(member);
                if (member == "AO") continue;
                if (std::find(names.begin(), names.end(), lowered) == names.end()) names.push_back(std::move(lowered));
            }
            return names;
        }
        case SourceType::meshMap: {
            std::vector<std::string> names;
            for (const auto& [name, _] : kMeshMaps) names.emplace_back(name);
            return names;
        }
        case SourceType::virtualMap: return VirtualMapNames();
        case SourceType::defaultMap: return {"black", "white"};
        case SourceType::diagnosticMap: return Strings(kDiagnosticKinds);
    }
    return {};
}

std::optional<core::ChannelType> DocumentMapMember(std::string_view name) {
    const std::string lowered = Lower(name);
    if (lowered == "ambientocclusion") return core::ChannelType::AO;
    if (lowered == "ao") return std::nullopt;  // the documented name of AO is ambientOcclusion
    for (size_t i = 0; i < core::EnumTable<core::ChannelType>::names.size(); ++i) {
        if (Lower(core::EnumTable<core::ChannelType>::names[i]) == lowered) return static_cast<core::ChannelType>(i);
    }
    return std::nullopt;
}

std::string DocumentMapName(core::ChannelType member) {
    // `baseColor`, the documentation's own example, for BaseColor; the only spelling otherwise.
    return RecordedSpellings(member).back();
}

std::optional<core::ChannelType> RecordedAliasTarget(core::ChannelType member) {
    using enum core::ChannelType;
    switch (member) {
        case Roughness: return SpecularRoughness;
        case Metallic: return BaseMetalness;
        case Emissive: return EmissionColor;
        case Anisotropylevel: return SpecularRoughnessAnisotropy;
        case Scattering: return SubsurfaceRadiusScale;
        case CoatOpacity: return CoatWeight;
        case SheenColor: return FuzzColor;
        case SheenRoughness: return FuzzRoughness;
        case SheenOpacity: return FuzzWeight;
        case Translucency: return SubsurfaceWeight;
        case ScatteringColor: return SubsurfaceColor;
        default: return std::nullopt;
    }
}

bool RaisesWhenAbsent(core::ChannelType member) {
    using enum core::ChannelType;
    switch (member) {
        case CoatOpacity:
        case SheenColor:
        case SheenRoughness:
        case SheenOpacity:
        case Translucency:
        case ScatteringColor:
        case AbsorptionColor:
        case SpecularEdgeColor: return true;
        default: return false;
    }
}

std::optional<core::MeshMapUsage> MeshMapOf(std::string_view name) {
    for (const auto& [documented, usage] : kMeshMaps) {
        if (documented == name) return usage;
    }
    return std::nullopt;
}

std::optional<float> DefaultMapValue(std::string_view name) {
    if (name == "black") return 0.0f;
    if (name == "white") return 1.0f;
    return std::nullopt;
}

ExportConfig ParseConfig(std::string_view jsonText) {
    json::Value value;
    try {
        value = json::Parse(jsonText);
    } catch (const json::ParseError& e) {
        throw core::ValueError("export: the configuration is not JSON (byte " + std::to_string(e.offset()) +
                               "): " + e.what());
    }
    return ParseConfig(value);
}

PresetSpec ParsePreset(const json::Value& value, const std::string& path) {
    const json::Object& p = AsObject(value, path);
    CheckKeys(p, path, {"name", "maps"});
    PresetSpec preset;
    preset.name = AsString(Required(p, "name", path), path + ".name");
    const json::Array& maps = AsArray(Required(p, "maps", path), path + ".maps");
    for (size_t m = 0; m < maps.size(); ++m) preset.maps.push_back(ParseMap(maps[m], Index(path + ".maps", m)));
    return preset;
}

ExportConfig ParseConfig(const json::Value& value) { return ParseConfig(value, DefaultPresetDirectory()); }

ExportConfig ParseConfig(const json::Value& value, const std::filesystem::path& presetDirectory) {
    const std::string root = "config";
    const json::Object& object = AsObject(value, root);
    ExportConfig config;
    config.exportPath = AsString(Required(object, "exportPath", root), "exportPath");
    if (config.exportPath.empty()) Invalid("exportPath", "must not be empty");
    if (const json::Value* v = Member(object, "exportShaderParams"); v && AsBool(*v, "exportShaderParams")) {
        throw core::NotYetSupported(
            "export: exportShaderParams: writing shader instances to a JSON file is not implemented "
            "(phase2.3_realtime-preview: the shader instances)");
    }
    if (const json::Value* v = Member(object, "defaultExportPreset")) {
        config.defaultExportPreset = AsString(*v, "defaultExportPreset");
    }
    if (const json::Value* v = Member(object, "exportPresets")) {
        const json::Array& presets = AsArray(*v, "exportPresets");
        std::set<std::string> names;
        for (size_t i = 0; i < presets.size(); ++i) {
            const std::string path = Index("exportPresets", i);
            PresetSpec preset = ParsePreset(presets[i], path);
            if (!names.insert(preset.name).second) {
                Invalid(path + ".name", "the preset \"" + preset.name + "\" is defined twice");
            }
            config.exportPresets.push_back(std::move(preset));
        }
    }
    const json::Array& list = AsArray(Required(object, "exportList", root), "exportList");
    for (size_t i = 0; i < list.size(); ++i) {
        const std::string path = Index("exportList", i);
        const json::Object& e = AsObject(list[i], path);
        CheckKeys(e, path, {"rootPath", "filter", "exportPreset"});
        ExportListEntry entry;
        entry.rootPath = AsString(Required(e, "rootPath", path), path + ".rootPath");
        if (const json::Value* f = Member(e, "filter")) entry.filter = ParseFilter(*f, path + ".filter", false);
        if (const json::Value* p = Member(e, "exportPreset")) {
            entry.exportPreset = AsString(*p, path + ".exportPreset");
        }
        config.exportList.push_back(std::move(entry));
    }
    if (const json::Value* v = Member(object, "exportParameters")) {
        const json::Array& rules = AsArray(*v, "exportParameters");
        for (size_t i = 0; i < rules.size(); ++i) {
            const std::string path = Index("exportParameters", i);
            const json::Object& r = AsObject(rules[i], path);
            CheckKeys(r, path, {"filter", "parameters"});
            ParameterRule rule;
            if (const json::Value* f = Member(r, "filter")) rule.filter = ParseFilter(*f, path + ".filter", true);
            if (const json::Value* p = Member(r, "parameters")) rule.parameters = ParseParameters(*p, path + ".parameters");
            config.exportParameters.push_back(std::move(rule));
        }
    }
    // Every preset a list entry or the default names: an inline preset, else a shipped one
    // (decision 095), which joins exportPresets under its id.
    std::vector<std::string> inlineNames;
    for (const PresetSpec& p : config.exportPresets) inlineNames.push_back(p.name);
    const auto isInline = [&](const std::string& name) {
        return std::find(inlineNames.begin(), inlineNames.end(), name) != inlineNames.end();
    };
    std::set<std::string> shippedJoined;
    const auto resolvePreset = [&](std::string& name, const std::string& path) {
        if (isInline(name)) return;
        const std::optional<std::string> id = ShippedPresetId(name);
        if (!id) {
            if (name.starts_with("resource://") || name.starts_with("export-preset-generator://")) {
                throw core::NotYetSupported("export: " + path + ": the preset \"" + name +
                                            "\" is a shelf or predefined preset UzPainter does not ship; shipped: " +
                                            JoinNames({ShippedPresetIds().begin(), ShippedPresetIds().end()}) +
                                            " (decision 095)");
            }
            std::vector<std::string> valid = inlineNames;
            for (std::string_view shipped : ShippedPresetIds()) valid.emplace_back(shipped);
            for (const PresetAlias& alias : PresetAliases()) valid.emplace_back(alias.painterName);
            Unknown(path, "export preset", name, std::move(valid));
        }
        if (isInline(*id)) {
            Invalid(path, "the preset \"" + name + "\" is the shipped preset \"" + *id +
                              "\", which an inline preset of that name would shadow");
        }
        if (shippedJoined.insert(*id).second) {
            ShippedPreset shipped = LoadShippedPreset(presetDirectory, *id);
            if (shipped.layout == PresetLayout::unconfirmed) {
                throw core::NotYetSupported("export: " + path + ": the preset \"" + name + "\" (shipped preset \"" +
                                            *id +
                                            "\") is written from public sources and no recording of Painter's "
                                            "output confirms its layout yet (" +
                                            JoinNames(shipped.pendingRecordings) + "; decision 095)");
            }
            config.exportPresets.push_back(std::move(shipped.spec));
        }
        name = *id;
    };
    if (config.defaultExportPreset) resolvePreset(*config.defaultExportPreset, "defaultExportPreset");
    for (size_t i = 0; i < config.exportList.size(); ++i) {
        ExportListEntry& entry = config.exportList[i];
        if (entry.exportPreset) {
            resolvePreset(*entry.exportPreset, Index("exportList", i) + ".exportPreset");
        } else if (!config.defaultExportPreset) {
            Invalid(Index("exportList", i), "no exportPreset and no defaultExportPreset");
        }
    }
    return config;
}

}  // namespace uzp::exporter
