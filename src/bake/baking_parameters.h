#pragma once

// The bake parameter model (phase3.1_baker-request-model item 2.8; `docs/architecture/06-baking.md`
// §2; decision 306), shaped like Painter's documented `BakingParameters` and `Property`
// (`substance_painter.baking`, `substance_painter.properties`): `common()` (common and detail
// keys), `baker(usage)`, `set({Property: value})` and the `Property` accessors.
//
// Only what an admitted source states is answered:
// - the keys are the Painter short names `06-baking.md` §2 lists;
// - labels and option labels come from Adobe's public mesh-map settings page (approved source
//   A-HELP-BAKING) and Painter's public Python API page (the `Distribution` example);
// - the value type comes only from the page's widget (a checkbox is a `Bool`, a dropdown an
//   `Enum`) or from the task's own listing (the `OutputSize` log2 pair, `DilationWidth` in texels,
//   the file-URL list, the suffix strings); a type that only the meaning of a key suggests (a ray
//   count, a distance, an angle) stays `Pending` (decision 306);
// - the only defaults are the three suffixes `06-baking.md` §2 lists.
// Everything else (Painter's `name()`, `widget_type()`, enum integers, ranges, `properties()`,
// the remaining defaults and value types) comes from the Tier 0 discovery capture on the owner's
// machine (items 2.8, 2.9 and 3.1) and raises `uzp::core::NotYetSupported` naming that item,
// never a guess. Descriptions are UzmiGames' own words.

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "bake/bake_request.h"

namespace uzp::bake {

enum class PropertyGroup { Common, Detail, Ao };

/// `Pending`: no admitted source states the value type yet; the property cannot be set.
/// Painter's float values have no established key yet, so no `Float` type is modelled.
enum class PropertyType { Bool, Int, IntPair, Enum, String, Pending };

const char* PropertyTypeName(PropertyType type);

/// An `Enum` value, given by its documented option label.
struct EnumLabel {
    std::string label;
    bool operator==(const EnumLabel&) const = default;
};

using PropertyValue =
    std::variant<bool, std::int64_t, std::pair<std::int64_t, std::int64_t>, double, EnumLabel, std::string>;

struct PropertySpec {
    std::string short_name;
    PropertyGroup group;
    PropertyType type;
    /// The label on Adobe's public mesh-map settings page; empty when the page does not state it.
    std::string label;
    /// `Enum`: the option labels an admitted source documents.
    std::vector<std::string> option_labels;
    /// True when the source lists every option; false when only some are documented.
    bool options_complete = false;
    /// A default an admitted source states; empty when only the private capture knows it.
    std::optional<PropertyValue> default_value;
    std::string default_source;
    /// Where the key, label, type and options come from.
    std::string source;
    /// UzmiGames' own words.
    std::string description;
};

/// Every modelled key: common, detail and AO, in that order.
const std::vector<PropertySpec>& PropertySpecs();

struct ParameterStore;

/// A handle to one parameter of one texture set's `BakingParameters`.
class Property {
public:
    const std::string& short_name() const;
    PropertyType type() const;
    PropertyGroup group() const;
    const std::string& description() const;
    /// The documented option labels of an `Enum` (possibly a partial list, see `spec()`).
    const std::vector<std::string>& documented_option_labels() const;
    const PropertySpec& spec() const { return *spec_; }

    /// The value set through `BakingParameters::set`, else the documented default, else
    /// `NotYetSupported` (item 2.9).
    PropertyValue value() const;
    /// `NotYetSupported` when the public page does not state the label.
    std::string label() const;
    /// Painter's full name, widget type, enum integers and meta properties: `NotYetSupported`
    /// until the Tier 0 discovery goldens (items 2.8 and 3.1).
    std::string name() const;
    std::string widget_type() const;
    std::map<std::string, int> enum_values() const;
    int enum_value(const std::string& enum_label) const;
    std::string properties() const;

private:
    friend class BakingParameters;
    Property(std::shared_ptr<ParameterStore> store, const PropertySpec* spec)
        : store_(std::move(store)), spec_(spec) {}
    std::shared_ptr<ParameterStore> store_;
    const PropertySpec* spec_;
};

/// One texture set's bake parameters.
class BakingParameters {
public:
    explicit BakingParameters(std::string texture_set);
    const std::string& texture_set() const;
    /// The common and detail parameters.
    std::map<std::string, Property> common() const;
    /// The parameters of `usage`: AO's; every other usage raises `NotYetSupported` naming its
    /// owner baker task.
    std::map<std::string, Property> baker(MeshMapUsage usage) const;
    /// Sets the values in one transaction: every value is checked first, and one failure
    /// (`ValueError`, or `NotYetSupported` for a pending type or an undocumented option) leaves
    /// every parameter, of every texture set in the batch, unchanged.
    static void set(const std::vector<std::pair<Property, PropertyValue>>& values);

private:
    std::shared_ptr<ParameterStore> store_;
};

}  // namespace uzp::bake
