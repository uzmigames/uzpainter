#include "store/container.h"

#include <array>
#include <chrono>
#include <cstdio>
#include <ctime>
#include <utility>

#include "sqlite3.h"
#include "store/fault.h"
#include "zstd.h"

namespace uzp::store {
namespace {

// 09-project-file-format.md §1. `locator` holds the `{path, sha256}` locators of a non-portable
// project (09 §2). The `plane*` tables hold the authoritative raster planes (`planes.h`): the
// triggers refuse any change to a committed `plane_version` (one created at or below
// `checkpoint('current')`) and to its chunk rows; compaction may delete unreachable rows. The
// indexes cover the child keys of the plane foreign keys.
constexpr const char* kSchema = R"sql(
CREATE TABLE meta      (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE revision  (revision INTEGER PRIMARY KEY, parent INTEGER, created_at TEXT, kind TEXT, name TEXT,
                        manifest BLOB, manifest_sha256 TEXT);
CREATE TABLE blob      (sha256 TEXT PRIMARY KEY, mime TEXT, size INTEGER, zstd_size INTEGER, data BLOB);
CREATE TABLE blob_meta (sha256 TEXT, name TEXT, usage TEXT, origin TEXT, color_space TEXT, imported_at TEXT,
                        PRIMARY KEY (sha256, name));
CREATE TABLE operation (idempotency_key TEXT PRIMARY KEY, project_uuid TEXT, request_hash TEXT, outcome BLOB,
                        committed_revision INTEGER REFERENCES revision, created_at TEXT);
CREATE TABLE cache     (key TEXT PRIMARY KEY, revision INTEGER, evaluator_profile TEXT, sha256 TEXT);
CREATE TABLE checkpoint(name TEXT PRIMARY KEY, revision INTEGER, created_at TEXT, note TEXT, protected INTEGER);
CREATE TABLE locator   (sha256 TEXT PRIMARY KEY, path TEXT NOT NULL);
CREATE TABLE plane     (plane_id INTEGER PRIMARY KEY, set_id INTEGER, stack_id INTEGER, channel TEXT, tile_u INTEGER,
                        tile_v INTEGER, format TEXT, width INTEGER, height INTEGER, chunk_size INTEGER,
                        created_revision INTEGER);
CREATE TABLE plane_version(version_id INTEGER PRIMARY KEY, plane_id INTEGER REFERENCES plane, created_revision INTEGER,
                        chunk_root TEXT);
CREATE TABLE plane_chunk(version_id INTEGER REFERENCES plane_version, chunk_x INTEGER, chunk_y INTEGER,
                        sha256 TEXT REFERENCES blob, PRIMARY KEY (version_id, chunk_x, chunk_y));
CREATE INDEX plane_version_plane ON plane_version (plane_id);
CREATE INDEX plane_chunk_sha256 ON plane_chunk (sha256);
CREATE TRIGGER plane_immutable BEFORE UPDATE ON plane
BEGIN SELECT RAISE(ABORT, 'a plane row is immutable'); END;
CREATE TRIGGER plane_version_immutable BEFORE UPDATE ON plane_version
BEGIN SELECT RAISE(ABORT, 'a plane_version is immutable'); END;
CREATE TRIGGER plane_chunk_immutable BEFORE UPDATE ON plane_chunk
BEGIN SELECT RAISE(ABORT, 'the chunk rows of a plane_version are immutable'); END;
CREATE TRIGGER plane_chunk_committed BEFORE INSERT ON plane_chunk
WHEN (SELECT created_revision FROM plane_version WHERE version_id = NEW.version_id)
     <= (SELECT revision FROM checkpoint WHERE name = 'current')
BEGIN SELECT RAISE(ABORT, 'a committed plane_version is immutable'); END;
)sql";

StoreError::Code CodeOf(int rc) {
    switch (rc & 0xff) {
        case SQLITE_FULL:
            return StoreError::Code::disk_full;
        case SQLITE_CORRUPT:
            return StoreError::Code::corrupt;
        case SQLITE_NOTADB:
            return StoreError::Code::not_a_project;
        default:
            return StoreError::Code::io;
    }
}

std::string Utf8(const std::filesystem::path& path) {
    const std::u8string text = path.u8string();
    return std::string(text.begin(), text.end());
}

}  // namespace

StoreError::StoreError(Code code, const std::string& message)
    : std::runtime_error(std::string(CodeName(code)) + ": " + message), code_(code) {}

std::string_view CodeName(StoreError::Code code) {
    static constexpr std::array<std::string_view, 9> names = {
        "io", "disk_full", "corrupt", "version", "not_a_project", "exists", "missing_resource", "missing_dependency",
        "conflict"};
    return names[static_cast<std::size_t>(code)];
}

std::string Compress(std::string_view bytes) {
    ZSTD_CCtx* cctx = ZSTD_createCCtx();
    if (cctx == nullptr) throw StoreError(StoreError::Code::io, "zstd: out of memory");
    ZSTD_CCtx_setParameter(cctx, ZSTD_c_compressionLevel, 3);
    ZSTD_CCtx_setParameter(cctx, ZSTD_c_checksumFlag, 1);
    ZSTD_CCtx_setParameter(cctx, ZSTD_c_contentSizeFlag, 1);
    std::string frame(ZSTD_compressBound(bytes.size()), '\0');
    const std::size_t size = ZSTD_compress2(cctx, frame.data(), frame.size(), bytes.data(), bytes.size());
    ZSTD_freeCCtx(cctx);
    if (ZSTD_isError(size)) throw StoreError(StoreError::Code::io, std::string("zstd: ") + ZSTD_getErrorName(size));
    frame.resize(size);
    return frame;
}

std::string Decompress(std::string_view frame, std::optional<std::uint64_t> expected_size, std::uint64_t max_size) {
    const unsigned long long declared = ZSTD_getFrameContentSize(frame.data(), frame.size());
    if (declared == ZSTD_CONTENTSIZE_ERROR || declared == ZSTD_CONTENTSIZE_UNKNOWN) {
        throw StoreError(StoreError::Code::corrupt, "zstd: not a frame with a content size");
    }
    if (declared > max_size || (expected_size && declared != *expected_size)) {
        throw StoreError(StoreError::Code::corrupt, "zstd: frame declares " + std::to_string(declared) + " bytes" +
                                                        (expected_size ? ", expected " + std::to_string(*expected_size)
                                                                       : std::string()));
    }
    std::string bytes(static_cast<std::size_t>(declared), '\0');
    const std::size_t size = ZSTD_decompress(bytes.data(), bytes.size(), frame.data(), frame.size());
    if (ZSTD_isError(size)) throw StoreError(StoreError::Code::corrupt, std::string("zstd: ") + ZSTD_getErrorName(size));
    if (size != declared) throw StoreError(StoreError::Code::corrupt, "zstd: frame shorter than declared");
    return bytes;
}

// ── Statement ─────────────────────────────────────────────────────────────────────────────────

Statement::Statement(Container& container, std::string_view sql) : container_(container) {
    const int rc = sqlite3_prepare_v2(container.handle(), sql.data(), static_cast<int>(sql.size()), &stmt_, nullptr);
    if (rc != SQLITE_OK) container.Fail(rc, "prepare");
}

Statement::~Statement() { sqlite3_finalize(stmt_); }

Statement& Statement::Bind(int index, std::int64_t value) {
    const int rc = sqlite3_bind_int64(stmt_, index, value);
    if (rc != SQLITE_OK) container_.Fail(rc, "bind");
    return *this;
}

Statement& Statement::Bind(int index, std::string_view text) {
    const int rc = sqlite3_bind_text64(stmt_, index, text.data(), text.size(), SQLITE_TRANSIENT, SQLITE_UTF8);
    if (rc != SQLITE_OK) container_.Fail(rc, "bind");
    return *this;
}

Statement& Statement::BindBlob(int index, std::string_view bytes) {
    const int rc = sqlite3_bind_blob64(stmt_, index, bytes.data(), bytes.size(), SQLITE_TRANSIENT);
    if (rc != SQLITE_OK) container_.Fail(rc, "bind");
    return *this;
}

Statement& Statement::BindNull(int index) {
    const int rc = sqlite3_bind_null(stmt_, index);
    if (rc != SQLITE_OK) container_.Fail(rc, "bind");
    return *this;
}

bool Statement::Step() {
    const int rc = sqlite3_step(stmt_);
    if (rc == SQLITE_ROW) return true;
    if (rc == SQLITE_DONE) return false;
    container_.Fail(rc, sqlite3_sql(stmt_));
}

void Statement::Run() {
    while (Step()) {
    }
}

void Statement::Reset() {
    sqlite3_reset(stmt_);
    sqlite3_clear_bindings(stmt_);
}

bool Statement::IsNull(int column) const { return sqlite3_column_type(stmt_, column) == SQLITE_NULL; }
std::int64_t Statement::Int(int column) const { return sqlite3_column_int64(stmt_, column); }

std::string Statement::Text(int column) const {
    const auto* text = reinterpret_cast<const char*>(sqlite3_column_text(stmt_, column));
    return text ? std::string(text, static_cast<std::size_t>(sqlite3_column_bytes(stmt_, column))) : std::string();
}

std::string Statement::Blob(int column) const {
    const void* data = sqlite3_column_blob(stmt_, column);
    const int size = sqlite3_column_bytes(stmt_, column);
    return data ? std::string(static_cast<const char*>(data), static_cast<std::size_t>(size)) : std::string();
}

// ── Container ─────────────────────────────────────────────────────────────────────────────────

sqlite3* Container::OpenHandle(const std::filesystem::path& path, bool create) {
    const char* vfs = nullptr;
#if defined(UZP_STORE_FAULT_HOOKS)
    vfs = fault::VfsName();
#endif
    sqlite3* db = nullptr;
    const int flags = SQLITE_OPEN_READWRITE | (create ? SQLITE_OPEN_CREATE : 0) | SQLITE_OPEN_FULLMUTEX |
                      SQLITE_OPEN_EXRESCODE;
    const int rc = sqlite3_open_v2(Utf8(path).c_str(), &db, flags, vfs);
    if (rc != SQLITE_OK) {
        const std::string message = db ? sqlite3_errmsg(db) : sqlite3_errstr(rc);
        sqlite3_close(db);
        throw StoreError(CodeOf(rc), "cannot open " + Utf8(path) + ": " + message);
    }
    return db;
}

Container Container::Create(const std::filesystem::path& path) {
    std::error_code ec;
    if (std::filesystem::exists(path, ec)) throw StoreError(StoreError::Code::exists, Utf8(path) + " already exists");
    Container container(OpenHandle(path, true), path);
    container.Exec("PRAGMA journal_mode = DELETE");
    container.Exec("PRAGMA synchronous = FULL");
    container.Exec("PRAGMA foreign_keys = ON");
    return container;
}

Container Container::Open(const std::filesystem::path& path) {
    std::error_code ec;
    if (!std::filesystem::is_regular_file(path, ec)) throw StoreError(StoreError::Code::io, Utf8(path) + " is not a file");
    Container container(OpenHandle(path, false), path);
    container.Exec("PRAGMA synchronous = FULL");
    container.Exec("PRAGMA foreign_keys = ON");
    return container;
}

Container::Container(Container&& other) noexcept
    : db_(std::exchange(other.db_, nullptr)), path_(std::move(other.path_)) {}

Container& Container::operator=(Container&& other) noexcept {
    if (this != &other) {
        Close();
        db_ = std::exchange(other.db_, nullptr);
        path_ = std::move(other.path_);
    }
    return *this;
}

Container::~Container() { Close(); }

void Container::Close() noexcept {
    if (db_ != nullptr) sqlite3_close_v2(db_);
    db_ = nullptr;
}

void Container::Fail(int rc, std::string_view what) const {
    const std::string message = db_ ? sqlite3_errmsg(db_) : sqlite3_errstr(rc);
    throw StoreError(CodeOf(rc), Utf8(path_) + ": " + message + " (" + std::string(what) + ")");
}

void Container::Exec(std::string_view sql) {
    const std::string text(sql);
    const int rc = sqlite3_exec(db_, text.c_str(), nullptr, nullptr, nullptr);
    if (rc != SQLITE_OK) Fail(rc, text);
}

bool Container::HasTable(std::string_view name) {
    Statement q(*this, "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?");
    q.Bind(1, name);
    return q.Step();
}

void Container::EnsureDeleteJournal() {
    Statement q(*this, "PRAGMA journal_mode");
    if (q.Step() && q.Text(0) == "delete") return;
    Exec("PRAGMA journal_mode = DELETE");
}

std::optional<std::string> Container::Meta(std::string_view key) {
    Statement q(*this, "SELECT value FROM meta WHERE key = ?");
    q.Bind(1, key);
    if (!q.Step() || q.IsNull(0)) return std::nullopt;
    return q.Text(0);
}

void Container::SetMeta(std::string_view key, std::string_view value) {
    Statement q(*this, "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value");
    q.Bind(1, key).Bind(2, value).Run();
}

Container::WriteTransaction::WriteTransaction(Container& container) : container_(container) {
    container_.Exec("BEGIN IMMEDIATE");
}

Container::WriteTransaction::~WriteTransaction() {
    if (open_ && !sqlite3_get_autocommit(container_.handle())) {
        sqlite3_exec(container_.handle(), "ROLLBACK", nullptr, nullptr, nullptr);
    }
}

void Container::WriteTransaction::Commit() {
#if defined(UZP_STORE_FAULT_HOOKS)
    fault::EnterCommit();
#endif
    const int rc = sqlite3_exec(container_.handle(), "COMMIT", nullptr, nullptr, nullptr);
#if defined(UZP_STORE_FAULT_HOOKS)
    fault::LeaveCommit();
#endif
    if (rc != SQLITE_OK) container_.Fail(rc, "COMMIT");
    open_ = false;
}

std::string UtcNow() {
    const std::time_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    std::tm utc{};
    gmtime_s(&utc, &now);
    char text[32];
    std::snprintf(text, sizeof text, "%04d-%02d-%02dT%02d:%02d:%02dZ", utc.tm_year + 1900, utc.tm_mon + 1,
                  utc.tm_mday, utc.tm_hour, utc.tm_min, utc.tm_sec);
    return text;
}

void Container::CreateSchema() { Exec(kSchema); }

}  // namespace uzp::store
