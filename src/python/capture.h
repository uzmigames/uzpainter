#pragma once

// Captures of the open project (docs/architecture/07-preview-and-render-parity.md §5; task
// phase2.2_preview-capture, decision 148), shared by `uzpainter.render.capture` (bind_display.cpp)
// and the worker's `capture` tool (src/supervisor/worker.cpp). Nothing here commits a revision.
//
// Every mode reads the committed revision of the open project once (inside an open native
// `Transaction` it refuses with `RuntimeError`, as the export does) and evaluates it
// synchronously, so the capture shows exactly the revision its receipt names.
//
// - `painter_iray` raises `PathTracerUnavailable` before anything else: no argument is checked,
//   no project read, no device created and no file written (a release gap until P3-PATHTRACER).
// - `painter_viewport`: base colour, metalness, roughness and the combined Normal_OpenGL map of
//   every texture set's first stack evaluated on a CPU evaluator with the export's inputs; the
//   scene of the preview window (`preview::SceneOf`) with the project's display state, or with
//   `preset` applied to an in-memory copy; the pass rendered offscreen (no window, no swapchain)
//   on the process's GPU and read back through `TextureReadback`. The display configuration is
//   checked before any evaluation or device. Writes `path` (16-bit RGB PNG of the display codes),
//   `<stem>.exr` (RGB binary16 of the linear colour; alpha is always 1 and is not written).
// - `base_color`, `channel:<name>`, `mask:<uid>`: texture-space captures of one stack, equal to
//   the export by construction. The export engine compiles and encodes a one-file plan of the
//   source (`documentMap baseColor`, `documentMap <name>` with the export's map names,
//   `diagnosticMap materialMask/<uid>`) at the texture set's resolution with padding
//   `passthrough`, as a 16-bit PNG (`path`) and a 32-bit float OpenEXR (`<stem>.exr`).
//
// Every capture writes `<stem>.receipt.json` (`kCaptureReceiptSchema`) and returns it.

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <utility>

#include "render/backend.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/ids.h"

namespace uzp::render {
class Engine;
}

namespace uzp::python {

inline constexpr std::string_view kCaptureReceiptSchema = "uzpainter/capture-receipt/1";

/// The arguments of a capture. An absent option is the mode's default; an option the mode does
/// not take raises `ValueError` when given.
struct CaptureArguments {
    std::string mode;
    /// The PNG to write (its name ends in `.png`); the OpenEXR and the receipt go beside it.
    std::filesystem::path path;
    /// `painter_viewport`: a camera record in Painter's convention (display.h `CameraFromJson`);
    /// default the display state's default camera, else the preview's fit camera.
    std::optional<core::json::Value> camera;
    /// Width and height. Required by `painter_viewport`; a diagnostic mode takes only its set's
    /// resolution (default).
    std::optional<std::pair<std::int64_t, std::int64_t>> size;
    /// `painter_viewport`: 1 (the pass renders one deterministic sample per pixel).
    std::optional<std::int64_t> samples;
    /// `painter_viewport`: recorded in the receipt; the pass uses no randomness. Default the
    /// display state's seed.
    std::optional<std::int64_t> seed;
    /// `painter_viewport`: a standard preset's name or a whole preset (display.h), applied to an
    /// in-memory copy of the project for this capture only.
    std::optional<core::json::Value> preset;
    /// `base_color`, `channel:<name>`: the (texture set, stack); default the active stack.
    std::optional<std::pair<core::Id, core::Id>> stack;
};

/// The GPU of `painter_viewport` captures in this process: the worker's own engine, or, with
/// `engine` null (`UzPainter.exe run`, the test runner), a device of `backend` created for each
/// capture. Dx12 and no engine until set.
void SetCaptureGpu(render::Backend backend, render::Engine* engine);

/// Raises `PathTracerUnavailable` for `painter_iray`; the first step of every capture call.
void RefuseUnavailableMode(std::string_view mode);

/// True when `mode` renders on the GPU (`painter_viewport`).
[[nodiscard]] bool UsesGpu(std::string_view mode);

/// Runs the capture: the receipt it wrote, with `files` {png, exr, receipt} (absolute paths).
/// Raises `ApiError`: `PathTracerUnavailable`; `ValueError` for an unknown mode, a malformed or
/// inapplicable argument, a node in no stack; `UnsupportedInUzPainter` for a display
/// configuration other than the pinned one (decision 134); `NotYetSupported` for an orthographic
/// camera; `ProjectError` without an open project, a mesh or an environment;
/// `ResourceNotFoundError` for an environment the project does not store; `RuntimeError` inside
/// an open Transaction, without a device (`gpu_backend_unavailable {backend, reason}`) or when
/// rendering fails;
/// the export's and the evaluator's classes for a refused or failed evaluation.
[[nodiscard]] core::json::Object Capture(const CaptureArguments& arguments);

}  // namespace uzp::python
