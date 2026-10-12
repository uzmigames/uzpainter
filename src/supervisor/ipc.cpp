// The pipe protocol's frames (ipc.h).

#include "supervisor/ipc.h"

#include "python/session.h"

#ifndef UZP_BUILD_MODE
#error "UZP_BUILD_MODE is defined by build.zig"
#endif

namespace uzp::supervisor {

namespace json = core::json;

std::string EncodeFrame(const json::Object& frame) {
    std::string text = json::WriteCanonical(frame);
    if (text.size() > kMaxFrameBytes) throw FrameError("frame of " + std::to_string(text.size()) + " bytes exceeds the limit");
    text.push_back('\n');
    return text;
}

Decoded FrameDecoder::Feed(std::string_view bytes) {
    Decoded decoded;
    while (!bytes.empty()) {
        const std::size_t newline = bytes.find('\n');
        const std::string_view chunk = bytes.substr(0, newline);
        bytes = newline == std::string_view::npos ? std::string_view() : bytes.substr(newline + 1);
        if (m_discarding) {
            if (newline != std::string_view::npos) m_discarding = false;
            continue;
        }
        m_pending.append(chunk);
        if (m_pending.size() > kMaxFrameBytes) {
            m_pending.clear();
            m_discarding = newline == std::string_view::npos;
            decoded.errors.push_back("frame exceeds " + std::to_string(kMaxFrameBytes) + " bytes");
            continue;
        }
        if (newline == std::string_view::npos) break;
        std::string text = std::move(m_pending);
        m_pending.clear();
        if (!text.empty() && text.back() == '\r') text.pop_back();
        if (text.empty()) continue;
        try {
            json::Value value = json::Parse(text);
            if (!value.IsObject()) {
                decoded.errors.push_back("frame is not a JSON object");
                continue;
            }
            decoded.frames.push_back(std::get<json::Object>(std::move(value.data)));
        } catch (const json::ParseError& e) {
            decoded.errors.push_back(std::string("frame is not JSON: ") + e.what());
        }
    }
    return decoded;
}

json::Object HandshakeFrame(const Handshake& handshake) {
    return {{"protocol", std::string(kProtocol)},
            {"worker_pid", handshake.worker_pid},
            {"build", handshake.build},
            {"gpu_backend", handshake.gpu_backend},
            {"gpu_status", handshake.gpu_ready ? "ready" : "unavailable"},
            {"python", handshake.python_allowed ? "allowed" : "disabled"}};
}

json::Object ResultReply(const json::Value& id, json::Object result, std::optional<std::int64_t> committed_revision) {
    json::Object reply{{"id", id}, {"result", std::move(result)}};
    if (committed_revision) reply["committed_revision"] = *committed_revision;
    return reply;
}

json::Object ErrorReply(const json::Value& id, std::string code, std::string message, json::Object details) {
    return {{"id", id},
            {"error", json::Object{{"code", std::move(code)}, {"message", std::move(message)}, {"details", std::move(details)}}}};
}

std::string BuildString() { return std::string(python::kAppVersion) + "+uzpainter-" + UZP_BUILD_MODE; }

}  // namespace uzp::supervisor
