#include "bake/baking_parameters.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <stdexcept>

#include "bake/baking_catalog.h"
#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;
namespace json = core::json;

const char* PropertyTypeName(PropertyType type) {
    switch (type) {
        case PropertyType::Bool: return "Bool";
        case PropertyType::Int: return "Int";
        case PropertyType::Float: return "Float";
        case PropertyType::IntPair: return "IntPair";
        case PropertyType::FloatPair: return "FloatPair";
        case PropertyType::Enum: return "Enum";
        case PropertyType::String: return "String";
    }
    return "unknown";
}

namespace {

// ── The authored table (assets/defaults/baking.json) ─────────────────────────────────────────

constexpr MeshMapUsage kUsages[] = {
    MeshMapUsage::Normal,    MeshMapUsage::WorldSpaceNormal, MeshMapUsage::ID,     MeshMapUsage::AO,
    MeshMapUsage::Curvature, MeshMapUsage::Position,         MeshMapUsage::Thickness, MeshMapUsage::Height,
    MeshMapUsage::BentNormals, MeshMapUsage::Opacity,
};

[[noreturn]] void Malformed(const std::string& what) {
    throw std::logic_error("assets/defaults/baking.json: " + what);
}

const json::Value& Member(const json::Object& object, const char* key, const std::string& where) {
    const auto it = object.find(key);
    if (it == object.end()) Malformed(where + " has no '" + key + "'");
    return it->second;
}

const json::Object& AsObject(const json::Value& value, const std::string& where) {
    if (!value.IsObject()) Malformed(where + " is not an object");
    return std::get<json::Object>(value.data);
}

const json::Array& AsArray(const json::Value& value, const std::string& where) {
    if (!value.IsArray()) Malformed(where + " is not an array");
    return std::get<json::Array>(value.data);
}

const std::string& AsString(const json::Value& value, const std::string& where) {
    if (!value.IsString()) Malformed(where + " is not a string");
    return std::get<std::string>(value.data);
}

double AsNumber(const json::Value& value, const std::string& where) {
    if (value.IsInt()) return static_cast<double>(std::get<std::int64_t>(value.data));
    if (value.IsDouble()) return std::get<double>(value.data);
    Malformed(where + " is not a number");
}

std::int64_t AsInt(const json::Value& value, const std::string& where) {
    if (!value.IsInt()) Malformed(where + " is not an integer");
    return std::get<std::int64_t>(value.data);
}

PropertyType TypeNamed(const std::string& name, const std::string& where) {
    for (PropertyType type : {PropertyType::Bool, PropertyType::Int, PropertyType::Float, PropertyType::IntPair,
                              PropertyType::FloatPair, PropertyType::Enum, PropertyType::String}) {
        if (name == PropertyTypeName(type)) return type;
    }
    Malformed(where + " has an unknown type '" + name + "'");
}

/// A value of `spec`'s type from the table (an `Enum` as its integer, stored as its label).
PropertyValue TableValue(const PropertySpec& spec, const json::Value& value, const std::string& where) {
    const auto pair = [&](auto convert) {
        const json::Array& array = AsArray(value, where);
        if (array.size() != 2) Malformed(where + " is not a pair");
        return std::pair{convert(array[0], where), convert(array[1], where)};
    };
    switch (spec.type) {
        case PropertyType::Bool:
            if (!value.IsBool()) Malformed(where + " is not a bool");
            return std::get<bool>(value.data);
        case PropertyType::Int: return AsInt(value, where);
        case PropertyType::Float: return AsNumber(value, where);
        case PropertyType::IntPair: return pair(AsInt);
        case PropertyType::FloatPair: return pair(AsNumber);
        case PropertyType::Enum: {
            const std::int64_t number = AsInt(value, where);
            for (const auto& [label, integer] : spec.enum_values) {
                if (integer == number) return EnumLabel{label};
            }
            Malformed(where + " names no enum value");
        }
        case PropertyType::String: return AsString(value, where);
    }
    Malformed(where + " has no type");
}

PropertySpec ParseEntry(const json::Value& value, PropertyGroup group, MeshMapUsage usage, const std::string& where) {
    const json::Object& entry = AsObject(value, where);
    PropertySpec spec;
    spec.short_name = AsString(Member(entry, "short_name", where), where + ".short_name");
    const std::string at = where + " (" + spec.short_name + ")";
    spec.name = AsString(Member(entry, "name", at), at + ".name");
    spec.label = AsString(Member(entry, "label", at), at + ".label");
    spec.widget_type = AsString(Member(entry, "widget_type", at), at + ".widget_type");
    spec.type = TypeNamed(AsString(Member(entry, "type", at), at + ".type"), at);
    spec.usage = usage;
    if (group == PropertyGroup::Baker) {
        spec.group = group;
    } else if (spec.name.starts_with("Common.")) {
        spec.group = PropertyGroup::Common;
    } else if (spec.name.starts_with("Detail.")) {
        spec.group = PropertyGroup::Detail;
    } else {
        Malformed(at + ": a common() key's name starts with Common. or Detail.");
    }
    if (const auto it = entry.find("enum_values"); it != entry.end()) {
        for (const auto& [label, integer] : AsObject(it->second, at + ".enum_values")) {
            spec.enum_values.emplace_back(label, static_cast<int>(AsInt(integer, at + ".enum_values")));
        }
        std::sort(spec.enum_values.begin(), spec.enum_values.end(),
                  [](const auto& a, const auto& b) { return a.second < b.second; });
    }
    if ((spec.type == PropertyType::Enum) == spec.enum_values.empty()) {
        Malformed(at + ": enum_values belong to Enum keys only, and every Enum key has them");
    }
    if (const auto it = entry.find("range"); it != entry.end()) {
        const json::Object& range = AsObject(it->second, at + ".range");
        if (const auto min = range.find("min"); min != range.end()) spec.minimum = TableValue(spec, min->second, at + ".min");
        if (const auto max = range.find("max"); max != range.end()) spec.maximum = TableValue(spec, max->second, at + ".max");
    }
    const json::Value& default_value = Member(entry, "default", at);
    if (default_value.IsNull()) {
        spec.default_note = AsString(Member(entry, "default_note", at), at + ".default_note");
    } else {
        spec.default_value = TableValue(spec, default_value, at + ".default");
    }
    const json::Object& provenance = AsObject(Member(entry, "provenance", at), at + ".provenance");
    spec.record_sha256 = AsString(Member(provenance, "record_sha256", at), at + ".record_sha256");
    spec.output_id = AsString(Member(provenance, "output_id", at), at + ".output_id");
    return spec;
}

struct Catalog {
    std::vector<PropertySpec> specs;
    TextureSetBakeState state;
};

Catalog ParseCatalog(std::string_view text) {
    json::Value root;
    try {
        root = json::Parse(text);
    } catch (const json::ParseError& error) {
        Malformed(error.what());
    }
    const json::Object& table = AsObject(root, "the table");
    if (AsString(Member(table, "schema", "the table"), "schema") != "uzpainter/baking-defaults/1") {
        Malformed("unknown schema");
    }
    Catalog catalog;
    for (const json::Value& entry : AsArray(Member(table, "common", "the table"), "common")) {
        catalog.specs.push_back(ParseEntry(entry, PropertyGroup::Common, MeshMapUsage::AO, "common"));
    }
    const json::Object& bakers = AsObject(Member(table, "bakers", "the table"), "bakers");
    if (bakers.size() != std::size(kUsages)) Malformed("bakers names every MeshMapUsage once");
    for (MeshMapUsage usage : kUsages) {
        const std::string where = std::string("bakers.") + UsageName(usage);
        for (const json::Value& entry : AsArray(Member(bakers, UsageName(usage), "bakers"), where)) {
            catalog.specs.push_back(ParseEntry(entry, PropertyGroup::Baker, usage, where));
        }
    }
    const json::Object& state = AsObject(Member(table, "texture_set_state", "the table"), "texture_set_state");
    const auto state_default = [&](const char* key) -> const json::Value& {
        return Member(AsObject(Member(state, key, "texture_set_state"), key), "default", key);
    };
    catalog.state.curvature_method = AsString(state_default("curvature_method"), "curvature_method");
    for (const json::Value& baker : AsArray(state_default("enabled_bakers"), "enabled_bakers")) {
        catalog.state.enabled_bakers.push_back(AsString(baker, "enabled_bakers"));
    }
    const json::Value& enabled = state_default("textureset_enabled");
    if (!enabled.IsBool()) Malformed("textureset_enabled is not a bool");
    catalog.state.textureset_enabled = std::get<bool>(enabled.data);
    return catalog;
}

const Catalog& TheCatalog() {
    static const Catalog catalog = ParseCatalog(BakingDefaultsText());
    return catalog;
}

std::string Owner(MeshMapUsage usage) { return UsageOwnerTask(usage); }

void RefuseOtherUsage(MeshMapUsage usage, const std::string& what) {
    if (usage != MeshMapUsage::AO) {
        throw NotYetSupported(what + " of " + UsageName(usage) + " (owned by " + Owner(usage) + ")");
    }
}

void RefuseUnstored(MeshMapUsage usage, const std::string& what) {
    if (!StoresBakerValues(usage)) {
        throw NotYetSupported(what + " of " + UsageName(usage) + " (owned by " + Owner(usage) + ")");
    }
}

}  // namespace

bool StoresBakerValues(MeshMapUsage usage) {
    return usage == MeshMapUsage::AO || usage == MeshMapUsage::Position || usage == MeshMapUsage::ID;
}

const std::vector<PropertySpec>& PropertySpecs() { return TheCatalog().specs; }

const TextureSetBakeState& DefaultTextureSetState() { return TheCatalog().state; }

/// One copy of a group of parameters: a texture set's own, or a link group's shared one.
struct ParameterSlot {
    std::map<std::string, PropertyValue> values;
};

struct ParameterStore {
    std::string texture_set;
    std::shared_ptr<ParameterSlot> common = std::make_shared<ParameterSlot>();  // common and detail keys
    std::shared_ptr<ParameterSlot> ao = std::make_shared<ParameterSlot>();
    /// The set's own values of the other stored bakers (decision 337): never in a link group.
    std::shared_ptr<ParameterSlot> position = std::make_shared<ParameterSlot>();
    std::shared_ptr<ParameterSlot> id = std::make_shared<ParameterSlot>();
    /// Shared by the texture sets of one session; null for a set outside a session.
    std::shared_ptr<std::uint64_t> revision;

    /// The slot holding `spec`'s values; null for a baker whose values are not stored.
    ParameterSlot* SlotOf(const PropertySpec& spec) const {
        if (spec.group != PropertyGroup::Baker) return common.get();
        switch (spec.usage) {
            case MeshMapUsage::AO: return ao.get();
            case MeshMapUsage::Position: return position.get();
            case MeshMapUsage::ID: return id.get();
            default: return nullptr;
        }
    }
};

// ── Property ─────────────────────────────────────────────────────────────────────────────────

const std::string& Property::short_name() const { return spec_->short_name; }
PropertyType Property::type() const { return spec_->type; }
PropertyGroup Property::group() const { return spec_->group; }
const std::string& Property::name() const { return spec_->name; }
const std::string& Property::label() const { return spec_->label; }
const std::string& Property::widget_type() const { return spec_->widget_type; }

PropertyValue Property::value() const {
    if (const ParameterSlot* slot = store_->SlotOf(*spec_)) {
        const auto it = slot->values.find(spec_->short_name);
        if (it != slot->values.end()) return it->second;
    }
    if (spec_->default_value) return *spec_->default_value;
    throw NotYetSupported("the default of " + spec_->short_name + " is not established: " + spec_->default_note +
                          " (decision 323)");
}

std::map<std::string, int> Property::enum_values() const {
    return {spec_->enum_values.begin(), spec_->enum_values.end()};
}

int Property::enum_value(const std::string& enum_label) const {
    for (const auto& [label, integer] : spec_->enum_values) {
        if (label == enum_label) return integer;
    }
    throw ValueError(spec_->short_name + " has no enum value '" + enum_label + "'");
}

std::string Property::properties() const {
    throw NotYetSupported("the meta properties of " + spec_->short_name +
                          " carry Painter's descriptive text, which UzPainter does not reproduce (clean room; "
                          "decision 323)");
}

// ── BakingParameters ─────────────────────────────────────────────────────────────────────────

BakingParameters::BakingParameters(std::string texture_set) : store_(std::make_shared<ParameterStore>()) {
    store_->texture_set = std::move(texture_set);
}

const std::string& BakingParameters::texture_set() const { return store_->texture_set; }

std::map<std::string, Property> BakingParameters::common() const {
    std::map<std::string, Property> out;
    for (const PropertySpec& spec : PropertySpecs()) {
        if (spec.group != PropertyGroup::Baker) out.emplace(spec.short_name, Property(store_, &spec));
    }
    return out;
}

std::map<std::string, Property> BakingParameters::baker(MeshMapUsage usage) const {
    std::map<std::string, Property> out;
    for (const PropertySpec& spec : PropertySpecs()) {
        if (spec.group == PropertyGroup::Baker && spec.usage == usage) out.emplace(spec.short_name, Property(store_, &spec));
    }
    return out;
}

namespace {

std::string Text(const PropertyValue& value) {
    if (const auto* i = std::get_if<std::int64_t>(&value)) return std::to_string(*i);
    if (const auto* d = std::get_if<double>(&value)) return json::FormatDouble(*d);
    if (const auto* p = std::get_if<std::pair<std::int64_t, std::int64_t>>(&value)) {
        return "[" + std::to_string(p->first) + ", " + std::to_string(p->second) + "]";
    }
    return "the value";
}

/// `value` inside `spec`'s range, component by component for a pair.
void CheckRange(const PropertySpec& spec, const PropertyValue& value) {
    const auto below = [](const PropertyValue& v, const PropertyValue& bound) {
        if (const auto* i = std::get_if<std::int64_t>(&v)) return *i < std::get<std::int64_t>(bound);
        if (const auto* d = std::get_if<double>(&v)) return *d < std::get<double>(bound);
        const auto& p = std::get<std::pair<std::int64_t, std::int64_t>>(v);
        const auto& b = std::get<std::pair<std::int64_t, std::int64_t>>(bound);
        return p.first < b.first || p.second < b.second;
    };
    const bool low = spec.minimum && below(value, *spec.minimum);
    const bool high = spec.maximum && below(*spec.maximum, value);
    if (low || high) {
        throw NotYetSupported(spec.short_name + " = " + Text(value) + " lies outside Painter's range [" +
                              (spec.minimum ? Text(*spec.minimum) : std::string("-inf")) + ", " +
                              (spec.maximum ? Text(*spec.maximum) : std::string("inf")) +
                              "]; how Painter treats such a value is not recorded (decision 323)");
    }
}

/// The value `value` takes in the store for `spec`, or the refusal.
PropertyValue Checked(const PropertySpec& spec, const PropertyValue& value) {
    const std::string& key = spec.short_name;
    const auto wrong = [&] { return ValueError(key + " takes a " + PropertyTypeName(spec.type) + " value"); };
    switch (spec.type) {
        case PropertyType::Bool:
            if (!std::holds_alternative<bool>(value)) throw wrong();
            return value;
        case PropertyType::Int:
            if (!std::holds_alternative<std::int64_t>(value)) throw wrong();
            CheckRange(spec, value);
            return value;
        case PropertyType::Float: {
            double number = 0.0;
            if (const auto* d = std::get_if<double>(&value)) {
                number = *d;
            } else if (const auto* i = std::get_if<std::int64_t>(&value)) {
                number = static_cast<double>(*i);
            } else {
                throw wrong();
            }
            if (!std::isfinite(number)) throw ValueError(key + " takes a finite number");
            CheckRange(spec, number);
            return number;
        }
        case PropertyType::IntPair:
            if (!std::holds_alternative<std::pair<std::int64_t, std::int64_t>>(value)) throw wrong();
            CheckRange(spec, value);
            return value;
        case PropertyType::FloatPair: {
            const auto* pair = std::get_if<std::pair<double, double>>(&value);
            if (!pair) throw wrong();
            if (!std::isfinite(pair->first) || !std::isfinite(pair->second)) throw ValueError(key + " takes finite numbers");
            return value;
        }
        case PropertyType::Enum: {
            const auto* label = std::get_if<EnumLabel>(&value);
            if (!label) throw wrong();
            for (const auto& [known, integer] : spec.enum_values) {
                if (known == label->label) return value;
            }
            throw ValueError(key + " has no enum value '" + label->label + "'");
        }
        case PropertyType::String:
            if (!std::holds_alternative<std::string>(value)) throw wrong();
            return value;
    }
    throw wrong();
}

/// Advances each distinct session revision once.
void Advance(const std::vector<const ParameterStore*>& stores) {
    std::set<std::uint64_t*> seen;
    for (const ParameterStore* store : stores) {
        if (store->revision && seen.insert(store->revision.get()).second) ++*store->revision;
    }
}

}  // namespace

void BakingParameters::set(const std::vector<std::pair<Property, PropertyValue>>& values) {
    std::vector<PropertyValue> checked;
    checked.reserve(values.size());
    // A linked group's sets share one slot: a key named twice in one slot is one parameter set twice.
    std::set<std::pair<const ParameterSlot*, std::string>> seen;
    for (const auto& [property, value] : values) {
        const PropertySpec& spec = *property.spec_;
        if (spec.group == PropertyGroup::Baker) RefuseUnstored(spec.usage, "storing the bake parameters");
        const ParameterSlot* slot = property.store_->SlotOf(spec);
        if (!seen.emplace(slot, spec.short_name).second) {
            throw ValueError(spec.short_name + " of texture set '" + property.store_->texture_set +
                             "' appears twice in one set() (directly or through a link group)");
        }
        checked.push_back(Checked(spec, value));
    }
    std::vector<const ParameterStore*> stores;
    for (std::size_t i = 0; i < values.size(); ++i) {
        const Property& property = values[i].first;
        property.store_->SlotOf(*property.spec_)->values[property.spec_->short_name] = std::move(checked[i]);
        stores.push_back(property.store_.get());
    }
    Advance(stores);
}

// ── BakingSession ────────────────────────────────────────────────────────────────────────────

BakingSession::BakingSession(std::vector<std::string> texture_sets)
    : names_(std::move(texture_sets)), revision_(std::make_shared<std::uint64_t>(0)) {
    std::set<std::string> unique(names_.begin(), names_.end());
    if (unique.size() != names_.size()) throw ValueError("a session's texture sets need distinct names");
    for (const std::string& name : names_) {
        auto store = std::make_shared<ParameterStore>();
        store->texture_set = name;
        store->revision = revision_;
        stores_.push_back(std::move(store));
    }
    if (names_.size() >= 2) {
        const auto shared = std::make_shared<ParameterSlot>();
        for (const auto& store : stores_) store->common = shared;
        common_group_ = names_;
    }
}

std::size_t BakingSession::IndexOf(const std::string& texture_set) const {
    const auto it = std::find(names_.begin(), names_.end(), texture_set);
    if (it == names_.end()) throw ValueError("the project has no texture set '" + texture_set + "'");
    return static_cast<std::size_t>(it - names_.begin());
}

BakingParameters BakingSession::parameters(const std::string& texture_set) const {
    return BakingParameters(stores_[IndexOf(texture_set)]);
}

std::uint64_t BakingSession::revision() const { return *revision_; }

void BakingSession::Link(const std::vector<std::string>& group, const std::string& reference, Slot slot) {
    std::set<std::size_t> members;
    for (const std::string& name : group) {
        if (!members.insert(IndexOf(name)).second) {
            throw ValueError("texture set '" + name + "' appears twice in the group");
        }
    }
    const std::size_t ref = IndexOf(reference);
    if (!members.count(ref)) {
        throw NotYetSupported("linking with the reference '" + reference +
                              "' outside the group is not established (decision 311)");
    }
    if (members.size() < 2) {
        throw NotYetSupported("a link group of fewer than two texture sets is not established (decision 311)");
    }
    std::vector<std::string> ordered;
    for (std::size_t i : members) ordered.push_back(names_[i]);
    std::vector<std::string>& current = GroupOf(slot);
    if (!current.empty() && current != ordered) {
        throw NotYetSupported(
            "regrouping: another group is already linked for these parameters, and how Painter replaces "
            "it is not established (unlink_all first; decision 311)");
    }
    const ParameterStore& source = *stores_[ref];
    const auto shared = std::make_shared<ParameterSlot>(slot == Slot::Ao ? *source.ao : *source.common);
    for (std::size_t i : members) (slot == Slot::Ao ? stores_[i]->ao : stores_[i]->common) = shared;
    current = std::move(ordered);
    ++*revision_;
}

void BakingSession::Unlink(Slot slot) {
    std::vector<std::string>& current = GroupOf(slot);
    if (current.empty()) return;
    for (const std::string& name : current) {
        std::shared_ptr<ParameterSlot>& own = slot == Slot::Ao ? stores_[IndexOf(name)]->ao : stores_[IndexOf(name)]->common;
        own = std::make_shared<ParameterSlot>(*own);
    }
    current.clear();
    ++*revision_;
}

void BakingSession::set_linked_group(const std::vector<std::string>& group, const std::string& reference,
                                     MeshMapUsage usage) {
    RefuseOtherUsage(usage, "a link group of the bake parameters");
    Link(group, reference, Slot::Ao);
}

void BakingSession::set_linked_group_common_parameters(const std::vector<std::string>& group,
                                                       const std::string& reference) {
    Link(group, reference, Slot::Common);
}

void BakingSession::unlink_all(MeshMapUsage usage) {
    RefuseOtherUsage(usage, "the link group of the bake parameters");
    Unlink(Slot::Ao);
}

void BakingSession::unlink_all_common_parameters() { Unlink(Slot::Common); }

std::vector<std::string> BakingSession::get_link_group(MeshMapUsage usage) const {
    RefuseOtherUsage(usage, "the link group of the bake parameters");
    return ao_group_;
}

std::vector<std::string> BakingSession::get_link_group_common_parameters() const { return common_group_; }

std::vector<std::string> BakingSession::Linked(const std::string& texture_set, Slot slot) const {
    IndexOf(texture_set);
    const std::vector<std::string>& group = GroupOf(slot);
    if (std::find(group.begin(), group.end(), texture_set) != group.end()) return group;
    return {texture_set};
}

std::vector<std::string> BakingSession::get_linked_texture_sets(const std::string& texture_set,
                                                                MeshMapUsage usage) const {
    RefuseOtherUsage(usage, "the link group of the bake parameters");
    return Linked(texture_set, Slot::Ao);
}

std::vector<std::string> BakingSession::get_linked_texture_sets_common_parameters(const std::string& texture_set) const {
    return Linked(texture_set, Slot::Common);
}

// ── The manifest's bake_settings ─────────────────────────────────────────────────────────────

namespace {

json::Value ToJson(const PropertySpec& spec, const PropertyValue& value) {
    switch (spec.type) {
        case PropertyType::Bool: return std::get<bool>(value);
        case PropertyType::Int: return std::get<std::int64_t>(value);
        case PropertyType::Float: return std::get<double>(value);
        case PropertyType::IntPair: {
            const auto& pair = std::get<std::pair<std::int64_t, std::int64_t>>(value);
            return json::Array{pair.first, pair.second};
        }
        case PropertyType::FloatPair: {
            const auto& pair = std::get<std::pair<double, double>>(value);
            return json::Array{pair.first, pair.second};
        }
        case PropertyType::Enum: return std::get<EnumLabel>(value).label;
        case PropertyType::String: return std::get<std::string>(value);
    }
    throw std::logic_error("a property of no type");
}

PropertyValue FromJson(const PropertySpec& spec, const json::Value& value, const std::string& where) {
    const auto wrong = [&] {
        return ValueError(where + "." + spec.short_name + " is not a " + PropertyTypeName(spec.type) + " value");
    };
    const auto number = [&](const json::Value& v) {
        if (v.IsInt()) return static_cast<double>(std::get<std::int64_t>(v.data));
        if (v.IsDouble()) return std::get<double>(v.data);
        throw wrong();
    };
    switch (spec.type) {
        case PropertyType::Bool:
            if (!value.IsBool()) throw wrong();
            return std::get<bool>(value.data);
        case PropertyType::Int:
            if (!value.IsInt()) throw wrong();
            return std::get<std::int64_t>(value.data);
        case PropertyType::Float: return number(value);
        case PropertyType::IntPair: {
            if (!value.IsArray()) throw wrong();
            const auto& array = std::get<json::Array>(value.data);
            if (array.size() != 2 || !array[0].IsInt() || !array[1].IsInt()) throw wrong();
            return std::pair<std::int64_t, std::int64_t>{std::get<std::int64_t>(array[0].data),
                                                         std::get<std::int64_t>(array[1].data)};
        }
        case PropertyType::FloatPair: {
            if (!value.IsArray()) throw wrong();
            const auto& array = std::get<json::Array>(value.data);
            if (array.size() != 2) throw wrong();
            return std::pair<double, double>{number(array[0]), number(array[1])};
        }
        case PropertyType::Enum:
            if (!value.IsString()) throw wrong();
            return EnumLabel{std::get<std::string>(value.data)};
        case PropertyType::String:
            if (!value.IsString()) throw wrong();
            return std::get<std::string>(value.data);
    }
    throw wrong();
}

const PropertySpec* SpecOf(const std::string& key, PropertyGroup group, MeshMapUsage usage) {
    for (const PropertySpec& spec : PropertySpecs()) {
        if (spec.short_name != key) continue;
        if (group == PropertyGroup::Baker ? spec.group == group && spec.usage == usage : spec.group == group) {
            return &spec;
        }
    }
    return nullptr;
}

}  // namespace

core::BakeSettings ToBakeSettings(const BakingParameters& parameters) {
    core::BakeSettings out;
    const ParameterStore& store = *parameters.store_;
    for (const PropertySpec& spec : PropertySpecs()) {
        const ParameterSlot* slot = store.SlotOf(spec);
        if (!slot) continue;
        const auto it = slot->values.find(spec.short_name);
        if (it == slot->values.end()) continue;
        json::Value value = ToJson(spec, it->second);
        switch (spec.group) {
            case PropertyGroup::Common: out.common[spec.short_name] = std::move(value); break;
            case PropertyGroup::Detail: out.detail[spec.short_name] = std::move(value); break;
            case PropertyGroup::Baker: out.per_baker[UsageName(spec.usage)][spec.short_name] = std::move(value); break;
        }
    }
    return out;
}

void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings) {
    ParameterSlot common, ao, position, id;
    const auto load = [](const json::Object& object, PropertyGroup group, MeshMapUsage usage, const std::string& where,
                         ParameterSlot& into) {
        for (const auto& [key, value] : object) {
            const PropertySpec* spec = SpecOf(key, group, usage);
            if (!spec) throw ValueError(where + " has no key '" + key + "'");
            into.values[key] = Checked(*spec, FromJson(*spec, value, where));
        }
    };
    load(settings.common, PropertyGroup::Common, MeshMapUsage::AO, "bake_settings.common", common);
    load(settings.detail, PropertyGroup::Detail, MeshMapUsage::AO, "bake_settings.detail", common);
    for (const auto& [baker, object] : settings.per_baker) {
        bool known = false;
        for (MeshMapUsage usage : kUsages) {
            if (baker != UsageName(usage)) continue;
            known = true;
            const std::string where = "bake_settings.per_baker." + baker;
            if (usage == MeshMapUsage::AO) {
                load(object, PropertyGroup::Baker, usage, where, ao);
            } else if (usage == MeshMapUsage::Position) {
                load(object, PropertyGroup::Baker, usage, where, position);
            } else if (usage == MeshMapUsage::ID) {
                load(object, PropertyGroup::Baker, usage, where, id);
            } else if (!object.empty()) {
                RefuseUnstored(usage, "the bake parameters");
            }
        }
        if (!known) throw ValueError("bake_settings.per_baker has no baker '" + baker + "'");
    }
    ParameterStore& store = *parameters.store_;
    store.common->values = std::move(common.values);
    store.ao->values = std::move(ao.values);
    store.position->values = std::move(position.values);
    store.id->values = std::move(id.values);
    Advance({&store});
}

// ── Parameters to a request ──────────────────────────────────────────────────────────────────

MappedRequest RequestFromParameters(const BakingParameters& parameters, BakeRequest base) {
    const std::map<std::string, Property> common = parameters.common();
    const auto value = [&](const std::map<std::string, Property>& group, const char* key) {
        return group.at(key).value();
    };
    const auto label = [&](const std::map<std::string, Property>& group, const char* key) {
        return std::get<EnumLabel>(value(group, key)).label;
    };
    const auto boolean = [&](const std::map<std::string, Property>& group, const char* key) {
        return std::get<bool>(value(group, key));
    };
    const auto text = [&](const std::map<std::string, Property>& group, const char* key) {
        return std::get<std::string>(value(group, key));
    };
    const auto real = [&](const std::map<std::string, Property>& group, const char* key) {
        return static_cast<float>(std::get<double>(value(group, key)));
    };
    const auto only = [&](const std::map<std::string, Property>& group, const char* key, const char* implemented,
                          const std::string& owner) {
        const std::string given = label(group, key);
        if (given != implemented) {
            throw NotYetSupported(std::string(key) + " '" + given + "': the CPU baker implements only '" + implemented +
                                  "' (" + owner + ")");
        }
    };
    MappedRequest out;
    BakeRequest& r = base;
    r.texture_set = parameters.texture_set();
    const auto size = std::get<std::pair<std::int64_t, std::int64_t>>(value(common, "OutputSize"));
    r.output_size_log2[0] = static_cast<std::uint32_t>(size.first);
    r.output_size_log2[1] = static_cast<std::uint32_t>(size.second);
    r.common.dilation_width = static_cast<std::uint32_t>(std::get<std::int64_t>(value(common, "DilationWidth")));
    r.common.apply_diffusion = boolean(common, "ApplyDiffusion");
    r.detail.low_as_high = boolean(common, "LowAsHigh");
    const std::string cage = label(common, "CageMode");
    r.detail.cage_mode = cage == "Distance-based"             ? CageMode::DistanceBased
                         : cage == "Automatic (experimental)" ? CageMode::Automatic
                                                              : CageMode::CustomFile;
    r.detail.max_height = real(common, "MaxHeight");
    r.detail.max_depth = real(common, "MaxDepth");
    r.detail.relative_to_bounding_box = boolean(common, "RelativeScale");
    r.detail.ignore_backface = boolean(common, "IgnoreBackface");
    r.detail.filter_method = label(common, "FilterMethod") == "Always" ? FilterMethod::Always : FilterMethod::ByMeshName;
    r.detail.low_suffix = text(common, "LowpolySuffix");
    r.detail.high_suffix = text(common, "HipolySuffix");
    r.detail.ignore_backface_suffix = text(common, "BackfaceCullingSuffix");
    const std::string sub = label(common, "SubSampling");
    r.detail.subsampling = sub == "None"              ? 1u
                           : sub == "Subsampling 2x2" ? 2u
                           : sub == "Subsampling 4x4" ? 4u
                                                      : 8u;
    if (!text(common, "OffsetMap").empty()) {
        throw NotYetSupported("OffsetMap: the per-texel cage offset is not implemented (phase3.5_embree-bakers)");
    }
    out.keys_not_read = {"SmoothNormals", "SkewFaceBehavior"};
    if (std::find(r.usages.begin(), r.usages.end(), MeshMapUsage::AO) != r.usages.end()) {
        const std::map<std::string, Property> ao = parameters.baker(MeshMapUsage::AO);
        const std::string owner = UsageOwnerTask(MeshMapUsage::AO);
        if (boolean(ao, "GroundPlane")) {
            throw NotYetSupported("GroundPlane: the AO ground plane is not implemented (" + owner + ")");
        }
        only(ao, "Attenuation", "None", owner);
        only(ao, "IgnoreBackfaceSecondary", "Never", owner);
        only(ao, "FilterMethodSecondary", "Always", owner);
        if (std::get<double>(value(ao, "Spread")) != 180.0) {
            throw NotYetSupported("Spread: the CPU baker casts over the whole hemisphere only, 180 degrees (" + owner + ")");
        }
        r.ao.secondary_rays = static_cast<std::uint32_t>(std::get<std::int64_t>(value(ao, "NbSecondary")));
        r.ao.min_distance = real(ao, "MinDistance");
        r.ao.max_distance = real(ao, "MaxDistance");
        r.ao.relative_to_bounding_box = boolean(ao, "MaxDistanceRelativeScale");
        r.ao.distribution = label(ao, "Distribution") == "Cosine" ? Distribution::Cosine : Distribution::Uniform;
    }
    if (std::find(r.usages.begin(), r.usages.end(), MeshMapUsage::Position) != r.usages.end()) {
        // Every label maps; the baker refuses the values it does not establish (decision 337).
        const std::map<std::string, Property> position = parameters.baker(MeshMapUsage::Position);
        r.position.mode = label(position, "Mode") == "All axis" ? PositionMode::AllAxis : PositionMode::OneAxis;
        const std::string axis = label(position, "Axis");
        r.position.axis = axis == "X" ? PositionAxis::X : axis == "Y" ? PositionAxis::Y : PositionAxis::Z;
        const std::string normalization = label(position, "Normalization");
        r.position.normalization = normalization == "BBox"      ? PositionNormalization::BBox
                                   : normalization == "BSphere" ? PositionNormalization::BSphere
                                                                : PositionNormalization::None;
        r.position.scale = label(position, "NormalizationScale") == "Per Material"
                               ? PositionNormalizationScale::PerMaterial
                               : PositionNormalizationScale::FullScene;
    }
    if (std::find(r.usages.begin(), r.usages.end(), MeshMapUsage::ID) != r.usages.end()) {
        // Both labels map, the generator always; the baker refuses what it does not establish.
        const std::map<std::string, Property> id = parameters.baker(MeshMapUsage::ID);
        const std::string source = label(id, "ColorSource");
        r.id.source = source == "Vertex color"          ? IdColorSource::VertexColor
                      : source == "Material color"      ? IdColorSource::MaterialColor
                      : source == "File ID"             ? IdColorSource::FileId
                      : source == "Mesh ID / Polygroup" ? IdColorSource::MeshId
                                                        : IdColorSource::Submesh;
        const std::string generator = label(id, "ColorGenerator");
        r.id.generator = generator == "Random"      ? IdColorGenerator::Random
                         : generator == "Hue shift" ? IdColorGenerator::HueShift
                                                    : IdColorGenerator::Grayscale;
    }
    out.request = std::move(r);
    return out;
}

}  // namespace uzp::bake
