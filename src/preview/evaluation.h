#pragma once

// The preview's evaluation of a committed revision (docs/architecture/07-preview-and-render-parity.md
// §6; decisions 018, 042, 248).
//
// - `EvaluateFrame` evaluates what the window shows of one revision: the base colour, metalness and
//   roughness of every texture set's first stack and its combined Normal_OpenGL map, on a GPU
//   `evaluator::Evaluator`, and publishes them as one frame. A project whose display configuration
//   the viewport refuses (decision 038) is published without evaluating anything, so the window
//   shows the refusal. A failed evaluation is recorded in the frame, and the window shows it in
//   place of the image. `UzPainter.exe --preview` evaluates its project once with it (cli.h).
// - `AttachedEvaluation` is the preview of a worker (`--worker ... --preview`, decision 248). The
//   worker hands it the open project after every change of what the session holds
//   (`python::Session::on_durable_change`: create, open, every committed call, `save_as`, close).
//   Its own thread evaluates the newest committed revision with `EvaluateFrame` on its own GPU
//   device and evaluator, so neither the worker's request thread nor its device ever waits for the
//   preview, and the window's thread never queues a render behind an evaluation. It is the feed's
//   only publisher. A revision superseded before its evaluation ends is abandoned and never
//   published. A closed project is published as a frame without a project. Nothing is evaluated
//   after the window was closed.
// - The evaluation thread reads the project's resources through a `StoreAccess`, which holds the
//   open project. Each read takes the access's lock for that one read. When the project closes, or
//   another one opens, `Committed` revokes the access inside the session's change. It waits at
//   most for a read in flight, and later reads find nothing. So the store, its lock sidecar and an
//   untitled project's folder are released before the call that closed the project returns.

#include "evaluator/evaluator.h"
#include "mesh/texturing_mesh.h"
#include "preview/preview.h"
#include "render/backend.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "uzp_core/document/document.h"
#include "uzp_core/types/project.h"

namespace uzp::python {
struct OpenProject;
}

namespace uzp::preview {

/// The texturing mesh of a project's frames, kept while its mesh reference is unchanged.
struct MeshCache {
    std::optional<core::MeshReference> reference;
    std::shared_ptr<const mesh::TexturingMesh> mesh;
};

/// Evaluates the frame of `snapshot` into `feed` and publishes it (see above). `read` reads the
/// project's resource bytes, `resources` decodes them (kept by the caller across revisions of one
/// project). Returns one line per failed evaluation (the frame carries them). Returns nothing, and
/// publishes nothing, when `superseded` turns true before an evaluation or before publishing.
std::optional<std::vector<std::string>> EvaluateFrame(const core::Snapshot& snapshot, const ResourceReader& read,
                                                      const std::shared_ptr<const evaluator::IResourceProvider>& resources,
                                                      evaluator::Evaluator& evaluator, MeshCache& meshes,
                                                      PreviewFeed& feed, const std::function<bool()>& superseded = {});

/// The open project's resources, read from another thread until the project is revoked.
class StoreAccess {
public:
    explicit StoreAccess(std::shared_ptr<python::OpenProject> open);
    /// The bytes of a resource; none for a hash the project does not hold, or once revoked.
    std::optional<std::string> Read(const std::string& sha256);
    /// Whether it reads `open`.
    [[nodiscard]] bool Reads(const python::OpenProject* open) const { return m_identity == open; }
    /// Ends the reads (waiting for one in flight) and returns the reference it held.
    std::shared_ptr<python::OpenProject> Revoke();

private:
    std::mutex m_mutex;
    std::shared_ptr<python::OpenProject> m_open;
    const python::OpenProject* m_identity;
};

class AttachedEvaluation {
public:
    /// Starts the evaluation thread, with its own device of `backend` (every GPU wait bounded by
    /// `deadline`), publishing to `feed`. `windowClosed` tells it the window was closed for good.
    AttachedEvaluation(render::Backend backend, std::chrono::milliseconds deadline, std::shared_ptr<PreviewFeed> feed,
                       std::function<bool()> windowClosed);
    /// Stops the thread after the evaluation in flight and revokes the project.
    ~AttachedEvaluation();
    AttachedEvaluation(const AttachedEvaluation&) = delete;
    AttachedEvaluation& operator=(const AttachedEvaluation&) = delete;

    /// The session's change (`python::Session::on_durable_change`), on the thread that made it:
    /// `open` is the open project, null when none is. Hands its committed revision to the
    /// evaluation thread, replacing one not yet started. When the project is another one than
    /// before, or none, the previous one's access is revoked first and its last reference dropped
    /// here.
    void Committed(std::shared_ptr<python::OpenProject> open);
    /// Test hook: while set, the evaluation thread blocks inside its evaluation, between its steps
    /// (after it started a revision's frame, before each map and before publishing). A Debug worker
    /// reaches it with `test_fault preview_evaluation_stall` / `preview_evaluation_resume`.
    void Stall(bool stalled);
    /// Whether the evaluation thread is blocked by `Stall`.
    [[nodiscard]] bool Stalled() const { return m_stalled; }

private:
    /// A committed revision, as the evaluation thread reads it.
    struct Revision {
        std::int64_t number = 0;
        std::shared_ptr<const core::Project> project;  // null: no project is open
        std::shared_ptr<StoreAccess> access;
    };

    void Run();

    render::Backend m_backend;
    std::chrono::milliseconds m_deadline;
    std::shared_ptr<PreviewFeed> m_feed;
    std::function<bool()> m_windowClosed;
    std::mutex m_committing;  // serialises `Committed` callers; the evaluation thread never takes it
    std::shared_ptr<StoreAccess> m_access;  // guarded by m_committing
    std::mutex m_mutex;  // guards m_next, m_stop and m_stall; never held while evaluating
    std::condition_variable m_wake;
    std::optional<Revision> m_next;
    bool m_stop = false;
    bool m_stall = false;
    std::atomic<bool> m_stalled{false};
    std::thread m_thread;
};

}  // namespace uzp::preview
