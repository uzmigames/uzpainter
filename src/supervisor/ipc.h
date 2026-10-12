#pragma once

// The private pipe protocol between the supervisor and its worker
// (docs/architecture/02-runtime-topology.md §2; task phase2.1_supervisor-ipc-worker, `SUPERVISOR.md`).
//
// Frames are newline-delimited UTF-8 JSON objects in canonical form (`core::json::WriteCanonical`,
// which escapes every control character, so a frame holds no literal newline). The worker speaks
// first with the handshake frame; then the supervisor sends requests and the worker answers each
// with one reply carrying the request's `id`:
//
// - request  `{"id", "method": "tools/list"}` or `{"id", "method": "tools/call", "name", "arguments",
//   "idempotency_key", "expected_revision"}` (the key required on a mutating tool, the precondition
//   decided with it); `{"id", "method": "worker/reopen" | "worker/operations", ...}` (supervisor
//   recovery and reconciliation, not tools);
// - reply    `{"id", "result": {...}, "committed_revision"?, "admission"?, "request_hash"?}` (the
//   last two on a mutating call: `executed` or `stored_outcome`) or `{"id", "error": {"code",
//   "message", "details"}}`;
// - notifications (no `id`): `{"job_id", "status", "progress", "message"}` and
//   `{"event": "revision", "revision", "project", "project_uuid", "untitled"}`.
//
// Large payloads never travel inline: the worker writes them under its output root and replies
// with their path and SHA-256.

#include <cstddef>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "uzp_core/manifest/json.h"

namespace uzp::supervisor {

/// The protocol version of the handshake.
inline constexpr std::string_view kProtocol = "uzp-ipc/1";

/// The largest frame either side accepts, newline excluded (large payloads go by path).
inline constexpr std::size_t kMaxFrameBytes = std::size_t{16} << 20;

/// A frame longer than `kMaxFrameBytes` given to `EncodeFrame`.
class FrameError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// The canonical text of `frame` followed by `\n`; `FrameError` when it is too long.
[[nodiscard]] std::string EncodeFrame(const core::json::Object& frame);

/// What one `FrameDecoder::Feed` completed.
struct Decoded {
    std::vector<core::json::Object> frames;
    /// One message per rejected frame: not JSON, not a JSON object, or longer than
    /// `kMaxFrameBytes` (skipped up to its newline).
    std::vector<std::string> errors;
};

/// Splits a byte stream into frames.
class FrameDecoder {
public:
    /// Appends `bytes` and returns every frame they complete, in order, with the frames rejected
    /// on the way; the decoder stays usable after a rejected frame.
    Decoded Feed(std::string_view bytes);

private:
    std::string m_pending;
    bool m_discarding = false;  ///< Inside an oversized frame, up to its newline.
};

/// What the worker reports in its handshake.
struct Handshake {
    std::int64_t worker_pid = 0;
    std::string build;
    std::string gpu_backend;  ///< "dx12" or "vulkan"
    bool gpu_ready = false;   ///< `gpu_status`: "ready" or "unavailable"
    bool python_allowed = false;  ///< `python`: "allowed" or "disabled"
};

/// `{"protocol": "uzp-ipc/1", "worker_pid", "build", "gpu_backend", "gpu_status", "python"}`.
[[nodiscard]] core::json::Object HandshakeFrame(const Handshake& handshake);

/// `{"id", "result", "committed_revision"?}`.
[[nodiscard]] core::json::Object ResultReply(const core::json::Value& id, core::json::Object result,
                                             std::optional<std::int64_t> committed_revision);

/// `{"id", "error": {"code", "message", "details"}}`.
[[nodiscard]] core::json::Object ErrorReply(const core::json::Value& id, std::string code, std::string message,
                                            core::json::Object details = {});

/// The build reported in the handshake: `<version>+uzpainter-<build mode>`.
[[nodiscard]] std::string BuildString();

}  // namespace uzp::supervisor
