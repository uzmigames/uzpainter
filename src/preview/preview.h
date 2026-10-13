#pragma once

// The preview window and its thread (docs/architecture/07-preview-and-render-parity.md §5, §6;
// task phase2.1_preview-viewport-window items 2.4 and 2.5; decisions 018, 042, 134).
//
// - `PreviewFeed` is the publisher side, called by the thread that evaluates (the worker's request
//   thread, or the `--preview` host after its evaluations). It accumulates the last evaluation of
//   every (texture set, material slot) with the revision, project, mesh and environment it was
//   evaluated from, and publishes a snapshot through a wait-free triple buffer (latest.h).
//   Publishing copies shared pointers only: it never waits for, locks against or calls into the
//   preview thread.
// - `PreviewHost` owns the preview thread: its own GPU device (a separate engine, so preview
//   rendering never queues behind or in front of evaluation), the read-only window (vendored
//   `platform_window` and `input`) with an orbit camera only (left drag orbits, the wheel zooms),
//   and a low frame rate (at most one `painter_viewport` render per `period`, none while
//   minimised). The window is double buffered (decision 227): each frame is composed off screen
//   and presented whole, only when it changed or Windows asks, and never erased. The
//   `painter_iray` panel states that the mode is unavailable: no capture can exist before the path
//   tracer (P3-PATHTRACER). Errors (an unsupported display configuration, a
//   missing environment, no mesh) are shown in place of the image, and nothing is drawn.
// - The stall hook (`Stall`) blocks the preview thread while it holds its frame, for the tests of
//   item 3.2; nothing else ever waits for that thread.

#include "evaluator/evaluate.h"
#include "evaluator/height_to_normal.h"
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

#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::preview {

/// The material inputs the viewport reads (viewport.h `MaterialInputs`).
enum class MaterialSlot : uint8_t { BaseColor, Metalness, Roughness, Normal };

/// The slot an evaluated channel feeds: BaseColor; BaseMetalness or Metallic; SpecularRoughness or
/// Roughness; Normal. Empty for every other channel.
[[nodiscard]] std::optional<MaterialSlot> SlotOf(core::ChannelType channel);

/// The channel of `stack` that feeds `slot`: the OpenPBR name, else the legacy one; none for
/// `Normal` (the combined virtual map feeds it) and for a slot the stack has no channel for.
[[nodiscard]] std::optional<core::ChannelType> ChannelFor(const core::Stack& stack, MaterialSlot slot);

using EvaluatedMap =
    std::variant<std::shared_ptr<const evaluator::ChannelResult>, std::shared_ptr<const evaluator::VirtualNormalResult>>;

/// What the preview shows: the last evaluation, as published.
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
    /// The last evaluated map of each (texture set id, slot).
    std::map<std::pair<core::Id, MaterialSlot>, EvaluatedMap> maps;
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
    /// Records the state an evaluation of `revision` read. The environment's bytes are read with
    /// `read` only when its hash differs from the last one.
    void Update(std::int64_t revision, std::shared_ptr<const core::Project> project,
                std::shared_ptr<const mesh::TexturingMesh> mesh, const ResourceReader& read);
    /// Records the last evaluation of `slot` of texture set `set`.
    void Record(core::Id set, MaterialSlot slot, EvaluatedMap map);
    /// Makes the accumulated state the newest frame. Wait-free with respect to the preview thread.
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
    std::int64_t revisionShown = -1;
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
    std::atomic<std::uint64_t> m_taken{0};
    std::atomic<std::uint64_t> m_rendered{0};
    std::atomic<std::uint64_t> m_presents{0};
    std::atomic<std::int64_t> m_revisionShown{-1};
    mutable std::mutex m_errorMutex;  // guards m_lastError only; the publisher never takes it
    std::string m_lastError;
    std::thread m_thread;
};

/// The viewport inputs of `frame`: its texture sets' maps in mesh material order (texture set i is
/// material i), with the defaults of `MaterialInputs` where a slot was never evaluated.
[[nodiscard]] std::vector<MaterialInputs> MaterialsOf(const PreviewFrame& frame);

/// The decoded environments' lighting by SHA-256, kept by a caller across frames.
using LightingCache = std::unordered_map<std::string, std::shared_ptr<const EnvironmentLighting>>;

/// The viewport scene of `frame` (scene.cpp): the display state of the display presets (its view,
/// its config pin and the active preset's clear colour; `python::display::PresetOf`), the mesh,
/// the environment's lighting (from `cache`, decoded and precomputed on first use), the material
/// maps and the environment's rotation and exposure. Otherwise the message that replaces the
/// image: the `unsupported_configuration` error (decision 134), no mesh, a missing environment or
/// a frame without one (RES-03), an environment that does not decode.
[[nodiscard]] std::expected<ViewportScene, std::string> SceneOf(const PreviewFrame& frame, LightingCache& cache);

}  // namespace uzp::preview
