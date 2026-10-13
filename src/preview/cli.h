#pragma once

// `UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan]` (docs/architecture/
// 07-preview-and-render-parity.md §6; task phase2.1_preview-viewport-window item 2.5): one process
// in the worker role opens the project read-only for its lifetime (it holds the project's lock, as
// `run` does), evaluates the material channels of every texture set once on its engine (BaseColor,
// BaseMetalness or Metallic, SpecularRoughness or Roughness, and the combined Normal_OpenGL map;
// `EvaluateFrame`, evaluation.h), publishes them to the preview (preview.h) and shows the window
// until it is closed. A project whose display configuration the viewport refuses (a Legacy
// project, decision 038) is not evaluated: the window shows the refusal and nothing is rendered.
//
// Output: when the window closes, one line `UZP_JSON:{"status": "closed", "frames_rendered",
// "revision_shown", "display", "last_error"}` on `out`; `display` is the panel's display line
// (`DisplayLabel`). Exit status: 0 the window was shown and closed (also when it only showed a
// refusal: `frames_rendered` 0 and the refusal in `last_error`); 1 the project could not be opened
// or the window could not be created (message on `err`); 2 a usage error, which includes a preview
// asked for while headless.
//
// Headless (decision 252): no role opens a window unless `--preview` asks for one. `UZP_HEADLESS=1`
// in the environment, which a `--headless` option sets for the process and its children, refuses
// every window as a usage error before any project or device is opened: `--preview <file>`,
// `--mcp --preview` (python/uzpainter_supervisor/main.py) and `--worker --preview`.

#include <cstdio>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "preview/preview.h"

namespace uzp::python {
struct OpenProject;
}

namespace uzp::evaluator {
class Evaluator;
}

namespace uzp::preview {

inline constexpr int kPreviewOk = 0;
inline constexpr int kPreviewFailed = 1;
inline constexpr int kPreviewUsage = 2;

inline constexpr const char* kHeadlessOption = "--headless";
inline constexpr const char* kHeadlessEnv = "UZP_HEADLESS";
/// The refusal of a window while headless, after `<command>: `.
inline constexpr const char* kHeadlessRefusal =
    "the preview opens a window, which headless refuses (UZP_HEADLESS=1 or --headless, decision 252)";

/// True when `UZP_HEADLESS` is `1`.
bool Headless();

/// Sets `UZP_HEADLESS=1` in this process's environment, which its children inherit.
void SetHeadless();

/// True for `--preview`.
bool IsPreviewCommand(std::string_view first);

/// Runs `args` (`--preview` first) and returns the exit status.
int RunPreviewCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

/// Evaluates the preview's material channels of every texture set of `open`'s current revision
/// with `evaluator` and publishes them to `feed` (`EvaluateFrame`). Returns one line per failed
/// evaluation (the window shows them in place of the image).
std::vector<std::string> EvaluateForPreview(const python::OpenProject& open, evaluator::Evaluator& evaluator,
                                            PreviewFeed& feed);

}  // namespace uzp::preview
