#include "export/preset_aliases.h"

#include <algorithm>
#include <array>
#include <fstream>
#include <iterator>

#include "render/kernel_cache.h"
#include "uzp_core/types/errors.h"

namespace uzp::exporter {

namespace json = core::json;

namespace {

constexpr std::string_view kProvenanceSchema = "uzpainter/export-preset-provenance/1";
constexpr std::string_view kStarterAssets = "resource://starter_assets/";
constexpr std::string_view kRecording = "recording R-095, decision 095";

/// The `?version=` of the Blender preset's URL in UzmiGames' Assets3D hat report
/// (`SM/10-Chapeu/report.json → painter_recipe.export.preset_details.preset.url`).
constexpr std::array<std::string_view, 1> kBlenderVersions{"13120355637414252359"};

constexpr std::array<std::string_view, 7> kShippedIds{"pbr-metallic-roughness",   "blender-principled-bsdf",
                                                       "assets3d-inline-five-map", "gltf-pbr-metal-roughness",
                                                       "uzengine",                 "unreal-engine-packed",
                                                       "unreal-engine-packed-dds"};

const std::array<PresetAlias, 4> kAliases{{
    {"PBR Metallic Roughness", "pbr-metallic-roughness", {}, kRecording},
    {"Blender (Principled BSDF)", "blender-principled-bsdf", kBlenderVersions, kRecording},
    // R-314 observes a predefined generator, not a starter-assets resource.
    {"glTF PBR Metal Roughness", "gltf-pbr-metal-roughness", {}, "recording R-314, decision 314",
     "export-preset-generator://gltf"},
    // phase3.2_unreal-ue56-packed-preset item 2.4 (CLR-06); its URL's versions: recording R-322.
    {"Unreal Engine (Packed)", "unreal-engine-packed", {}, "recording R-322, decision 322"},
}};

[[noreturn]] void Fail(std::string_view id, const std::string& problem) {
    throw core::ManifestError("export preset \"" + std::string(id) + "\": " + problem);
}

json::Value ReadJson(const std::filesystem::path& file, std::string_view id) {
    std::ifstream stream(file, std::ios::binary);
    if (!stream) Fail(id, file.string() + " cannot be read");
    const std::string text((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    try {
        return json::Parse(text);
    } catch (const json::ParseError& e) {
        Fail(id, file.string() + " is not JSON: " + e.what());
    }
}

const json::Value* Member(const json::Value& value, std::string_view key) {
    if (!value.IsObject()) return nullptr;
    const json::Object& object = std::get<json::Object>(value.data);
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &it->second;
}

const std::string* StringMember(const json::Value& value, std::string_view key) {
    const json::Value* member = Member(value, key);
    return member != nullptr && member->IsString() ? &std::get<std::string>(member->data) : nullptr;
}

/// The preset's map whose unexpanded fileName is `fileName`.
const MapSpec* MapNamed(const PresetSpec& spec, std::string_view fileName) {
    for (const MapSpec& map : spec.maps) {
        if (map.fileName == fileName) return &map;
    }
    return nullptr;
}

/// The `uzengine` block of a shipped preset (config.h `UzEngineTargets`), checked against its maps.
/// Throws `core::ManifestError` naming the preset.
UzEngineTargets ParseUzEngine(const json::Value& block, const PresetSpec& spec, std::string_view id,
                              const std::string& file) {
    const auto fail = [&](const std::string& problem) { Fail(id, file + ": uzengine: " + problem); };
    if (!block.IsObject()) fail("expected an object");
    const auto string = [&](const json::Value& object, std::string_view key, bool required) -> std::string {
        const json::Value* member = Member(object, key);
        if (member == nullptr && !required) return {};
        if (member == nullptr || !member->IsString()) fail("\"" + std::string(key) + "\" must be a string");
        return std::get<std::string>(member->data);
    };
    const auto allowed = [&](const json::Value& object, std::initializer_list<std::string_view> keys) {
        for (const auto& [key, _] : std::get<json::Object>(object.data)) {
            if (std::find(keys.begin(), keys.end(), key) == keys.end()) fail("unknown key \"" + key + "\"");
        }
    };
    allowed(block, {"textures", "material"});
    UzEngineTargets targets;
    const json::Value* textures = Member(block, "textures");
    if (textures == nullptr || !textures->IsArray()) fail("\"textures\" must be an array");
    for (const json::Value& item : std::get<json::Array>(textures->data)) {
        if (!item.IsObject()) fail("a texture must be an object");
        allowed(item, {"map", "canonical", "binding", "format", "srgb", "mips", "negativeZ"});
        UzEngineTexture t;
        t.map = string(item, "map", true);
        t.canonical = string(item, "canonical", true);
        const json::Value* binding = Member(item, "binding");
        if (binding == nullptr || !(binding->IsString() || binding->IsNull())) {
            fail(t.map + ": \"binding\" must be a string or null");
        }
        if (binding->IsString()) t.binding = std::get<std::string>(binding->data);
        const std::string format = string(item, "format", true);
        if (format == "BC4") t.format = UzTextureStorage::BC4;
        else if (format == "BC5") t.format = UzTextureStorage::BC5;
        else if (format == "BC7") t.format = UzTextureStorage::BC7;
        else fail(t.map + ": format \"" + format + "\" is not BC4, BC5 or BC7");
        const json::Value* srgb = Member(item, "srgb");
        if (srgb == nullptr || !srgb->IsBool()) fail(t.map + ": \"srgb\" must be a boolean");
        t.srgb = std::get<bool>(srgb->data);
        const std::string mips = string(item, "mips", true);
        if (mips == "linear") t.mips = DerivativeMips::linear;
        else if (mips == "colour") t.mips = DerivativeMips::colour;
        else if (mips == "normal") t.mips = DerivativeMips::normal;
        else if (mips == "masked_colour") t.mips = DerivativeMips::masked_colour;
        else fail(t.map + ": mips \"" + mips + "\" is not linear, colour, normal or masked_colour");
        const std::string negativeZ = string(item, "negativeZ", false);
        if (t.mips == DerivativeMips::normal) {
            if (negativeZ == "fail") t.negativeZ = NegativeZPolicy::fail;
            else if (negativeZ == "rgb") t.negativeZ = NegativeZPolicy::rgb;
            else fail(t.map + ": a normal map needs \"negativeZ\" fail or rgb (decision 316)");
            if (t.format != UzTextureStorage::BC5 || t.srgb) fail(t.map + ": a normal map is a linear BC5");
        } else if (!negativeZ.empty()) {
            fail(t.map + ": \"negativeZ\" is for normal maps only");
        }
        if (t.srgb && t.format != UzTextureStorage::BC7) fail(t.map + ": BC4 and BC5 are always linear (decision 315)");
        if (t.srgb != (t.mips == DerivativeMips::colour || t.mips == DerivativeMips::masked_colour)) {
            fail(t.map + ": an sRGB texture has colour mips and a linear one has none");
        }
        const MapSpec* map = MapNamed(spec, t.map);
        const MapSpec* canonical = MapNamed(spec, t.canonical);
        if (map == nullptr) fail("no map \"" + t.map + "\"");
        if (canonical == nullptr) fail(t.map + ": no canonical map \"" + t.canonical + "\"");
        if (canonical->channels != map->channels) fail(t.map + ": its canonical map reads other channels");
        for (const UzEngineTexture& other : targets.textures) {
            if (other.map == t.map) fail("two textures of the map \"" + t.map + "\"");
        }
        targets.textures.push_back(std::move(t));
    }
    if (const json::Value* material = Member(block, "material")) {
        if (!material->IsObject()) fail("\"material\" must be an object");
        allowed(*material, {"fileName", "albedo", "normal", "orm", "emissive", "height"});
        UzEngineMaterial m;
        m.fileName = string(*material, "fileName", true);
        m.albedo = string(*material, "albedo", true);
        m.normal = string(*material, "normal", true);
        m.orm = string(*material, "orm", true);
        m.emissive = string(*material, "emissive", true);
        m.height = string(*material, "height", false);
        if (m.fileName.empty() || m.fileName.find('/') != std::string::npos) {
            fail("the material's fileName must be a name at the delivery root");
        }
        for (const std::string* ref : {&m.albedo, &m.normal, &m.orm, &m.emissive, &m.height}) {
            if (ref->empty()) continue;
            const bool known = std::any_of(targets.textures.begin(), targets.textures.end(),
                                           [&](const UzEngineTexture& t) { return t.map == *ref; });
            if (!known) fail("the material names \"" + *ref + "\", which is no texture");
        }
        targets.material = std::move(m);
    }
    return targets;
}

/// The `dds` block of a shipped preset (config.h `DdsTarget`, decision 322), checked against its
/// maps: BC5 with normal mips, BC7 with linear mips, BC7_SRGB with colour mips. Throws
/// `core::ManifestError` naming the preset.
std::vector<DdsTarget> ParseDds(const json::Value& block, const PresetSpec& spec, std::string_view id,
                                const std::string& file) {
    const auto fail = [&](const std::string& problem) { Fail(id, file + ": dds: " + problem); };
    if (!block.IsArray()) fail("expected an array");
    std::vector<DdsTarget> targets;
    for (const json::Value& item : std::get<json::Array>(block.data)) {
        if (!item.IsObject()) fail("a target must be an object");
        for (const auto& [key, _] : std::get<json::Object>(item.data)) {
            if (key != "map" && key != "format" && key != "mips") fail("unknown key \"" + key + "\"");
        }
        const std::string* map = StringMember(item, "map");
        const std::string* format = StringMember(item, "format");
        const std::string* mips = StringMember(item, "mips");
        if (map == nullptr || format == nullptr || mips == nullptr) fail("map, format and mips must be strings");
        DdsTarget t;
        t.map = *map;
        if (*format == "BC5") t.format = BcFormat::Bc5;
        else if (*format == "BC7") t.format = BcFormat::Bc7;
        else if (*format == "BC7_SRGB") t.format = BcFormat::Bc7Srgb;
        else fail(t.map + ": format \"" + *format + "\" is not BC5, BC7 or BC7_SRGB");
        if (*mips == "linear") t.mips = DerivativeMips::linear;
        else if (*mips == "colour") t.mips = DerivativeMips::colour;
        else if (*mips == "normal") t.mips = DerivativeMips::normal;
        else if (*mips == "masked_colour") t.mips = DerivativeMips::masked_colour;
        else fail(t.map + ": mips \"" + *mips + "\" is not linear, colour, normal or masked_colour");
        const bool colour = t.mips == DerivativeMips::colour || t.mips == DerivativeMips::masked_colour;
        if ((t.format == BcFormat::Bc5) != (t.mips == DerivativeMips::normal)) {
            fail(t.map + ": BC5 goes with normal mips, and only with them");
        }
        if (colour != (t.format == BcFormat::Bc7Srgb)) fail(t.map + ": BC7_SRGB goes with colour mips, and only with them");
        if (MapNamed(spec, t.map) == nullptr) fail("no map \"" + t.map + "\"");
        for (const DdsTarget& other : targets) {
            if (other.map == t.map) fail("two targets of the map \"" + t.map + "\"");
        }
        targets.push_back(std::move(t));
    }
    if (targets.empty()) fail("no target");
    return targets;
}

}  // namespace

std::span<const PresetAlias> PresetAliases() { return kAliases; }

std::span<const std::string_view> ShippedPresetIds() { return kShippedIds; }

std::optional<std::string> ShippedPresetId(std::string_view reference) {
    if (std::find(kShippedIds.begin(), kShippedIds.end(), reference) != kShippedIds.end()) {
        return std::string(reference);
    }
    for (const PresetAlias& alias : kAliases) {
        if (reference == alias.painterName) return std::string(alias.presetId);
    }
    for (const PresetAlias& alias : kAliases) {
        const std::string url = alias.url.empty() ? std::string(kStarterAssets) + std::string(alias.painterName)
                                                : std::string(alias.url);
        if (reference == url) return std::string(alias.presetId);
        if (!reference.starts_with(url + "?")) continue;
        const std::string_view text = reference.substr(url.size() + 1);
        constexpr std::string_view kVersion = "version=";
        if (text.starts_with(kVersion) &&
            std::find(alias.versions.begin(), alias.versions.end(), text.substr(kVersion.size())) !=
                alias.versions.end()) {
            return std::string(alias.presetId);
        }
        throw core::NotYetSupported("export: the preset \"" + std::string(reference) + "\": the query \"" +
                                    std::string(text) + "\" of the Painter preset \"" + std::string(alias.painterName) +
                                    "\" is not recorded; the shipped preset \"" + std::string(alias.presetId) +
                                    "\" answers to its URL without a query or with a recorded version (" +
                                    std::string(alias.recording) + ")");
    }
    return std::nullopt;
}

ShippedPreset LoadShippedPreset(const std::filesystem::path& directory, std::string_view id) {
    const std::filesystem::path presetFile = directory / (std::string(id) + ".json");
    const std::filesystem::path recordFile = directory / (std::string(id) + ".provenance.json");
    std::error_code ec;
    if (!std::filesystem::is_regular_file(presetFile, ec)) Fail(id, presetFile.string() + " is missing");
    if (!std::filesystem::is_regular_file(recordFile, ec)) {
        Fail(id, "the provenance record " + recordFile.string() + " is missing");
    }
    ShippedPreset shipped;
    shipped.id = std::string(id);
    json::Value presetJson = ReadJson(presetFile, id);
    // The UzEngine and DDS targets: keys only a shipped preset may carry (an inline one is refused).
    std::optional<json::Value> uzengine;
    std::optional<json::Value> dds;
    if (presetJson.IsObject()) {
        json::Object& object = std::get<json::Object>(presetJson.data);
        if (const auto it = object.find("uzengine"); it != object.end()) {
            uzengine = std::move(it->second);
            object.erase(it);
        }
        if (const auto it = object.find("dds"); it != object.end()) {
            dds = std::move(it->second);
            object.erase(it);
        }
    }
    shipped.spec = ParsePreset(presetJson, presetFile.filename().string());
    if (shipped.spec.name != id) Fail(id, presetFile.string() + ": the preset's name is not its id");
    if (uzengine) shipped.spec.uzengine = ParseUzEngine(*uzengine, shipped.spec, id, presetFile.string());
    if (dds) shipped.spec.dds = ParseDds(*dds, shipped.spec, id, presetFile.string());

    const json::Value record = ReadJson(recordFile, id);
    const std::string* schema = StringMember(record, "schema");
    if (schema == nullptr || *schema != kProvenanceSchema) {
        Fail(id, recordFile.string() + " is not a " + std::string(kProvenanceSchema) + " record");
    }
    const std::string* preset = StringMember(record, "preset");
    if (preset == nullptr || *preset != id) Fail(id, recordFile.string() + " records another preset");
    const json::Value* parity = Member(record, "parity");
    const std::string* layout = parity != nullptr ? StringMember(*parity, "layout") : nullptr;
    if (layout == nullptr) Fail(id, recordFile.string() + ": parity.layout is missing");
    if (*layout == "pipeline") shipped.layout = PresetLayout::pipeline;
    else if (*layout == "confirmed") shipped.layout = PresetLayout::confirmed;
    else if (*layout == "unconfirmed") shipped.layout = PresetLayout::unconfirmed;
    else if (*layout == "consumer") shipped.layout = PresetLayout::consumer;
    else {
        Fail(id, recordFile.string() + ": parity.layout \"" + *layout +
                     "\" is not pipeline, confirmed, unconfirmed or consumer");
    }
    if ((shipped.layout == PresetLayout::consumer) != shipped.spec.uzengine.has_value()) {
        Fail(id, recordFile.string() + ": a consumer layout goes with uzengine targets, and only with them");
    }
    if (const json::Value* pending = Member(*parity, "pending"); pending != nullptr && pending->IsArray()) {
        for (const json::Value& item : std::get<json::Array>(pending->data)) {
            const std::string* recording = StringMember(item, "recording");
            if (recording == nullptr) Fail(id, recordFile.string() + ": a parity.pending item without its recording");
            shipped.pendingRecordings.push_back(*recording);
        }
    }
    if (shipped.layout == PresetLayout::unconfirmed && shipped.pendingRecordings.empty()) {
        Fail(id, recordFile.string() + ": an unconfirmed layout names no pending recording");
    }
    return shipped;
}

std::filesystem::path DefaultPresetDirectory() {
    return render::DefaultDxcompilerPath().parent_path() / "assets" / "export-presets";
}

}  // namespace uzp::exporter
