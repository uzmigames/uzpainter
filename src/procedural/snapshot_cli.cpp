#include "procedural/snapshot_cli.h"

#include "evaluator/support.h"
#include "procedural/admission.h"
#include "procedural/snapshot_recording.h"
#include "procedural/snapshot_backend.h"
#include "procedural/snapshot_source.h"
#include "python/interpreter.h"
#include "store/snapshots.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"

#include <Python.h>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <memory>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

namespace uzp::procedural {
namespace {
namespace fs = std::filesystem;
namespace json = core::json;

std::string Utf8(const fs::path& path) {
    const auto text = path.generic_u8string();
    return std::string(text.begin(), text.end());
}

fs::path Path(std::string_view text) { return fs::path(std::u8string(text.begin(), text.end())); }

struct ReleasePython {
    void operator()(PyObject* object) const { Py_XDECREF(object); }
};
using PythonObject = std::unique_ptr<PyObject, ReleasePython>;

std::runtime_error PythonError() {
    PythonObject error(PyErr_GetRaisedException());
    PythonObject message(error ? PyObject_Str(error.get()) : nullptr);
    const char* text = message ? PyUnicode_AsUTF8(message.get()) : nullptr;
    return std::runtime_error(text ? text : "Painter snapshot bridge failed");
}

void RunBridge(const fs::path& work) {
    const std::string error = python::Start();
    if (!error.empty()) throw std::runtime_error(error);
    struct Stop { ~Stop() { python::Stop(); } } stop;
    PythonObject module(PyImport_ImportModule("uzpainter_snapshot.bridge"));
    if (!module) throw PythonError();
    PythonObject function(PyObject_GetAttrString(module.get(), "main"));
    PythonObject args(PyList_New(0));
    if (!function || !args) throw PythonError();
    for (const fs::path& path : {work / "context.json", work / "request.json", work}) {
        const std::wstring value = path.wstring();
        PythonObject item(PyUnicode_FromWideChar(value.data(), static_cast<Py_ssize_t>(value.size())));
        if (!item || PyList_Append(args.get(), item.get()) != 0) throw PythonError();
    }
    PythonObject result(PyObject_CallFunctionObjArgs(function.get(), args.get(), nullptr));
    if (!result) throw PythonError();
    if (PyLong_AsLong(result.get()) != 0 || PyErr_Occurred()) throw PythonError();
}

std::string Read(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("cannot read " + Utf8(path));
    std::ostringstream text;
    text << stream.rdbuf();
    if (stream.bad()) throw std::runtime_error("cannot finish reading " + Utf8(path));
    return text.str();
}

void Write(const fs::path& path, std::string_view text) {
    std::ofstream stream(path, std::ios::binary);
    stream.write(text.data(), static_cast<std::streamsize>(text.size()));
    stream.close();
    if (!stream) throw std::runtime_error("cannot write " + Utf8(path));
}

const json::Object& Object(const json::Value& value) { return std::get<json::Object>(value.data); }
std::string String(const json::Object& value, std::string_view key) {
    return std::get<std::string>(value.at(std::string(key)).data);
}

fs::path BinaryDirectory() {
    std::wstring value(32768, L'\0');
    const DWORD size = GetModuleFileNameW(nullptr, value.data(), static_cast<DWORD>(value.size()));
    if (size == 0 || size == value.size()) throw std::runtime_error("cannot locate installed recorder");
    value.resize(size);
    return fs::path(value).parent_path();
}

void CheckCaptureDomain(const core::Project& project, std::string_view mesh, std::string_view plane) {
    const auto& settings = project.settings;
    const auto& colour = settings.color_management;
    if (!project.mesh || mesh != plane || project.mesh->resource != core::Sha256Hex(mesh)) {
        throw std::runtime_error("snapshot recording requires the exact shipped full-UV plane mesh");
    }
    if (settings.normal_map_format != core::NormalMapFormat::OpenGL ||
        settings.tangent_space != core::TangentSpace::PerVertex || settings.mesh_unit_scale != 1.0 ||
        settings.workflow != core::ProjectWorkflow::Default || (!colour.mode.empty() && colour.mode != "legacy") ||
        !colour.config_hash.empty() || !colour.working_space.empty() || !colour.io_rules.empty()) {
        throw std::runtime_error("snapshot recording requires Legacy, OpenGL, PerVertex, default workflow and mesh scale 1");
    }
}

void Print(std::FILE* out, const json::Object& report) {
    std::fprintf(out, "UZP_JSON:%s\n", json::WriteCanonical(report).c_str());
    // Flushed here: a buffered report was observed lost at process exit (exit code kept).
    std::fflush(out);
}

/// A refusal of `assets bind-snapshot`: printed as `refused`, nothing was written.
struct BindRefusal : std::runtime_error {
    using std::runtime_error::runtime_error;
};

/// One `assets bind-snapshot` request: exactly `signature_sha256`, `node`, `channel` and
/// `resolution_override` (null: deliberately absent; otherwise exactly `mode`, `value` and
/// `log2_offset`). Nothing is defaulted.
struct BindRequest {
    std::string signature;
    core::Id node = core::kNoId;
    core::ChannelType channel{};
    std::optional<core::ProceduralResolution> override;
    json::Value overrideJson;  ///< As supplied, for the operation's arguments.
};

int64_t Int(const json::Value& value, std::string_view what) {
    if (!value.IsInt()) throw BindRefusal(std::string(what) + " must be an integer");
    return std::get<int64_t>(value.data);
}

BindRequest ParseBindRequest(const json::Value& value) {
    const auto* object = std::get_if<json::Object>(&value.data);
    if (object == nullptr || object->size() != 4 || !object->contains("signature_sha256") || !object->contains("node") ||
        !object->contains("channel") || !object->contains("resolution_override")) {
        throw BindRefusal("request requires exactly signature_sha256, node, channel and resolution_override");
    }
    BindRequest request;
    const json::Value& signature = object->at("signature_sha256");
    if (!signature.IsString() || !core::IsSha256Hex(std::get<std::string>(signature.data))) {
        throw BindRefusal("signature_sha256 must be a lowercase SHA-256");
    }
    request.signature = std::get<std::string>(signature.data);
    const int64_t node = Int(object->at("node"), "node");
    if (node <= 0) throw BindRefusal("node must be a positive node uid");
    request.node = static_cast<core::Id>(node);
    const json::Value& channel = object->at("channel");
    const auto parsed = channel.IsString() ? core::FromString<core::ChannelType>(std::get<std::string>(channel.data))
                                           : std::nullopt;
    if (!parsed) throw BindRefusal("channel must name a channel type");
    request.channel = *parsed;
    request.overrideJson = object->at("resolution_override");
    if (request.overrideJson.IsNull()) return request;
    const auto* r = std::get_if<json::Object>(&request.overrideJson.data);
    if (r == nullptr || r->size() != 3 || !r->contains("mode") || !r->contains("value") || !r->contains("log2_offset")) {
        throw BindRefusal("resolution_override must be null or exactly mode, value and log2_offset");
    }
    const json::Value& mode = r->at("mode");
    const auto parsedMode = mode.IsString() ? core::FromString<core::ProceduralResolutionMode>(
                                                  std::get<std::string>(mode.data))
                                            : std::nullopt;
    if (!parsedMode) throw BindRefusal("resolution_override.mode must name a resolution mode");
    const auto* sizes = std::get_if<json::Array>(&r->at("value").data);
    if (sizes == nullptr || sizes->size() != 2) throw BindRefusal("resolution_override.value must be two integers");
    const auto bounded = [](const json::Value& item, std::string_view what) {
        const int64_t number = Int(item, what);
        if (number < std::numeric_limits<int>::min() || number > std::numeric_limits<int>::max()) {
            throw BindRefusal(std::string(what) + " is outside the signed-int range");
        }
        return static_cast<int>(number);
    };
    core::ProceduralResolutionOverride resolution;
    resolution.mode = *parsedMode;
    resolution.value = {bounded((*sizes)[0], "resolution_override.value"),
                        bounded((*sizes)[1], "resolution_override.value")};
    resolution.log2_offset = bounded(r->at("log2_offset"), "resolution_override.log2_offset");
    request.override = resolution;
    return request;
}

/// The fill layer `node`, its owning set and stack, checked before any transaction: a fill layer
/// (fill effects are not claimed) outside every mask list, with a split fill whose `channel` is
/// an active User channel of its stack in L32F.
struct BindTarget {
    const core::Layer* layer = nullptr;
    const core::TextureSet* set = nullptr;
    core::ChannelFormat format{};
};

BindTarget FindBindTarget(const core::Project& project, core::Id node, core::ChannelType channel) {
    std::optional<core::NodeVisit> found;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if ((visit.layer != nullptr && visit.layer->uid == node) || (visit.effect != nullptr && visit.effect->uid == node)) {
            found = visit;
        }
    });
    if (!found) throw BindRefusal("node " + std::to_string(node) + " does not exist");
    if (found->effect != nullptr) throw BindRefusal("node " + std::to_string(node) + " is an effect; only fill layers are bound");
    if (found->owner_stack == core::NodeStack::Mask) throw BindRefusal("node " + std::to_string(node) + " is in a mask");
    const core::Layer& layer = *found->layer;
    if (layer.kind != core::LayerKind::fill || !layer.fill) {
        throw BindRefusal("node " + std::to_string(node) + " is not a fill layer");
    }
    if (layer.fill->source_mode != core::SourceMode::Split) throw BindRefusal("the fill layer is not in split source mode");
    BindTarget target{&layer};
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.id == found->texture_set) target.set = &set;
    }
    const core::Stack* stack = core::FindStack(project, found->texture_set, found->stack);
    if (target.set == nullptr || stack == nullptr) throw BindRefusal("the fill layer has no owning stack");
    const auto entry = stack->channels.find(channel);
    if (!core::ToString(channel).starts_with("User") || entry == stack->channels.end() ||
        entry->second.format != core::ChannelFormat::L32F || !layer.fill->active_channels.contains(channel)) {
        throw BindRefusal("channel " + std::string(core::ToString(channel)) +
                          " is not an active User L32F channel of the fill layer's stack");
    }
    target.format = entry->second.format;
    return target;
}

/// The stored snapshot `signature` of `project` (store `uuid`): its entry, request and backend.
struct BoundSnapshot {
    store::SnapshotEntry entry;
    ProceduralRequest request;
    SnapshotBackend backend;
};

BoundSnapshot FindSnapshot(store::ProjectStore& store, const core::Project& project, const std::string& signature) {
    std::optional<store::SnapshotEntry> entry;
    for (store::SnapshotEntry& candidate : store::ProjectSnapshots(project)) {
        if (candidate.key == signature) entry = std::move(candidate);
    }
    if (!entry) throw BindRefusal("the project holds no snapshot with signature " + signature);
    if (const std::string problem = store::SnapshotProblem(*entry, store.project_uuid()); !problem.empty()) {
        throw BindRefusal("the snapshot entry is refused: " + problem);
    }
    auto request = RequestFromSignature(entry->signature);
    if (!request) throw BindRefusal("the snapshot signature is refused: " + request.error());
    if (request->preset || !request->inputs.empty() || request->outputId.empty() ||
        request->output.format != ChannelFormat::F32 || request->output.colourSpace != "raw" ||
        request->output.channels != 1) {
        throw BindRefusal("the snapshot lies outside the bindable domain (no preset, no image inputs, one named raw F32 scalar output)");
    }
    auto backend = SnapshotBackend::Load(store, project);
    if (!backend) throw BindRefusal("the project's snapshots are refused: " + backend.error());
    if (const auto stored = backend->Stored(*request); !stored) throw BindRefusal(stored.error().Describe());
    return {std::move(*entry), std::move(*request), std::move(*backend)};
}

/// The fill source `ref` bound to `channel` of `node`, served by the provider of `project`
/// exactly as the snapshot `signature`, or the refusal.
void CheckServed(store::ProjectStore& store, const core::Project& project, const core::Id node,
                 core::ChannelType channel, const core::ProceduralRef& ref, const std::string& signature) {
    const BindTarget target = FindBindTarget(project, node, channel);
    const SnapshotSourceProvider provider(store, project);
    const auto image = provider.Resolve(project, *target.set, channel, target.format, *target.layer->fill, ref, node, false);
    if (!image) throw BindRefusal(image.error().reason);
    if ((*image)->signature != signature) throw BindRefusal("the provider serves another signature than the request's");
}
}  // namespace

int RunSnapshotCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    if (args.size() != 5 || args[0] != "assets" || args[1] != "snapshot" || args[3] != "--request") {
        std::fputs("usage: UzPainter.exe assets snapshot <file.uzp> --request <request.json>\n", err);
        return 2;
    }
    fs::path work;
    try {
        const fs::path bin = BinaryDirectory();
        const fs::path bridge = bin / "python" / "uzpainter_snapshot" / "bridge.py";
        const std::string bridgeHash = core::Sha256Hex(Read(bridge));
        const fs::path painterSide = bridge.parent_path() / "painter_side.py";
        const std::string painterSideHash = core::Sha256Hex(Read(painterSide));
        const json::Value requested = json::Parse(Read(Path(args[4])));
        const auto& requestObject = Object(requested);
        if (requestObject.size() != 2 || !requestObject.contains("parameters")) {
            throw std::runtime_error("request requires exactly resource and parameters");
        }
        const std::string resource = String(requestObject, "resource");
        auto opened = store::ProjectStore::Open(Path(args[2]));
        core::Document document(std::move(opened.state));
        opened.store->Attach(document);
        const auto state = document.snapshot();
        const auto& project = *state.project;
        if (!project.mesh) throw std::runtime_error("snapshot recording requires an imported plane mesh");
        const std::string mesh = opened.store->ReadResource(project.mesh->resource);
        CheckCaptureDomain(project, mesh, Read(bin / "assets" / "snapshot" / "plane.obj"));
        const wchar_t* local = _wgetenv(L"LOCALAPPDATA");
        if (local == nullptr || *local == L'\0') throw std::runtime_error("LOCALAPPDATA is not set");
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        work = fs::path(local) / "UzPainter" / "snapshot-recordings" /
               (std::to_string(GetCurrentProcessId()) + "-" + std::to_string(stamp));
        if (!fs::create_directories(work)) throw std::runtime_error("snapshot work directory already exists");
        Write(work / "mesh.obj", mesh);
        Write(work / "request.json", json::WriteCanonical(requested));
        json::Object settings;
        for (const auto& [name, value] : EvaluationSettings(project)) settings[name] = ParamJson(value);
        const json::Object context{{"project_uuid", opened.store->project_uuid()},
                                   {"revision", document.revision()}, {"settings", settings},
                                   {"mesh_path", Utf8(work / "mesh.obj")}, {"bridge_sha256", bridgeHash},
                                   {"painter_side_sha256", painterSideHash}};
        Write(work / "context.json", json::WriteCanonical(context));
        RunBridge(work);
        if (core::Sha256Hex(Read(bridge)) != bridgeHash || core::Sha256Hex(Read(painterSide)) != painterSideHash) {
            throw std::runtime_error("installed recorder changed during capture");
        }
        const json::Value capture = json::Parse(Read(work / "capture.json"));
        const auto& receipt = Object(capture);
        if (String(receipt, "schema") != "uzpainter/procedural-capture/1" ||
            String(receipt, "project_uuid") != opened.store->project_uuid() ||
            std::get<int64_t>(receipt.at("revision").data) != document.revision() ||
            String(receipt, "resource") != resource) throw std::runtime_error("capture identity differs from request");
        const auto parsed = RequestFromSignature(receipt.at("signature"));
        if (!parsed) throw std::runtime_error(parsed.error());
        const ProceduralRequest& request = *parsed;
        if (core::FormatAssetUrl(request.asset) != "uzasset://snapshot/" + core::Sha256Hex(resource) + "@1" ||
            request.output != RasterSpec{128, ChannelFormat::F32, "raw", 1} || request.preset ||
            !request.inputs.empty() || request.meshClass != "quad" || request.uvTiles != 1 || request.outputId.empty()) {
            throw std::runtime_error("capture signature lies outside the supported domain");
        }
        // Only the receipt's explicit, paired readback gives the observations; nothing is inferred.
        const auto observed = ReceiptSourceMetadata(capture, resource, request);
        if (!observed) throw std::runtime_error("capture observations: " + observed.error());
        std::string scalarExport;
        std::string scalarTexels;
        const auto& hashes = Object(receipt.at("files"));
        for (int repeat = 1; repeat <= 2; ++repeat) {
            for (int channel = 0; channel <= 1; ++channel) {
                const std::string name = "export" + std::to_string(repeat) + "/user" + std::to_string(channel) + ".exr";
                const std::string bytes = Read(work / name);
                if (core::Sha256Hex(bytes) != String(hashes, name)) throw std::runtime_error("capture file hash differs");
                RasterSpec spec = request.output;
                spec.channels = channel == 0 ? 1 : 3;
                const auto texels = SnapshotExportTexels(bytes, spec);
                if (!texels) throw std::runtime_error(texels.error());
                if (repeat == 1 && channel == 0) { scalarExport = bytes; scalarTexels = *texels; }
                for (size_t pixel = 0; pixel < size_t{128 * 128}; ++pixel) {
                    for (uint32_t component = 0; component < spec.channels; ++component) {
                        if (texels->compare((pixel * spec.channels + component) * 4, 4, scalarTexels, pixel * 4, 4) != 0) {
                            throw std::runtime_error("paired scalar/RGB or repeated capture differs at native float32 precision");
                        }
                    }
                }
            }
        }
        const auto outcome = RecordSnapshotExport(*opened.store, document, request, scalarExport,
                                                  opened.store->project_uuid(), document.revision(), *observed);
        if (!outcome) throw std::runtime_error(outcome.error());
        if (!outcome->result || outcome->result->status != core::ResultStatus::committed) {
            throw std::runtime_error("snapshot transaction did not commit");
        }
        opened.store->Save(document);
        const int64_t recordedRevision = document.revision();
        opened.store->Close();
        auto reopened = store::ProjectStore::Open(Path(args[2]));
        const auto backend = SnapshotBackend::Load(*reopened.store, reopened.state.project);
        if (!backend) throw std::runtime_error("saved snapshot backend did not reload: " + backend.error());
        const auto stored = backend->Stored(request);
        if (!stored || (*stored)->bytes != scalarTexels) {
            throw std::runtime_error("saved snapshot did not serve the captured texels exactly after reopen");
        }
        const auto storedObservations = backend->Metadata(request);
        if (!storedObservations || *storedObservations != *observed) {
            throw std::runtime_error("saved snapshot did not keep the captured observations after reopen");
        }
        Print(out, {{"status", "ok"}, {"asset", core::FormatAssetUrl(request.asset)},
                    {"signature_sha256", SignatureHash(request)}, {"revision", recordedRevision},
                    {"verified_after_reopen", true},
                    {"receipt", Utf8(work / "capture.json")}});
        return 0;
    } catch (const std::exception& error) {
        Print(out, {{"status", "host_error"}, {"error", error.what()}, {"work", Utf8(work)}});
        return 3;
    }
}

int RunBindSnapshotCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    if (args.size() != 5 || args[0] != "assets" || args[1] != "bind-snapshot" || args[3] != "--request") {
        std::fputs("usage: UzPainter.exe assets bind-snapshot <file.uzp> --request <bind.json>\n", err);
        return 2;
    }
    try {
        json::Value requested;
        try {
            requested = json::Parse(Read(Path(args[4])));
        } catch (const json::ParseError& error) {
            throw BindRefusal(std::string("request is not JSON: ") + error.what());
        }
        const BindRequest bind = ParseBindRequest(requested);
        const std::string channelName(core::ToString(bind.channel));
        auto opened = store::ProjectStore::Open(Path(args[2]));
        core::Document document(std::move(opened.state));
        opened.store->Attach(document);
        store::ProjectStore& store = *opened.store;
        const auto state = document.snapshot();
        const core::Project& project = *state.project;
        BoundSnapshot snapshot = FindSnapshot(store, project, bind.signature);
        const BindTarget target = FindBindTarget(project, bind.node, bind.channel);
        // The complete selected signature, an explicit channel mapping and the supplied override.
        core::ProceduralRef ref;
        ref.asset = core::FormatAssetUrl(snapshot.request.asset);
        ref.params = Object(Object(snapshot.entry.signature).at("params"));
        ref.output_mapping = {{channelName, snapshot.request.outputId}};
        ref.resolution_override = bind.override;
        // The context is the target's own: its set, settings, dimensions and the ref's seed.
        const auto context = SnapshotUseContext(project, *target.set, ref, snapshot.request.outputId);
        if (!context) throw BindRefusal(context.error());
        const AssetLibrary library;
        const auto effective = RequestFor(ref, *context, library);
        if (!effective) throw BindRefusal(effective.error().Describe());
        if (SignatureHash(*effective) != bind.signature) {
            throw BindRefusal("in the target's context the bound source is not the snapshot's signature (effective resolution " +
                              std::to_string(effective->output.resolution) + ", snapshot " +
                              std::to_string(snapshot.request.output.resolution) + ")");
        }
        core::Project candidate = project;
        core::FindLayer(candidate, bind.node)->fill->sources[bind.channel] = core::Source{core::ProceduralSource{ref}};
        CheckServed(store, candidate, bind.node, bind.channel, ref, bind.signature);
        const json::Object identity{{"signature_sha256", bind.signature},
                                    {"node", static_cast<int64_t>(bind.node)},
                                    {"channel", channelName}};
        const auto current = target.layer->fill->sources.find(bind.channel);
        if (current != target.layer->fill->sources.end() && current->second == core::Source{core::ProceduralSource{ref}}) {
            json::Object report = identity;
            report["status"] = "unchanged";
            report["revision"] = document.revision();
            Print(out, report);
            return 0;
        }
        // The key names the base revision: replaying A after A->B->A would otherwise return A's
        // stored outcome and leave B bound.
        const int64_t base = document.revision();
        json::Object arguments = identity;
        arguments["resolution_override"] = bind.overrideJson;
        arguments["base_revision"] = base;
        const std::string key = "bind-snapshot-" + core::Sha256Hex(json::WriteCanonical(arguments));
        const ProceduralSeam seam(&snapshot.backend, nullptr);
        const auto outcome = SetFillProcedural(
            bind.node, bind.channel, ref, *context, library, seam, [&](const std::function<void(core::Edit&)>& call) {
                return store.Submit(document, core::MutationRequest{"bind_snapshot", arguments, key, base},
                                    [&](core::Edit& edit) {
                                        call(edit);
                                        const SnapshotSourceProvider procedurals(store, edit.project());
                                        evaluator::RequireSupported(edit.base(), edit.project(), {}, &procedurals);
                                    });
            });
        if (!outcome) throw BindRefusal(outcome.error().Describe());
        if (!outcome->result || outcome->result->status != core::ResultStatus::committed) {
            throw BindRefusal("the bind did not commit: " +
                              (outcome->result ? json::WriteCanonical(outcome->result->ToJson())
                                               : std::string(core::ToString(outcome->decision.admission))));
        }
        const int64_t revision = document.revision();
        store.Save(document);
        store.Close();
        auto reopened = store::ProjectStore::Open(Path(args[2]));
        const core::Project& saved = reopened.state.project;
        const BindTarget savedTarget = FindBindTarget(saved, bind.node, bind.channel);
        const auto bound = savedTarget.layer->fill->sources.find(bind.channel);
        if (bound == savedTarget.layer->fill->sources.end() || bound->second != core::Source{core::ProceduralSource{ref}}) {
            throw std::runtime_error("the saved project does not hold the complete bound reference after reopen");
        }
        const auto savedContext = SnapshotUseContext(saved, *savedTarget.set, ref, snapshot.request.outputId);
        const auto savedRequest = savedContext ? RequestFor(ref, *savedContext, library) : decltype(effective){};
        if (!savedContext || !savedRequest || SignatureHash(*savedRequest) != bind.signature) {
            throw std::runtime_error("the saved binding no longer gives the snapshot's signature after reopen");
        }
        CheckServed(*reopened.store, saved, bind.node, bind.channel, ref, bind.signature);
        if (snapshot.entry.source_metadata) {
            const SnapshotSourceProvider provider(*reopened.store, saved);
            const auto metadata = provider.Metadata(saved, *savedTarget.set, bind.channel, savedTarget.format,
                                                    *savedTarget.layer->fill, ref, bind.node, false);
            if (!metadata || *metadata != *snapshot.entry.source_metadata) {
                throw std::runtime_error("the saved binding does not read the snapshot's recorded metadata after reopen");
            }
        }
        json::Object report = identity;
        report["status"] = "ok";
        report["revision"] = revision;
        report["verified_after_reopen"] = true;
        Print(out, report);
        return 0;
    } catch (const BindRefusal& refusal) {
        Print(out, {{"status", "refused"}, {"error", refusal.what()}});
        return 3;
    } catch (const std::exception& error) {
        Print(out, {{"status", "host_error"}, {"error", error.what()}});
        return 3;
    }
}
}  // namespace uzp::procedural
