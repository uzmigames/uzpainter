#include "evaluator/templates.h"

#include <algorithm>
#include <fstream>
#include <iterator>
#include <set>
#include <sstream>

#include "evaluator/error.h"
#include "evaluator/sources.h"
#include "render/kernel_cache.h"
#include "uzp_core/types/errors.h"

namespace uzp::evaluator {

namespace {

using core::ManifestError;
using core::json::Value;

[[noreturn]] void Fail(std::string_view path, const std::string& message) {
    throw ManifestError(std::string(path) + ": " + message);
}

const core::json::Object& Object(const Value& value, std::string_view path) {
    if (!value.IsObject()) Fail(path, "expected an object");
    return std::get<core::json::Object>(value.data);
}

const Value& Need(const core::json::Object& object, std::string_view key, std::string_view path) {
    const auto it = object.find(key);
    if (it == object.end()) Fail(path, "missing key '" + std::string(key) + "'");
    return it->second;
}

std::string String(const core::json::Object& object, std::string_view key, std::string_view path) {
    const Value& value = Need(object, key, path);
    if (!value.IsString()) Fail(std::string(path) + "." + std::string(key), "expected a string");
    return std::get<std::string>(value.data);
}

double Number(const Value& value, std::string_view path) {
    if (value.IsInt()) return static_cast<double>(std::get<std::int64_t>(value.data));
    if (!value.IsDouble()) Fail(path, "expected a number");
    return std::get<double>(value.data);
}

template <typename E>
E Enum(const std::string& name, std::string_view path) {
    const auto parsed = core::FromString<E>(name);
    if (!parsed) Fail(path, "unknown member '" + name + "'");
    return *parsed;
}

TemplateChannel ParseChannel(const Value& value, std::string_view path, bool defaults) {
    const core::json::Object& object = Object(value, path);
    TemplateChannel channel;
    channel.type = Enum<core::ChannelType>(String(object, "type", path), std::string(path) + ".type");
    if (!defaults || object.contains("format")) {
        channel.format = Enum<core::ChannelFormat>(String(object, "format", path),
                                                   std::string(path) + ".format");
    }
    if (const auto it = object.find("project_templates"); it != object.end()) {
        const std::string scopePath = std::string(path) + ".project_templates";
        if (!defaults) Fail(scopePath, "only channel defaults may restrict project templates");
        if (!it->second.IsArray()) Fail(scopePath, "expected a non-empty array of template ids");
        const auto& scope = std::get<core::json::Array>(it->second.data);
        if (scope.empty()) Fail(scopePath, "expected a non-empty array of template ids");
        std::set<std::string> seen;
        for (const Value& entry : scope) {
            if (!entry.IsString()) Fail(scopePath, "expected a template id");
            const std::string& id = std::get<std::string>(entry.data);
            if (id.empty() || !seen.insert(id).second) Fail(scopePath, "empty or duplicate template id");
            channel.projectTemplates.push_back(id);
        }
    }
    if (const auto it = object.find("colour_management"); it != object.end()) {
        const std::string scopePath = std::string(path) + ".colour_management";
        if (!defaults) Fail(scopePath, "only channel defaults may restrict colour management");
        if (!it->second.IsString() || std::get<std::string>(it->second.data) != "legacy") {
            Fail(scopePath, "expected \"legacy\"");
        }
        channel.colourManagement = ColourDomain::Legacy;
    }
    const Value& base = Need(object, "base", path);
    const std::string basePath = std::string(path) + ".base";
    if (!base.IsArray()) Fail(basePath, "expected an array of three numbers");
    const core::json::Array& components = std::get<core::json::Array>(base.data);
    if (components.size() != 3) Fail(basePath, "expected three components");
    for (size_t i = 0; i < 3; ++i) {
        const double component = Number(components[i], basePath);
        channel.base[i] = static_cast<float>(component);
    }
    const Value& provenance = Need(object, "base_provenance", path);
    const std::string provenancePath = std::string(path) + ".base_provenance";
    channel.provenanceRecord = Object(provenance, provenancePath);
    channel.baseProvenance = String(channel.provenanceRecord, "kind", provenancePath);
    static const std::set<std::string, std::less<>> kKinds = {"observed", "fitted", "inferred", "unobserved"};
    if (!kKinds.contains(channel.baseProvenance)) {
        Fail(provenancePath + ".kind", "expected observed, fitted, inferred or unobserved");
    }
    return channel;
}

}  // namespace

ColourDomain ColourDomainOf(const core::ColorManagement& colour) {
    if (colour.mode.empty() || colour.mode == "legacy") return ColourDomain::Legacy;
    if (colour.mode == "ocio" && colour.config_hash == kPainterOcioConfigSha256) return ColourDomain::PainterOcio;
    return ColourDomain::Unknown;
}

const TemplateChannel* ProjectTemplate::Find(core::ChannelType type) const {
    for (const TemplateChannel& channel : channels) {
        if (channel.type == type) return &channel;
    }
    return nullptr;
}

std::map<core::ChannelType, core::Channel> ProjectTemplate::StackChannels() const {
    std::map<core::ChannelType, core::Channel> result;
    for (const TemplateChannel& channel : channels) {
        core::Channel stackChannel;
        stackChannel.format = channel.format.value_or(core::ChannelFormat::sRGB8);
        result.emplace(channel.type, std::move(stackChannel));
    }
    return result;
}

ProjectTemplate ParseTemplate(const Value& document, std::string_view path) {
    const core::json::Object& object = Object(document, path);
    if (String(object, "schema", path) != kTemplateSchema) {
        Fail(std::string(path) + ".schema", "expected " + std::string(kTemplateSchema));
    }
    ProjectTemplate result;
    result.id = String(object, "id", path);
    result.name = String(object, "name", path);
    const std::string kind = String(object, "kind", path);
    if (kind == "channel-defaults") {
        result.channelDefaults = true;
    } else if (kind != "project") {
        Fail(std::string(path) + ".kind", "expected project or channel-defaults");
    }
    if (const auto it = object.find("painter_template"); it != object.end() && !it->second.IsNull()) {
        if (!it->second.IsString()) Fail(std::string(path) + ".painter_template", "expected a string");
        result.painterTemplate = std::get<std::string>(it->second.data);
    }
    if (const auto it = object.find("default_resolution"); it != object.end()) {
        const std::string resolutionPath = std::string(path) + ".default_resolution";
        if (!it->second.IsInt()) Fail(resolutionPath, "expected an integer");
        const std::int64_t size = std::get<std::int64_t>(it->second.data);
        if (size < 1 || (size & (size - 1)) != 0 || size > 8192) Fail(resolutionPath, "expected a power of two up to 8192");
        result.defaultResolution = static_cast<int>(size);
    }
    if (const auto it = object.find("provenance"); it != object.end()) {
        result.provenance = Object(it->second, std::string(path) + ".provenance");
    }
    const Value& channels = Need(object, "channels", path);
    const std::string channelsPath = std::string(path) + ".channels";
    if (!channels.IsArray()) Fail(channelsPath, "expected an array");
    // A channel-defaults type may repeat with distinct formats, each entry recorded on its own; an
    // entry for any format stands alone.
    std::map<core::ChannelType, std::set<std::optional<core::ChannelFormat>>> seen;
    size_t index = 0;
    for (const Value& entry : std::get<core::json::Array>(channels.data)) {
        const std::string entryPath = channelsPath + "[" + std::to_string(index++) + "]";
        TemplateChannel channel = ParseChannel(entry, entryPath, result.channelDefaults);
        std::set<std::optional<core::ChannelFormat>>& formats = seen[channel.type];
        const bool repeated = !result.channelDefaults || !channel.format || formats.contains(std::nullopt)
                                  ? !formats.empty()
                                  : formats.contains(channel.format);
        if (repeated) Fail(entryPath, "channel '" + std::string(core::ToString(channel.type)) + "' repeats");
        formats.insert(channel.format);
        result.channels.push_back(std::move(channel));
    }
    return result;
}

TemplateLibrary TemplateLibrary::Load(const std::filesystem::path& directory) {
    TemplateLibrary library;
    std::error_code ec;
    if (!std::filesystem::is_directory(directory, ec)) {
        Fail(directory.string(), "not a directory");
    }
    std::vector<std::filesystem::path> files;
    for (const auto& entry : std::filesystem::directory_iterator(directory)) {
        if (entry.is_regular_file() && entry.path().extension() == ".json") {
            files.push_back(entry.path());
        }
    }
    std::sort(files.begin(), files.end());
    bool defaultsFound = false;
    for (const std::filesystem::path& file : files) {
        std::ifstream stream(file, std::ios::binary);
        if (!stream) Fail(file.string(), "cannot be read");
        std::string text((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
        Value document;
        try {
            document = core::json::Parse(text);
        } catch (const core::json::ParseError& error) {
            Fail(file.string(), std::string("invalid JSON: ") + error.what());
        }
        ProjectTemplate parsed = ParseTemplate(document, file.string());
        if (parsed.channelDefaults) {
            if (parsed.id != kChannelDefaultsId) {
                Fail(file.string() + ".id", "the channel-defaults table is named channel-defaults");
            }
            if (defaultsFound) Fail(file.string(), "a second channel-defaults table");
            defaultsFound = true;
            library.defaults_ = std::move(parsed);
            continue;
        }
        if (library.templates_.contains(parsed.id)) {
            Fail(file.string() + ".id", "template id '" + parsed.id + "' repeats");
        }
        library.templates_.emplace(parsed.id, std::move(parsed));
    }
    if (!defaultsFound) Fail(directory.string(), "no channel-defaults table");
    if (!library.templates_.contains(kDefaultTemplateId)) {
        Fail(directory.string(), "no 'default' template");
    }
    for (const TemplateChannel& channel : library.defaults_.channels) {
        for (const std::string& id : channel.projectTemplates) {
            if (!library.templates_.contains(id)) {
                Fail(directory.string(), "channel default names unknown project template '" + id + "'");
            }
        }
    }
    return library;
}

std::filesystem::path TemplateLibrary::DefaultDirectory() {
    const std::filesystem::path dxc = render::DefaultDxcompilerPath();
    return dxc.parent_path() / "assets" / "templates";
}

const ProjectTemplate* TemplateLibrary::Find(std::string_view id) const {
    const auto it = templates_.find(id);
    return it == templates_.end() ? nullptr : &it->second;
}

std::vector<std::string> TemplateLibrary::Ids() const {
    std::vector<std::string> ids;
    for (const auto& [id, _] : templates_) ids.push_back(id);
    return ids;
}

render::Result<const TemplateChannel*> TemplateLibrary::BaseChannel(std::string_view templateId,
                                                                   core::ChannelType type,
                                                                   std::optional<core::ChannelFormat> format,
                                                                   std::optional<ColourDomain> colour) const {
    const ProjectTemplate* project = Find(templateId);
    if (project == nullptr) {
        return EvalFail(EvalErrorKind::UnknownTemplate,
                        "no template '" + std::string(templateId) + "' in the library");
    }
    if (const TemplateChannel* channel = project->Find(type)) return channel;
    std::string recorded;  // the formats of the type's entries, when none applies to `format`
    for (const TemplateChannel& fallback : defaults_.channels) {
        if (fallback.type != type) continue;
        if (!fallback.projectTemplates.empty() &&
            std::find(fallback.projectTemplates.begin(), fallback.projectTemplates.end(), templateId) ==
                fallback.projectTemplates.end()) continue;
        const bool formatApplies = !fallback.format || fallback.format == format;
        if (fallback.colourManagement && formatApplies) {
            if (!colour) {
                return EvalFail(EvalErrorKind::MissingBaseValue,
                                "the channel default of " + std::string(core::ToString(type)) +
                                    " is restricted to legacy colour management and no colour management was given");
            }
            if (*colour != *fallback.colourManagement) continue;
        }
        if (formatApplies) return &fallback;
        recorded += (recorded.empty() ? "" : " and ") + std::string(core::ToString(*fallback.format));
    }
    if (!recorded.empty()) {
        return EvalFail(EvalErrorKind::MissingBaseValue,
                        "channel " + std::string(core::ToString(type)) + " is not in template '" +
                            std::string(templateId) + "', and its channel default is recorded as " + recorded +
                            " only");
    }
    return EvalFail(EvalErrorKind::MissingBaseValue,
                    "channel " + std::string(core::ToString(type)) + " is neither in template '" +
                        std::string(templateId) + "' nor in the channel defaults");
}

render::Result<std::array<float, 3>> TemplateLibrary::BaseValue(std::string_view templateId, core::ChannelType type,
                                                                std::optional<core::ChannelFormat> format,
                                                                std::optional<ColourDomain> colour) const {
    render::Result<const TemplateChannel*> channel = BaseChannel(templateId, type, format, colour);
    if (!channel) return render::Unexpected(channel.error());
    return (*channel)->base;
}

}  // namespace uzp::evaluator
