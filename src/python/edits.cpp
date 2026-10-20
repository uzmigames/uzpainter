// The native edits the `uzpainter` API and the typed MCP tools share (edits.h).

#include "python/edits.h"

#include <algorithm>
#include <fstream>
#include <iterator>

#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "mesh/mesh_import.h"
#include "python/display.h"
#include "python/errors.h"
#include "uzp_core/types/errors.h"

namespace uzp::python {

namespace {

std::string Lower(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return text;
}

/// Every fill of `layers` whose sources bind `sha256`, rebound to `replacement`; their uids.
void Rebind(std::vector<core::Layer>& layers, const std::string& sha256, const std::string& replacement,
            std::vector<core::Id>& nodes) {
    const auto rebind = [&](std::optional<core::FillContent>& fill, core::Id uid) {
        if (!fill) return;
        bool changed = false;
        const auto visit = [&](core::Source& source) {
            if (source.kind() != core::SourceKind::bitmap) return;
            auto& bitmap = std::get<core::BitmapSource>(source.value);
            if (bitmap.resource.sha256 != sha256) return;
            bitmap.resource.sha256 = replacement;
            changed = true;
        };
        for (auto& [channel, source] : fill->sources) visit(source);
        if (fill->mono_source) visit(*fill->mono_source);
        if (changed) nodes.push_back(uid);
    };
    for (core::Layer& layer : layers) {
        rebind(layer.fill, layer.uid);
        for (core::Effect& effect : layer.content_effects) rebind(effect.fill, effect.uid);
        if (layer.mask) {
            for (core::Effect& effect : layer.mask->effects) rebind(effect.fill, effect.uid);
        }
        Rebind(layer.children, sha256, replacement, nodes);
    }
}

}  // namespace

// ── Nodes ───────────────────────────────────────────────────────────────────────────────────────

void CheckChannel(bool mask, const ChannelArg& channel, core::Id uid) {
    if (mask && channel) {
        throw core::ValueError("node " + std::to_string(uid) + " is in a mask stack: its channel argument must be None");
    }
    if (!mask && !channel) ThrowEditionContext("node " + std::to_string(uid) + " is multichannel: give the channel");
}

core::FillContent& EditFill(core::Edit& edit, core::Id uid, bool* mask) {
    if (core::Layer* layer = core::FindLayer(edit.project(), uid)) {
        if (mask) *mask = false;
        if (layer->fill) return *layer->fill;
    } else if (core::Effect* effect = core::FindEffect(edit.project(), uid)) {
        if (mask) *mask = effect->mono_blending.has_value();
        if (effect->fill) return *effect->fill;
    } else {
        throw core::ValueError("stale handle: node " + std::to_string(uid) + " no longer exists");
    }
    throw core::ValueError("node " + std::to_string(uid) + " is not a fill");
}

core::Source& EditSource(core::Edit& edit, core::Id uid, const ChannelArg& channel, core::SourceKind kind) {
    bool mask = false;
    core::FillContent& fill = EditFill(edit, uid, &mask);
    CheckChannel(mask, channel, uid);
    core::Source* source = nullptr;
    if (!channel) {
        if (fill.mono_source) source = &*fill.mono_source;
    } else if (auto it = fill.sources.find(*channel); it != fill.sources.end()) {
        source = &it->second;
    }
    if (source == nullptr || source->kind() != kind) {
        throw core::ValueError("node " + std::to_string(uid) + " has no " + std::string(core::ToString(kind)) + " source" +
                               (channel ? " on " + std::string(core::ToString(*channel)) : std::string()));
    }
    return *source;
}

core::Blending& EditBlending(core::Edit& edit, core::Id uid, const ChannelArg& channel) {
    if (core::Layer* layer = core::FindLayer(edit.project(), uid)) {
        CheckChannel(false, channel, uid);
        return layer->blending[*channel];
    }
    core::Effect& effect = EditEffect(edit, uid);
    if (effect.mono_blending) {
        CheckChannel(true, channel, uid);
        return *effect.mono_blending;
    }
    CheckChannel(false, channel, uid);
    return effect.blending[*channel];
}

bool HasBlending(core::NodeType type) {
    return type != core::NodeType::AnchorPointEffect && type != core::NodeType::LevelsEffect;
}

std::string DefaultName(core::NodeType type) {
    switch (type) {
        case core::NodeType::FillLayer: return "Fill";
        case core::NodeType::PaintLayer: return "Layer";
        case core::NodeType::GroupLayer: return "Folder";
        case core::NodeType::InstanceLayer: return "Instance";
        case core::NodeType::FillEffect: return "Fill";
        case core::NodeType::PaintEffect: return "Paint";
        case core::NodeType::GeneratorEffect: return "Generator";
        case core::NodeType::FilterEffect: return "Filter";
        case core::NodeType::LevelsEffect: return "Levels";
        case core::NodeType::CompareMaskEffect: return "Compare mask";
        case core::NodeType::ColorSelectionEffect: return "Color Selection";
        case core::NodeType::AnchorPointEffect: return "Anchor Point";
    }
    return "Node";
}

core::NameScope ScopeOf(const core::Project& project, const core::InsertPosition& position) {
    switch (position.kind) {
        case core::InsertPosition::Kind::TopOfStack:
            return {position.texture_set, position.stack, core::kNoId, core::NodeStack::Substack};
        case core::InsertPosition::Kind::InsideNode: {
            const NodeInfo info = Resolve(project, position.node);
            return {info.texture_set, info.stack, position.node, position.node_stack};
        }
        case core::InsertPosition::Kind::AboveNode:
        case core::InsertPosition::Kind::BelowNode: {
            const NodeInfo info = Resolve(project, position.node);
            return {info.texture_set, info.stack, info.root ? core::kNoId : info.owner, info.owner_stack};
        }
    }
    return {};
}

Inserted InsertNode(core::Edit& edit, const core::InsertPosition& position, core::NodeType type,
                    const std::optional<std::string>& name, core::Id instance_source,
                    const std::function<void(core::Edit&, core::Id)>& configure) {
    if (name) {
        const core::NameScope scope = ScopeOf(edit.project(), position);
        if (const std::optional<core::Id> found = core::ResolveName(edit.project(), scope, *name)) {
            const std::optional<core::NodeType> found_type = core::FindNodeType(edit.project(), *found);
            if (found_type != type) {
                throw core::ValueError("the node named '" + *name + "' (" + std::to_string(*found) + ") is a " +
                                       std::string(core::ToString(*found_type)) + ", not a " +
                                       std::string(core::ToString(type)));
            }
            edit.returned()["node"] = static_cast<std::int64_t>(*found);
            edit.returned()["created"] = false;
            return {*found, false};
        }
    }
    const core::Id uid = edit.Insert(position, type, name.value_or(DefaultName(type)), instance_source);
    if (configure) configure(edit, uid);
    edit.returned()["node"] = static_cast<std::int64_t>(uid);
    edit.returned()["created"] = true;
    return {uid, true};
}

bool RgbChannel(const core::Project& project, const NodeInfo& info, const core::LevelsParams* params) {
    if (info.in_mask()) return false;  // a mask is mono (`phase1-levels-params` s27, s28)
    if (params == nullptr || !params->affected_channel) return params && params->components.size() == 3;
    const core::Stack& stack = ResolveStack(project, {info.texture_set, info.stack});
    const auto it = stack.channels.find(*params->affected_channel);
    if (it == stack.channels.end()) return params->components.size() == 3;
    const core::ChannelFormat f = it->second.format;
    return f == core::ChannelFormat::sRGB8 || f == core::ChannelFormat::RGB8 || f == core::ChannelFormat::RGB16 ||
           f == core::ChannelFormat::RGB16F || f == core::ChannelFormat::RGB32F;
}

core::LevelsComponent Component(double in_min, double in_max, double gamma, double out_min, double out_max, bool clamp) {
    return {F32(in_min), F32(in_max), F32(gamma), F32(out_min), F32(out_max), clamp, {}};
}

core::LevelsComponent MonoOf(const std::vector<core::LevelsComponent>& rgb) {
    const auto mean = [&](double core::LevelsComponent::*field) {
        return (rgb[0].*field + rgb[1].*field + rgb[2].*field) / 3.0;
    };
    return {mean(&core::LevelsComponent::input_min), mean(&core::LevelsComponent::input_max),
            mean(&core::LevelsComponent::gamma),     mean(&core::LevelsComponent::output_min),
            mean(&core::LevelsComponent::output_max), rgb[0].clamp, {}};
}

void InsertDefaults(core::Edit& edit, core::Id uid, bool named) {
    const NodeInfo info = Resolve(edit.project(), uid);
    if (info.in_mask()) return;
    const std::map<core::ChannelType, core::Channel> channels =
        ResolveStack(edit.project(), {info.texture_set, info.stack}).channels;
    switch (info.type()) {
        case core::NodeType::FillLayer:
        case core::NodeType::GroupLayer: {
            core::Layer& layer = EditLayer(edit, uid);
            ApplyDefaultBlending(layer.blending, channels);
            if (layer.fill) ApplyDefaultSources(*layer.fill, channels);
            break;
        }
        case core::NodeType::FillEffect: {
            core::Effect& effect = EditEffect(edit, uid);
            ApplyDefaultBlending(effect.blending, channels);
            if (effect.fill) ApplyDefaultSources(*effect.fill, channels);
            break;
        }
        case core::NodeType::LevelsEffect: {
            if (!channels.contains(core::ChannelType::BaseColor)) break;
            core::Effect& effect = EditEffect(edit, uid);
            if (!named) effect.name = "Levels - Base color";
            effect.levels = core::LevelsParams{};
            effect.levels->affected_channel = core::ChannelType::BaseColor;
            const std::size_t arity = RgbChannel(edit.project(), info, &*effect.levels) ? 3 : 1;
            effect.levels->components.assign(arity, core::LevelsComponent{});
            break;
        }
        default:
            break;
    }
}

void SetAffectedChannel(core::Edit& edit, core::Id uid, core::ChannelType channel) {
    const NodeInfo info = Resolve(edit.project(), uid);
    core::Effect& e = EditEffect(edit, uid);
    if (e.mono_blending) throw core::ValueError("a mask-stack levels effect has no affected channel");
    if (!e.levels) e.levels = core::LevelsParams{};
    const bool changed = e.levels->affected_channel != channel;
    e.levels->affected_channel = channel;
    // One component for a mono channel, three for an RGB one. Another channel starts from the
    // identity levels (`phase1-levels-params` s18, and s14 after reopen); the same channel keeps
    // its parameters.
    const std::size_t arity = RgbChannel(edit.project(), info, &*e.levels) ? 3 : 1;
    std::vector<core::LevelsComponent>& components = e.levels->components;
    if (changed) components.clear();
    if (components.empty()) components.push_back(core::LevelsComponent{});
    components.resize(arity, components.front());
}

ImageReader MaskImageReader(const std::filesystem::path& dir) {
    return [dir](const std::string& name) -> std::optional<std::string> {
        std::ifstream file(dir / PathFromUtf8(name + ".png"), std::ios::binary);
        if (!file) return std::nullopt;
        return std::string{std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
    };
}

core::BitmapSource& EditBitmap(core::Edit& edit, core::Id uid, const ChannelArg& channel) {
    core::FillContent* fill = nullptr;
    bool mask = false;
    if (core::Layer* layer = core::FindLayer(edit.project(), uid)) {
        if (layer->fill) fill = &*layer->fill;
    } else if (core::Effect* effect = core::FindEffect(edit.project(), uid)) {
        if (effect->fill) fill = &*effect->fill;
        mask = effect->mono_blending.has_value();
    } else {
        throw core::ValueError("stale handle: node " + std::to_string(uid) + " no longer exists");
    }
    if (fill == nullptr) throw core::ValueError("node " + std::to_string(uid) + " is not a fill: it has no resource source");
    core::Source* source = nullptr;
    if (mask) {
        if (channel) throw core::ValueError("a mask-stack fill takes no channel (None)");
        if (fill->mono_source) source = &*fill->mono_source;
    } else {
        if (!channel) ThrowEditionContext("node " + std::to_string(uid) + " is multichannel: give the channel");
        const auto it = fill->sources.find(*channel);
        if (it != fill->sources.end()) source = &it->second;
    }
    if (source == nullptr || source->kind() != core::SourceKind::bitmap) {
        throw core::ValueError("node " + std::to_string(uid) + " has no bitmap source" +
                               (channel ? " on " + std::string(core::ToString(*channel)) : std::string()));
    }
    return std::get<core::BitmapSource>(source->value);
}

// ── Uniform colours ─────────────────────────────────────────────────────────────────────────────

namespace {

constexpr const char* kOcioGap = "phase1.15_compositor-colour-fits item 2.6, decision 202";

[[noreturn]] void OcioUnrecorded(const std::string& what) {
    throw core::NotYetSupported("under OCIO, " + what + " is not recorded (" + std::string(kOcioGap) + ")");
}

}  // namespace

bool DecodesColour(const std::map<core::ChannelType, core::Channel>& channels, const ChannelArg& channel) {
    if (!channel || core::ToString(*channel).starts_with("User")) return false;
    const auto it = channels.find(*channel);
    return it != channels.end() && it->second.format == core::ChannelFormat::sRGB8;
}

bool OcioColourProfile(const core::Project& project) {
    const core::ColorManagement& cm = project.settings.color_management;
    if (cm.mode.empty() || cm.mode == "legacy") return false;
    if (evaluator::PainterOcio(project)) return true;
    throw core::NotYetSupported("colour management '" + cm.mode + "' (working space '" + cm.working_space +
                                "', config hash '" + cm.config_hash +
                                "') is not a pinned colour profile; only Painter's Legacy mode and OCIO with Painter's "
                                "substance config (SHA-256 " +
                                std::string(evaluator::kPainterOcioConfigSha256.substr(0, 8)) +
                                "...) are supported (decisions 107, 190 and 202)");
}

std::array<double, 3> WorkingColour(const std::array<double, 3>& rgb, const std::optional<std::string>& space,
                                    bool decodes, bool ocio) {
    const std::string name = space.value_or(decodes ? "sRGB" : "Raw");
    const bool srgb = name == "sRGB";
    const bool given = name == "Raw" || name == "Working" || (!ocio && name == "Linear");
    if (ocio) {
        if (!decodes && srgb) OcioUnrecorded("an sRGB uniform colour on a channel that does not decode it");
        if (!srgb && !given) OcioUnrecorded("a uniform colour in the colour space '" + name + "'");
    } else if (!srgb && !given) {
        throw core::ValueError("'" + name + "' is not a colour space of Painter's Legacy colour management");
    }
    std::array<double, 3> working{};
    for (std::size_t c = 0; c < 3; ++c) {  // every component before any change
        const float x = static_cast<float>(rgb[c]);
        if (!decodes || !srgb) {
            working[c] = x;  // as given (a channel that does not decode: decision 115)
        } else if (!ocio) {
            working[c] = evaluator::PainterLegacySrgbDecode(x);
        } else if (const std::optional<float> value = evaluator::PainterOcioSrgbDecode(x)) {
            working[c] = *value;
        } else {
            throw core::NotYetSupported(
                "under OCIO, Painter's working value of the sRGB component " + core::json::FormatDouble(rgb[c]) +
                " is not recorded: the decode is Painter's measured value of the components c / 255 and of the other "
                "recorded components, and no analytic decode reproduces it (" + std::string(kOcioGap) +
                "; a Tier 0 readback of the component settles it)");
        }
    }
    return working;
}

core::UniformColorSource StoredUniformColour(const core::Project& project, core::Id uid, const ChannelArg& channel,
                                            const std::array<double, 3>& rgb, const std::optional<std::string>& space) {
    const NodeInfo info = Resolve(project, uid);
    const bool decodes = DecodesColour(ResolveStack(project, {info.texture_set, info.stack}).channels, channel);
    return core::UniformColorSource{WorkingColour(rgb, space, decodes, OcioColourProfile(project)), "Working", {}};
}

// ── Texture sets ────────────────────────────────────────────────────────────────────────────────

core::Stack& EditStack(core::Edit& edit, const StackHandle& handle) {
    for (core::TextureSet& set : edit.project().texture_sets) {
        if (set.id != handle.texture_set) continue;
        for (core::Stack& stack : set.stacks) {
            if (stack.id == handle.stack) return stack;
        }
    }
    throw core::ValueError("stale handle: stack " + std::to_string(handle.stack) + " no longer exists");
}

core::TextureSet& EditSet(core::Edit& edit, core::Id id) {
    for (core::TextureSet& set : edit.project().texture_sets) {
        if (set.id == id) return set;
    }
    throw core::ValueError("stale handle: texture set " + std::to_string(id) + " no longer exists");
}

void StripChannel(std::vector<core::Layer>& layers, core::ChannelType channel) {
    const auto strip_fill = [channel](std::optional<core::FillContent>& fill) {
        if (!fill) return;
        fill->active_channels.erase(channel);
        fill->sources.erase(channel);
    };
    for (core::Layer& layer : layers) {
        layer.blending.erase(channel);
        strip_fill(layer.fill);
        if (layer.paint) layer.paint->planes.erase(channel);
        for (core::Effect& effect : layer.content_effects) {
            effect.blending.erase(channel);
            effect.active_channels.erase(channel);
            strip_fill(effect.fill);
            if (effect.paint) effect.paint->planes.erase(channel);
        }
        StripChannel(layer.children, channel);
    }
}

void SetMeshMapResource(core::Edit& edit, core::Id set_id, core::MeshMapUsage usage,
                        const std::optional<ResourceIdHandle>& resource) {
    core::TextureSet& set = EditSet(edit, set_id);
    if (!resource) {
        set.mesh_maps.erase(usage);
        return;
    }
    const std::string sha256 = ResolveResource(edit.project(), *resource);
    const core::Project& p = edit.project();
    core::MeshMapBinding binding;
    binding.resource = sha256;
    binding.format = core::ChannelFormat::RGB16;
    binding.color_space = "Raw";
    binding.provenance = core::ImportedProvenance{p.resources.at(sha256).front().origin, sha256,
                                                  core::MeshMapRole::geometry_only, p.settings.normal_map_format, "", {}};
    set.mesh_maps[usage] = std::move(binding);
}

// ── Resources ───────────────────────────────────────────────────────────────────────────────────

ResourceFile ReadResourceFile(const std::string& file_path, ResourceUsage usage, const std::optional<std::string>& name) {
    // A Substance archive, whatever its usage: UzPainter has no runtime that executes one and
    // reserves none (05-procedural-content.md §5, decisions 002 and 006). Refused before the file
    // is read.
    if (const std::filesystem::path archive = PathFromUtf8(file_path); Lower(Utf8(archive.extension())) == ".sbsar") {
        const std::string file = Utf8(archive.filename());
        ThrowUnsupportedProcedural("importing " + file + ": UnsupportedProcedural{asset: " + file +
                                       ", reason: no runtime}: UzPainter executes no .sbsar file "
                                       "(05-procedural-content.md §5, decision 006)",
                                   file, "no runtime");
    }
    if (usage == ResourceUsage::COLOR_LUT) {
        ApiError error("UnsupportedInUzPainter",
                       "uzpainter.resource.import_project_resource is not supported in UzPainter: a COLOR_LUT "
                       "resource; the colour LUT is pinned to none by the fixed render pipeline (decision 038)");
        error.symbol = "uzpainter.resource.import_project_resource";
        error.reason = "a COLOR_LUT resource; the colour LUT is pinned to none by the fixed render pipeline "
                       "(decision 038)";
        throw error;
    }
    if (usage != ResourceUsage::TEXTURE && usage != ResourceUsage::ENVIRONMENT) {
        ThrowNotYetSupported("importing a resource of usage GENERATOR or SMART_MATERIAL "
                             "(phase3.3_procedural-families)");
    }
    const bool environment = usage == ResourceUsage::ENVIRONMENT;
    const std::filesystem::path path = PathFromUtf8(file_path);
    if (!environment && Lower(Utf8(path.extension())) != ".png") {
        ThrowNotYetSupported("importing " + Utf8(path.filename()) +
                             ": the bitmap decoder of this build reads PNG files only (src/evaluator/sources.h)");
    }
    std::ifstream file(path, std::ios::binary);
    if (!file) ThrowResourceNotFound("cannot read " + file_path);
    ResourceFile read;
    read.bytes.assign(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
    // An environment is an OpenEXR equirectangular map, stored as its unmodified bytes under
    // their SHA-256 (RES-03; display.h).
    if (environment) {
        if (const std::string problem = display::EnvironmentProblem(read.bytes); !problem.empty()) {
            throw core::ValueError("cannot import " + Utf8(path.filename()) + " as an environment: " + problem);
        }
    }
    read.kind = environment ? "ENVIRONMENT" : "TEXTURE";
    read.mime = environment ? "image/x-exr" : "image/png";
    read.entry = name.value_or(Utf8(path.stem()));
    read.origin = Utf8(path);
    read.file_name = Utf8(path.filename());
    return read;
}

std::string ImportResourceFile(core::Edit& edit, store::ProjectStore& store, const ResourceFile& file,
                               const std::optional<std::string>& group) {
    const std::string sha256 = ImportResource(edit, store, file.bytes, file.entry, file.mime, file.kind, file.origin);
    if (group) {
        for (core::ResourceMeta& meta : edit.project().resources.at(sha256)) {
            // The resource group (Painter's `group` argument) is kept with the entry.
            if (meta.name == file.entry) meta.extra["group"] = *group;
        }
    }
    return sha256;
}

std::vector<core::Id> ReplaceLayerStackResource(core::Edit& edit, const ResourceIdHandle& old_resource,
                                                const ResourceIdHandle& new_resource) {
    const std::string from = ResolveResource(edit.project(), old_resource);
    const std::string to = ResolveResource(edit.project(), new_resource);
    std::vector<core::Id> nodes;
    // The same content: no binding changes.
    if (from == to) return nodes;
    // Mesh maps are not rebound here. A mesh-map binding holds the content hash only, so it
    // cannot tell the named resource from another name of the same bytes, which Painter keeps
    // bound (`p22b-mesh-map-alias-update` s9-s11). The facade rebinds the mesh maps bound to the
    // named resource in the same transaction (decision 336).
    for (core::TextureSet& set : edit.project().texture_sets) {
        for (core::Stack& stack : set.stacks) Rebind(stack.root_layers, from, to, nodes);
    }
    return nodes;
}

// ── Project ─────────────────────────────────────────────────────────────────────────────────────

MeshReloadCall::MeshReloadCall(const std::string& mesh_file_path, std::optional<bool> import_cameras,
                               std::map<std::string, std::string> material_mapping)
    : project_(Session::Get().Current()), path_(PathFromUtf8(mesh_file_path)), import_cameras_(import_cameras) {
    std::ifstream file(path_, std::ios::binary);
    if (!file) ThrowProjectError("cannot read " + mesh_file_path);
    bytes_.assign(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());

    const evaluator::TemplateLibrary templates =
        evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory());
    // Texture sets the reload adds start from the project's template.
    const std::string template_id = project_->document->snapshot().project->settings.template_id;
    const evaluator::ProjectTemplate* fresh = templates.Find(template_id);
    if (fresh == nullptr) throw ApiError("RuntimeError", "the project template '" + template_id + "' is not installed");
    settings_.import.mesh_unit_scale = project_->document->snapshot().project->settings.mesh_unit_scale;
    settings_.material_mapping = std::move(material_mapping);
    settings_.new_set_channels = fresh->StackChannels();

    store::ProjectStore* store = project_->store.get();
    read_ = [store](const std::string& sha256) { return store->ReadResource(sha256); };
    source_ = mesh::MeshSource{Utf8(std::filesystem::absolute(path_)), NowUtc()};
    arguments_ = core::json::Object{{"mesh", Utf8(path_.filename())}};
    if (import_cameras_) arguments_["import_cameras"] = *import_cameras_;
}

void MeshReloadCall::Apply(core::Edit& edit) const {
    // A project written before a glTF's external files were stored, whose files are gone, has a
    // mesh that cannot be re-derived: the reload replaces it without the comparison.
    std::optional<mesh::ImportResult> current;
    std::string unavailable;
    try {
        current = mesh::RederiveMesh(edit.base(), read_);
    } catch (const mesh::MeshFileMissing& missing) {
        unavailable = missing.what();
    }
    const mesh::ImportResult next = mesh::ImportMesh(bytes_, Utf8(path_.filename()), settings_.import, path_.parent_path());
    store::ProjectStore& store = *project_->store;
    store.StageResource(bytes_, std::string(mesh::MimeOf(next.format)));
    for (const mesh::ExternalFile& external : next.external_files) {
        store.StageResource(external.bytes, std::string(mesh::kExternalFileMime));
    }
    if (current) mesh::ApplyReload(edit, *current, next, source_, settings_);
    else mesh::ApplyReloadWithoutCurrent(edit, next, source_, settings_, unavailable);
    if (import_cameras_) edit.project().settings.import_cameras = *import_cameras_;
}

void MeshReloadCall::Finish() const { project_->mesh_path = Utf8(path_); }

}  // namespace uzp::python
