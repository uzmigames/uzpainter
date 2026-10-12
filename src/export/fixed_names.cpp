#include "export/fixed_names.h"

#include "uzp_core/manifest/json.h"

#include <algorithm>
#include <set>

#if defined(UZP_EXPORT_FAULT_HOOKS)
#include "export/fault.h"
#endif

namespace uzp::exporter {

namespace fs = std::filesystem;
namespace json = core::json;
using publish_detail::Fail;
using publish_detail::ReadBytes;
using publish_detail::RenameDurable;
using publish_detail::Verifies;
using publish_detail::WriteDurable;

namespace {

struct Journal {
    std::string generation;
    std::vector<std::string> files;
    std::vector<std::string> copied;
    std::vector<std::string> obsolete;

    [[nodiscard]] bool Complete() const { return copied.size() == files.size() && obsolete.empty(); }
};

json::Array Strings(const std::vector<std::string>& items) {
    json::Array array;
    for (const std::string& item : items) array.emplace_back(item);
    return array;
}

render::Result<void> WriteJournal(const fs::path& directory, const Journal& journal) {
    const std::string text = json::WriteCanonical(json::Object{{"schema", std::string(kJournalSchema)},
                                                               {"generation", journal.generation},
                                                               {"files", Strings(journal.files)},
                                                               {"copied", Strings(journal.copied)},
                                                               {"obsolete", Strings(journal.obsolete)}});
    const fs::path path = directory / Utf8Path(kJournalFile);
    const fs::path staging = directory / Utf8Path(std::string(kJournalFile) + std::string(kStagingSuffix));
    render::Result<void> written = WriteDurable(staging, text);
    if (!written) return written;
    return RenameDurable(staging, path);
}

/// The journal of `directory`: nullopt when there is none.
render::Result<std::optional<Journal>> ReadJournal(const fs::path& directory) {
    const fs::path path = directory / Utf8Path(kJournalFile);
    std::error_code error;
    if (!fs::exists(path, error)) return std::optional<Journal>{};
    const std::optional<std::string> text = ReadBytes(path);
    if (!text) return Fail("cannot read " + Utf8String(path));
    const auto bad = [&](const std::string& why) {
        return Fail(Utf8String(path) + " is not a fixed-name journal: " + why);
    };
    json::Value value;
    try {
        value = json::Parse(*text);
    } catch (const json::ParseError& e) {
        return bad(e.what());
    }
    if (!value.IsObject()) return bad("expected an object");
    const json::Object& o = std::get<json::Object>(value.data);
    const auto schema = o.find("schema");
    if (schema == o.end() || schema->second != json::Value(kJournalSchema)) {
        return bad("schema: expected " + std::string(kJournalSchema));
    }
    Journal journal;
    const auto generation = o.find("generation");
    if (generation == o.end() || !generation->second.IsString()) return bad("generation: expected a string");
    journal.generation = std::get<std::string>(generation->second.data);
    for (const auto& [key, out] : {std::pair<const char*, std::vector<std::string>*>{"files", &journal.files},
                                   {"copied", &journal.copied},
                                   {"obsolete", &journal.obsolete}}) {
        const auto it = o.find(key);
        if (it == o.end() || !it->second.IsArray()) return bad(std::string(key) + ": expected an array");
        for (const json::Value& item : std::get<json::Array>(it->second.data)) {
            if (!item.IsString() || !IsDeliveryPath(std::get<std::string>(item.data))) {
                return bad(std::string(key) + ": expected relative delivery paths");
            }
            out->push_back(std::get<std::string>(item.data));
        }
    }
    return std::optional<Journal>(std::move(journal));
}

/// Generation `id` of `exportPath`, which must be complete.
render::Result<GenerationState> CompleteGeneration(const fs::path& exportPath, const std::string& id) {
    GenerationState state = InspectGeneration(exportPath, id);
    if (!state.complete) {
        return Fail("generation " + id + " of " + Utf8String(exportPath) + " is not complete: " + state.problem);
    }
    return state;
}

/// Copies `file` of generation `generation` to its fixed name in `directory` (index `index`).
render::Result<void> CopyOne(const fs::path& exportPath, const std::string& generation, const fs::path& directory,
                             const std::string& file, [[maybe_unused]] size_t index) {
    const fs::path source = GenerationPath(exportPath, generation) / "files" / Utf8Path(file);
    const std::optional<std::string> bytes = ReadBytes(source);
    if (!bytes) return Fail("cannot read " + Utf8String(source));
    const fs::path target = directory / Utf8Path(file);
    const fs::path staging = directory / Utf8Path(file + std::string(kStagingSuffix));
    std::error_code error;
    fs::create_directories(target.parent_path(), error);
    if (error) return Fail("cannot create the folder of " + Utf8String(target) + ": " + error.message());
    render::Result<void> written = WriteDurable(staging, *bytes);
    if (!written) return written;
#if defined(UZP_EXPORT_FAULT_HOOKS)
    fault::Reach(fault::Point::kill_before_fixed_rename, index);
#endif
    render::Result<void> renamed = RenameDurable(staging, target);
#if defined(UZP_EXPORT_FAULT_HOOKS)
    if (renamed) fault::Reach(fault::Point::kill_after_fixed_rename, index);
#endif
    return renamed;
}

/// Completes `journal`'s copy into `directory` (the lock held): every file not yet recorded, then
/// the obsolete names.
render::Result<void> RollForward(const fs::path& exportPath, const fs::path& directory, Journal journal) {
    render::Result<GenerationState> state = CompleteGeneration(exportPath, journal.generation);
    if (!state) return render::Unexpected(state.error());
    for (size_t i = 0; i < journal.files.size(); ++i) {
        const std::string& file = journal.files[i];
        if (std::find(journal.copied.begin(), journal.copied.end(), file) != journal.copied.end()) continue;
        render::Result<void> copied = CopyOne(exportPath, journal.generation, directory, file, i);
        if (!copied) return copied;
        journal.copied.push_back(file);
        render::Result<void> recorded = WriteJournal(directory, journal);
        if (!recorded) return recorded;
    }
    if (journal.obsolete.empty()) return {};
    for (const std::string& file : journal.obsolete) {
        std::error_code error;
        fs::remove(directory / Utf8Path(file), error);
        if (error) {
            return Fail("cannot remove the obsolete fixed name " + Utf8String(directory / Utf8Path(file)) + ": " +
                        error.message());
        }
        fs::remove(directory / Utf8Path(file + std::string(kStagingSuffix)), error);
    }
    journal.obsolete.clear();
    return WriteJournal(directory, journal);
}

/// The journal of `directory` (the lock held), rolled forward when its copy was interrupted:
/// nullopt when there is none; `rolled` says whether a roll forward ran.
render::Result<std::optional<Journal>> SettledJournal(const fs::path& exportPath, const fs::path& directory,
                                                      bool& rolled) {
    render::Result<std::optional<Journal>> journal = ReadJournal(directory);
    if (!journal || !*journal) return journal;
    rolled = !(*journal)->Complete();
    if (rolled) {
        render::Result<void> done = RollForward(exportPath, directory, **journal);
        if (!done) return render::Unexpected(done.error());
        journal = ReadJournal(directory);
    }
    return journal;
}

bool SameName(std::string_view a, std::string_view b) {
    return a.size() == b.size() && std::equal(a.begin(), a.end(), b.begin(), [](char x, char y) {
               const auto lower = [](char c) { return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c; };
               return lower(x) == lower(y);
           });
}

}  // namespace

render::Result<Delivery> OpenPinnedDelivery(const fs::path& exportPath) {
    render::Result<std::optional<CurrentPointer>> current = ReadCurrent(exportPath);
    if (!current) return render::Unexpected(current.error());
    if (!*current) return Fail("nothing is published in " + Utf8String(exportPath));
    render::Result<GenerationState> state = CompleteGeneration(exportPath, (*current)->generation);
    if (!state) return render::Unexpected(state.error());
    if (state->receiptSha256 != (*current)->receiptSha256) {
        return Fail("the receipt of generation " + state->id + " is not the one current.json names");
    }
    return Delivery{state->id, GenerationPath(exportPath, state->id) / "files", std::move(state->receipt->files)};
}

render::Result<Delivery> CopyFixedNames(const fs::path& exportPath, const fs::path& directory,
                                        std::chrono::milliseconds lockTimeout) {
    render::Result<PublicationLock> lock = PublicationLock::Acquire(exportPath, lockTimeout);
    if (!lock) return render::Unexpected(lock.error());
    std::error_code error;
    fs::create_directories(directory, error);
    if (error) return Fail("cannot create " + Utf8String(directory) + ": " + error.message());
    bool rolled = false;
    render::Result<std::optional<Journal>> previous = SettledJournal(exportPath, directory, rolled);
    if (!previous) return render::Unexpected(previous.error());

    render::Result<Delivery> pinned = OpenPinnedDelivery(exportPath);
    if (!pinned) return render::Unexpected(pinned.error());
    std::vector<std::string_view> reserved{kJournalFile};
    if (fs::equivalent(directory, exportPath, error)) {
        reserved.insert(reserved.end(), {kCurrentFile, kGenerationsDir, kLockFile});
    }
    Journal journal;
    journal.generation = pinned->generation;
    for (const ReceiptFile& file : pinned->files) {
        const std::string_view first = std::string_view(file.path).substr(0, file.path.find('/'));
        for (const std::string_view name : reserved) {
            if (SameName(first, name)) {
                return Fail("the fixed name " + file.path + " is the publication's own " + std::string(name) + " in " +
                            Utf8String(directory));
            }
        }
        journal.files.push_back(file.path);
    }
    if (*previous) {
        const std::set<std::string> kept(journal.files.begin(), journal.files.end());
        for (const std::string& file : (*previous)->files) {
            if (!kept.contains(file)) journal.obsolete.push_back(file);
        }
    }
    render::Result<void> started = WriteJournal(directory, journal);
    if (!started) return render::Unexpected(started.error());
    render::Result<void> done = RollForward(exportPath, directory, journal);
    if (!done) return render::Unexpected(done.error());
    return Delivery{pinned->generation, directory, std::move(pinned->files)};
}

render::Result<std::optional<std::string>> RecoverFixedNames(const fs::path& exportPath, const fs::path& directory,
                                                             std::chrono::milliseconds lockTimeout) {
    render::Result<PublicationLock> lock = PublicationLock::Acquire(exportPath, lockTimeout);
    if (!lock) return render::Unexpected(lock.error());
    bool rolled = false;
    render::Result<std::optional<Journal>> journal = SettledJournal(exportPath, directory, rolled);
    if (!journal) return render::Unexpected(journal.error());
    if (!rolled) return std::optional<std::string>{};
    return std::optional<std::string>((*journal)->generation);
}

render::Result<LockedFixedNames> LockedFixedNames::Open(const fs::path& exportPath, const fs::path& directory,
                                                        std::chrono::milliseconds lockTimeout) {
    render::Result<PublicationLock> lock = PublicationLock::Acquire(exportPath, lockTimeout);
    if (!lock) return render::Unexpected(lock.error());
    bool rolled = false;
    render::Result<std::optional<Journal>> journal = SettledJournal(exportPath, directory, rolled);
    if (!journal) return render::Unexpected(journal.error());
    if (!*journal) return Fail("no fixed-name delivery in " + Utf8String(directory));
    render::Result<GenerationState> state = CompleteGeneration(exportPath, (*journal)->generation);
    if (!state) return render::Unexpected(state.error());
    for (const ReceiptFile& file : state->receipt->files) {
        std::string problem;
        if (!Verifies(directory / Utf8Path(file.path), file.bytes, file.sha256, problem)) {
            return Fail("the fixed-name delivery of generation " + state->id + " does not verify: " + problem);
        }
    }
    return LockedFixedNames(std::move(*lock), Delivery{state->id, directory, std::move(state->receipt->files)});
}

}  // namespace uzp::exporter
