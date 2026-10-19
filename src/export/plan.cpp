#include "export/plan.h"

#include "export/encode.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>
#include <set>
#include <utility>

#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "evaluator/sources.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::exporter {

namespace json = core::json;

std::string RootPathOf(const core::TextureSet& set, const core::Stack& stack) {
    if (set.stacks.size() == 1 && stack.name.empty()) return set.name;
    return set.name + "/" + stack.name;
}

namespace {

using core::ChannelType;

/// The Painter recording a refusal of an unrecorded behaviour asks for (decisions 085 and 091).
constexpr std::string_view kRecording = "export-semantics recording R-091 (decision 091)";

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

/// How a source stands in one stack: `ExportError` is a source Painter lists but whose export
/// raises ValueError (decision 091).
enum class Presence : uint8_t { Present, Absent, Constant, ExportError };

struct Resolved {
    Presence presence = Presence::Present;
    PlannedSource source;
    /// Absent and ExportError: why.
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

Resolved ResolveDocument(const ChannelSpec& spec, const Root& root) {
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
        // The same pairing read the other way: the stack holds the alias member itself (recorded
        // for the pairings of decision 085 only).
        for (const auto& [type, _] : root.stack->channels) {
            if (RecordedAliasTarget(type) == member && !RaisesWhenAbsent(type)) read = type;
        }
    }
    if (!read && RaisesWhenAbsent(member)) {
        r.presence = Presence::ExportError;
        const std::optional<ChannelType> target = RecordedAliasTarget(member);
        r.absentReason = "the stack has no " + std::string(core::ToString(member)) + " channel" +
                         (target ? " and no " + std::string(core::ToString(*target)) + " channel it pairs with" : "") +
                         "; Painter's export of the legacy name \"" + spec.name + "\" raises ValueError (probe P13)";
        return r;
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
        r.presence = Presence::ExportError;
        r.absentReason = "the meshMap \"" + spec.name + "\" is not bound to the texture set " + root.set->name +
                         "; Painter's export raises ValueError (probe P12)";
        return r;
    }
    r.source.meshMap = usage;
    if (usage == core::MeshMapUsage::Normal) {
        r.source.components = 3;
        r.source.normalRole = core::MeshMapRole::geometry_only;
        return r;
    }
    const std::optional<uint32_t> components = PassThroughComponents(usage);
    if (!components) {
        Gap(what,
            "exporting the meshMap \"" + spec.name +
                "\" is not recorded (recording R-090 P7 shows ambient_occlusion, curvature and position)",
            "decision 103");
    }
    r.source.components = *components;
    return r;
}

Resolved ResolveVirtual(const ChannelSpec& spec, const Root& root, const std::string& what) {
    Resolved r;
    r.source.type = spec.type;
    r.source.name = spec.name;
    const VirtualMap map = *ParseVirtualMap(spec.name);
    const VirtualMapSupport support = Support(map);
    if (!support.supported) {
        Gap(what, "the virtualMap \"" + spec.name + "\" is not reproduced exactly", support.evidenceOrOwner);
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
        case SourceType::documentMap: return ResolveDocument(spec, root);
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
        Gap(what, "srcChannel A of a " + std::string(SourceTypeName(source.type)) +
                      " is recorded only at full and no coverage (probe P6)", kRecording);
    }
    return source.components == 1 ? 0 : LetterIndex(spec.src);
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

/// Whether `filter` selects the map `fileName` of `root`. A texture set of the Default workflow is
/// the single tile [0, 0] (probe P4, decision 091).
bool Selects(const Filter& filter, const Root& root, const std::string& fileName) {
    if (filter.dataPaths && !Contains(*filter.dataPaths, root.rootPath) && !Contains(*filter.dataPaths, root.set->name)) {
        return false;
    }
    if (filter.outputMaps && !Contains(*filter.outputMaps, fileName)) return false;
    if (filter.uvTiles && std::find(filter.uvTiles->begin(), filter.uvTiles->end(), UvTile{0, 0}) == filter.uvTiles->end()) {
        return false;
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

/// The name of `path`'s last component without its extension; a name with more than one dot is
/// not recorded (which dot ends the stem is unknown) and is refused.
std::string Stem(const std::string& path, std::string_view wildcard, const std::string& what) {
    const size_t slash = path.find_last_of("/\\");
    const std::string name = slash == std::string::npos ? path : path.substr(slash + 1);
    const size_t dot = name.find('.');
    if (dot != std::string::npos && name.find('.', dot + 1) != std::string::npos) {
        Gap(what, "$" + std::string(wildcard) + " of the file name \"" + name + "\", which holds more than one dot, is not recorded",
            kRecording);
    }
    return name.substr(0, dot);
}

/// The imported mesh's file name (its import report's source name).
std::string MeshFileName(const core::Project& project, const std::string& what) {
    if (project.mesh) {
        const auto source = project.mesh->import_report.find("source");
        if (source != project.mesh->import_report.end() && source->second.IsObject()) {
            const json::Object& o = std::get<json::Object>(source->second.data);
            const auto name = o.find("name");
            if (name != o.end() && name->second.IsString()) return std::get<std::string>(name->second.data);
        }
    }
    Invalid(what, "$mesh needs the imported mesh's file name, and the project has none");
}

/// `$colorSpace` of `file` under OCIO with Painter's substance config (decision 190), as the
/// probes of `export-ocio-encode` (steps 50 and 51, PNG 16 and 8) name it: "sRGB" for a PNG of an
/// sRGB8 BaseColor, "Raw" for a PNG whose every channel reads a document channel that is not
/// sRGB8. Any other file is not recorded and is refused.
std::string OcioColourSpace(const PlannedFile& file, const Root& root, const std::string& what) {
    constexpr std::string_view owner = "Session O, export-ocio-encode; phase1.15_compositor-colour-fits, decision 190";
    if (!file.parameters || file.parameters->fileFormat != FileFormat::png || file.channels.empty()) {
        Gap(what, "$colorSpace under OCIO is recorded for PNG files only", owner);
    }
    bool srgb = true;
    bool raw = true;
    for (const PlannedChannel& channel : file.channels) {
        const PlannedSource& s = channel.source;
        const auto it = s.type == SourceType::documentMap && s.channel ? root.stack->channels.find(*s.channel)
                                                                       : root.stack->channels.end();
        if (it == root.stack->channels.end()) {
            srgb = raw = false;
            break;
        }
        const bool srgb8 = it->second.format == core::ChannelFormat::sRGB8;
        srgb = srgb && srgb8 && *s.channel == core::ChannelType::BaseColor;
        raw = raw && !srgb8;
    }
    if (srgb) return "sRGB";
    if (raw) return "Raw";
    Gap(what, "$colorSpace under OCIO of a file that is not one sRGB8 BaseColor or only non-sRGB8 document channels "
              "is not recorded",
        owner);
}

/// The value of a wildcard in `root` for `file` (probe P1, decision 091).
std::string WildcardValue(std::string_view token, const core::Project& project, const PlanContext& context,
                          const Root& root, const PlannedFile& file, const std::string& what) {
    if (token == "textureSet") return root.set->name;
    if (token == "sceneMaterial") {
        // Recorded on a set named after its material only (probe P1).
        if (root.set->original_name != root.set->name) {
            Gap(what, "$sceneMaterial of the texture set " + root.set->name + ", renamed from its material " +
                          root.set->original_name + ", is not recorded", kRecording);
        }
        return root.set->original_name;
    }
    if (token == "mesh") return Stem(MeshFileName(project, what), token, what);
    if (token == "project") return context.projectPath.empty() ? "Untitled" : Stem(context.projectPath, token, what);
    if (token == "colorSpace" && evaluator::PainterOcio(project)) return OcioColourSpace(file, root, what);
    return {};  // colorSpace (legacy colour management), udim and uvTileName (Default workflow)
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

/// Expands `pattern` for `root` into a `/`-separated name. A `( … )` holding no parenthesis and
/// at least one wildcard is a group: dropped when its wildcards are empty, written without its
/// parentheses when they are not. Every other parenthesis is literal (probe P3, decision 091). A
/// group with both empty and non-empty wildcards, and a `)` after no literal `(`, are not
/// recorded and are refused.
std::string ExpandName(const std::string& pattern, const core::Project& project, const PlanContext& context,
                       const Root& root, const PlannedFile& file, const std::string& what) {
    // Expands the wildcards of `text`; returns whether they were empty (in a group: all or none).
    const auto expand = [&](std::string_view text, std::string& out, bool group) {
        bool empty = false;
        bool filled = false;
        for (size_t i = 0; i < text.size();) {
            if (text[i] != '$') {
                out += text[i++];
                continue;
            }
            size_t end = i + 1;
            while (end < text.size() && std::isalpha(static_cast<unsigned char>(text[end]))) ++end;
            const std::string token(text.substr(i + 1, end - i - 1));
            if (std::find(kWildcards.begin(), kWildcards.end(), token) == kWildcards.end()) {
                std::vector<std::string> valid;
                for (std::string_view w : kWildcards) valid.push_back("$" + std::string(w));
                Invalid(what, "unknown wildcard \"$" + token + "\" in \"" + pattern + "\"; valid: " +
                                  JoinNames(Nearest("$" + token, valid)));
            }
            const std::string value = WildcardValue(token, project, context, root, file, what);
            empty = empty || value.empty();
            filled = filled || !value.empty();
            out += value;
            i = end;
        }
        if (group && empty && filled) {
            Gap(what, "a ( … ) group of \"" + pattern + "\" with both an empty and a non-empty wildcard is not recorded",
                kRecording);
        }
        return empty;
    };
    std::string out;
    size_t open = 0;  // literal '(' written so far, less the literal ')' matched with them
    for (size_t i = 0; i < pattern.size();) {
        const size_t paren = pattern.find_first_of("()", i);
        expand(std::string_view(pattern).substr(i, (paren == std::string::npos ? pattern.size() : paren) - i), out,
               false);
        if (paren == std::string::npos) break;
        const size_t next = pattern.find_first_of("()", paren + 1);
        const bool group = pattern[paren] == '(' && next != std::string::npos && pattern[next] == ')' &&
                           pattern.find('$', paren) < next;
        if (!group) {
            if (pattern[paren] == '(') {
                ++open;
            } else if (open-- == 0) {
                Gap(what, "a \")\" after no literal \"(\" in \"" + pattern + "\" is not recorded", kRecording);
            }
            out += pattern[paren];
            i = paren + 1;
            continue;
        }
        std::string content;
        if (!expand(std::string_view(pattern).substr(paren + 1, next - paren - 1), content, true)) out += content;
        i = next + 1;
    }
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
void CompileMap(const core::Project& project, const PlanContext& context, const ExportConfig& config,
                const ExportListEntry& entry, const Root& root, const PresetSpec& preset, size_t mapIndex,
                ExportPlan& plan, std::set<std::string>& diagnosticsNamed, std::set<std::string>& diagnosticsSeen) {
    const MapSpec& map = preset.maps[mapIndex];
    const std::string what = Describe(root, preset, mapIndex, map);
    if (entry.filter && !Selects(*entry.filter, root, map.fileName)) return;
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
    std::vector<ChannelSpec> specs = map.channels;
    std::vector<Resolved> resolved;
    for (const ChannelSpec& spec : specs) resolved.push_back(Resolve(project, spec, root, what));
    const auto skip = [&](std::string reason, SkipKind kind) {
        plan.skipped.push_back(
            {file.textureSet, file.stack, file.rootPath, file.preset, mapIndex, map.fileName, std::move(reason), kind});
    };
    for (const Resolved& r : resolved) {
        if (r.presence == Presence::ExportError) return skip(r.absentReason, SkipKind::export_error);
    }
    const auto count = [&](Presence presence) {
        return std::count_if(resolved.begin(), resolved.end(), [&](const Resolved& r) { return r.presence == presence; });
    };
    const auto absentAt = [&](ChannelLetter dest) {
        for (size_t i = 0; i < specs.size(); ++i) {
            if (specs[i].dest == dest) return resolved[i].presence == Presence::Absent;
        }
        return false;
    };
    // An absent documentMap as the alpha of present R, G and B: the file is R+G+B (probe P7).
    if (file.layout == FileLayout::RGBA && count(Presence::Present) == 3 && count(Presence::Absent) == 1 &&
        absentAt(ChannelLetter::A)) {
        for (size_t i = specs.size(); i-- > 0;) {
            if (specs[i].dest != ChannelLetter::A) continue;
            specs.erase(specs.begin() + static_cast<std::ptrdiff_t>(i));
            resolved.erase(resolved.begin() + static_cast<std::ptrdiff_t>(i));
        }
        file.layout = FileLayout::RGB;
    }
    std::string reason;
    for (const Resolved& r : resolved) {
        if (r.presence == Presence::Absent && reason.empty()) reason = r.absentReason;
        if (r.source.type == SourceType::diagnosticMap && r.presence == Presence::Present) {
            diagnosticsSeen.insert(r.source.name);
        }
    }
    const auto present = count(Presence::Present);
    const auto absent = count(Presence::Absent);
    if (present > 0 && absent > 0) {
        Gap(what, "a map with a present source and an absent one (" + reason + ") is not recorded", kRecording);
    }
    if (present == 0 && absent == 0) {
        const auto black = std::count_if(specs.begin(), specs.end(), [](const ChannelSpec& c) { return c.name == "black"; });
        if (black == static_cast<std::ptrdiff_t>(specs.size())) {
            return skip("every channel reads defaultMap black; Painter lists the map and writes nothing (probe P8)",
                        SkipKind::not_written);
        }
        if (black > 0) Gap(what, "a map of black and white default maps is not recorded", kRecording);
        return skip("every channel reads defaultMap white", SkipKind::absent);
    }
    if (present == 0) return skip(reason, SkipKind::absent);

    for (size_t i = 0; i < specs.size(); ++i) {
        const ChannelSpec& spec = specs[i];
        PlannedChannel channel;
        channel.dest = spec.dest;
        channel.src = spec.src;
        channel.source = resolved[i].source;
        if (!statistics) {
            channel.component = ComponentRead(spec, channel.source, what);
            channel.luma = channel.source.type != SourceType::defaultMap && channel.source.components == 3 &&
                           spec.src == ChannelLetter::L;
        }
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
            if (!rule.filter || Selects(*rule.filter, root, map.fileName)) Override(parameters, rule.parameters);
        }
        file.parameters = Require(parameters, what);
        std::tie(file.width, file.height) = SizeOf(*root.set, file.parameters->sizeLog2);
    }

    file.relativePath = ExpandName(map.fileName, project, context, root, file, what) + "." + Extension(file);
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
                                        {"luma", c.luma},
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
                                       {"reason", s.reason},
                                       {"kind", std::string(SkipKindName(s.kind))}});
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

std::string_view SkipKindName(SkipKind kind) {
    static constexpr std::array<std::string_view, 3> names{"absent", "not_written", "export_error"};
    return names[static_cast<size_t>(kind)];
}

ExportPlan CompilePlan(const core::Project& project, const ExportConfig& config, const PlanContext& context) {
    const std::string& mode = project.settings.color_management.mode;
    if (!mode.empty() && mode != "legacy" && !evaluator::PainterOcio(project)) {
        throw core::NotYetSupported("export: the colour-management mode \"" + mode +
                                    "\" with this configuration (its $colorSpace and encodings) is not recorded: "
                                    "legacy and OCIO with Painter's substance config are (decision 190)");
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
        const size_t first = plan.files.size();
        for (size_t m = 0; m < preset.maps.size(); ++m) {
            CompileMap(project, context, config, entry, root, preset, m, plan, diagnosticsNamed, diagnosticsSeen);
        }
        // Two maps of one entry resolving to one path: the later one gets `_1` before its
        // extension (probe P9, decision 091).
        std::map<std::string, bool> seen;  // path -> made by a rename
        for (size_t f = first; f < plan.files.size(); ++f) {
            PlannedFile& file = plan.files[f];
            const auto existing = seen.find(file.relativePath);
            if (existing == seen.end()) {
                seen.emplace(file.relativePath, false);
                continue;
            }
            const size_t dot = file.relativePath.rfind('.');
            const std::string renamed = file.relativePath.substr(0, dot) + "_1" + file.relativePath.substr(dot);
            if (existing->second || seen.contains(renamed)) {
                Gap(file.rootPath + " map \"" + file.fileName + "\"",
                    "a third map resolving to \"" + file.relativePath + "\" (after a `_1` rename) is not recorded",
                    kRecording);
            }
            file.relativePath = renamed;
            file.path = JoinPath(config.exportPath, file.relativePath);
            seen.emplace(renamed, true);
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
    plan.hash = core::Sha256Hex(json::WriteCanonical(PlanBody(plan)));
    return plan;
}

ExportPlan CompilePlan(const core::Project& project, std::string_view configJson, const PlanContext& context) {
    return CompilePlan(project, ParseConfig(configJson), context);
}

void CheckExportable(const ExportPlan& plan) {
    for (const SkippedMap& s : plan.skipped) {
        if (s.kind != SkipKind::export_error) continue;
        const std::string what = "export: " + s.rootPath + ": preset \"" + s.preset + "\" map " +
                                 std::to_string(s.mapIndex) + " (\"" + s.fileName + "\"): " + s.reason;
        // Recorded only where no other file is written (probes P12, P13): whether Painter writes
        // the other files before it raises is not known.
        if (!plan.files.empty()) {
            throw core::NotYetSupported(what + "; an export that also writes other files is not recorded (" +
                                        std::string(kRecording) + ")");
        }
        throw core::ValueError(what);
    }
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

std::vector<StackFiles> ListProjectTextures(const core::Project& project, std::string_view configJson,
                                            const PlanContext& context) {
    const ExportPlan plan = CompilePlan(project, configJson, context);
    CheckExportable(plan);
    return FilesByStack(plan);
}

namespace {

/// The stack channel whose read-out (its template base included) a source's values depend on:
/// a documentMap's channel, the channel a diagnosticMap isolates, compares, summarises, views or
/// checks for leaks (a non-ID materialLeaks view compares the channel's full and solo read-outs).
/// None for the other sources (mesh maps; the virtual normals read Height and Normal, whose bases
/// are observed or fitted; the material masks read masks; the ID views read the ID mesh map).
std::optional<ChannelType> ChannelRead(const PlannedSource& s) {
    if (s.type == SourceType::documentMap) return s.channel;
    if (s.type != SourceType::diagnosticMap || !s.diagnostic) return std::nullopt;
    using Kind = evaluator::DiagnosticSource::Kind;
    const evaluator::DiagnosticSource& d = *s.diagnostic;
    if (d.kind == Kind::Isolated || d.kind == Kind::Contribution || d.kind == Kind::RegionStats) {
        if (d.map.kind == evaluator::DiagnosticMapId::Kind::Channel) return d.map.channel;
        return std::nullopt;
    }
    if ((d.kind == Kind::MaterialView || d.kind == Kind::MaterialLeaks) && d.view != evaluator::MaterialViewKind::ID) {
        return evaluator::MaterialViewChannel(d.view);
    }
    return std::nullopt;
}

/// Refuses (`unsupported_source`) a file whose values depend on channel `type` of the file's stack
/// when that channel's base value is `inferred` (templates.h): a range of linear values writes
/// the template's recorded 16-bit PNG code, so no output built on it is exact, whatever the
/// channel's format (decision 126). A channel the stack lacks is left to the evaluation.
render::Result<void> RequireIdentifiedChannel(const core::Project& project, core::Id textureSet, core::Id stackId,
                                              ChannelType type, std::string_view templateId,
                                              const evaluator::TemplateLibrary& templates) {
    const core::Stack* stack = core::FindStack(project, textureSet, stackId);
    if (stack == nullptr) return {};
    const auto it = stack->channels.find(type);
    if (it == stack->channels.end()) return {};
    render::Result<const evaluator::TemplateChannel*> base = templates.BaseChannel(templateId, type, it->second.format);
    if (!base) return render::Unexpected(base.error());
    if ((*base)->baseProvenance != "inferred") return {};
    return evaluator::EvalFail(evaluator::EvalErrorKind::UnsupportedSource,
                               "the base value of the channel " + std::string(core::ToString(type)) + " in template '" +
                                   std::string(templateId) +
                                   "' is inferred from its 16-bit PNG export only (an OpenEXR export of the empty "
                                   "channel on this template settles it; decision 126)");
}

}  // namespace

render::Result<void> RequireIdentifiedBase(const core::Project& project, core::Id textureSet, core::Id stack,
                                           const PlannedSource& source, std::string_view templateId,
                                           const evaluator::TemplateLibrary& templates) {
    const std::optional<ChannelType> read = ChannelRead(source);
    if (!read) return {};
    return RequireIdentifiedChannel(project, textureSet, stack, *read, templateId, templates);
}

bool SrgbEncodedOnExport(ChannelType type) {
    return type == ChannelType::BaseColor || type == ChannelType::Specular || type == ChannelType::Emissive;
}

bool SrgbEncodedRead(ChannelType type, core::ChannelFormat format, ChannelLetter src) {
    if (!SrgbEncodedOnExport(type)) return false;
    return format == core::ChannelFormat::sRGB8 || (format == core::ChannelFormat::L8 && src != ChannelLetter::G);
}

render::Result<FileRaster> EvaluateFileOn(const core::Project& project, std::int64_t revision, const PlannedFile& file,
                                          const SourceInputs& inputs, const evaluator::TemplateLibrary& templates,
                                          evaluator::ITileStore& store, evaluator::TileCache& cache) {
    using evaluator::DiagnosticMap;
    const VirtualMapRequest request{file.textureSetId, file.stackId, inputs.templateId, inputs.resources,
                                    inputs.geometry};
    const evaluator::DiagnosticRequest diagnostic{file.textureSetId, file.stackId, inputs.templateId, inputs.resources,
                                                  inputs.geometry, inputs.materialViews};
    FileRaster raster;
    std::map<std::string, DiagnosticMap> evaluated;  // by srcMapType/srcMapName
    std::map<std::string, core::ChannelFormat> stored;  // documentMap sources: the channel's format
    for (const PlannedChannel& channel : file.channels) {
        const PlannedSource& s = channel.source;
        const std::string key = std::string(SourceTypeName(s.type)) + "/" + s.name;
        if (evaluated.contains(key) || s.type == SourceType::defaultMap) continue;
        render::Result<void> identified =
            RequireIdentifiedBase(project, file.textureSetId, file.stackId, s, inputs.templateId, templates);
        if (!identified) return render::Unexpected(identified.error());
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
                // An sRGB8 or L8 BaseColor, Specular or Emissive is read out linear, its template
                // constant included, and written to PNG sRGB-encoded (SrgbEncodedRead).
                stored[key] = result->format;
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
    raster.srgbEncoded.assign(raster.channels, 0);
    raster.documentFormat.assign(raster.channels, std::nullopt);
    for (uint32_t c = 0; c < raster.channels; ++c) {
        const PlannedChannel& channel = file.channels[c];
        const PlannedSource& s = channel.source;
        if (s.type == SourceType::defaultMap) {
            for (size_t t = 0; t < texels; ++t) raster.values[t * raster.channels + c] = *s.constant;
            continue;
        }
        const std::string key = std::string(SourceTypeName(s.type)) + "/" + s.name;
        const auto format = stored.find(key);
        raster.srgbEncoded[c] =
            format != stored.end() && SrgbEncodedRead(*s.channel, format->second, channel.src) ? 1 : 0;
        if (format != stored.end() && !channel.luma) raster.documentFormat[c] = format->second;
        const DiagnosticMap& map = evaluated.at(key);
        if (map.width != raster.width || map.height != raster.height || channel.component >= map.components) {
            return evaluator::EvalFail(evaluator::EvalErrorKind::Internal,
                                       "the sources of " + file.relativePath + " disagree in size or components");
        }
        if (channel.luma) {
            // Rec. 601 luma of the linear components, Painter 12.1.5's order of operations (probe
            // P5): the green product, then fused into red, then into blue.
            for (size_t t = 0; t < texels; ++t) {
                const float* rgb = &map.values[t * map.components];
                raster.values[t * raster.channels + c] =
                    std::fma(0.114f, rgb[2], std::fma(0.299f, rgb[0], 0.587f * rgb[1]));
            }
            continue;
        }
        for (size_t t = 0; t < texels; ++t) {
            raster.values[t * raster.channels + c] = map.values[t * map.components + channel.component];
        }
    }
    raster.ocio = evaluator::PainterOcio(project);
    if (raster.ocio && file.parameters && file.parameters->fileFormat == FileFormat::png) {
        // Session O records the PNG encode of an sRGB-encoded channel for the stored sRGB8 codes and
        // the empty BaseColor only (encode.h, decision 190).
        for (uint32_t c = 0; c < raster.channels; ++c) {
            if (raster.srgbEncoded[c] == 0) continue;
            for (size_t t = 0; t < texels; ++t) {
                const float v = raster.values[t * raster.channels + c];
                if (OcioSrgbPng16Code(v)) continue;
                return evaluator::EvalFail(evaluator::EvalErrorKind::UnsupportedSource,
                                           "under OCIO, the PNG encode of the linear value " + std::to_string(v) + " of " +
                                               file.relativePath +
                                               " is not recorded (Session O records the sRGB8 codes and the empty "
                                               "BaseColor; phase1.15_compositor-colour-fits, decision 190)");
            }
        }
    }
    return raster;
}

}  // namespace uzp::exporter
