#include "store/snapshots.h"

#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/resource_url.h"

#include <algorithm>
#include <array>
#include <cmath>

namespace uzp::store {

using core::Id;
using core::json::Object;
using core::json::Value;

namespace {

/// The signature's `<asset>@<version>` pin and output id, or empty strings when it lacks them.
std::pair<std::string, std::string> PinAndOutput(const Value& signature) {
    const auto* object = std::get_if<Object>(&signature.data);
    if (object == nullptr) return {};
    const auto text = [](const Object& from, std::string_view name) -> std::string {
        const auto it = from.find(name);
        return it != from.end() && it->second.IsString() ? std::get<std::string>(it->second.data) : std::string();
    };
    const std::string asset = text(*object, "asset");
    const std::string version = text(*object, "version");
    const auto output = object->find("output");
    const auto* out = output == object->end() ? nullptr : std::get_if<Object>(&output->second.data);
    return {asset.empty() || version.empty() ? std::string() : asset + "@" + version,
            out ? text(*out, "id") : std::string()};
}

/// True when the signature's `asset` is of the reserved observation family, whatever else it holds.
bool ReservedAsset(const Value& signature) {
    const auto* object = std::get_if<Object>(&signature.data);
    const auto asset = object == nullptr ? Object::const_iterator{} : object->find("asset");
    return object != nullptr && asset != object->end() && asset->second.IsString() &&
           core::IsObservationAsset(std::get<std::string>(asset->second.data));
}

}  // namespace

namespace {

core::json::Array Strings(const std::vector<std::string>& values) {
    core::json::Array array;
    for (const std::string& value : values) array.push_back(value);
    return array;
}

/// A `source_metadata` member that must be an array of distinct nonempty strings.
std::expected<std::vector<std::string>, std::string> DistinctNames(const Value& value, std::string_view member,
                                                                   bool nonempty) {
    using Result = std::expected<std::vector<std::string>, std::string>;
    const std::string what = "source_metadata " + std::string(member);
    const auto* array = std::get_if<core::json::Array>(&value.data);
    if (array == nullptr || (nonempty && array->empty())) {
        return Result(std::unexpect, what + (nonempty ? " must be a nonempty array" : " must be an array"));
    }
    std::vector<std::string> names;
    for (const Value& item : *array) {
        if (!item.IsString() || std::get<std::string>(item.data).empty()) {
            return Result(std::unexpect, what + " must hold nonempty strings");
        }
        const std::string& name = std::get<std::string>(item.data);
        if (std::find(names.begin(), names.end(), name) != names.end()) {
            return Result(std::unexpect, what + " repeats " + name);
        }
        names.push_back(name);
    }
    return names;
}

/// Why `description` is not one `properties.Property` as the snapshot bridge serializes it
/// (python/uzpainter_snapshot/painter_side.py `described`): exactly the documented getters
/// `value`, `name`, `short_name`, `label`, `widget_type` (one of the documented widget types),
/// `enum_values` (label -> integer) and `properties` (an object), with `name` equal to its key.
std::string PropertyProblem(const std::string& key, const Value& description, bool colours) {
    static constexpr std::array<std::string_view, 7> kFields = {
        "value", "name", "short_name", "label", "widget_type", "enum_values", "properties"};
    // python-doc `Property.widget_type() -> str`, "One of:".
    static constexpr std::array<std::string_view, 11> kWidgets = {
        "Slider", "Angle", "Color", "Togglebutton", "Combobox", "RandomSeed",
        "File", "FileList", "LineEdit", "Resource", "TextEdit"};
    const auto* object = std::get_if<Object>(&description.data);
    if (key.empty() || object == nullptr || object->size() != kFields.size() ||
        !std::all_of(kFields.begin(), kFields.end(), [&](std::string_view f) { return object->contains(std::string(f)); })) {
        return "a property is an object of exactly value, name, short_name, label, widget_type, enum_values and properties";
    }
    const auto text = [&](std::string_view field) { return object->at(std::string(field)).IsString(); };
    if (!text("name") || std::get<std::string>(object->at("name").data) != key) return "name must equal its key";
    if (!text("short_name") || !text("label")) return "short_name and label must be strings";
    if (!text("widget_type") ||
        std::find(kWidgets.begin(), kWidgets.end(), std::get<std::string>(object->at("widget_type").data)) ==
            kWidgets.end()) {
        return "widget_type must be a documented widget type";
    }
    const auto* labels = std::get_if<Object>(&object->at("enum_values").data);
    if (labels == nullptr ||
        !std::all_of(labels->begin(), labels->end(), [](const auto& entry) { return entry.second.IsInt(); })) {
        return "enum_values must map labels to integers";
    }
    if (!object->at("properties").IsObject()) return "properties must be an object";
    // No typed codec exists for vectors or other values yet: only finite scalars, and under `/5`
    // tagged colours, are kept.
    const Value& value = object->at("value");
    const bool finite = value.IsInt() || value.IsString() ||
                        (value.IsDouble() && std::isfinite(std::get<double>(value.data)));
    if (!finite && !(colours && IsColourParam(value))) {
        return colours ? "value must be a finite integer, number, string or tagged colour"
                       : "value must be a finite integer, number or string";
    }
    return {};
}

/// Why `typed` is not the typed parameter map of a snapshot of `signature` (decision 361): an
/// object whose keys are exactly the signature's `params` and whose int64, finite double or
/// string values equal them by value. The raw values are kept; nothing is converted.
std::string TypedParametersProblem(const Value& signature, const Value& typed, bool colours) {
    const auto* map = std::get_if<Object>(&typed.data);
    if (map == nullptr) return "typed_effective_parameters must be an object";
    const auto* object = std::get_if<Object>(&signature.data);
    const auto params = object ? object->find("params") : Object::const_iterator{};
    const auto* expected = object && params != object->end() ? std::get_if<Object>(&params->second.data) : nullptr;
    if (expected == nullptr) return "typed_effective_parameters needs a signature with params";
    if (map->size() != expected->size()) return "typed_effective_parameters keys must be exactly the signature's parameters";
    for (const auto& [name, value] : *map) {
        const auto it = expected->find(name);
        if (it == expected->end()) return "typed_effective_parameters keys must be exactly the signature's parameters";
        const std::optional<Value> byValue = colours ? TypedParamByValue(value) : ParamByValue(value);
        if (!byValue) {
            return "typed_effective_parameters." + name +
                   (colours ? " must be an int64, finite double, string or tagged colour"
                            : " must be an int64, finite double or string");
        }
        if (core::json::WriteCanonical(*byValue) != core::json::WriteCanonical(it->second)) {
            return "typed_effective_parameters." + name + " is not the signature's value";
        }
    }
    return {};
}

/// `value` read as an observed ResourceID of the snapshot pinned as `pin`, or why not: exactly
/// four nonempty strings, and `pin` the snapshot asset of `url` (`uzasset://snapshot/<sha256>@1`).
std::expected<ObservedResourceId, std::string> ParseObservedResourceId(const Value& value, const std::string& pin) {
    using Result = std::expected<ObservedResourceId, std::string>;
    static constexpr std::array<std::string_view, 4> kParts = {"url", "context", "name", "version"};
    const auto* object = std::get_if<Object>(&value.data);
    const auto part = [&](std::string_view name) -> const std::string* {
        const auto it = object->find(name);
        return it != object->end() && it->second.IsString() && !std::get<std::string>(it->second.data).empty()
                   ? &std::get<std::string>(it->second.data)
                   : nullptr;
    };
    if (object == nullptr || object->size() != kParts.size() ||
        !std::all_of(kParts.begin(), kParts.end(), [&](std::string_view name) { return part(name) != nullptr; })) {
        return Result(std::unexpect, "observed_resource_id must be exactly the nonempty strings url, context, name and version");
    }
    ObservedResourceId id{*part("url"), *part("context"), *part("name"), *part("version")};
    if (pin != "uzasset://snapshot/" + core::Sha256Hex(id.url) + "@1") {
        return Result(std::unexpect, "observed_resource_id url is not the resource the snapshot pin " + pin + " names");
    }
    return id;
}

/// `{"raised": {"type": <nonempty>, "message": <string>}}` or `{"returned": <nonempty>}`; with
/// `value`, also `{"value": <nonempty>}`.
bool Outcome(const Value& outcome, bool value = false) {
    const auto* object = std::get_if<Object>(&outcome.data);
    if (object == nullptr || object->size() != 1) return false;
    const auto text = [](const Value& item) { return item.IsString() && !std::get<std::string>(item.data).empty(); };
    if (const auto it = object->find("raised"); it != object->end()) {
        const auto* raised = std::get_if<Object>(&it->second.data);
        return raised != nullptr && raised->size() == 2 && raised->contains("type") && raised->contains("message") &&
               text(raised->at("type")) && raised->at("message").IsString();
    }
    if (const auto it = object->find("returned"); it != object->end()) return text(it->second);
    if (const auto it = object->find("value"); value && it != object->end()) return text(it->second);
    return false;
}

/// Exactly the names of `observed` when it is given, as a set.
bool SameKeys(const Object& object, const std::optional<std::vector<std::string>>& observed) {
    if (!observed) return true;
    if (object.size() != observed->size()) return false;
    return std::all_of(observed->begin(), observed->end(), [&](const std::string& name) { return object.contains(name); });
}

/// Why `value` is not the `/4` `preset_parameters` of a snapshot of `signature` (decision 413).
std::string PresetParametersProblem(const Value& signature, const Value& value,
                                    const std::optional<std::vector<std::string>>& presets, bool colours) {
    const auto* map = std::get_if<Object>(&value.data);
    if (map == nullptr || !SameKeys(*map, presets)) return "preset_parameters must be an object keyed by the presets";
    const auto* object = std::get_if<Object>(&signature.data);
    const auto params = object ? object->find("params") : Object::const_iterator{};
    const auto* expected = object && params != object->end() ? std::get_if<Object>(&params->second.data) : nullptr;
    if (expected == nullptr) return "preset_parameters needs a signature with params";
    for (const auto& [preset, parameters] : *map) {
        const auto* values = std::get_if<Object>(&parameters.data);
        if (preset.empty() || values == nullptr || values->size() != expected->size()) {
            return "preset_parameters." + preset + " must map exactly the signature's parameters";
        }
        for (const auto& [name, item] : *values) {
            if (!expected->contains(name) || !(colours ? TypedParamByValue(item) : ParamByValue(item))) {
                return "preset_parameters." + preset + "." + name + " must be a signature parameter of int64, finite double or string";
            }
        }
    }
    return {};
}

/// Why `value` is not the `/4` `input_sources` of a snapshot of `signature` (decision 413).
std::string InputSourcesProblem(const Value& signature, const Value& value,
                                const std::optional<std::vector<std::string>>& inputs) {
    const auto* map = std::get_if<Object>(&value.data);
    if (map == nullptr || !SameKeys(*map, inputs)) return "input_sources must be an object keyed by the image inputs";
    const auto* object = std::get_if<Object>(&signature.data);
    const auto member = object ? object->find("inputs") : Object::const_iterator{};
    const auto* plugged = object && member != object->end() ? std::get_if<Object>(&member->second.data) : nullptr;
    if (plugged == nullptr) return "input_sources needs a signature with inputs";
    std::size_t sources = 0;
    for (const auto& [name, input] : *plugged) {
        const auto* fields = std::get_if<Object>(&input.data);
        if (fields != nullptr && (fields->contains("working_colour") || fields->contains("bitmap_sha256"))) ++sources;
    }
    std::size_t matched = 0;
    for (const auto& [name, source] : *map) {
        const auto* fields = std::get_if<Object>(&source.data);
        const auto signed_input = plugged->find(name);
        if (fields != nullptr && fields->contains("raised")) {
            if (!Outcome(source) || signed_input != plugged->end()) {
                return "input_sources." + name + ": an unplugged input is a raised outcome absent from the signature";
            }
            continue;
        }
        const Value* kind = fields && fields->contains("class") ? &fields->at("class") : nullptr;
        // An unplugged input whose `get_source` returns a bitmap: its `resource_id` raised, and its
        // colour space read or raised (decision 413). It is absent from the signature.
        if (kind && kind->IsString() && std::get<std::string>(kind->data) == "SourceBitmap" &&
            fields->contains("resource_id")) {
            const bool space = fields->size() == 3 &&
                               ((fields->contains("colour_space") && fields->at("colour_space").IsString()) ||
                                (fields->contains("colour_space_raised") && Outcome(fields->at("colour_space_raised"))));
            const auto* id = std::get_if<Object>(&fields->at("resource_id").data);
            if (!space || id == nullptr || !id->contains("raised") || !Outcome(fields->at("resource_id")) ||
                signed_input != plugged->end()) {
                return "input_sources." + name + ": an unplugged bitmap is a raised resource_id absent from the signature";
            }
            continue;
        }
        Object expected;
        if (kind && kind->IsString() && std::get<std::string>(kind->data) == "SourceUniformColor" && fields->size() == 2 &&
            fields->contains("working")) {
            const auto* working = std::get_if<core::json::Array>(&fields->at("working").data);
            core::json::Array components;
            for (const Value& component : working ? *working : core::json::Array{}) {
                const auto byValue = ParamByValue(component);
                if (!byValue || byValue->IsString()) return "input_sources." + name + ": working must be finite numbers";
                components.push_back(*byValue);
            }
            if (components.size() != 3) return "input_sources." + name + ": working must be three numbers";
            expected = Object{{"working_colour", std::move(components)}};
        } else if (kind && kind->IsString() && std::get<std::string>(kind->data) == "SourceBitmap" && fields->size() == 3 &&
                   fields->contains("sha256") && fields->contains("colour_space")) {
            expected = Object{{"bitmap_sha256", fields->at("sha256")}, {"colour_space", fields->at("colour_space")}};
        } else {
            return "input_sources." + name + " must be a raised outcome, a SourceUniformColor or a SourceBitmap";
        }
        if (signed_input == plugged->end() ||
            core::json::WriteCanonical(signed_input->second) != core::json::WriteCanonical(Value(expected))) {
            return "input_sources." + name + " is not the signature's plugged input";
        }
        ++matched;
    }
    if (matched != sources) return "input_sources must describe every plugged input of the signature";
    return {};
}

/// True when `name` is a channel type name.
bool ChannelName(const std::string& name) {
    return core::FromString<core::ChannelType>(name).has_value();
}

/// Why `value` is not the `/4` `contexts` of a snapshot listing `outputs` (decision 413).
std::string ContextsProblem(const Value& value, const std::vector<std::string>& outputs,
                            const std::optional<std::vector<std::string>>& colourParameters) {
    const auto* object = std::get_if<Object>(&value.data);
    if (object == nullptr || object->size() != 2 || !object->contains("split") || !object->contains("material")) {
        return "contexts must hold exactly split and material";
    }
    const auto* split = std::get_if<Object>(&object->at("split").data);
    if (split == nullptr || split->size() != 2 || !split->contains("output_mapping") || !split->contains("mask_output") ||
        !Outcome(split->at("output_mapping")) || !Outcome(split->at("mask_output"))) {
        return "contexts.split must hold exactly the output_mapping and mask_output outcomes";
    }
    const auto* material = std::get_if<Object>(&object->at("material").data);
    static constexpr std::array<std::string_view, 4> kMaterial = {"output_mapping", "mask_output", "active_channels",
                                                                  "active_output"};
    // Under `/5`, the space the material source reads each colour parameter in (item 2.16).
    const std::size_t extra = colourParameters ? 1 : 0;
    if (material == nullptr || material->size() != kMaterial.size() + extra ||
        !std::all_of(kMaterial.begin(), kMaterial.end(), [&](std::string_view k) { return material->contains(std::string(k)); }) ||
        (colourParameters && !material->contains("colour_spaces"))) {
        return colourParameters ? "contexts.material must hold exactly output_mapping, mask_output, active_channels, "
                                  "active_output and colour_spaces"
                                : "contexts.material must hold exactly output_mapping, mask_output, active_channels and "
                                  "active_output";
    }
    if (colourParameters) {
        const auto* spaces = std::get_if<Object>(&material->at("colour_spaces").data);
        if (spaces == nullptr || spaces->size() != colourParameters->size() ||
            !std::all_of(colourParameters->begin(), colourParameters->end(), [&](const std::string& name) {
                const auto it = spaces->find(name);
                return it != spaces->end() && it->second.IsString() && !std::get<std::string>(it->second.data).empty();
            })) {
            return "contexts.material.colour_spaces must name a space for exactly the colour parameters";
        }
    }
    const auto* mapping = std::get_if<Object>(&material->at("output_mapping").data);
    if (mapping == nullptr) return "contexts.material.output_mapping must be an object";
    for (const auto& [channel, output] : *mapping) {
        if (!ChannelName(channel) || !output.IsString() ||
            std::find(outputs.begin(), outputs.end(), std::get<std::string>(output.data)) == outputs.end()) {
            return "contexts.material.output_mapping must map channel types to listed outputs";
        }
    }
    const Value& mask = material->at("mask_output");
    if (!mask.IsString() || std::get<std::string>(mask.data).empty()) return "contexts.material.mask_output must be a nonempty string";
    auto channels = DistinctNames(material->at("active_channels"), "contexts.material.active_channels", false);
    if (!channels) return channels.error();
    if (!std::all_of(channels->begin(), channels->end(), ChannelName)) {
        return "contexts.material.active_channels must name channel types";
    }
    if (!Outcome(material->at("active_output"), true)) return "contexts.material.active_output must be an outcome or a value";
    return {};
}

}  // namespace

std::optional<Value> ParamByValue(const Value& value) {
    if (value.IsInt() || value.IsString()) return value;
    if (!value.IsDouble()) return std::nullopt;
    const double number = std::get<double>(value.data);
    if (!std::isfinite(number)) return std::nullopt;
    // ParamJson: an integral double inside the int64 range is that integer. Both bounds are exact
    // doubles, so the comparison decides before the cast, which then cannot overflow.
    if (std::trunc(number) == number && number >= -9223372036854775808.0 && number < 9223372036854775808.0) {
        return Value(static_cast<std::int64_t>(number));
    }
    return value;
}

bool IsColourParam(const Value& value) {
    const auto* object = std::get_if<Object>(&value.data);
    if (object == nullptr || object->size() != 4) return false;
    const auto field = [&](std::string_view name) -> const Value* {
        const auto it = object->find(name);
        return it == object->end() ? nullptr : &it->second;
    };
    const Value* type = field("type");
    const Value* space = field("working_space");
    const Value* components = field("components");
    const Value* alpha = field("alpha");
    if (type == nullptr || *type != Value("color") || space == nullptr || !space->IsString() ||
        std::get<std::string>(space->data).empty() || alpha == nullptr || !alpha->IsNull() || components == nullptr) {
        return false;
    }
    const auto* list = std::get_if<core::json::Array>(&components->data);
    return list != nullptr && list->size() == 3 && std::all_of(list->begin(), list->end(), [](const Value& component) {
               const auto number = ParamByValue(component);
               return number && !number->IsString();
           });
}

std::optional<Value> TypedParamByValue(const Value& value) {
    if (auto scalar = ParamByValue(value)) return scalar;
    if (!IsColourParam(value)) return std::nullopt;
    Object colour = std::get<Object>(value.data);
    core::json::Array components;
    for (const Value& component : std::get<core::json::Array>(colour.at("components").data)) {
        components.push_back(*ParamByValue(component));
    }
    colour["components"] = std::move(components);
    return Value(std::move(colour));
}

namespace {

/// Whether any parameter, preset parameter or property value of `metadata` is a tagged colour.
bool HoldsColour(const SourceMetadata& metadata) {
    const auto any = [](const Object& map) {
        return std::any_of(map.begin(), map.end(), [](const auto& entry) { return IsColourParam(entry.second); });
    };
    if (metadata.typed_effective_parameters && any(*metadata.typed_effective_parameters)) return true;
    if (metadata.preset_parameters) {
        for (const auto& [preset, parameters] : *metadata.preset_parameters) {
            if (const auto* map = std::get_if<Object>(&parameters.data); map && any(*map)) return true;
        }
    }
    if (metadata.properties) {
        for (const auto& [name, description] : *metadata.properties) {
            const auto* object = std::get_if<Object>(&description.data);
            const auto value = object ? object->find("value") : Object::const_iterator{};
            if (object && value != object->end() && IsColourParam(value->second)) return true;
        }
    }
    return false;
}

}  // namespace

Value SourceMetadataJson(const Value& signature, const SourceMetadata& metadata) {
    const bool v5 = HoldsColour(metadata);
    const bool v4 = metadata.preset_parameters || metadata.input_sources || metadata.contexts;
    const bool v3 = metadata.typed_effective_parameters || metadata.observed_resource_id;
    const bool v2 = metadata.image_inputs || metadata.presets || metadata.properties;
    const std::string_view schema = v5   ? kSourceMetadataSchemaV5
                                    : v4 ? kSourceMetadataSchemaV4
                                    : v3 ? kSourceMetadataSchemaV3
                                    : v2 ? kSourceMetadataSchemaV2
                                         : kSourceMetadataSchema;
    Object object{{"schema", std::string(schema)},
                  {"asset", PinAndOutput(signature).first},
                  {"image_outputs", Strings(metadata.image_outputs)}};
    if (metadata.image_inputs) object["image_inputs"] = Strings(*metadata.image_inputs);
    if (metadata.presets) object["presets"] = Strings(*metadata.presets);
    if (metadata.properties) object["properties"] = *metadata.properties;
    if (metadata.typed_effective_parameters) object["typed_effective_parameters"] = *metadata.typed_effective_parameters;
    if (const auto& id = metadata.observed_resource_id) {
        object["observed_resource_id"] =
            Object{{"url", id->url}, {"context", id->context}, {"name", id->name}, {"version", id->version}};
    }
    if (metadata.preset_parameters) object["preset_parameters"] = *metadata.preset_parameters;
    if (metadata.input_sources) object["input_sources"] = *metadata.input_sources;
    if (metadata.contexts) object["contexts"] = *metadata.contexts;
    return object;
}

Value SourceMetadataJson(const Value& signature, const std::vector<std::string>& image_outputs) {
    return SourceMetadataJson(signature, SourceMetadata{image_outputs, std::nullopt, std::nullopt, std::nullopt, std::nullopt, std::nullopt});
}

std::expected<SourceMetadata, std::string> ParseSourceMetadata(const Value& signature, const Value& metadata) {
    using Result = std::expected<SourceMetadata, std::string>;
    const auto* object = std::get_if<Object>(&metadata.data);
    const Value* schema = object ? (object->contains("schema") ? &object->at("schema") : nullptr) : nullptr;
    const bool v1 = schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchema;
    const bool v2 = schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchemaV2;
    const bool v3 = schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchemaV3;
    const bool v5 = schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchemaV5;
    const bool v4 = v5 || (schema && schema->IsString() && std::get<std::string>(schema->data) == kSourceMetadataSchemaV4);
    if (object == nullptr || !object->contains("asset") || !object->contains("image_outputs") || schema == nullptr) {
        return Result(std::unexpect, "source_metadata must be an object of schema, asset and image_outputs");
    }
    if (!v1 && !v2 && !v3 && !v4) {
        return Result(std::unexpect, "source_metadata schema must be " + std::string(kSourceMetadataSchema) + ", " +
                                         std::string(kSourceMetadataSchemaV2) + ", " +
                                         std::string(kSourceMetadataSchemaV3) + ", " +
                                         std::string(kSourceMetadataSchemaV4) + " or " +
                                         std::string(kSourceMetadataSchemaV5));
    }
    for (const auto& [name, ignored] : *object) {
        const bool required = name == "schema" || name == "asset" || name == "image_outputs";
        const bool optional = name == "image_inputs" || name == "presets" || name == "properties";
        const bool observed = name == "typed_effective_parameters" || name == "observed_resource_id";
        const bool contexts = name == "preset_parameters" || name == "input_sources" || name == "contexts";
        if (!required && !((v2 || v3 || v4) && optional) && !((v3 || v4) && observed) && !(v4 && contexts)) {
            return Result(std::unexpect, v1 ? "source_metadata must be an object of exactly schema, asset and image_outputs"
                                            : "source_metadata has the unknown member " + name);
        }
    }
    // One encoding per observation set: /3 exists only for its own members.
    if (v3 && !object->contains("typed_effective_parameters") && !object->contains("observed_resource_id")) {
        return Result(std::unexpect, "source_metadata /3 needs typed_effective_parameters or observed_resource_id");
    }
    if (v4 && !v5 && !object->contains("preset_parameters") && !object->contains("input_sources") && !object->contains("contexts")) {
        return Result(std::unexpect, "source_metadata /4 needs preset_parameters, input_sources or contexts");
    }
    const auto [pin, output] = PinAndOutput(signature);
    if (pin.empty() || output.empty()) {
        return Result(std::unexpect, "source_metadata needs a signature with asset, version and output id");
    }
    const Value& asset = object->at("asset");
    if (!asset.IsString() || std::get<std::string>(asset.data) != pin) {
        return Result(std::unexpect, "source_metadata asset must be the signature's exact pin " + pin);
    }
    SourceMetadata parsed;
    auto outputs = DistinctNames(object->at("image_outputs"), "image_outputs", true);
    if (!outputs) return Result(std::unexpect, outputs.error());
    parsed.image_outputs = std::move(*outputs);
    if (std::find(parsed.image_outputs.begin(), parsed.image_outputs.end(), output) == parsed.image_outputs.end()) {
        return Result(std::unexpect, "source_metadata image_outputs does not hold the signature's output " + output);
    }
    for (const auto& [member, target] : {std::pair{"image_inputs", &parsed.image_inputs}, std::pair{"presets", &parsed.presets}}) {
        if (!object->contains(member)) continue;
        auto names = DistinctNames(object->at(member), member, false);
        if (!names) return Result(std::unexpect, names.error());
        *target = std::move(*names);
    }
    if (object->contains("properties")) {
        const auto* properties = std::get_if<Object>(&object->at("properties").data);
        if (properties == nullptr) return Result(std::unexpect, "source_metadata properties must be an object");
        for (const auto& [name, description] : *properties) {
            const std::string problem = PropertyProblem(name, description, v5);
            if (!problem.empty()) return Result(std::unexpect, "source_metadata properties." + name + ": " + problem);
        }
        parsed.properties = *properties;
    }
    if (const auto typed = object->find("typed_effective_parameters"); typed != object->end()) {
        const std::string problem = TypedParametersProblem(signature, typed->second, v5);
        if (!problem.empty()) return Result(std::unexpect, "source_metadata " + problem);
        parsed.typed_effective_parameters = std::get<Object>(typed->second.data);
    }
    if (const auto id = object->find("observed_resource_id"); id != object->end()) {
        auto observed = ParseObservedResourceId(id->second, pin);
        if (!observed) return Result(std::unexpect, "source_metadata " + observed.error());
        parsed.observed_resource_id = std::move(*observed);
    }
    if (const auto presets = object->find("preset_parameters"); presets != object->end()) {
        const std::string problem = PresetParametersProblem(signature, presets->second, parsed.presets, v5);
        if (!problem.empty()) return Result(std::unexpect, "source_metadata " + problem);
        parsed.preset_parameters = std::get<Object>(presets->second.data);
    }
    if (const auto inputs = object->find("input_sources"); inputs != object->end()) {
        const std::string problem = InputSourcesProblem(signature, inputs->second, parsed.image_inputs);
        if (!problem.empty()) return Result(std::unexpect, "source_metadata " + problem);
        parsed.input_sources = std::get<Object>(inputs->second.data);
    }
    if (const auto contexts = object->find("contexts"); contexts != object->end()) {
        std::optional<std::vector<std::string>> colourParameters;
        if (v5 && parsed.typed_effective_parameters) {
            colourParameters.emplace();
            for (const auto& [name, value] : *parsed.typed_effective_parameters) {
                if (IsColourParam(value)) colourParameters->push_back(name);
            }
        }
        const std::string problem = ContextsProblem(contexts->second, parsed.image_outputs, colourParameters);
        if (!problem.empty()) return Result(std::unexpect, "source_metadata " + problem);
        parsed.contexts = std::get<Object>(contexts->second.data);
    }
    // One encoding per observation set: /5 exists only for metadata holding a colour.
    if (v5 && !HoldsColour(parsed)) return Result(std::unexpect, "source_metadata /5 needs a colour parameter or property");
    return parsed;
}

std::string SourceMetadataProblem(const Value& signature, const Value& metadata) {
    const auto parsed = ParseSourceMetadata(signature, metadata);
    return parsed ? std::string() : parsed.error();
}

std::vector<SnapshotEntry> SnapshotEntries(const Value& member) {
    std::vector<SnapshotEntry> out;
    const std::string base(kSnapshotsKey);
    const auto* entries = std::get_if<Object>(&member.data);
    if (entries == nullptr) {
        SnapshotEntry malformed;
        malformed.path = base;
        malformed.error = "procedural_snapshots is not an object";
        out.push_back(std::move(malformed));
        return out;
    }
    for (const auto& [key, value] : *entries) {
        SnapshotEntry entry;
        entry.key = key;
        entry.path = base + "." + key;
        const auto* object = std::get_if<Object>(&value.data);
        if (object == nullptr) {
            entry.error = "the entry is not an object";
            out.push_back(std::move(entry));
            continue;
        }
        const auto member_of = [&](std::string_view name) -> const Value* {
            const auto it = object->find(name);
            return it == object->end() ? nullptr : &it->second;
        };
        const Value* signature = member_of("signature");
        const Value* uuid = member_of("project_uuid");
        const Value* plane = member_of("plane");
        const Value* versions = member_of(kPlaneVersionsKey);
        if (signature == nullptr || !signature->IsObject()) {
            entry.error = "the entry has no signature object";
        } else if (uuid == nullptr || !uuid->IsString() || std::get<std::string>(uuid->data).empty()) {
            entry.error = "the entry names no project_uuid";
        } else if (plane == nullptr || !plane->IsInt() || std::get<std::int64_t>(plane->data) <= 0) {
            entry.error = "the entry holds no plane";
        } else {
            entry.signature = *signature;
            entry.project_uuid = std::get<std::string>(uuid->data);
            entry.plane_id = static_cast<Id>(std::get<std::int64_t>(plane->data));
            const auto* map = versions ? std::get_if<Object>(&versions->data) : nullptr;
            const auto bound = map ? map->find(std::to_string(entry.plane_id)) : Object::const_iterator{};
            if (map == nullptr || bound == map->end()) {
                entry.error = "the entry does not bind its plane " + std::to_string(entry.plane_id);
            } else if (map->size() != 1) {
                entry.error = "the entry binds planes other than its own";
            } else {
                entry.version = ParseBinding(bound->second, entry.error);
            }
            const Value* metadata = member_of(kSourceMetadataKey);
            if (entry.error.empty() && metadata != nullptr) {
                auto parsed = ParseSourceMetadata(entry.signature, *metadata);
                if (parsed) {
                    entry.source_metadata = std::move(*parsed);
                } else {
                    entry.error = parsed.error();
                }
            }
        }
        out.push_back(std::move(entry));
    }
    return out;
}

std::vector<SnapshotEntry> ManifestSnapshots(const Value& manifest) {
    const auto* top = std::get_if<Object>(&manifest.data);
    if (top == nullptr) return {};
    const auto member = top->find(kSnapshotsKey);
    return member == top->end() ? std::vector<SnapshotEntry>{} : SnapshotEntries(member->second);
}

std::vector<SnapshotEntry> ProjectSnapshots(const core::Project& project) {
    const auto member = project.extra.find(kSnapshotsKey);
    return member == project.extra.end() ? std::vector<SnapshotEntry>{} : SnapshotEntries(member->second);
}

std::string SnapshotProblem(const SnapshotEntry& entry, std::string_view project_uuid) {
    if (!entry.error.empty()) return entry.error;
    if (ReservedAsset(entry.signature)) {
        return "the snapshot's asset is of the reserved observation family, which is never stored as a snapshot "
               "(decision 362)";
    }
    const std::string hash = core::Sha256Hex(core::json::WriteCanonical(entry.signature));
    if (hash != entry.key) {
        return "the entry is stored under " + entry.key + ", its signature hashes to " + hash;
    }
    if (entry.project_uuid != project_uuid) {
        return "the snapshot was recorded for project " + entry.project_uuid + ", not for project " +
               std::string(project_uuid) + ": snapshots are project-private and are never copied into another project";
    }
    return {};
}

void CheckSnapshots(const core::Project& project, std::string_view project_uuid) {
    for (const SnapshotEntry& entry : ProjectSnapshots(project)) {
        const std::string problem = SnapshotProblem(entry, project_uuid);
        if (!problem.empty()) throw StoreError(StoreError::Code::conflict, entry.path + ": " + problem);
    }
}

Id StageSnapshot(Container& container, PendingPlanes& pending, core::Edit& edit, std::string_view project_uuid,
                 const Value& signature, const PlaneImage& image,
                 const std::optional<SourceMetadata>& observed) {
    if (!signature.IsObject()) throw core::ValueError("snapshot: the signature is not a JSON object");
    // Before any allocation or plane write: the reserved observation family is never a snapshot.
    if (ReservedAsset(signature)) {
        throw core::ValueError("snapshot: the asset is of the reserved observation family (decision 362)");
    }
    std::optional<Value> metadata;
    if (observed) {
        metadata = SourceMetadataJson(signature, *observed);
        const std::string problem = SourceMetadataProblem(signature, *metadata);
        if (!problem.empty()) throw core::ValueError("snapshot: " + problem);
    }
    if (image.width < 1 || image.height < 1 || image.width > kMaxPlaneEdge || image.height > kMaxPlaneEdge) {
        throw core::ValueError("snapshot: size " + std::to_string(image.width) + "x" + std::to_string(image.height) +
                               " is outside 1.." + std::to_string(kMaxPlaneEdge));
    }
    const std::string key = core::Sha256Hex(core::json::WriteCanonical(signature));
    core::Project& project = edit.project();
    Value& member = project.extra[std::string(kSnapshotsKey)];
    if (member.IsNull()) member = Object{};
    if (!member.IsObject()) throw core::ValueError("snapshot: the project's procedural_snapshots is not an object");
    if (std::get<Object>(member.data).count(key) != 0) {
        throw core::ValueError("snapshot: the project already holds a snapshot with signature " + key +
                               "; a snapshot is immutable migration data");
    }

    const Id plane_id = edit.AllocateId();
    if (pending.planes.count(plane_id) != 0 || ReadPlaneRow(container, plane_id)) {
        throw StoreError(StoreError::Code::conflict, "plane id " + std::to_string(plane_id) +
                                                         " is already a stored plane (the project counter went back)");
    }
    PlaneRow row;  // no texture set, stack, channel or UV tile: the project's own raster
    row.plane_id = plane_id;
    row.format = image.format;
    row.width = image.width;
    row.height = image.height;
    const VersionRef ref = StageVersion(container, pending, row, image);
    pending.planes[plane_id] = row;
    Object entry{
        {"signature", signature},
        {"project_uuid", std::string(project_uuid)},
        {"plane", static_cast<std::int64_t>(plane_id)},
        {std::string(kPlaneVersionsKey), Object{{std::to_string(plane_id), ref.ToJson()}}},
    };
    if (metadata) entry[std::string(kSourceMetadataKey)] = std::move(*metadata);
    std::get<Object>(member.data)[key] = std::move(entry);
    return plane_id;
}

}  // namespace uzp::store
