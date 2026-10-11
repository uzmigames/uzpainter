#pragma once

// The `.uzp` container: a SQLite database (vendored public-domain amalgamation) with zstd
// payloads (`docs/architecture/09-project-file-format.md` §1). The container is an
// implementation detail; the public schema is the canonical JSON manifest each revision stores.
//
// Files at rest use `journal_mode = DELETE` with `synchronous = FULL`: SQLite's rollback journal
// keeps a file at either the previous or the new state when a commit is interrupted
// (https://www.sqlite.org/atomiccommit.html). Foreign keys are enforced on every connection.
// Every connection waits up to `kBusyTimeoutMs` for another connection's file lock (a worker's
// commit while `uzpainter inspect` reads, and the reverse) instead of failing at once.
// This file creates `meta`, `revision`, `blob`, `blob_meta`, `operation`, `cache`, `checkpoint`,
// `locator` (the `{path, sha256}` locators of a non-portable project, 09 §2) and the raster-plane
// tables `plane`, `plane_version` and `plane_chunk` (`planes.h`).

#include <cstdint>
#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

struct sqlite3;
struct sqlite3_stmt;

namespace uzp::store {

/// How long a connection waits for another connection's SQLite file lock.
inline constexpr int kBusyTimeoutMs = 10000;

/// Every error of the project store. `code()` names the class; the message starts with its
/// spelling (`CodeName`) and says what failed.
class StoreError : public std::runtime_error {
public:
    enum class Code {
        io,                  // the file cannot be opened, read or written
        disk_full,           // SQLITE_FULL: the commit was rolled back, the file holds the previous state
        corrupt,             // a hash, a payload or the SQLite structure does not verify
        version,             // `format_version` cannot be read by this reader
        not_a_project,       // the file is not a `.uzp` container
        exists,              // `Create` on an existing path
        missing_resource,    // a commit names resource bytes the store does not hold
        missing_dependency,  // a non-portable locator target is absent or changed
        conflict,            // the store and the document disagree (revision, project uuid)
        locked,              // another live worker holds the project's lock sidecar
        protected_checkpoint,  // a save or compaction would overwrite or collapse a protected checkpoint
        not_retained,        // a revert names a revision or checkpoint outside the retained set
    };

    StoreError(Code code, const std::string& message);
    Code code() const { return code_; }

private:
    Code code_;
};

/// The spelling of `code` in reports (`"disk_full"`, ...).
std::string_view CodeName(StoreError::Code code);

/// zstd frame of `bytes` (level 3, content size and checksum in the frame).
std::string Compress(std::string_view bytes);

/// The bytes of one zstd frame. Throws `StoreError(corrupt)` when the frame is malformed, its
/// checksum fails, or its content size is unknown, above `max_size` or (when given) not
/// `expected_size`.
std::string Decompress(std::string_view frame, std::optional<std::uint64_t> expected_size = std::nullopt,
                       std::uint64_t max_size = std::uint64_t{1} << 34);

class Container;

/// A prepared statement. Bind indices start at 1, column indices at 0.
class Statement {
public:
    Statement(Container& container, std::string_view sql);
    ~Statement();
    Statement(const Statement&) = delete;
    Statement& operator=(const Statement&) = delete;

    Statement& Bind(int index, std::int64_t value);
    Statement& Bind(int index, std::string_view text);
    Statement& Bind(int index, const char* text) { return Bind(index, std::string_view(text)); }
    Statement& Bind(int index, const std::string& text) { return Bind(index, std::string_view(text)); }
    Statement& BindBlob(int index, std::string_view bytes);
    Statement& BindNull(int index);

    /// Advances: true when a row is available, false when done. Throws `StoreError`.
    bool Step();
    /// Steps a statement that returns no row.
    void Run();
    void Reset();

    bool IsNull(int column) const;
    std::int64_t Int(int column) const;
    std::string Text(int column) const;
    std::string Blob(int column) const;

private:
    Container& container_;
    sqlite3_stmt* stmt_ = nullptr;
};

class Container {
public:
    /// Creates a new, empty container at `path` (the path must not exist); `CreateSchema` adds
    /// the tables, inside the caller's first write transaction.
    static Container Create(const std::filesystem::path& path);
    /// Opens an existing container read-write. Only connection settings are applied
    /// (`foreign_keys`, `synchronous`); nothing is written (`EnsureDeleteJournal` does that).
    static Container Open(const std::filesystem::path& path);
    /// Opens an existing container read-only (`uzpainter inspect`): the connection never writes
    /// to the file, so a file left with a hot journal by a killed worker is refused
    /// (`StoreError(io)`) instead of being rolled back.
    static Container OpenReadOnly(const std::filesystem::path& path);
    /// Copies the database pages of `source` into the new file `target` (SQLite online backup):
    /// a consistent snapshot that keeps `source`'s read lock only while the pages are copied.
    static void Snapshot(Container& source, const std::filesystem::path& target);

    Container(Container&& other) noexcept;
    Container& operator=(Container&& other) noexcept;
    Container(const Container&) = delete;
    Container& operator=(const Container&) = delete;
    ~Container();

    const std::filesystem::path& path() const { return path_; }
    sqlite3* handle() const { return db_; }

    void Exec(std::string_view sql);
    /// The tables of 09 §1 and `locator`.
    void CreateSchema();
    /// True when the table exists.
    bool HasTable(std::string_view name);
    /// `journal_mode = DELETE` (a no-op when it already is).
    void EnsureDeleteJournal();

    std::optional<std::string> Meta(std::string_view key);
    void SetMeta(std::string_view key, std::string_view value);

    /// Throws the `StoreError` of SQLite result code `rc` (with the connection's message).
    [[noreturn]] void Fail(int rc, std::string_view what) const;

    /// `BEGIN IMMEDIATE` … `COMMIT`; destroying it uncommitted rolls back.
    class WriteTransaction {
    public:
        explicit WriteTransaction(Container& container);
        ~WriteTransaction();
        WriteTransaction(const WriteTransaction&) = delete;
        WriteTransaction& operator=(const WriteTransaction&) = delete;
        void Commit();

    private:
        Container& container_;
        bool open_ = true;
    };

private:
    Container(sqlite3* db, std::filesystem::path path) : db_(db), path_(std::move(path)) {}
    static sqlite3* OpenHandle(const std::filesystem::path& path, bool create, bool read_only = false);
    void Close() noexcept;

    sqlite3* db_ = nullptr;
    std::filesystem::path path_;
};

/// The current UTC time in RFC 3339 (`2026-10-10T12:00:00Z`).
std::string UtcNow();

}  // namespace uzp::store
