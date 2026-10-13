#pragma once

// The preview window and its thread (docs/architecture/07-preview-and-render-parity.md §5, §6;
// task phase2.1_preview-viewport-window items 2.4 and 2.5; decisions 018, 042, 134).
//
// - `PreviewFeed` is the publisher side, called by the one thread that evaluates the preview's
//   frames (the attached preview's evaluation thread, evaluation.h, or the `--preview` host after
//   its evaluations). It collects one revision's frame: its maps of every (texture set, material
//   slot) with the revision, project, mesh and environment they were evaluated from, or why they
//   are missing, and publishes it through a wait-free triple buffer (latest.h). Publishing copies
//   shared pointers only: it never waits for, locks against or calls into the preview thread.
// - `PreviewHost` owns the preview thread: its own GPU device (a separate engine, so preview
//   rendering never queues behind or in front of evaluation), the read-only window (vendored
//   `platform_window` and `input`) with an orbit camera only (left drag orbits, the wheel zooms),
//   and a low frame rate (at most one `painter_viewport` render per `period`, none while
//   minimised). The window is double buffered (decision 227): each frame is composed off screen
//   and presented whole, only when it changed or Windows asks, and never erased. The
//   `painter_iray` panel states that the mode is unavailable: no capture can exist before the path
//   tracer (P3-PATHTRACER). The panel also names the project's display configuration and the
//   revision shown. Errors (an unsupported display configuration, a failed evaluation, a missing
//   environment, no mesh) are shown in place of the image, and nothing is drawn; a frame without
//   a project (it was closed) shows that no project is open.
// - The stall hook (`Stall`) blocks the preview thread while it holds its frame, for the tests of
//   item 3.2; nothing else ever waits for that thread.

#include "evaluator/diagnostics.h"
#include "evaluator/evaluate.h"
#include "evaluator/height_to_normal.h"
#include "evaluator/resources.h"
#include "mesh/texturing_mesh.h"
#include "preview/latest.h"
#include "preview/viewport.h"
#include "render/backend.h"

#include <atomic>
#include <chrono>
#include <cstdint>
#include <expected>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <utility>
#include <variant>
#include <vector>

#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::preview {

/// The material inputs the viewport reads (viewport.h `MaterialInputs`). `Occlusion` is the
/// texture set's AO mesh map, passed through (decision 257), never a channel.
enum class MaterialSlot : uint8_t { BaseColor, Metalness, Roughness, Normal, Occlusion };

/// The slot an evaluated channel feeds: BaseColor; BaseMetalness or Metallic; SpecularRoughness or
/// Roughness; Normal. Empty for every other channel (the AO channel is not applied, decision 257).
[[nodiscard]] std::optional<MaterialSlot> SlotOf(core::ChannelType channel);

/// The channel of `stack` that feeds `slot`: the OpenPBR name, else the legacy one; none for
/// `Normal` (the combined virtual map feeds it) and for a slot the stack has no channel for.
[[nodiscard]] std::optional<core::ChannelType> ChannelFor(const core::Stack& stack, MaterialSlot slot);

/// A channel read-out, the combined virtual normal, or a passed-through mesh map (the AO mesh map
/// of `Occlusion`).
using EvaluatedMap =
    std::variant<std::shared_ptr<const evaluator::ChannelResult>, std::shared_ptr<const evaluator::VirtualNormalResult>,
                 std::shared_ptr<const evaluator::DiagnosticMap>>;

/// What the preview shows: the last evaluated revision, as published. Without a project, no project
/// is open.
struct PreviewFrame {
    std::int64_t revision = 0;
    std::shared_ptr<const core::Project> project;
    std::shared_ptr<const mesh::TexturingMesh> mesh;
    /// The environment the frame is lit by: its SHA-256, its bytes, or why there are none. The
    /// project's, or the installation's default when the project names none (`environmentDefault`,
    /// `DefaultEnvironment`).
    std::string environmentHash;
    std::shared_ptr<const std::string> environmentBytes;
    std::string environmentError;
    bool environmentDefault = false;
    /// The evaluated map of each (texture set id, slot).
    std::map<std::pair<core::Id, MaterialSlot>, EvaluatedMap> maps;
    /// The evaluations of the revision that failed, one per line; the window shows them in place of
    /// the image, never a material with those maps missing.
    std::string evaluationError;
};

/// The installation's default environment (decision 212): the shipped CC0 `studio-small-09.exr`
/// (`assets/environments/`, its provenance record's SHA-256), which lights a `painter_viewport`
/// render of a project that names no environment, as Painter lights a new project with an
/// installed default. It is neither preset's standard environment, so such a render is a
/// non-parity preview, never parity evidence. A project that names an environment is lit by that
/// one or fails with no substitute (RES-03).
inline constexpr std::string_view kDefaultEnvironmentFile = "studio-small-09.exr";
inline constexpr std::string_view kDefaultEnvironmentSha256 =
    "44dcbed056512ecd8afd2a3d7ba73d2dd4c24694d0c72005fafcb2469bbc8fd4";
/// Its bytes, read once from `bin/assets/environments/` beside the executable and checked against
/// `kDefaultEnvironmentSha256`; otherwise why they are unavailable.
[[nodiscard]] std::expected<std::shared_ptr<const std::string>, std::string> DefaultEnvironment();

/// Reads a resource's bytes by SHA-256; empty when the project does not hold it.
using ResourceReader = std::function<std::optional<std::string>(const std::string& sha256)>;

class PreviewFeed {
public:
    /// Starts the frame of `revision`: the state its evaluation reads (no project: none is open).
    /// The maps and failures of the previous frame are dropped. The environment's bytes are read
    /// with `read` only when its hash differs from the last one.
    void Update(std::int64_t revision, std::shared_ptr<const core::Project> project,
                std::shared_ptr<const mesh::TexturingMesh> mesh, const ResourceReader& read);
    /// Records the evaluation of `slot` of texture set `set`.
    void Record(core::Id set, MaterialSlot slot, EvaluatedMap map);
    /// Records an evaluation of the frame that failed.
    void RecordFailure(const std::string& failure);
    /// Makes the collected frame the newest one. Wait-free with respect to the preview thread.
    void Publish();

    /// The reader side, for the preview thread.
    Latest<std::shared_ptr<const PreviewFrame>>& Frames() { return m_frames; }

private:
    PreviewFrame m_state;
    Latest<std::shared_ptr<const PreviewFrame>> m_frames;
};

/// What the preview thread has done so far (atomically readable from any thread).
struct PreviewStatus {
    bool windowOpen = false;
    bool stalled = false;
    std::uint64_t framesPublished = 0;
    std::uint64_t framesTaken = 0;
    std::uint64_t framesRendered = 0;
    /// Frames presented: one BitBlt of the whole back buffer each (a composed frame, or WM_PAINT).
    std::uint64_t presents = 0;
    /// Times the orbit camera was fitted: on the first frame and on another mesh.
    std::uint64_t cameraFits = 0;
    /// The revision of the image shown; -1 while the window shows a message instead.
    std::int64_t revisionShown = -1;
    /// The maps of the image shown, as `<texture set>/<slot>` (slots BaseColor, Metalness,
    /// Roughness, Normal, Occlusion).
    std::vector<std::string> mapsShown;
    /// The panel's display line: the taken frame's display configuration (`DisplayLabel`).
    std::string display;
    std::string lastError;
};

struct PreviewOptions {
    render::Backend backend = render::Backend::Dx12;
    /// At most one render per period (the low frame rate).
    std::chrono::milliseconds period{200};
    /// The window's title; tests find the window by it.
    std::string title{"UzPainter preview"};
    /// The bound of every GPU wait of a preview render.
    std::chrono::milliseconds deadline{60'000};
};

/// The preview's error when its window cannot be created (no desktop session).
inline constexpr const char* kWindowNotCreated = "the preview window could not be created";

/// The `painter_iray` panel's text while no capture exists.
inline constexpr const char* kIrayUnavailable =
    "painter_iray: unavailable - no capture exists (the path tracer arrives with P3-PATHTRACER)";

class PreviewHost {
public:
    /// Starts the preview thread on `feed`; the window opens on that thread.
    PreviewHost(PreviewOptions options, std::shared_ptr<PreviewFeed> feed);
    /// Closes the window and joins the preview thread.
    ~PreviewHost();
    PreviewHost(const PreviewHost&) = delete;
    PreviewHost& operator=(const PreviewHost&) = delete;

    /// Test hook: while set, the preview thread blocks, holding the frame it took.
    void Stall(bool stalled);
    [[nodiscard]] PreviewStatus Status() const;
    /// The window was closed, or could not be created: it never shows a frame again.
    [[nodiscard]] bool Closed() const { return m_closed; }
    /// Blocks until the window was closed (or never opened); the thread then ends.
    void WaitClosed();

private:
    void Run();

    PreviewOptions m_options;
    std::shared_ptr<PreviewFeed> m_feed;
    std::atomic<bool> m_stop{false};
    std::atomic<bool> m_stall{false};
    std::atomic<bool> m_stalled{false};
    std::atomic<bool> m_windowOpen{false};
    std::atomic<bool> m_closed{false};
    std::atomic<std::uint64_t> m_taken{0};
    std::atomic<std::uint64_t> m_rendered{0};
    std::atomic<std::uint64_t> m_presents{0};
    std::atomic<std::uint64_t> m_cameraFits{0};
    std::atomic<std::int64_t> m_revisionShown{-1};
    // Guards m_lastError, m_mapsShown and m_display only; the publisher never takes it.
    mutable std::mutex m_errorMutex;
    std::string m_lastError;
    std::vector<std::string> m_mapsShown;
    std::string m_display;
    std::thread m_thread;
};

/// The viewport inputs of `frame`: its texture sets' maps in mesh material order (texture set i is
/// material i), with the defaults of `MaterialInputs` where a slot was never evaluated.
[[nodiscard]] std::vector<MaterialInputs> MaterialsOf(const PreviewFrame& frame);

/// The `Occlusion` slot of texture set `set` of `project` (scene.cpp, decision 257): its AO mesh
/// map passed through by `exporter::PassThroughMeshMap` (one linear channel, the UNORM code over
/// the code maximum, at the set's resolution) from `resources`. Null when the set binds no AO mesh
/// map, so the viewport reads ao = 1; the pass-through's error for any other image layout or size
/// (`evaluator:unsupported_source`) or a missing image, never silently 1.
[[nodiscard]] render::Result<std::shared_ptr<const evaluator::DiagnosticMap>> OcclusionOf(
    const core::Project& project, const core::TextureSet& set,
    const std::shared_ptr<const evaluator::IResourceProvider>& resources);

/// The decoded environments' lighting by SHA-256, kept by a caller across frames.
using LightingCache = std::unordered_map<std::string, std::shared_ptr<const EnvironmentLighting>>;

/// The display configuration the viewport renders `project` with (scene.cpp): the project's colour
/// management, with the view and config pin of the display presets' state
/// (`python::display::PresetOf`).
[[nodiscard]] DisplayConfiguration DisplayOf(const core::Project& project);

/// The viewport scene of `frame` (scene.cpp): the display configuration (`DisplayOf`), the active
/// preset's clear colour, the mesh, the environment's lighting (from `cache`, decoded and
/// precomputed on first use), the material maps and the environment's rotation and exposure.
/// Otherwise the message that replaces the image: the `unsupported_configuration` error (decision
/// 134), the frame's failed evaluations, no mesh, a missing environment or a frame without one
/// (RES-03), an environment that does not decode.
[[nodiscard]] std::expected<ViewportScene, std::string> SceneOf(const PreviewFrame& frame, LightingCache& cache);

}  // namespace uzp::preview
