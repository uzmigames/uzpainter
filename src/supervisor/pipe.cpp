// The worker's end of the supervisor pipe (pipe.h).

#include "supervisor/pipe.h"

#include <algorithm>
#include <mutex>
#include <vector>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <sddl.h>

namespace uzp::supervisor {

namespace {

constexpr DWORD kBufferBytes = 1 << 16;

std::string LastError(const char* what) { return std::string(what) + " failed (Windows error " + std::to_string(GetLastError()) + ")"; }

/// The SID of the user the process runs as, in string form; empty on failure.
std::wstring CurrentUserSid() {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return {};
    DWORD size = 0;
    GetTokenInformation(token, TokenUser, nullptr, 0, &size);
    std::vector<unsigned char> buffer(size);
    std::wstring sid;
    if (size != 0 && GetTokenInformation(token, TokenUser, buffer.data(), size, &size)) {
        wchar_t* text = nullptr;
        if (ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buffer.data())->User.Sid, &text)) {
            sid = text;
            LocalFree(text);
        }
    }
    CloseHandle(token);
    return sid;
}

}  // namespace

struct PipeServer::Impl {
    HANDLE pipe = INVALID_HANDLE_VALUE;
    HANDLE connect_event = nullptr;
    HANDLE read_event = nullptr;
    HANDLE write_event = nullptr;
    std::mutex write_mutex;

    ~Impl() {
        if (pipe != INVALID_HANDLE_VALUE) CloseHandle(pipe);
        for (HANDLE event : {connect_event, read_event, write_event}) {
            if (event) CloseHandle(event);
        }
    }
};

PipeServer::PipeServer(std::unique_ptr<Impl> impl) : m_impl(std::move(impl)) {}
PipeServer::~PipeServer() = default;

std::unique_ptr<PipeServer> PipeServer::Create(const std::wstring& path, std::string& error) {
    const std::wstring sid = CurrentUserSid();
    if (sid.empty()) {
        error = LastError("reading the current user's SID");
        return nullptr;
    }
    // Protected DACL: generic all to the current user, nobody else.
    const std::wstring sddl = L"D:P(A;;GA;;;" + sid + L")";
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &descriptor, nullptr)) {
        error = LastError("building the pipe's security descriptor");
        return nullptr;
    }
    SECURITY_ATTRIBUTES attributes{sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
    auto impl = std::make_unique<Impl>();
    impl->pipe = CreateNamedPipeW(path.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED,
                                  PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS, 1,
                                  kBufferBytes, kBufferBytes, 0, &attributes);
    LocalFree(descriptor);
    if (impl->pipe == INVALID_HANDLE_VALUE) {
        error = LastError("CreateNamedPipeW");
        return nullptr;
    }
    impl->connect_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    impl->read_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    impl->write_event = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    if (!impl->connect_event || !impl->read_event || !impl->write_event) {
        error = LastError("CreateEventW");
        return nullptr;
    }
    return std::unique_ptr<PipeServer>(new PipeServer(std::move(impl)));
}

bool PipeServer::Accept(std::uint32_t client_pid, void* client_process, std::chrono::milliseconds timeout,
                        std::string& error) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    for (;;) {
        // Checked before every attempt: a refused client that connects again at once must not
        // keep the worker waiting past its deadline or past its supervisor's end.
        if (client_process && WaitForSingleObject(static_cast<HANDLE>(client_process), 0) == WAIT_OBJECT_0) {
            error = "the supervisor process ended before it connected";
            return false;
        }
        if (std::chrono::steady_clock::now() >= deadline) {
            error = "the supervisor did not connect in time";
            return false;
        }
        OVERLAPPED overlapped{};
        overlapped.hEvent = m_impl->connect_event;
        ResetEvent(overlapped.hEvent);
        if (!ConnectNamedPipe(m_impl->pipe, &overlapped)) {
            const DWORD code = GetLastError();
            if (code == ERROR_IO_PENDING) {
                const auto left = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now());
                HANDLE waits[2] = {overlapped.hEvent, static_cast<HANDLE>(client_process)};
                const DWORD count = client_process ? 2 : 1;
                const DWORD wait = WaitForMultipleObjects(count, waits, FALSE,
                                                          static_cast<DWORD>(std::max<long long>(left.count(), 0)));
                DWORD ignored = 0;
                if (wait != WAIT_OBJECT_0) {
                    CancelIoEx(m_impl->pipe, &overlapped);
                    GetOverlappedResult(m_impl->pipe, &overlapped, &ignored, TRUE);
                    error = wait == WAIT_OBJECT_0 + 1 ? "the supervisor process ended before it connected"
                                                      : "the supervisor did not connect in time";
                    return false;
                }
                if (!GetOverlappedResult(m_impl->pipe, &overlapped, &ignored, FALSE)) {
                    error = LastError("ConnectNamedPipe");
                    return false;
                }
            } else if (code != ERROR_PIPE_CONNECTED) {
                SetLastError(code);
                error = LastError("ConnectNamedPipe");
                return false;
            }
        }
        ULONG pid = 0;
        if (GetNamedPipeClientProcessId(m_impl->pipe, &pid) && pid == client_pid) return true;
        ++m_refused;
        DisconnectNamedPipe(m_impl->pipe);
    }
}

std::optional<std::string> PipeServer::Read() {
    std::string buffer(kBufferBytes, '\0');
    for (;;) {
        OVERLAPPED overlapped{};
        overlapped.hEvent = m_impl->read_event;
        ResetEvent(overlapped.hEvent);
        DWORD count = 0;
        BOOL ok = ReadFile(m_impl->pipe, buffer.data(), kBufferBytes, &count, &overlapped);
        if (!ok && GetLastError() == ERROR_IO_PENDING) ok = GetOverlappedResult(m_impl->pipe, &overlapped, &count, TRUE);
        if (!ok) return std::nullopt;  // ERROR_BROKEN_PIPE: the client closed its end
        if (count == 0) continue;
        buffer.resize(count);
        return buffer;
    }
}

bool PipeServer::Write(std::string_view bytes) {
    std::lock_guard lock(m_impl->write_mutex);
    while (!bytes.empty()) {
        OVERLAPPED overlapped{};
        overlapped.hEvent = m_impl->write_event;
        ResetEvent(overlapped.hEvent);
        const DWORD chunk = static_cast<DWORD>(std::min<std::size_t>(bytes.size(), kBufferBytes));
        DWORD written = 0;
        BOOL ok = WriteFile(m_impl->pipe, bytes.data(), chunk, &written, &overlapped);
        if (!ok && GetLastError() == ERROR_IO_PENDING) ok = GetOverlappedResult(m_impl->pipe, &overlapped, &written, TRUE);
        if (!ok) return false;
        bytes.remove_prefix(written);
    }
    return true;
}

}  // namespace uzp::supervisor
