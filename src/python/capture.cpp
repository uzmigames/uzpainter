// Captures of the open project (capture.h).

#include "python/capture.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <charconv>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <tuple>
#include <utility>
#include <vector>

#include "evaluator/error.h"
#include "evaluator/evaluator.h"
#include "evaluator/templates.h"
#include "export/config.h"
#include "export/exr_writer.h"
#include "export/plan.h"
#include "export/png_writer.h"
#include "export/publish.h"
#include "export/write.h"
#include "mesh/texturing_mesh.h"
#include "preview/display_transform.h"
#include "preview/preview.h"
#include "preview/viewport.h"
#include "python/display.h"
#include "python/errors.h"
#include "python/evaluation.h"
#include "python/session.h"
#include "render/engine_thread.h"
#include "store/container.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/errors.h"

namespace uzp::python {

namespace {

namespace json = core::json;

constexpr const char* kSymbol = "uzpainter.render.capture";

std::mutex g_gpuMutex;
render::Backend g_backend = render::Backend::Dx12;
render::Engine* g_engine = nullptr;

enum class Mode : uint8_t { Viewport, BaseColor, Channel, Mask };

struct ParsedMode {
    Mode mode = Mode::Viewport;
    /// `base_color`, `channel:<name>`: the export's map name; `mask:<uid>`: the node.
    std::string channel;
    core::Id node = core::kNoId;
    /// `base_color`, `channel:<name>`: the channel type.
    core::ChannelType member = core::ChannelType::BaseColor;
};

[[noreturn]] void Value(const std::string& message) { throw ApiError("ValueError", message); }

[[noreturn]] void RaiseRender(const render::Error& error) {
    if (const std::optional<evaluator::EvalErrorKind> kind = evaluator::EvalErrorKindOf(error)) {
        throw ApiError(std::string(evaluator::ErrorClassName(*kind)), error.reason);
    }
    throw ApiError("RuntimeError", error.reason);
}

template <typename T>
T Take(render::Result<T> result) {
    if (!result) RaiseRender(result.error());
    return std::move(*result);
}

ParsedMode ParseMode(const std::string& mode) {
    if (mode == "painter_viewport") return {Mode::Viewport, {}, core::kNoId};
    if (mode == "base_color") return {Mode::BaseColor, "baseColor", core::kNoId, core::ChannelType::BaseColor};
    if (mode.starts_with("channel:") && mode.size() > 8) {
        // A channel type, as evaluate_channel and source_set take it (`SpecularRoughness`), or the
        // export's documentMap name of one (`specularroughness`); the source is the documentMap the
        // export records for it (decision 242).
        const std::string name = mode.substr(8);
        std::optional<core::ChannelType> member = core::FromString<core::ChannelType>(name);
        if (!member) member = exporter::DocumentMapMember(name);
        if (!member) {
            Value("channel:" + name +
                  " names no channel: give a channel type, e.g. BaseColor or SpecularRoughness (the export's "
                  "documentMap names, e.g. specularroughness, are accepted too)");
        }
        return {Mode::Channel, exporter::DocumentMapName(*member), core::kNoId, *member};
    }
    if (mode.starts_with("mask:")) {
        const std::string_view digits = std::string_view(mode).substr(5);
        std::uint64_t uid = 0;
        const auto [end, error] = std::from_chars(digits.data(), digits.data() + digits.size(), uid);
        if (!digits.empty() && error == std::errc() && end == digits.data() + digits.size() && uid > 0) {
            return {Mode::Mask, {}, static_cast<core::Id>(uid)};
        }
        Value("mask:<uid> needs a positive node uid, not '" + std::string(digits) + "'");
    }
    Value("unknown capture mode '" + mode +
          "': painter_viewport, base_color, channel:<name>, mask:<uid> (painter_iray arrives with P3-PATHTRACER)");
}

/// `name` ends in `.png` (any case).
bool IsPng(const std::filesystem::path& path) {
    std::string extension = Utf8(path.extension());
    std::ranges::transform(extension, extension.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return extension == ".png";
}

std::filesystem::path Sibling(const std::filesystem::path& png, const char* suffix) {
    std::filesystem::path out = png;
    out.replace_extension(suffix);
    return out;
}

/// The resource reader of the open project's store: nullopt for a resource it does not hold.
std::function<std::optional<std::string>(std::string_view)> StoreReader(store::ProjectStore* store) {
    return [store](std::string_view sha256) -> std::optional<std::string> {
        try {
            return store->ReadResource(sha256);
        } catch (const store::StoreError& error) {
            if (error.code() == store::StoreError::Code::missing_resource) return std::nullopt;
            throw;
        }
    };
}

json::Array Json3(const std::array<double, 3>& v) { return json::Array{v[0] + 0.0, v[1] + 0.0, v[2] + 0.0}; }

/// The written files' bytes, then the receipt beside them; the receipt with `files`.
json::Object Write(const std::filesystem::path& png, const std::string& pngBytes, const std::string& exrBytes,
                   json::Object receipt) {
    const std::filesystem::path exr = Sibling(png, ".exr");
    const std::filesystem::path receiptPath = Sibling(png, ".receipt.json");
    receipt["hashes"] = json::Object{{"png", core::Sha256Hex(pngBytes)}, {"exr", core::Sha256Hex(exrBytes)}};
    std::error_code ec;
    if (!png.parent_path().empty()) std::filesystem::create_directories(png.parent_path(), ec);
    if (ec) throw ApiError("RuntimeError", "capture: cannot create " + Utf8(png.parent_path()) + ": " + ec.message());
    const std::string receiptText = json::WriteCanonical(json::Value(receipt)) + "\n";
    for (const auto& [path, bytes] : {std::pair<const std::filesystem::path*, const std::string*>{&png, &pngBytes},
                                      {&exr, &exrBytes},
                                      {&receiptPath, &receiptText}}) {
        std::ofstream out(*path, std::ios::binary | std::ios::trunc);
        out.write(bytes->data(), static_cast<std::streamsize>(bytes->size()));
        out.close();
        if (!out) throw ApiError("RuntimeError", "capture: cannot write " + Utf8(*path));
    }
    receipt["files"] = json::Object{{"png", Utf8(std::filesystem::absolute(png))},
                                    {"exr", Utf8(std::filesystem::absolute(exr))},
                                    {"receipt", Utf8(std::filesystem::absolute(receiptPath))}};
    return receipt;
}

/// The receipt's fields every mode has.
json::Object ReceiptBase(const OpenProject& open, const core::Snapshot& snapshot, const std::string& mode) {
    return {{"schema", std::string(kCaptureReceiptSchema)},
            {"revision", snapshot.revision},
            {"project_uuid", open.store->project_uuid()},
            {"evaluator_profile", snapshot.project->versions.evaluator_profile},
            {"mode", mode}};
}

std::string Digest(const json::Object& state) { return core::Sha256Hex(json::WriteCanonical(json::Value(state))); }

// ── Diagnostic modes ──────────────────────────────────────────────────────────────────────────

/// The export configuration of one file: `source` of `rootPath` read as R+G+B (`rgb`) or L.
std::string DiagnosticConfig(const std::string& exportPath, const std::string& rootPath, const char* sourceType,
                             const std::string& sourceName, bool rgb, const char* format, const char* bitDepth) {
    json::Array channels;
    for (const char* letter : rgb ? std::vector<const char*>{"R", "G", "B"} : std::vector<const char*>{"L"}) {
        channels.push_back(json::Object{
            {"destChannel", letter}, {"srcChannel", letter}, {"srcMapType", sourceType}, {"srcMapName", sourceName}});
    }
    const json::Object config{
        {"exportPath", exportPath},
        {"exportShaderParams", false},
        {"defaultExportPreset", "uzpainter-capture"},
        {"exportPresets",
         json::Array{json::Object{
             {"name", "uzpainter-capture"},
             {"maps", json::Array{json::Object{{"fileName", "capture"}, {"channels", std::move(channels)}}}}}}},
        {"exportList", json::Array{json::Object{{"rootPath", rootPath}}}},
        {"exportParameters", json::Array{json::Object{{"parameters", json::Object{{"fileFormat", format},
                                                                                   {"bitDepth", bitDepth},
                                                                                   {"dithering", false},
                                                                                   {"paddingAlgorithm", "passthrough"}}}}}}};
    return json::WriteCanonical(config);
}

json::Object CaptureDiagnostic(const CaptureArguments& a, const ParsedMode& parsed) {
    for (const auto& [given, name] : {std::pair{a.camera.has_value(), "camera"}, std::pair{a.preset.has_value(), "preset"},
                                      std::pair{a.samples.has_value(), "samples"}, std::pair{a.seed.has_value(), "seed"}}) {
        if (given) Value(std::string(name) + " does not apply to the texture-space capture mode " + a.mode);
    }
    if (parsed.mode == Mode::Mask && a.stack) Value("mask:<uid> captures the stack of its node: stack does not apply");

    Session& session = Session::Get();
    const std::shared_ptr<OpenProject> open = session.Current();
    const core::Snapshot snapshot = open->document->snapshot();
    const core::Project& project = *snapshot.project;

    core::Id setId = core::kNoId;
    core::Id stackId = core::kNoId;
    if (parsed.mode == Mode::Mask) {
        core::ForEachNode(project, [&](const core::NodeVisit& visit) {
            if ((visit.layer ? visit.layer->uid : visit.effect->uid) == parsed.node) {
                setId = visit.texture_set;
                stackId = visit.stack;
            }
        });
        if (stackId == core::kNoId) {
            Value("node " + std::to_string(parsed.node) + " is in no stack of revision " + std::to_string(snapshot.revision));
        }
    } else if (a.stack) {
        std::tie(setId, stackId) = *a.stack;
    } else {
        setId = open->active_set;
        stackId = open->active_stack;
    }
    const core::TextureSet* set = nullptr;
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == setId) set = &candidate;
    }
    const core::Stack* stack = core::FindStack(project, setId, stackId);
    if (!set || !stack) Value("the capture names no stack of revision " + std::to_string(snapshot.revision));

    const char* sourceType = parsed.mode == Mode::Mask ? "diagnosticMap" : "documentMap";
    const std::string sourceName =
        parsed.mode == Mode::Mask ? "materialMask/" + std::to_string(parsed.node) : parsed.channel;
    const std::string rootPath = exporter::RootPathOf(*set, *stack);
    const std::filesystem::path folder = std::filesystem::absolute(a.path).parent_path();
    const std::string exportPath = exporter::Utf8String(folder);
    const std::optional<std::filesystem::path> file = session.FilePath();
    const exporter::PlanContext context{file ? exporter::Utf8String(*file) : std::string()};

    // The revision's evaluation: the one an earlier call on this revision kept, tiles included.
    EvaluationLease evaluation = LeaseEvaluation(open, snapshot);

    // A first plan reads the source's components, so a colour source is written R+G+B, never as
    // its luma (as the diagnostics' export does).
    const exporter::ExportPlan probe =
        exporter::CompilePlan(project, DiagnosticConfig(exportPath, rootPath, sourceType, sourceName, false, "png", "16"), context);
    exporter::CheckExportable(probe);
    if (probe.files.size() != 1) {
        const std::string missing = parsed.mode == Mode::Mask
                                        ? "source " + sourceName
                                        : "channel " + std::string(core::ToString(parsed.member));
        Value("the stack " + rootPath + " has no " + missing +
              (probe.skipped.empty() ? std::string() : ": " + probe.skipped.front().reason));
    }
    const bool rgb = probe.files.front().channels.front().source.components == 3;
    const uint32_t width = probe.files.front().width;
    const uint32_t height = probe.files.front().height;
    if (a.size && (a.size->first != width || a.size->second != height)) {
        Value("a texture-space capture is written at its texture set's resolution " + std::to_string(width) + " x " +
              std::to_string(height) + ", not " + std::to_string(a.size->first) + " x " + std::to_string(a.size->second));
    }
    std::array<std::string, 2> bytes;
    const std::array<std::pair<const char*, const char*>, 2> formats{{{"png", "16"}, {"exr", "32f"}}};
    for (size_t i = 0; i < formats.size(); ++i) {
        const exporter::ExportPlan plan = exporter::CompilePlan(
            project, DiagnosticConfig(exportPath, rootPath, sourceType, sourceName, rgb, formats[i].first, formats[i].second),
            context);
        exporter::CheckExportable(plan);
        std::vector<exporter::EncodedFile> encoded =
            Take(exporter::EncodeExport(project, snapshot.revision, plan, evaluation->inputs, *evaluation->templates,
                                        evaluation->cpu.store(), evaluation->cpu.cache()));
        bytes[i] = std::move(encoded.front().bytes);
    }
    evaluation.Keep();

    const json::Object source{{"type", sourceType},
                              {"name", sourceName},
                              {"texture_set", set->name},
                              {"stack", stack->name},
                              {"root_path", rootPath}};
    const json::Object encoding{{"png", json::Object{{"bit_depth", "16"}, {"layout", rgb ? "RGB" : "L"}}},
                                {"exr", json::Object{{"bit_depth", "32f"}, {"layout", rgb ? "RGB" : "L"}}},
                                {"padding", "passthrough"}};
    const json::Array size{static_cast<std::int64_t>(width), static_cast<std::int64_t>(height)};
    json::Object receipt = ReceiptBase(*open, snapshot, a.mode);
    receipt["render_state_digest"] =
        Digest(json::Object{{"mode", a.mode}, {"source", source}, {"size", size}, {"encoding", encoding}});
    receipt["source"] = source;
    receipt["encoding"] = encoding;
    receipt["backend"] = "cpu";
    receipt["adapter"] = nullptr;
    receipt["driver"] = nullptr;
    receipt["samples"] = nullptr;
    receipt["seed"] = nullptr;
    receipt["camera"] = nullptr;
    receipt["size"] = size;
    receipt["display_configuration"] = nullptr;
    receipt["environment"] = nullptr;
    receipt["visibility"] = nullptr;
    receipt["shadows"] = nullptr;
    return Write(a.path, bytes[0], bytes[1], std::move(receipt));
}

// ── painter_viewport ──────────────────────────────────────────────────────────────────────────

/// The camera of the capture: its pose and the receipt's record of it.
std::pair<preview::CameraPose, json::Object> CameraOf(const CaptureArguments& a, const core::Project& project,
                                                      const mesh::TexturingMesh& mesh) {
    json::Value record = a.camera ? *a.camera : display::DefaultCamera(project);
    if (record.IsNull()) {
        const preview::OrbitCamera fit = preview::FitCamera(mesh);
        const preview::CameraPose pose = preview::PoseOf(fit);
        return {pose, json::Object{{"source", "fit"},
                                   {"position", Json3(pose.eye)},
                                   {"right", Json3(pose.right)},
                                   {"up", Json3(pose.up)},
                                   {"forward", Json3(pose.forward)},
                                   {"field_of_view", pose.fovDegrees}}};
    }
    const json::Object camera = display::CameraFromJson(record, kSymbol);
    const std::array<std::array<double, 3>, 3> r = display::CameraRotation(json::Value(camera), kSymbol);
    preview::CameraPose pose;
    const json::Array& position = std::get<json::Array>(camera.at("position").data);
    for (size_t i = 0; i < 3; ++i) {
        pose.eye[i] = position[i].IsInt() ? static_cast<double>(std::get<std::int64_t>(position[i].data))
                                          : std::get<double>(position[i].data);
        pose.right[i] = r[i][0];
        pose.up[i] = r[i][1];
        pose.forward[i] = -r[i][2] + 0.0;
    }
    const auto number = [](const json::Value& v) {
        return v.IsInt() ? static_cast<double>(std::get<std::int64_t>(v.data)) : std::get<double>(v.data);
    };
    pose.fovDegrees = number(camera.at("field_of_view"));
    pose.nearPlane = 1e-6;
    // Decision 163: parallel rays over `orthographic_height` (the full vertical extent, a UzPainter
    // convention like the vertical field of view).
    pose.orthographic = std::get<std::string>(camera.at("projection_type").data) == "Orthographic";
    if (pose.orthographic) pose.orthographicHeight = number(camera.at("orthographic_height"));
    return {pose, json::Object{{"source", a.camera ? "argument" : "default_camera"}, {"record", camera}}};
}

json::Object CaptureViewport(const CaptureArguments& a) {
    if (a.stack) Value("painter_viewport renders every texture set: stack does not apply");
    if (!a.size) Value("painter_viewport needs a size (width, height)");
    const std::int64_t width64 = a.size->first;
    const std::int64_t height64 = a.size->second;
    if (width64 < 1 || height64 < 1 || width64 > preview::kMaxViewportSide || height64 > preview::kMaxViewportSide) {
        Value("the size " + std::to_string(width64) + " x " + std::to_string(height64) + " is outside 1 to " +
              std::to_string(preview::kMaxViewportSide));
    }
    const auto width = static_cast<uint32_t>(width64);
    const auto height = static_cast<uint32_t>(height64);
    if (a.samples && *a.samples != 1) {
        Value("painter_viewport renders one deterministic sample per pixel: samples must be 1, not " +
              std::to_string(*a.samples));
    }
    if (a.seed && *a.seed < 0) Value("seed must be a non-negative integer");

    const std::shared_ptr<OpenProject> open = Session::Get().Current();
    const core::Snapshot snapshot = open->document->snapshot();
    // The project as rendered: the committed revision, with `preset` applied to a copy.
    auto project = std::make_shared<core::Project>(*snapshot.project);
    if (a.preset) {
        display::ApplyPreset(*project, a.preset->IsString()
                                           ? json::Value(display::StandardPreset(std::get<std::string>(a.preset->data)))
                                           : *a.preset);
    }
    if (!project->mesh) throw ApiError("ProjectError", "capture: painter_viewport needs a mesh; the project has none");

    store::ProjectStore* store = open->store.get();
    const auto read = StoreReader(store);
    preview::PreviewFrame frame;
    frame.revision = snapshot.revision;
    frame.project = project;
    // The revision's evaluation (evaluation.h): its mesh, re-derived from the stored bytes (a preset
    // changes display state only), and the tiles an earlier call on this revision computed.
    std::optional<EvaluationLease> evaluation;
    evaluation.emplace(LeaseEvaluation(open, snapshot));
    frame.mesh = (*evaluation)->mesh;
    if (const std::optional<std::string>& hash = project->display.environment.resource) {
        frame.environmentHash = *hash;
        std::optional<std::string> bytes = read(*hash);
        if (!bytes) {
            throw ApiError("ResourceNotFoundError", "capture: missing environment: the project holds no bytes for sha256 " +
                                                        *hash + " (RES-03: no substitute)");
        }
        frame.environmentBytes = std::make_shared<const std::string>(std::move(*bytes));
    } else {
        // A project that names no environment is lit by the installation's default (decision 212).
        std::expected<std::shared_ptr<const std::string>, std::string> shipped = preview::DefaultEnvironment();
        if (!shipped) throw ApiError("RuntimeError", "capture: " + shipped.error());
        frame.environmentHash = std::string(preview::kDefaultEnvironmentSha256);
        frame.environmentBytes = *shipped;
        frame.environmentDefault = true;
    }
    // The display configuration, the environment and the lighting, before any evaluation or device.
    preview::LightingCache cache;
    std::expected<preview::ViewportScene, std::string> scene = preview::SceneOf(frame, cache);
    if (!scene) {
        const std::string& message = scene.error();
        if (message.starts_with("unsupported_configuration")) {
            ApiError error("UnsupportedInUzPainter", std::string(kSymbol) + " is not supported in UzPainter: " + message);
            error.symbol = kSymbol;
            error.reason = message;
            throw error;
        }
        if (frame.environmentHash.empty()) throw ApiError("ProjectError", "capture: " + message);
        throw ApiError("RuntimeError", "capture: " + message);
    }
    const std::pair<preview::CameraPose, json::Object> camera = CameraOf(a, *project, *frame.mesh);
    const preview::CameraPose& pose = camera.first;
    const json::Object& cameraRecord = camera.second;
    if (render::Result<void> valid = preview::ValidateViewport(*scene, pose, width, height, g_backend); !valid) {
        Value("capture: " + valid.error().reason);
    }

    // The material maps of the committed revision, on its CPU evaluation with the export's inputs.
    // The evaluator never reads display state, so the revision itself is evaluated, not the copy
    // the preset changed.
    RevisionEvaluation& revision = **evaluation;
    const core::Project& material = *snapshot.project;
    for (const core::TextureSet& set : material.texture_sets) {
        if (set.stacks.empty()) continue;
        const core::Stack& stack = set.stacks.front();
        for (const preview::MaterialSlot slot :
             {preview::MaterialSlot::BaseColor, preview::MaterialSlot::Metalness, preview::MaterialSlot::Roughness}) {
            const std::optional<core::ChannelType> channel = preview::ChannelFor(stack, slot);
            if (!channel) continue;
            evaluator::EvaluateRequest request;
            request.textureSet = set.id;
            request.stack = stack.id;
            request.channel = *channel;
            request.templateId = material.settings.template_id;
            request.resources = revision.inputs.resources;
            request.geometry = revision.inputs.geometry;
            frame.maps[{set.id, slot}] =
                std::make_shared<const evaluator::ChannelResult>(Take(revision.cpu.Evaluate(material, request)));
        }
        evaluator::VirtualNormalRequest normal;
        normal.textureSet = set.id;
        normal.stack = stack.id;
        normal.kind = evaluator::NormalSourceKind::Combined;
        normal.convention = core::NormalMapFormat::OpenGL;
        normal.templateId = material.settings.template_id;
        normal.resources = revision.inputs.resources;
        normal.geometry = revision.inputs.geometry;
        frame.maps[{set.id, preview::MaterialSlot::Normal}] = std::make_shared<const evaluator::VirtualNormalResult>(
            Take(revision.cpu.EvaluateNormal(material, snapshot.revision, normal)));
    }
    evaluation->Keep();
    evaluation.reset();  // the next call may use it while this one renders
    scene->materials = preview::MaterialsOf(frame);

    // The GPU: the worker's engine, or a device of the process's backend for this capture.
    std::unique_lock lock(g_gpuMutex);
    render::Engine* engine = g_engine;
    std::unique_ptr<render::Engine> local;
    if (!engine) {
        render::EngineOptions options;
        options.device.backend = g_backend;
        local = std::make_unique<render::Engine>(options);
        engine = local.get();
    }
    lock.unlock();
    if (const std::optional<render::Error>& unavailable = engine->DeviceError()) {
        throw ApiError("RuntimeError", unavailable->Describe());
    }
    const auto submitted = std::make_shared<const core::Snapshot>(snapshot);
    preview::ViewportImage image = Take(engine
                                            ->Submit(submitted,
                                                     [&](render::EngineContext& context, const core::Snapshot&) {
                                                         return preview::RenderViewport(context, *scene, pose, width, height);
                                                     })
                                            .get());
    const render::Result<render::CapabilityReport> capabilities = engine->Capabilities();
    const std::string adapter = capabilities ? capabilities->adapter : "unknown";
    const render::Backend backend = engine->Options().device.backend;
    const std::string driver =
        backend == render::Backend::Dx12 ? preview::DriverVersion(engine->Options().device.adapterIndex) : "unknown";
    local.reset();

    // RGB of the display codes (16-bit PNG) and of the linear colour (binary16 OpenEXR); alpha is 1.
    exporter::PngImage png{width, height, 3, 16, {}};
    exporter::ExrImage exr{width, height, 3, {}, true};
    png.samples.reserve(size_t{width} * height * 3);
    exr.values.reserve(size_t{width} * height * 3);
    for (size_t i = 0; i < size_t{width} * height; ++i) {
        for (size_t c = 0; c < 3; ++c) {
            png.samples.push_back(image.display[i * 4 + c]);
            exr.values.push_back(preview::HalfToFloat(image.linear[i * 4 + c]));
        }
    }

    const json::Object state = display::PresetOf(*project);
    const preview::DisplayConfiguration& configuration = scene->display;
    const json::Object displayConfiguration{
        {"mode", configuration.mode}, {"config_sha256", configuration.configHash}, {"view", configuration.view}};
    const std::int64_t seed =
        a.seed ? *a.seed : (state.contains("seed") && state.at("seed").IsInt() ? std::get<std::int64_t>(state.at("seed").data) : 0);
    const json::Array size{width64, height64};
    json::Object poseRecord{{"position", Json3(pose.eye)},
                            {"right", Json3(pose.right)},
                            {"up", Json3(pose.up)},
                            {"forward", Json3(pose.forward)},
                            {"field_of_view", pose.fovDegrees}};
    if (pose.orthographic) {  // perspective records stay as they were (decision 163)
        poseRecord["projection"] = "orthographic";
        poseRecord["orthographic_height"] = pose.orthographicHeight;
    }
    // The self-occlusion model and its ray counts change the image (decision 251).
    const json::Object visibility{{"model", std::string(preview::kVisibilityModel)},
                                  {"diffuse_rays", static_cast<std::int64_t>(scene->diffuseRays)},
                                  {"specular_rays", static_cast<std::int64_t>(scene->specularRays)}};
    const json::Object renderState{
        {"mode", a.mode},
        {"environment", json::Object{{"sha256", frame.environmentHash},
                                     {"default", frame.environmentDefault},
                                     {"rotation", scene->environmentRotationDegrees},
                                     {"exposure", scene->environmentExposure}}},
        {"background_linear", json::Array{static_cast<double>(scene->background[0]),
                                          static_cast<double>(scene->background[1]),
                                          static_cast<double>(scene->background[2])}},
        {"camera", cameraRecord},
        {"pose", poseRecord},
        {"size", size},
        {"samples", std::int64_t{1}},
        {"seed", seed},
        {"shader", display::Shader(*project)},
        {"display_configuration", displayConfiguration},
        {"visibility", visibility}};

    json::Object receipt = ReceiptBase(*open, snapshot, a.mode);
    receipt["render_state_digest"] = Digest(renderState);
    receipt["source"] = nullptr;
    receipt["encoding"] = json::Object{{"png", json::Object{{"bit_depth", "16"}, {"layout", "RGB"}, {"content", "display_codes"}}},
                                       {"exr", json::Object{{"bit_depth", "16f"}, {"layout", "RGB"}, {"content", "linear"}}}};
    receipt["backend"] = std::string(render::BackendName(backend));
    receipt["adapter"] = adapter;
    receipt["driver"] = driver;
    receipt["samples"] = std::int64_t{1};
    receipt["seed"] = seed;
    receipt["camera"] = renderState.at("camera");
    receipt["size"] = size;
    receipt["display_configuration"] = displayConfiguration;
    receipt["environment"] = renderState.at("environment");
    receipt["visibility"] = visibility;
    // Requested, outside the digest: painter_viewport always traces its self-occlusion and the
    // flag changes nothing (decision 251).
    receipt["shadows"] = json::Object{{"requested", project->display.shadows}, {"effect", std::string(display::kShadowsEffect)}};
    return Write(a.path, exporter::EncodePng(png), exporter::EncodeExr(exr), std::move(receipt));
}

}  // namespace

void SetCaptureGpu(render::Backend backend, render::Engine* engine) {
    std::lock_guard lock(g_gpuMutex);
    g_backend = backend;
    g_engine = engine;
}

void RefuseUnavailableMode(std::string_view mode) {
    if (mode == "painter_iray") {
        throw ApiError("PathTracerUnavailable",
                       "capture mode painter_iray is unavailable: the path tracer is a release gap until it passes "
                       "(P3-PATHTRACER, phase3.7_path-tracer); nothing was rendered");
    }
}

bool UsesGpu(std::string_view mode) { return mode == "painter_viewport"; }

json::Object Capture(const CaptureArguments& arguments) {
    RefuseUnavailableMode(arguments.mode);
    const ParsedMode parsed = ParseMode(arguments.mode);
    if (!IsPng(arguments.path)) Value("the capture path must name a .png file, not '" + Utf8(arguments.path) + "'");
    if (Session::Get().TransactionOpen()) {
        throw ApiError("RuntimeError", "a capture reads a committed revision: commit the open Transaction first");
    }
    try {
        return parsed.mode == Mode::Viewport ? CaptureViewport(arguments) : CaptureDiagnostic(arguments, parsed);
    } catch (const core::ValueError& error) {
        throw ApiError("ValueError", error.what());
    } catch (const core::NotYetSupported& error) {
        throw ApiError("NotYetSupported", error.what());
    } catch (const std::invalid_argument& error) {
        throw ApiError("RuntimeError", std::string("capture: ") + error.what());
    }
}

}  // namespace uzp::python
