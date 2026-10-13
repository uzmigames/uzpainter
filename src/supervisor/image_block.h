#pragma once

// The image content block of `capture` over MCP (`docs/architecture/11-mcp-server.md` §2, 02 §2:
// "a downscaled PNG built by the supervisor from the file"; task phase2.6_mcp-typed-tool-families,
// decision 165). The supervisor's embedded interpreter has no image library, so the supervisor
// calls this native function, registered as the built-in module `_uzpainter_image`
// (`preview_png(png: bytes, max_edge: int) -> bytes`). It is the supervisor's own helper, not part of
// the `uzpainter` API.

#include <cstdint>
#include <string>
#include <string_view>

namespace uzp::supervisor {

/// The largest PNG file and side `PreviewPng` decodes: a capture's PNG is far smaller, and the
/// limits keep a malformed or hostile file from exhausting the supervisor's memory.
inline constexpr std::size_t kPreviewSourceBytes = 512u * 1024u * 1024u;
inline constexpr std::uint32_t kPreviewSourceSide = 16384;

/// `png` decoded (8- or 16-bit grey or RGB; an alpha channel is not kept), averaged over k×k
/// blocks with the smallest whole k that brings the long edge to at most `max_edge` (k = 1 keeps
/// the size; edge blocks average the pixels they hold), each average rounded to the nearest 8-bit
/// code (half up), and encoded as an 8-bit PNG of the same channels. Throws `std::invalid_argument`
/// for a file that is not a PNG, is over the limits above, or does not decode, and for `max_edge`
/// 0.
[[nodiscard]] std::string PreviewPng(std::string_view png, std::uint32_t max_edge);

}  // namespace uzp::supervisor
