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
//
// Decision 311 adds the mapping to a `BakeRequest`, linked groups (`BakingSession`, the documented
// `substance_painter.baking` link functions) and the project manifest's `bake_settings`.

#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <variant>
#include <vector>

#include "bake/bake_request.h"
#include "uzp_core/types/project.h"

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
class BakingParameters;
class BakingSession;
core::BakeSettings ToBakeSettings(const BakingParameters& parameters);
void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings);

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
    /// every parameter, of every texture set in the batch, unchanged. A value set on a member of
    /// a link group is the whole group's (one parameter, so naming it twice is a `ValueError`).
    static void set(const std::vector<std::pair<Property, PropertyValue>>& values);

private:
    friend class BakingSession;
    friend core::BakeSettings ToBakeSettings(const BakingParameters& parameters);
    friend void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings);
    explicit BakingParameters(std::shared_ptr<ParameterStore> store) : store_(std::move(store)) {}
    std::shared_ptr<ParameterStore> store_;
};

/// The bake parameters of a project's texture sets and their link groups (`06-baking.md` section 3,
/// Painter's documented `set_linked_group*`, `unlink_all*`, `get_link_group*`,
/// `get_linked_texture_sets*`; decision 311). A linked group shares one copy of its parameters:
/// the common group the common and detail keys, a usage's group that usage's keys. Lists are in
/// texture set order. Only AO's group exists (every other usage names its owner baker task).
/// Every change is one transaction: it is checked whole first, and a refusal changes nothing and
/// leaves `revision()` where it was.
class BakingSession {
public:
    /// The project's texture sets, in order. With two or more, all start in the common group
    /// (the documented example: common parameters are shared "at project creation").
    explicit BakingSession(std::vector<std::string> texture_sets);

    const std::vector<std::string>& texture_sets() const { return names_; }
    /// `ValueError` for a texture set the session does not have.
    BakingParameters parameters(const std::string& texture_set) const;
    /// Advances once per accepted change (a `set()` on any of its sets, a link, an unlink or a
    /// load); never on a refusal.
    std::uint64_t revision() const;

    /// The group shares `reference`'s current parameters of `usage`. `ValueError` for an unknown
    /// or repeated texture set; `NotYetSupported` for a usage other than AO, a reference outside
    /// the group, fewer than two sets, or a different group already linked for the usage (how
    /// Painter regroups is not established: `unlink_all` first).
    void set_linked_group(const std::vector<std::string>& group, const std::string& reference, MeshMapUsage usage);
    void set_linked_group_common_parameters(const std::vector<std::string>& group, const std::string& reference);
    /// Every set of the group keeps its own copy of the group's current values.
    void unlink_all(MeshMapUsage usage);
    void unlink_all_common_parameters();
    /// Empty when no group exists.
    std::vector<std::string> get_link_group(MeshMapUsage usage) const;
    std::vector<std::string> get_link_group_common_parameters() const;
    /// The sets sharing `texture_set`'s parameters; at least `texture_set` itself.
    std::vector<std::string> get_linked_texture_sets(const std::string& texture_set, MeshMapUsage usage) const;
    std::vector<std::string> get_linked_texture_sets_common_parameters(const std::string& texture_set) const;

private:
    enum class Slot { Common, Ao };
    void Link(const std::vector<std::string>& group, const std::string& reference, Slot slot);
    void Unlink(Slot slot);
    std::vector<std::string>& GroupOf(Slot slot) { return slot == Slot::Common ? common_group_ : ao_group_; }
    const std::vector<std::string>& GroupOf(Slot slot) const {
        return slot == Slot::Common ? common_group_ : ao_group_;
    }
    std::vector<std::string> Linked(const std::string& texture_set, Slot slot) const;
    std::size_t IndexOf(const std::string& texture_set) const;

    std::vector<std::string> names_;
    std::vector<std::shared_ptr<ParameterStore>> stores_;
    std::vector<std::string> common_group_;
    std::vector<std::string> ao_group_;
    std::shared_ptr<std::uint64_t> revision_;
};

/// The values set on `parameters` (never a default) as the manifest's `bake_settings`: common
/// keys in `common`, detail keys in `detail`, AO keys in `per_baker["AO"]`, by Painter short
/// name; a `Bool` as a JSON bool, an `Int` as an integer, an `IntPair` as `[a, b]`, an `Enum` as
/// its option label and a `String` as a string.
core::BakeSettings ToBakeSettings(const BakingParameters& parameters);

/// Replaces `parameters`' values with `settings` (its `extra` is not read), as one transaction
/// checked like `set()`: an unknown key, a key in the wrong group, a wrong JSON type, a pending
/// type or a baker other than AO with values refuses the whole load. Loading a linked set loads
/// its group.
void LoadBakeSettings(const BakingParameters& parameters, const core::BakeSettings& settings);

/// A `BakeRequest` from `parameters` over `base` (decision 311). Every key with a known type that
/// maps to a request field must have a value (set, or documented): otherwise `NotYetSupported`
/// (item 2.9). Keys whose type is still pending keep the request's own field and are listed in
/// `keys_from_request`. The mesh inputs (`HipolyMesh`, `CageMesh`) are the mesh-input step's:
/// `base` carries the meshes. A set feature the baker does not implement (`GroundPlane` on) is
/// refused with `NotYetSupported`.
struct MappedRequest {
    BakeRequest request;
    std::vector<std::string> keys_from_request;
};
MappedRequest RequestFromParameters(const BakingParameters& parameters, BakeRequest base);

}  // namespace uzp::bake
