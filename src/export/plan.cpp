#include "export/plan.h"

#include <algorithm>
#include <cctype>
#include <map>
#include <set>
#include <utility>

#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::exporter {

namespace json = core::json;

namespace {

using core::ChannelType;

/// The Painter recording a refusal of an unrecorded behaviour asks for (decision 085).
constexpr std::string_view kRecording = "export-semantics recording R-085 (decision 085)";

[[noreturn]] void Invalid(const std::string& what, const std::string& problem) {
    throw core::ValueError("export: " + what + ": " + problem);
}

[[noreturn]] void Gap(const std::string& what, const std::string& problem, std::string_view owner) {
    throw core::NotYetSupported("export: " + what + ": " + problem + " (" + std::string(owner) + ")");
}

std::string Lower(std::string_view text) {
    std::string out(text);
    for (char& c : out) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return out;
}

/// One exported stack: a rootPath resolved.
struct Root {
    const core::TextureSet* set = nullptr;
    const core::Stack* stack = nullptr;
    std::string rootPath;
};

std::string RootPathOf(const core::TextureSet& set, const core::Stack& stack) {
    if (set.stacks.size() == 1 && stack.name.empty()) return set.name;
    return set.name + "/" + stack.name;
}

std::vector<std::string> ValidRootPaths(const core::Project& project) {
    std::vector<std::string> paths;
    for (const core::TextureSet& set : project.texture_sets) {
        for (const core::Stack& stack : set.stacks) paths.push_back(RootPathOf(set, stack));
    }
    return paths;
}

Root ResolveRoot(const core::Project& project, const std::string& rootPath, const std::string& what) {
    for (const core::TextureSet& set : project.texture_sets) {
        for (const core::Stack& stack : set.stacks) {
            if (RootPathOf(set, stack) == rootPath) return {&set, &stack, rootPath};
        }
    }
    Invalid(what, "no texture set or stack \"" + rootPath + "\"; valid: " +
                      JoinNames(Nearest(rootPath, ValidRootPaths(project))));
}

bool HasChannel(const core::Stack& stack, ChannelType type) { return stack.channels.contains(type); }

uint32_t ComponentsOf(core::ChannelFormat format) {
    using enum core::ChannelFormat;
    return format == L8 || format == L16 || format == L16F || format == L32F ? 1 : 3;
}

bool NodeInStack(const core::Project& project, const Root& root, core::Id uid) {
    bool found = false;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (visit.texture_set != root.set->id || visit.stack != root.stack->id) return;
        const core::Id id = visit.layer != nullptr ? visit.layer->uid : visit.effect->uid;
        found = found || id == uid;
    });
    return found;
}

/// How a source stands in one stack.
enum class Presence : uint8_t { Present, Absent, Constant };

struct Resolved {
    Presence presence = Presence::Present;
    PlannedSource source;
    std::string absentReason;
};

/// The recorded presence of a virtual normal map: every golden holds Height and Normal channels.
/// The evaluator's own limits of the combination (set sizes, a bound Normal mesh map: the
/// phase1.12 boundary, height_to_normal.h) need decoded inputs and stay with the evaluator, which
/// refuses them with `unsupported_source` (NotYetSupported, decision 082) when the export
/// evaluates its files, before it writes any (decision 085).
void CheckVirtualNormal(const Root& root, const std::string& what) {
    if (!HasChannel(*root.stack, ChannelType::Height) || !HasChannel(*root.stack, ChannelType::Normal)) {
        Gap(what, "a virtual normal map of a stack without both a Height and a Normal channel is not recorded",
            kRecording);
    }
}

Resolved ResolveDocument(const ChannelSpec& spec, const Root& root, const std::string& what) {
    Resolved r;
    r.source.type = spec.type;
    r.source.name = spec.name;
    const ChannelType member = *DocumentMapMember(spec.name);
    std::optional<ChannelType> read;
    if (HasChannel(*root.stack, member)) {
        read = member;
    } else if (const std::optional<ChannelType> target = RecordedAliasTarget(member);
               target && HasChannel(*root.stack, *target)) {
        read = target;
    } else {
        // The same pairing read the other way: the stack holds the alias member itself.
        for (const auto& [type, _] : root.stack->channels) {
            if (RecordedAliasTarget(type) == member) read = type;
        }
    }
    if (!read && IsUnrecordedAlias(member)) {
        Gap(what, "the documentMap \"" + spec.name + "\" names a legacy alias whose OpenPBR pairing is not recorded",
            kRecording);
    }
    if (!read) {
        r.presence = Presence::Absent;
        r.absentReason = "the stack has no " + std::string(core::ToString(member)) + " channel";
        return r;
    }
    r.source.channel = read;
    r.source.components = ComponentsOf(root.stack->channels.at(*read).format);
    return r;
}

Resolved ResolveMesh(const ChannelSpec& spec, const Root& root, const std::string& what) {
    Resolved r;
    r.source.type = spec.type;
    r.source.name = spec.name;
    const core::MeshMapUsage usage = *MeshMapOf(spec.name);
    if (!root.set->mesh_maps.contains(usage)) {
        Gap(what, "the meshMap \"" + spec.name + "\" is not bound to the texture set; what Painter exports then is not "
                  "recorded", kRecording);
    }
    if (usage != core::MeshMapUsage::Normal) {
        Gap(what, "exporting the meshMap \"" + spec.name + "\" (a mesh map other than normal_base) is not recorded",
            "export-processing recording R-090 (decision 090)");
    }
    r.source.meshMap = usage;
    r.source.components = 3;
    r.source.normalRole = core::MeshMapRole::geometry_only;
    return r;
}

Resolved ResolveVirtual(const ChannelSpec& spec, const Root& root, const std::string& what) {
    Resolved r;
    r.source.type = spec.type;
    r.source.name = spec.name;
    const VirtualMap map = *ParseVirtualMap(spec.name);
    const VirtualMapSupport support = Support(map);
    if (!support.supported) {
        Gap(what, "the virtualMap \"" + spec.name + "\" has no exact Tier 0 golden yet", support.evidenceOrOwner);
    }
    if (map == VirtualMap::Normal_OpenGL || map == VirtualMap::Normal_DirectX) {
        CheckVirtualNormal(root, what);
        r.source.normalRole = core::MeshMapRole::combined;
    }
    r.source.virtualMap = map;
    r.source.components = support.components;
    return r;
}

/// The map a diagnostic reads in `root`, its components; a refusal or a ValueError when the stack
/// cannot give it.
uint32_t DiagnosticMapComponents(const evaluator::DiagnosticMapId& map, const Root& root, const std::string& what) {
    if (map.kind == evaluator::DiagnosticMapId::Kind::VirtualNormal) {
        CheckVirtualNormal(root, what);
        return 3;
    }
    if (!HasChannel(*root.stack, map.channel)) {
        Invalid(what, "the stack " + root.rootPath + " has no " + std::string(core::ToString(map.channel)) + " channel");
    }
    return ComponentsOf(root.stack->channels.at(map.channel).format);
}

Resolved ResolveDiagnostic(const core::Project& project, const ChannelSpec& spec, const Root& root,
                           const std::string& what) {
    using Kind = evaluator::DiagnosticSource::Kind;
    Resolved r;
    r.source.type = spec.type;
    r.source.name = spec.name;
    const evaluator::DiagnosticSource source = *evaluator::ParseSourceName(spec.name);
    r.source.diagnostic = source;
    if (!NodeInStack(project, root, source.node)) {
        r.presence = Presence::Absent;
        r.absentReason = "node " + std::to_string(source.node) + " is not in the stack";
        return r;
    }
    switch (source.kind) {
        case Kind::Isolated:
        case Kind::Contribution:
        case Kind::RegionStats: r.source.components = DiagnosticMapComponents(source.map, root, what); break;
        case Kind::MaterialMask:
        case Kind::MaterialLeaks: r.source.components = 1; break;
        case Kind::MaterialView:
            if (source.view == evaluator::MaterialViewKind::ID) {
                if (!root.set->mesh_maps.contains(core::MeshMapUsage::ID)) {
                    Invalid(what, "the texture set " + root.set->name + " has no ID mesh map");
                }
                r.source.components = 3;
            } else {
                r.source.components = DiagnosticMapComponents(
                    evaluator::DiagnosticMapId::Channel(evaluator::MaterialViewChannel(source.view)), root, what);
            }
            break;
    }
    if (source.kind == Kind::MaterialLeaks && source.view == evaluator::MaterialViewKind::ID &&
        !root.set->mesh_maps.contains(core::MeshMapUsage::ID)) {
        Invalid(what, "the texture set " + root.set->name + " has no ID mesh map");
    }
    if (source.kind == Kind::MaterialLeaks && source.view != evaluator::MaterialViewKind::ID) {
        DiagnosticMapComponents(evaluator::DiagnosticMapId::Channel(evaluator::MaterialViewChannel(source.view)), root,
                                what);
    }
    return r;
}

Resolved Resolve(const core::Project& project, const ChannelSpec& spec, const Root& root, const std::string& what) {
    switch (spec.type) {
        case SourceType::documentMap: return ResolveDocument(spec, root, what);
        case SourceType::meshMap: return ResolveMesh(spec, root, what);
        case SourceType::virtualMap: return ResolveVirtual(spec, root, what);
        case SourceType::defaultMap: {
            Resolved r;
            r.presence = Presence::Constant;
            r.source.type = spec.type;
            r.source.name = spec.name;
            r.source.constant = DefaultMapValue(spec.name);
            return r;
        }
        case SourceType::diagnosticMap: return ResolveDiagnostic(project, spec, root, what);
    }
    return {};
}

uint32_t LetterIndex(ChannelLetter letter) {
    switch (letter) {
        case ChannelLetter::R: return 0;
        case ChannelLetter::G: return 1;
        case ChannelLetter::B: return 2;
        default: return 0;
    }
}

/// The component a channel reads (decision 085, C9).
uint32_t ComponentRead(const ChannelSpec& spec, const PlannedSource& source, const std::string& what) {
    if (source.type == SourceType::defaultMap) return 0;
    if (spec.src == ChannelLetter::A) {
        Gap(what, "srcChannel A of a " + std::string(SourceTypeName(source.type)) + " is not recorded", kRecording);
    }
    if (source.components == 1) return 0;
    if (spec.src == ChannelLetter::L) {
        Gap(what, "srcChannel L of a three-component map (an undocumented mix of R, G and B) is not recorded",
            kRecording);
    }
    return LetterIndex(spec.src);
}

FileLayout LayoutOf(const std::vector<ChannelSpec>& channels) {
    bool alpha = false;
    bool grey = false;
    for (const ChannelSpec& c : channels) {
        alpha = alpha || c.dest == ChannelLetter::A;
        grey = grey || c.dest == ChannelLetter::L;
    }
    if (grey) return alpha ? FileLayout::LA : FileLayout::L;
    return alpha ? FileLayout::RGBA : FileLayout::RGB;
}

bool IsStatistics(const ChannelSpec& c) {
    return c.type == SourceType::diagnosticMap && c.name.starts_with("regionStats/");
}

// ── Filters and parameters ──────────────────────────────────────────────────

bool Contains(const std::vector<std::string>& list, std::string_view item) {
    return std::find(list.begin(), list.end(), item) != list.end();
}

/// Whether `filter` selects the map `fileName` of `root`; `uvTiles` (not recorded in the Default
/// workflow) is refused once the other members select the file.
bool Selects(const Filter& filter, const Root& root, const std::string& fileName, const std::string& what) {
    if (filter.dataPaths && !Contains(*filter.dataPaths, root.rootPath) && !Contains(*filter.dataPaths, root.set->name)) {
        return false;
    }
    if (filter.outputMaps && !Contains(*filter.outputMaps, fileName)) return false;
    if (filter.uvTiles) {
        Gap(what, "a uvTiles filter on a texture set of the Default workflow (no UV tiles) is not recorded", kRecording);
    }
    return true;
}

void Override(Parameters& into, const Parameters& from) {
    if (from.fileFormat) into.fileFormat = from.fileFormat;
    if (from.bitDepth) into.bitDepth = from.bitDepth;
    if (from.dithering) into.dithering = from.dithering;
    if (from.sizeLog2) into.sizeLog2 = from.sizeLog2;
    if (from.paddingAlgorithm) into.paddingAlgorithm = from.paddingAlgorithm;
    if (from.dilationDistance) into.dilationDistance = from.dilationDistance;
}

ResolvedParameters Require(const Parameters& p, const std::string& what) {
    const auto missing = [&](std::string_view name) {
        Invalid(what, "the parameter " + std::string(name) +
                          " is undefined after the preset map's parameters and every matching exportParameters rule");
    };
    if (!p.fileFormat) missing("fileFormat");
    if (!p.bitDepth) missing("bitDepth");
    if (!p.dithering) missing("dithering");
    if (!p.paddingAlgorithm) missing("paddingAlgorithm");
    if (NeedsDilation(*p.paddingAlgorithm) && !p.dilationDistance) missing("dilationDistance");
    const bool fits = *p.fileFormat == FileFormat::png ? (*p.bitDepth == BitDepth::u8 || *p.bitDepth == BitDepth::u16)
                                                       : (*p.bitDepth == BitDepth::f16 || *p.bitDepth == BitDepth::f32);
    if (!fits) {
        Invalid(what, "the bit depth " + std::string(BitDepthName(*p.bitDepth)) + " is not supported by the format " +
                          std::string(FileFormatName(*p.fileFormat)) + "; valid: " +
                          (*p.fileFormat == FileFormat::png ? "8, 16" : "16f, 32f"));
    }
    ResolvedParameters r;
    r.fileFormat = *p.fileFormat;
    r.bitDepth = *p.bitDepth;
    r.dithering = *p.dithering;
    r.sizeLog2 = p.sizeLog2;
    r.paddingAlgorithm = *p.paddingAlgorithm;
    r.dilationDistance = p.dilationDistance;
    return r;
}

std::pair<uint32_t, uint32_t> SizeOf(const core::TextureSet& set, const std::optional<SizeLog2>& sizeLog2) {
    const auto w = static_cast<uint32_t>(set.resolution.width);
    const auto h = static_cast<uint32_t>(set.resolution.height);
    if (!sizeLog2) return {w, h};
    if (const auto* pair = std::get_if<std::array<int, 2>>(&*sizeLog2)) {
        return {1u << (*pair)[0], 1u << (*pair)[1]};
    }
    // The larger side becomes 2^s, the aspect ratio kept (both sides are powers of two).
    const uint32_t larger = 1u << std::get<int>(*sizeLog2);
    if (w >= h) return {larger, std::max(1u, static_cast<uint32_t>((uint64_t{larger} * h) / w))};
    return {std::max(1u, static_cast<uint32_t>((uint64_t{larger} * w) / h)), larger};
}

// ── Names ───────────────────────────────────────────────────────────────────

constexpr std::array<std::string_view, 7> kWildcards{"colorSpace", "mesh",   "project",   "sceneMaterial",
                                                     "textureSet", "udim", "uvTileName"};

/// The value of a wildcard in `root` (nullopt: refused, see the header).
std::string WildcardValue(std::string_view token, const Root& root, const std::string& what) {
    if (token == "textureSet") return root.set->name;
    if (token == "colorSpace" || token == "udim" || token == "uvTileName") return {};
    Gap(what, "the wildcard $" + std::string(token) + " is not recorded", kRecording);
}

bool ForbiddenCharacter(char c) {
    return static_cast<unsigned char>(c) < 0x20 || std::string_view("<>:\"|?*\\").find(c) != std::string_view::npos;
}

void CheckComponent(const std::string& component, const std::string& name, const std::string& what) {
    if (component.empty()) Invalid(what, "the file name \"" + name + "\" has an empty path component");
    if (component == "." || component == "..") {
        Invalid(what, "the file name \"" + name + "\" must stay inside exportPath");
    }
    for (char c : component) {
        if (ForbiddenCharacter(c)) {
            Invalid(what, "the file name \"" + name + "\" holds a character Windows forbids in a file name");
        }
    }
    if (component.back() == '.' || component.back() == ' ') {
        Invalid(what, "the file name \"" + name + "\" has a component ending in a dot or a space");
    }
    std::string stem = Lower(component.substr(0, component.find('.')));
    static const std::set<std::string> reserved{"con",  "prn",  "aux",  "nul",  "com1", "com2", "com3", "com4",
                                                "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3",
                                                "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"};
    if (reserved.contains(stem)) Invalid(what, "the file name \"" + name + "\" uses a reserved Windows device name");
}

/// Expands `pattern` for `root` (wildcards and optional groups) into a `/`-separated name.
std::string ExpandName(const std::string& pattern, const Root& root, const std::string& what) {
    std::string out;
    std::string group;
    bool inGroup = false;
    bool groupHasWildcard = false;
    bool groupEmpty = false;
    for (size_t i = 0; i < pattern.size();) {
        const char c = pattern[i];
        if (c == '(') {
            if (inGroup) Gap(what, "nested ( … ) groups in \"" + pattern + "\" are not recorded", kRecording);
            inGroup = true;
            groupHasWildcard = false;
            groupEmpty = false;
            group.clear();
            ++i;
            continue;
        }
        if (c == ')') {
            if (!inGroup) Invalid(what, "the file name \"" + pattern + "\" closes a group it never opened");
            if (!groupHasWildcard) {
                Gap(what, "a ( … ) group without a wildcard in \"" + pattern + "\" is not recorded", kRecording);
            }
            if (!groupEmpty) out += group;
            inGroup = false;
            ++i;
            continue;
        }
        if (c == '$') {
            size_t end = i + 1;
            while (end < pattern.size() && std::isalpha(static_cast<unsigned char>(pattern[end]))) ++end;
            const std::string token = pattern.substr(i + 1, end - i - 1);
            if (std::find(kWildcards.begin(), kWildcards.end(), token) == kWildcards.end()) {
                std::vector<std::string> valid;
                for (std::string_view w : kWildcards) valid.push_back("$" + std::string(w));
                Invalid(what, "unknown wildcard \"$" + token + "\" in \"" + pattern + "\"; valid: " +
                                  JoinNames(Nearest("$" + token, valid)));
            }
            const std::string value = WildcardValue(token, root, what);
            if (inGroup) {
                groupHasWildcard = true;
                groupEmpty = groupEmpty || value.empty();
                group += value;
            } else {
                if (value.empty()) {
                    Gap(what, "the wildcard $" + token + " is empty here and stands outside a ( … ) group in \"" +
                                  pattern + "\"; that name is not recorded", kRecording);
                }
                out += value;
            }
            i = end;
            continue;
        }
        (inGroup ? group : out) += c;
        ++i;
    }
    if (inGroup) Invalid(what, "the file name \"" + pattern + "\" leaves a group open");
    size_t start = 0;
    while (true) {
        const size_t slash = out.find('/', start);
        CheckComponent(out.substr(start, slash == std::string::npos ? std::string::npos : slash - start), out, what);
        if (slash == std::string::npos) break;
        start = slash + 1;
    }
    return out;
}

std::string Extension(const PlannedFile& file) {
    if (file.layout == FileLayout::Statistics) return "json";
    return std::string(FileFormatName(file.parameters->fileFormat));
}

std::string JoinPath(std::string root, const std::string& relative) {
    while (!root.empty() && (root.back() == '/' || root.back() == '\\')) root.pop_back();
    return root + "/" + relative;
}

const PresetSpec& PresetNamed(const ExportConfig& config, const std::string& name) {
    for (const PresetSpec& p : config.exportPresets) {
        if (p.name == name) return p;
    }
    Invalid("exportPresets", "no preset \"" + name + "\"");
}

std::string Describe(const Root& root, const PresetSpec& preset, size_t mapIndex, const MapSpec& map) {
    return root.rootPath + ": preset \"" + preset.name + "\" map " + std::to_string(mapIndex) + " (\"" + map.fileName +
           "\")";
}

/// Compiles one preset map for one stack: a file, a skipped map, or nothing (filtered out).
void CompileMap(const core::Project& project, const ExportConfig& config, const ExportListEntry& entry,
                const Root& root, const PresetSpec& preset, size_t mapIndex, ExportPlan& plan,
                std::set<std::string>& diagnosticsNamed, std::set<std::string>& diagnosticsSeen) {
    const MapSpec& map = preset.maps[mapIndex];
    const std::string what = Describe(root, preset, mapIndex, map);
    if (entry.filter && !Selects(*entry.filter, root, map.fileName, what)) return;
    for (const ChannelSpec& c : map.channels) {
        if (c.type == SourceType::diagnosticMap) diagnosticsNamed.insert(c.name);
    }

    const bool statistics = std::any_of(map.channels.begin(), map.channels.end(), IsStatistics);
    if (statistics && (map.channels.size() != 1 || map.channels[0].dest != ChannelLetter::L)) {
        Invalid(what, "a regionStats source is a statistics file: it must be the map's only channel, destChannel L "
                      "(decision 076)");
    }

    PlannedFile file;
    file.textureSet = root.set->name;
    file.stack = root.stack->name;
    file.textureSetId = root.set->id;
    file.stackId = root.stack->id;
    file.rootPath = root.rootPath;
    file.preset = preset.name;
    file.mapIndex = mapIndex;
    file.fileName = map.fileName;
    file.layout = statistics ? FileLayout::Statistics : LayoutOf(map.channels);

    // Sources and presence.
    std::vector<Resolved> resolved;
    for (const ChannelSpec& spec : map.channels) resolved.push_back(Resolve(project, spec, root, what));
    size_t present = 0;
    size_t absent = 0;
    bool black = false;
    std::string reason;
    for (size_t i = 0; i < resolved.size(); ++i) {
        const Resolved& r = resolved[i];
        if (r.presence == Presence::Present) ++present;
        if (r.presence == Presence::Absent) {
            ++absent;
            if (reason.empty()) reason = r.absentReason;
        }
        if (r.presence == Presence::Constant && map.channels[i].name == "black") black = true;
        if (r.source.type == SourceType::diagnosticMap && r.presence == Presence::Present) {
            diagnosticsSeen.insert(r.source.name);
        }
    }
    if (present > 0 && absent > 0) {
        Gap(what, "a map with a present source and an absent one (" + reason + ") is not recorded", kRecording);
    }
    if (present == 0 && absent == 0) {
        if (black) Gap(what, "a map of default maps only, black among them, is not recorded", kRecording);
        plan.skipped.push_back({file.textureSet, file.stack, file.rootPath, file.preset, mapIndex, map.fileName,
                                "every channel reads a defaultMap"});
        return;
    }
    if (present == 0) {
        plan.skipped.push_back({file.textureSet, file.stack, file.rootPath, file.preset, mapIndex, map.fileName, reason});
        return;
    }

    for (size_t i = 0; i < map.channels.size(); ++i) {
        const ChannelSpec& spec = map.channels[i];
        PlannedChannel channel;
        channel.dest = spec.dest;
        channel.src = spec.src;
        channel.source = resolved[i].source;
        if (!statistics) channel.component = ComponentRead(spec, channel.source, what);
        file.channels.push_back(std::move(channel));
    }
    std::stable_sort(file.channels.begin(), file.channels.end(),
                     [](const PlannedChannel& a, const PlannedChannel& b) { return a.dest < b.dest; });

    // Parameters: the preset map's, then the matching rules in list order.
    if (statistics) {
        file.width = static_cast<uint32_t>(root.set->resolution.width);
        file.height = static_cast<uint32_t>(root.set->resolution.height);
    } else {
        Parameters parameters = map.parameters;
        for (const ParameterRule& rule : config.exportParameters) {
            if (!rule.filter || Selects(*rule.filter, root, map.fileName, what)) Override(parameters, rule.parameters);
        }
        file.parameters = Require(parameters, what);
        std::tie(file.width, file.height) = SizeOf(*root.set, file.parameters->sizeLog2);
    }

    file.relativePath = ExpandName(map.fileName, root, what) + "." + Extension(file);
    file.path = JoinPath(config.exportPath, file.relativePath);
    plan.files.push_back(std::move(file));
}

json::Value SourceJson(const PlannedSource& s) {
    json::Object o{{"srcMapType", std::string(SourceTypeName(s.type))}, {"srcMapName", s.name},
                   {"components", static_cast<std::int64_t>(s.components)}};
    if (s.channel) o["channel"] = std::string(core::ToString(*s.channel));
    if (s.meshMap) o["meshMap"] = std::string(core::ToString(*s.meshMap));
    if (s.virtualMap) o["virtualMap"] = std::string(VirtualMapName(*s.virtualMap));
    if (s.constant) o["constant"] = static_cast<double>(*s.constant);
    if (s.diagnostic) o["diagnostic"] = evaluator::SourceName(*s.diagnostic);
    if (s.normalRole) o["normal"] = std::string(core::ToString(*s.normalRole));
    return o;
}

json::Value SizeJson(const SizeLog2& size) {
    if (const auto* pair = std::get_if<std::array<int, 2>>(&size)) return json::Array{(*pair)[0], (*pair)[1]};
    return std::get<int>(size);
}

json::Value FileJson(const PlannedFile& f) {
    json::Array channels;
    for (const PlannedChannel& c : f.channels) {
        channels.push_back(json::Object{{"destChannel", std::string(ChannelLetterName(c.dest))},
                                        {"srcChannel", std::string(ChannelLetterName(c.src))},
                                        {"component", static_cast<std::int64_t>(c.component)},
                                        {"source", SourceJson(c.source)}});
    }
    json::Value parameters = nullptr;
    if (f.parameters) {
        const ResolvedParameters& p = *f.parameters;
        json::Object o{{"fileFormat", std::string(FileFormatName(p.fileFormat))},
                       {"bitDepth", std::string(BitDepthName(p.bitDepth))},
                       {"dithering", p.dithering},
                       {"paddingAlgorithm", std::string(PaddingName(p.paddingAlgorithm))}};
        if (p.sizeLog2) o["sizeLog2"] = SizeJson(*p.sizeLog2);
        if (p.dilationDistance) o["dilationDistance"] = *p.dilationDistance;
        parameters = std::move(o);
    }
    return json::Object{{"textureSet", f.textureSet},
                        {"stack", f.stack},
                        {"rootPath", f.rootPath},
                        {"preset", f.preset},
                        {"map", static_cast<std::int64_t>(f.mapIndex)},
                        {"fileName", f.fileName},
                        {"relativePath", f.relativePath},
                        {"path", f.path},
                        {"layout", std::string(FileLayoutName(f.layout))},
                        {"width", static_cast<std::int64_t>(f.width)},
                        {"height", static_cast<std::int64_t>(f.height)},
                        {"parameters", std::move(parameters)},
                        {"channels", std::move(channels)}};
}

json::Value PlanBody(const ExportPlan& plan) {
    json::Array files;
    for (const PlannedFile& f : plan.files) files.push_back(FileJson(f));
    json::Array skipped;
    for (const SkippedMap& s : plan.skipped) {
        skipped.push_back(json::Object{{"textureSet", s.textureSet},
                                       {"stack", s.stack},
                                       {"rootPath", s.rootPath},
                                       {"preset", s.preset},
                                       {"map", static_cast<std::int64_t>(s.mapIndex)},
                                       {"fileName", s.fileName},
                                       {"reason", s.reason}});
    }
    return json::Object{{"schema", std::string(kPlanSchema)},
                        {"exportPath", plan.exportPath},
                        {"files", std::move(files)},
                        {"skipped", std::move(skipped)}};
}

}  // namespace

std::string_view FileLayoutName(FileLayout layout) {
    static constexpr std::array<std::string_view, 5> names{"L", "LA", "RGB", "RGBA", "statistics"};
    return names[static_cast<size_t>(layout)];
}

ExportPlan CompilePlan(const core::Project& project, const ExportConfig& config) {
    const std::string& mode = project.settings.color_management.mode;
    if (!mode.empty() && mode != "legacy") {
        throw core::NotYetSupported("export: the colour-management mode \"" + mode +
                                    "\" (its $colorSpace and encodings) is a release gap (phase1.20_pyapi-facade)");
    }
    if (project.settings.workflow != core::ProjectWorkflow::Default) {
        throw core::NotYetSupported("export: the " + std::string(core::ToString(project.settings.workflow)) +
                                    " workflow (UV tiles, $udim) is a release gap (10-python-api.md §3)");
    }
    ExportPlan plan;
    plan.exportPath = config.exportPath;
    std::set<std::string> diagnosticsSeen;
    std::set<std::string> diagnosticsNamed;
    for (size_t i = 0; i < config.exportList.size(); ++i) {
        const ExportListEntry& entry = config.exportList[i];
        const std::string what = "exportList[" + std::to_string(i) + "]";
        const Root root = ResolveRoot(project, entry.rootPath, what + ".rootPath");
        const PresetSpec& preset = PresetNamed(config, entry.exportPreset ? *entry.exportPreset : *config.defaultExportPreset);
        for (size_t m = 0; m < preset.maps.size(); ++m) {
            CompileMap(project, config, entry, root, preset, m, plan, diagnosticsNamed, diagnosticsSeen);
        }
    }
    for (const std::string& name : diagnosticsNamed) {
        if (!diagnosticsSeen.contains(name)) {
            Invalid("diagnosticMap \"" + name + "\"", "its node is in none of the exported stacks");
        }
    }
    std::map<std::string, const PlannedFile*> paths;
    for (const PlannedFile& f : plan.files) {
        const auto [it, inserted] = paths.emplace(Lower(f.relativePath), &f);
        if (!inserted) {
            throw core::NotYetSupported(
                "export: " + f.rootPath + " map \"" + f.fileName + "\" and " + it->second->rootPath + " map \"" +
                it->second->fileName + "\" both resolve to \"" + f.relativePath +
                "\"; what Painter does on such a collision is not recorded (" + std::string(kRecording) + ")");
        }
    }
    if (plan.files.empty()) {
        throw core::ValueError("export: the configuration writes no file (every requested map is absent or filtered "
                               "out); Painter refuses such an export");
    }
    plan.hash = core::Sha256Hex(json::WriteCanonical(PlanBody(plan)));
    return plan;
}

ExportPlan CompilePlan(const core::Project& project, std::string_view configJson) {
    return CompilePlan(project, ParseConfig(configJson));
}

json::Value PlanJson(const ExportPlan& plan) {
    json::Value body = PlanBody(plan);
    std::get<json::Object>(body.data)["hash"] = plan.hash;
    return body;
}

std::vector<StackFiles> FilesByStack(const ExportPlan& plan) {
    std::vector<StackFiles> out;
    for (const PlannedFile& f : plan.files) {
        auto it = std::find_if(out.begin(), out.end(), [&](const StackFiles& s) {
            return s.textureSet == f.textureSet && s.stack == f.stack;
        });
        if (it == out.end()) {
            out.push_back({f.textureSet, f.stack, {}});
            it = std::prev(out.end());
        }
        it->files.push_back(f.path);
    }
    return out;
}

std::vector<StackFiles> ListProjectTextures(const core::Project& project, std::string_view configJson) {
    return FilesByStack(CompilePlan(project, configJson));
}

render::Result<FileRaster> EvaluateFileOn(const core::Project& project, std::int64_t revision, const PlannedFile& file,
                                          const SourceInputs& inputs, const evaluator::TemplateLibrary& templates,
                                          evaluator::ITileStore& store, evaluator::TileCache& cache) {
    using evaluator::DiagnosticMap;
    const VirtualMapRequest request{file.textureSetId, file.stackId, inputs.templateId, inputs.resources,
                                    inputs.geometry};
    const evaluator::DiagnosticRequest diagnostic{file.textureSetId, file.stackId, inputs.templateId, inputs.resources,
                                                  inputs.geometry};
    FileRaster raster;
    std::map<std::string, DiagnosticMap> evaluated;  // by srcMapType/srcMapName
    for (const PlannedChannel& channel : file.channels) {
        const PlannedSource& s = channel.source;
        const std::string key = std::string(SourceTypeName(s.type)) + "/" + s.name;
        if (evaluated.contains(key) || s.type == SourceType::defaultMap) continue;
        switch (s.type) {
            case SourceType::documentMap: {
                evaluator::EvaluateRequest r;
                r.textureSet = file.textureSetId;
                r.stack = file.stackId;
                r.channel = *s.channel;
                r.templateId = inputs.templateId;
                r.resources = inputs.resources;
                r.geometry = inputs.geometry;
                render::Result<evaluator::ChannelResult> result = evaluator::EvaluateOn(project, r, templates, store, cache);
                if (!result) return render::Unexpected(result.error());
                evaluated[key] = evaluator::MapOf(*result);
                break;
            }
            case SourceType::meshMap:
            case SourceType::virtualMap: {
                render::Result<VirtualMapResult> result =
                    s.type == SourceType::meshMap
                        ? EvaluateMeshMapOn(project, revision, *s.meshMap, request, templates, store, cache)
                        : EvaluateVirtualMapOn(project, revision, *s.virtualMap, request, templates, store, cache);
                if (!result) return render::Unexpected(result.error());
                if (result->tag) raster.normalTag = result->tag;
                evaluated[key] = std::move(result->values);
                break;
            }
            case SourceType::diagnosticMap: {
                render::Result<evaluator::DiagnosticOutput> result =
                    evaluator::EvaluateDiagnosticOn(project, revision, *s.diagnostic, diagnostic, templates, store, cache);
                if (!result) return render::Unexpected(result.error());
                if (result->stats) {
                    raster.width = file.width;
                    raster.height = file.height;
                    raster.statistics = evaluator::RegionStatsJson(*result->stats);
                    return raster;
                }
                evaluated[key] = std::move(*result->map);
                break;
            }
            case SourceType::defaultMap: break;
        }
    }
    raster.width = static_cast<uint32_t>(file.width);
    raster.height = static_cast<uint32_t>(file.height);
    for (const auto& [key, map] : evaluated) {
        raster.width = map.width;
        raster.height = map.height;
    }
    raster.channels = static_cast<uint32_t>(file.channels.size());
    const size_t texels = size_t{raster.width} * raster.height;
    raster.values.resize(texels * raster.channels);
    for (uint32_t c = 0; c < raster.channels; ++c) {
        const PlannedChannel& channel = file.channels[c];
        const PlannedSource& s = channel.source;
        if (s.type == SourceType::defaultMap) {
            for (size_t t = 0; t < texels; ++t) raster.values[t * raster.channels + c] = *s.constant;
            continue;
        }
        const DiagnosticMap& map = evaluated.at(std::string(SourceTypeName(s.type)) + "/" + s.name);
        if (map.width != raster.width || map.height != raster.height || channel.component >= map.components) {
            return evaluator::EvalFail(evaluator::EvalErrorKind::Internal,
                                       "the sources of " + file.relativePath + " disagree in size or components");
        }
        for (size_t t = 0; t < texels; ++t) {
            raster.values[t * raster.channels + c] = map.values[t * map.components + channel.component];
        }
    }
    return raster;
}

}  // namespace uzp::exporter
