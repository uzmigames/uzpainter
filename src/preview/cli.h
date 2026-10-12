#pragma once

// `UzPainter.exe --preview <file.uzp> [--gpu-backend dx12|vulkan]` (docs/architecture/
// 07-preview-and-render-parity.md §6; task phase2.1_preview-viewport-window item 2.5): one process
// in the worker role opens the project read-only for its lifetime (it holds the project's lock, as
// `run` does), evaluates the material channels of every texture set once on its engine (BaseColor,
// BaseMetalness or Metallic, SpecularRoughness or Roughness, and the combined Normal_OpenGL map),
// publishes them to the preview (preview.h) and shows the window until it is closed.
//
// Output: when the window closes, one line `UZP_JSON:{"status": "closed", "frames_rendered",
// "revision_shown", "last_error"}` on `out`. Exit status: 0 the window was shown and closed; 1 the
// project could not be opened or the window could not be created (message on `err`); 2 a usage
// error.

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

/// True for `--preview`.
bool IsPreviewCommand(std::string_view first);

/// Runs `args` (`--preview` first) and returns the exit status.
int RunPreviewCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);

/// Evaluates the preview's material channels of every texture set of `open`'s current revision
/// with `evaluator` and publishes them to `feed`. Returns one line per failed evaluation (the slot
/// keeps its default).
std::vector<std::string> EvaluateForPreview(const python::OpenProject& open, evaluator::Evaluator& evaluator,
                                            PreviewFeed& feed);

}  // namespace uzp::preview
