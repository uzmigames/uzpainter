#include "preview/cli.h"

#include "evaluator/evaluator.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "mesh/reload.h"
#include "python/session.h"
#include "render/backend.h"
#include "render/engine_thread.h"
#include "store/container.h"
#include "uzp_core/manifest/json.h"

#include <exception>
#include <filesystem>
#include <optional>

namespace uzp::preview {

namespace {

constexpr const char* kUsage = "usage: UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan]\n";

/// The channel of `set`'s stack that feeds `slot`: the OpenPBR name, else the legacy one.
std::optional<core::ChannelType> ChannelFor(const core::Stack& stack, MaterialSlot slot) {
    using core::ChannelType;
    const auto has = [&](ChannelType type) { return stack.channels.contains(type); };
    switch (slot) {
        case MaterialSlot::BaseColor:
            if (has(ChannelType::BaseColor)) return ChannelType::BaseColor;
            return std::nullopt;
        case MaterialSlot::Metalness:
            if (has(ChannelType::BaseMetalness)) return ChannelType::BaseMetalness;
            if (has(ChannelType::Metallic)) return ChannelType::Metallic;
            return std::nullopt;
        case MaterialSlot::Roughness:
            if (has(ChannelType::SpecularRoughness)) return ChannelType::SpecularRoughness;
            if (has(ChannelType::Roughness)) return ChannelType::Roughness;
            return std::nullopt;
        case MaterialSlot::Normal: return std::nullopt;  // the combined virtual map, below
    }
    return std::nullopt;
}

}  // namespace

bool IsPreviewCommand(std::string_view first) { return first == "--preview"; }

std::vector<std::string> EvaluateForPreview(const python::OpenProject& open, evaluator::Evaluator& evaluator,
                                            PreviewFeed& feed) {
    std::vector<std::string> failures;
    const core::Snapshot snapshot = open.document->snapshot();
    const core::Project& project = *snapshot.project;
    store::ProjectStore* store = open.store.get();
    const ResourceReader read = [store](const std::string& sha256) -> std::optional<std::string> {
        try {
            return store->ReadResource(sha256);
        } catch (const store::StoreError& error) {
            if (error.code() == store::StoreError::Code::missing_resource) return std::nullopt;
            throw;
        }
    };
    auto resources = std::make_shared<evaluator::DecodingResourceProvider>(
        [read](std::string_view sha256) { return read(std::string(sha256)); });
    std::shared_ptr<const mesh::TexturingMesh> mesh;
    std::shared_ptr<evaluator::MeshGeometryMasks> geometry;
    if (project.mesh) {
        mesh::ImportResult imported =
            mesh::RederiveMesh(project, [store](const std::string& sha256) { return store->ReadResource(sha256); });
        mesh = std::make_shared<const mesh::TexturingMesh>(std::move(imported.mesh));
        geometry = std::make_shared<evaluator::MeshGeometryMasks>(mesh);
    }
    feed.Update(snapshot.revision, snapshot.project, mesh, read);

    for (const core::TextureSet& set : project.texture_sets) {
        if (set.stacks.empty()) continue;
        const core::Stack& stack = set.stacks.front();
        for (MaterialSlot slot : {MaterialSlot::BaseColor, MaterialSlot::Metalness, MaterialSlot::Roughness}) {
            const std::optional<core::ChannelType> channel = ChannelFor(stack, slot);
            if (!channel) continue;
            evaluator::EvaluateRequest request;
            request.textureSet = set.id;
            request.stack = stack.id;
            request.channel = *channel;
            request.templateId = project.settings.template_id;
            request.resources = resources;
            request.geometry = geometry;
            render::Result<evaluator::ChannelResult> result = evaluator.Evaluate(snapshot, std::move(request)).get();
            if (!result) {
                failures.push_back(set.name + " " + std::string(core::ToString(*channel)) + ": " +
                                   result.error().Describe());
                continue;
            }
            feed.Record(set.id, slot, std::make_shared<const evaluator::ChannelResult>(std::move(*result)));
        }
        evaluator::VirtualNormalRequest normal;
        normal.textureSet = set.id;
        normal.stack = stack.id;
        normal.kind = evaluator::NormalSourceKind::Combined;
        normal.convention = core::NormalMapFormat::OpenGL;
        normal.templateId = project.settings.template_id;
        normal.resources = resources;
        normal.geometry = geometry;
        render::Result<evaluator::VirtualNormalResult> combined = evaluator.EvaluateNormal(snapshot, std::move(normal)).get();
        if (!combined) {
            failures.push_back(set.name + " Normal_OpenGL: " + combined.error().Describe());
        } else {
            feed.Record(set.id, MaterialSlot::Normal,
                        std::make_shared<const evaluator::VirtualNormalResult>(std::move(*combined)));
        }
    }
    feed.Publish();
    return failures;
}

int RunPreviewCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    std::optional<std::string> file;
    render::Backend backend = render::Backend::Dx12;
    for (size_t i = 1; i < args.size(); ++i) {
        if (args[i] == "--gpu-backend" && i + 1 < args.size()) {
            const std::optional<render::Backend> parsed = render::ParseBackend(args[++i]);
            if (!parsed) {
                std::fprintf(err, "UzPainter.exe --preview: unknown backend '%s'\n%s", args[i].c_str(), kUsage);
                return kPreviewUsage;
            }
            backend = *parsed;
        } else if (!file && !args[i].starts_with("--")) {
            file = args[i];
        } else {
            std::fprintf(err, "UzPainter.exe --preview: unexpected argument '%s'\n%s", args[i].c_str(), kUsage);
            return kPreviewUsage;
        }
    }
    if (!file) {
        std::fprintf(err, "UzPainter.exe --preview: no project file\n%s", kUsage);
        return kPreviewUsage;
    }

    python::Session& session = python::Session::Get();
    try {
        session.Open(python::PathFromUtf8(*file));
    } catch (const std::exception& e) {
        std::fprintf(err, "UzPainter.exe --preview: cannot open %s: %s\n", file->c_str(), e.what());
        return kPreviewFailed;
    }

    auto feed = std::make_shared<PreviewFeed>();
    PreviewOptions options;
    options.backend = backend;
    options.title = "UzPainter preview - " + python::Utf8(python::PathFromUtf8(*file).filename());
    PreviewHost host(options, feed);
    {
        render::EngineOptions engineOptions;
        engineOptions.device.backend = backend;
        render::Engine engine(engineOptions);
        if (const std::optional<render::Error>& unavailable = engine.DeviceError()) {
            std::fprintf(err, "UzPainter.exe --preview: %s\n", unavailable->Describe().c_str());
        }
        evaluator::Evaluator evaluator(engine, std::make_shared<const evaluator::TemplateLibrary>(
                                                   evaluator::TemplateLibrary::Load(
                                                       evaluator::TemplateLibrary::DefaultDirectory())));
        try {
            for (const std::string& failure : EvaluateForPreview(*session.Current(), evaluator, *feed)) {
                std::fprintf(err, "UzPainter.exe --preview: evaluation failed: %s\n", failure.c_str());
            }
        } catch (const std::exception& e) {
            std::fprintf(err, "UzPainter.exe --preview: evaluation failed: %s\n", e.what());
        }
        evaluator.Shutdown();
    }
    host.WaitClosed();
    const PreviewStatus status = host.Status();
    session.Close();
    if (status.lastError == kWindowNotCreated) {
        std::fprintf(err, "UzPainter.exe --preview: %s\n", status.lastError.c_str());
        return kPreviewFailed;
    }
    const core::json::Object report{{"status", "closed"},
                                    {"frames_rendered", static_cast<std::int64_t>(status.framesRendered)},
                                    {"revision_shown", status.revisionShown},
                                    {"last_error", status.lastError}};
    std::fprintf(out, "UZP_JSON:%s\n", core::json::WriteCanonical(core::json::Value(report)).c_str());
    std::fflush(out);
    return kPreviewOk;
}

}  // namespace uzp::preview
