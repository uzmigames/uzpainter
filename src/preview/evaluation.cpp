#include "preview/evaluation.h"

#include "evaluator/geometry_mask.h"
#include "evaluator/sources.h"
#include "evaluator/templates.h"
#include "mesh/reload.h"
#include "python/session.h"
#include "render/engine_thread.h"
#include "store/container.h"

#include <exception>
#include <utility>

#include "uzp_core/types/errors.h"

namespace uzp::preview {

std::optional<std::vector<std::string>> EvaluateFrame(const core::Snapshot& snapshot, const ResourceReader& read,
                                                      const std::shared_ptr<const evaluator::IResourceProvider>& resources,
                                                      evaluator::Evaluator& evaluator, MeshCache& meshes,
                                                      PreviewFeed& feed, const std::function<bool()>& superseded) {
    const auto stale = [&] { return superseded && superseded(); };
    std::vector<std::string> failures;
    const core::Project& project = *snapshot.project;
    // A configuration the viewport refuses is shown as that refusal: nothing to evaluate (decision 038).
    if (UnsupportedConfiguration(DisplayOf(project))) {
        feed.Update(snapshot.revision, snapshot.project, nullptr, read);
        if (stale()) return std::nullopt;
        feed.Publish();
        return failures;
    }
    if (!project.mesh) {
        meshes = {};
    } else if (meshes.reference != project.mesh || !meshes.mesh) {
        meshes = {};
        try {
            mesh::ImportResult imported = mesh::RederiveMesh(project, [&read](const std::string& sha256) {
                std::optional<std::string> bytes = read(sha256);
                if (!bytes) throw core::ValueError("the project holds no bytes for the mesh's resource " + sha256);
                return std::move(*bytes);
            });
            meshes = {project.mesh, std::make_shared<const mesh::TexturingMesh>(std::move(imported.mesh))};
        } catch (const std::exception& error) {
            failures.push_back(std::string("the mesh: ") + error.what());
        }
    }
    feed.Update(snapshot.revision, snapshot.project, meshes.mesh, read);
    const auto failed = [&](const std::string& failure) {
        failures.push_back(failure);
        feed.RecordFailure(failure);
    };
    for (const std::string& failure : failures) feed.RecordFailure(failure);
    auto geometry = meshes.mesh ? std::make_shared<evaluator::MeshGeometryMasks>(meshes.mesh) : nullptr;
    for (const core::TextureSet& set : project.texture_sets) {
        if (set.stacks.empty()) continue;
        const core::Stack& stack = set.stacks.front();
        for (MaterialSlot slot : {MaterialSlot::BaseColor, MaterialSlot::Metalness, MaterialSlot::Roughness}) {
            const std::optional<core::ChannelType> channel = ChannelFor(stack, slot);
            if (!channel) continue;
            if (stale()) return std::nullopt;
            const std::string what = set.name + " " + std::string(core::ToString(*channel));
            evaluator::EvaluateRequest request;
            request.textureSet = set.id;
            request.stack = stack.id;
            request.channel = *channel;
            request.templateId = project.settings.template_id;
            request.resources = resources;
            request.geometry = geometry;
            try {
                render::Result<evaluator::ChannelResult> result = evaluator.Evaluate(snapshot, std::move(request)).get();
                if (!result) {
                    failed(what + ": " + result.error().Describe());
                    continue;
                }
                feed.Record(set.id, slot, std::make_shared<const evaluator::ChannelResult>(std::move(*result)));
            } catch (const std::exception& error) {
                failed(what + ": " + error.what());
            }
        }
        if (stale()) return std::nullopt;
        const std::string what = set.name + " Normal_OpenGL";
        evaluator::VirtualNormalRequest normal;
        normal.textureSet = set.id;
        normal.stack = stack.id;
        normal.kind = evaluator::NormalSourceKind::Combined;
        normal.convention = core::NormalMapFormat::OpenGL;
        normal.templateId = project.settings.template_id;
        normal.resources = resources;
        normal.geometry = geometry;
        try {
            render::Result<evaluator::VirtualNormalResult> combined =
                evaluator.EvaluateNormal(snapshot, std::move(normal)).get();
            if (!combined) {
                failed(what + ": " + combined.error().Describe());
                continue;
            }
            feed.Record(set.id, MaterialSlot::Normal,
                        std::make_shared<const evaluator::VirtualNormalResult>(std::move(*combined)));
        } catch (const std::exception& error) {
            failed(what + ": " + error.what());
        }
    }
    if (stale()) return std::nullopt;
    feed.Publish();
    return failures;
}

StoreAccess::StoreAccess(std::shared_ptr<python::OpenProject> open)
    : m_open(std::move(open)), m_identity(m_open.get()) {}

std::optional<std::string> StoreAccess::Read(const std::string& sha256) {
    std::lock_guard lock(m_mutex);
    if (!m_open) return std::nullopt;
    try {
        return m_open->store->ReadResource(sha256);
    } catch (const store::StoreError& error) {
        if (error.code() == store::StoreError::Code::missing_resource) return std::nullopt;
        throw;
    }
}

std::shared_ptr<python::OpenProject> StoreAccess::Revoke() {
    std::lock_guard lock(m_mutex);
    return std::move(m_open);
}

AttachedEvaluation::AttachedEvaluation(render::Backend backend, std::chrono::milliseconds deadline,
                                       std::shared_ptr<PreviewFeed> feed, std::function<bool()> windowClosed)
    : m_backend(backend), m_deadline(deadline), m_feed(std::move(feed)), m_windowClosed(std::move(windowClosed)) {
    m_thread = std::thread([this] { Run(); });
}

AttachedEvaluation::~AttachedEvaluation() {
    {
        std::lock_guard lock(m_mutex);
        m_stop = true;
    }
    m_wake.notify_one();
    if (m_thread.joinable()) m_thread.join();
    std::shared_ptr<python::OpenProject> released;  // dropped after the lock below
    std::lock_guard committing(m_committing);
    if (m_access) released = m_access->Revoke();
}

void AttachedEvaluation::Committed(std::shared_ptr<python::OpenProject> open) {
    std::shared_ptr<python::OpenProject> released;  // the previous project's last reference, dropped last
    std::lock_guard committing(m_committing);
    if (m_access && !m_access->Reads(open.get())) {
        released = m_access->Revoke();
        m_access.reset();
    }
    Revision revision;
    if (open) {
        if (!m_access) m_access = std::make_shared<StoreAccess>(open);
        const core::Snapshot snapshot = open->document->snapshot();
        revision = {snapshot.revision, snapshot.project, m_access};
    }
    {
        std::lock_guard lock(m_mutex);
        m_next = std::move(revision);
    }
    m_wake.notify_one();
}

void AttachedEvaluation::Stall(bool stalled) {
    {
        std::lock_guard lock(m_mutex);
        m_stall = stalled;
    }
    m_wake.notify_one();
}

void AttachedEvaluation::Run() {
    render::EngineOptions options;
    options.device.backend = m_backend;
    options.requestDeadline = m_deadline;
    render::Engine engine(options);
    // Without the project templates nothing can be evaluated: every frame shows why, and the
    // worker is unaffected.
    std::optional<evaluator::Evaluator> evaluator;
    std::string unavailable;
    try {
        evaluator.emplace(engine, std::make_shared<const evaluator::TemplateLibrary>(evaluator::TemplateLibrary::Load(
                                      evaluator::TemplateLibrary::DefaultDirectory())));
    } catch (const std::exception& error) {
        unavailable = std::string("the project templates cannot be loaded: ") + error.what();
    }
    MeshCache meshes;
    std::shared_ptr<StoreAccess> decoding;  // the project `resources` decodes the bitmaps of
    std::shared_ptr<const evaluator::IResourceProvider> resources;
    const auto superseded = [this] {
        std::unique_lock lock(m_mutex);
        // Test hook: the thread blocks here, inside the evaluation, while it is stalled.
        if (m_stall && !m_stop) {
            m_stalled = true;
            m_wake.wait(lock, [this] { return !m_stall || m_stop; });
            m_stalled = false;
        }
        return m_stop || m_next.has_value();
    };
    for (;;) {
        Revision revision;
        {
            std::unique_lock lock(m_mutex);
            m_wake.wait(lock, [this] { return m_stop || m_next.has_value(); });
            if (m_stop) break;
            revision = std::move(*m_next);
            m_next.reset();
        }
        if (m_windowClosed && m_windowClosed()) continue;  // nobody sees it
        if (revision.access != decoding) {
            decoding = revision.access;
            meshes = {};
            resources.reset();
            if (decoding) {
                resources = std::make_shared<evaluator::DecodingResourceProvider>(
                    [access = decoding](std::string_view sha256) { return access->Read(std::string(sha256)); });
            }
        }
        if (!revision.project) {
            m_feed->Update(0, nullptr, nullptr, {});
            m_feed->Publish();
            continue;
        }
        const ResourceReader read = [access = revision.access](const std::string& sha256) {
            return access->Read(sha256);
        };
        const core::Snapshot snapshot{revision.number, revision.project};
        std::string failure = unavailable;
        if (evaluator) {
            try {
                EvaluateFrame(snapshot, read, resources, *evaluator, meshes, *m_feed, superseded);
                continue;
            } catch (const std::exception& error) {
                failure = error.what();
            }
        }
        if (superseded()) continue;
        m_feed->Update(snapshot.revision, snapshot.project, nullptr, read);
        m_feed->RecordFailure("the evaluation of revision " + std::to_string(snapshot.revision) + " failed: " + failure);
        m_feed->Publish();
    }
    if (evaluator) evaluator->Shutdown();
    engine.Stop();
}

}  // namespace uzp::preview
