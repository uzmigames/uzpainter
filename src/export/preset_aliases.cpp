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

constexpr std::array<std::string_view, 3> kShippedIds{"pbr-metallic-roughness", "blender-principled-bsdf",
                                                       "assets3d-inline-five-map"};

const std::array<PresetAlias, 2> kAliases{{
    {"PBR Metallic Roughness", "pbr-metallic-roughness", {}},
    {"Blender (Principled BSDF)", "blender-principled-bsdf", kBlenderVersions},
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
    if (!reference.starts_with(kStarterAssets)) return std::nullopt;
    const std::string_view rest = reference.substr(kStarterAssets.size());
    const size_t query = rest.find('?');
    const std::string_view name = rest.substr(0, query);
    for (const PresetAlias& alias : kAliases) {
        if (name != alias.painterName) continue;
        if (query == std::string_view::npos) return std::string(alias.presetId);
        const std::string_view text = rest.substr(query + 1);
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
                                    std::string(kRecording) + ")");
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
    shipped.spec = ParsePreset(ReadJson(presetFile, id), presetFile.filename().string());
    if (shipped.spec.name != id) Fail(id, presetFile.string() + ": the preset's name is not its id");

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
    else Fail(id, recordFile.string() + ": parity.layout \"" + *layout + "\" is not pipeline, confirmed or unconfirmed");
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
