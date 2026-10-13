#pragma once

// Project templates (docs/architecture/03-project-model.md §2, 04-layer-stack-and-compositing.md
// §2 step 1): the channel set, the `ChannelFormat` of each channel and the stack base value of
// each channel, per template shipped with Painter 12.1.0 and for the project created with no
// template ("default"), plus the base values of channels added to a stack afterwards
// ("channel-defaults"). Authored by UzmiGames in `assets/templates/*.json`, each entry with a
// provenance record (`src/evaluator/EVALUATOR.md` §3); checked against the private Tier 0
// captures in a local run on the owner's machine (tests/evaluator/test_compositor_tile_dag.py).
//
// A base value is a float32 constant per component: the value an empty channel evaluates to and
// the backdrop of the first layer. It is not a stored code of the channel: Painter's empty
// channels export values that no channel code produces (the BaseColor of the shipped templates,
// the flat normal float32(127/255) of an RGB16F Normal channel).

#include <array>
#include <filesystem>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "render/backend.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// The template file schema.
inline constexpr std::string_view kTemplateSchema = "uzpainter/template/1";
/// The id of the project created with no template.
inline constexpr std::string_view kDefaultTemplateId = "default";
/// The id of the channel-defaults table.
inline constexpr std::string_view kChannelDefaultsId = "channel-defaults";

struct TemplateChannel {
    core::ChannelType type = core::ChannelType::BaseColor;
    /// Absent in a channel-defaults entry that applies to any format; present in one that applies
    /// to that format only (its base is recorded on that format alone; the type may have one such
    /// entry per format).
    std::optional<core::ChannelFormat> format;
    std::array<float, 3> base{0.0f, 0.0f, 0.0f};
    /// "observed", "fitted", "inferred" or "unobserved" (EVALUATOR.md §3).
    std::string baseProvenance;
    core::json::Object provenanceRecord;
};

struct ProjectTemplate {
    std::string id;
    std::string name;
    /// The shipped `.spt` path the template reproduces; absent for "default" and the defaults.
    std::optional<std::string> painterTemplate;
    /// The texture set resolution a project created from the template gets when its settings name
    /// none (Painter's template capture); absent = the project default, 1024.
    std::optional<int> defaultResolution;
    bool channelDefaults = false;
    std::vector<TemplateChannel> channels;
    core::json::Object provenance;

    [[nodiscard]] const TemplateChannel* Find(core::ChannelType type) const;
    /// The stack channels a project created from this template starts with.
    [[nodiscard]] std::map<core::ChannelType, core::Channel> StackChannels() const;
};

class TemplateLibrary {
public:
    /// Reads every `*.json` of `directory`. Throws `core::ManifestError` (the JSON path in the
    /// message) for a malformed file, a duplicate id, a missing "default" template or a missing
    /// channel-defaults table.
    static TemplateLibrary Load(const std::filesystem::path& directory);
    /// `assets/templates` beside the running executable.
    [[nodiscard]] static std::filesystem::path DefaultDirectory();

    [[nodiscard]] const ProjectTemplate* Find(std::string_view id) const;
    [[nodiscard]] std::vector<std::string> Ids() const;
    [[nodiscard]] const ProjectTemplate& ChannelDefaults() const { return defaults_; }

    /// The entry giving the base value of channel `type` stored as `format` in a stack created
    /// from `templateId`: the template's entry when it lists the channel, else the channel default
    /// for any format or for `format` (none for a format-restricted default when `format` is
    /// unknown). `evaluator:unknown_template` or `evaluator:missing_base_value` otherwise.
    [[nodiscard]] render::Result<const TemplateChannel*> BaseChannel(
        std::string_view templateId, core::ChannelType type,
        std::optional<core::ChannelFormat> format = std::nullopt) const;
    /// The base value of that entry (BaseChannel).
    [[nodiscard]] render::Result<std::array<float, 3>> BaseValue(
        std::string_view templateId, core::ChannelType type,
        std::optional<core::ChannelFormat> format = std::nullopt) const;

private:
    std::map<std::string, ProjectTemplate, std::less<>> templates_;
    ProjectTemplate defaults_;
};

/// Parses one template document (the public form of `assets/templates/*.json`). Throws
/// `core::ManifestError`.
[[nodiscard]] ProjectTemplate ParseTemplate(const core::json::Value& document, std::string_view path);

}  // namespace uzp::evaluator
