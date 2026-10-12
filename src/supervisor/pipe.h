#pragma once

// The worker's end of the supervisor pipe (docs/architecture/02-runtime-topology.md §1, §2): a
// Windows named pipe in byte mode that accepts exactly one client, its supervisor.
//
// - The pipe is created as the first and only instance of its name (a name already taken fails
//   instead of sharing it), refuses remote clients, and its DACL grants access to the current
//   user only.
// - A connecting process other than the supervisor (checked with `GetNamedPipeClientProcessId`) is
//   disconnected and the worker keeps waiting for its supervisor.
// - The handle is overlapped, so one thread may block in `Read` while another writes.

#include <chrono>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>

namespace uzp::supervisor {

class PipeServer {
public:
    /// Creates the pipe `\\.\pipe\<name>` (the full path is given). Empty and `error` set when it
    /// cannot be created, for example because the name exists.
    static std::unique_ptr<PipeServer> Create(const std::wstring& path, std::string& error);
    ~PipeServer();
    PipeServer(const PipeServer&) = delete;
    PipeServer& operator=(const PipeServer&) = delete;

    /// Waits until process `client_pid` connects, refusing every other client. Fails with a
    /// reason when `timeout` passes first or `client_process` (a process handle) ends.
    [[nodiscard]] bool Accept(std::uint32_t client_pid, void* client_process, std::chrono::milliseconds timeout,
                              std::string& error);

    /// The bytes available next (blocking until some arrive); nullopt once the client closed its
    /// end or the pipe broke.
    std::optional<std::string> Read();
    /// Writes all of `bytes`; false once the pipe is broken. Thread-safe.
    bool Write(std::string_view bytes);

    /// The number of clients `Accept` refused.
    [[nodiscard]] int RefusedClients() const { return m_refused; }

private:
    struct Impl;
    explicit PipeServer(std::unique_ptr<Impl> impl);
    std::unique_ptr<Impl> m_impl;
    int m_refused = 0;
};

}  // namespace uzp::supervisor
