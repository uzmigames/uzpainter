// Native tests of transactions, operation records and name addressing (`src/uzp_core/document/`,
// `transaction/`, `operation/`, `naming/`; task phase1.2_docmodel-transactions). Built by
// `zig build uzp-core-transaction-tests` and driven by tests/uzp_core/test_transactions.py.
//
// Usage:
//   uzp-core-transaction-tests run [case]                run every native case (or one); exit 0
//                                                       when all pass
//   uzp-core-transaction-tests request-hash <tool> <file> print the request hash of the tool and
//                                                       the JSON object in <file>
// Errors print "<ErrorClass>: <message>" on stderr and exit 3.

#include <atomic>
#include <cstdio>
#include <fstream>
#include <functional>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/naming/naming.h"
#include "uzp_core/operation/operation.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

namespace {

using namespace uzp::core;

struct Failure {
    std::string message;
};

#define CHECK(cond)                                                                           \
    do {                                                                                      \
        if (!(cond)) throw Failure{std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #cond}; \
    } while (false)

template <typename E, typename F>
std::string ExpectThrow(F&& body, const char* what) {
    try {
        body();
    } catch (const E& error) {
        return error.what();
    }
    throw Failure{std::string("expected an exception: ") + what};
}

#define EXPECT_THROW(E, expr) ExpectThrow<E>([&] { expr; }, #expr)

constexpr const char* kUuid = "6f1c2a3e-0000-4000-8000-000000000001";
// Ids of the base project: texture set, its UV tile, its stack; the next id is 4.
constexpr Id kSet = 1, kTile = 2, kStack = 3;

Project BaseProject() {
    Project p;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-layerq-linear";
    TextureSet set;
    set.id = p.AllocateId();
    set.name = "M_body";
    set.original_name = "M_body";
    set.material_id = "material-0";
    set.uv_tiles = {UVTile{p.AllocateId(), 1001, {}}};
    Stack stack;
    stack.id = p.AllocateId();
    stack.channels[ChannelType::BaseColor] = Channel{ChannelFormat::sRGB8, "", {}};
    stack.channels[ChannelType::Roughness] = Channel{ChannelFormat::L8, "", {}};
    set.stacks = {stack};
    p.texture_sets = {set};
    if (set.uv_tiles[0].id != kTile || stack.id != kStack || set.id != kSet) throw std::logic_error("base project ids");
    return p;
}

DocumentState State(Project project = BaseProject(), std::int64_t revision = 0) {
    DocumentState state;
    state.project_uuid = kUuid;
    state.project = std::move(project);
    state.revision = revision;
    return state;
}

MutationRequest Req(std::string key, std::optional<std::int64_t> expected, std::string tool = "layer_insert",
                    json::Object arguments = {}) {
    if (arguments.empty()) arguments = json::Object{{"name", key}};
    return MutationRequest{std::move(tool), std::move(arguments), std::move(key), expected};
}

const InsertPosition kTop = InsertPosition::FromStack(kSet, kStack);
const NameScope kRoot{kSet, kStack, kNoId, NodeStack::Substack};

/// Commits one fill layer named `key` at the top of the stack; returns its id.
Id CommitLayer(Document& doc, const std::string& key) {
    Id created = kNoId;
    const RequestOutcome outcome = Execute(doc, Req(key, doc.revision()), [&](Edit& e) {
        created = e.Insert(kTop, NodeType::FillLayer, key);
    });
    if (!outcome.result || outcome.result->status != ResultStatus::committed) throw Failure{"commit of " + key + " failed"};
    return created;
}

std::string Manifest(const Document& doc) { return SaveManifest(*doc.snapshot().project); }

Layer MakeLayer(Id uid, LayerKind kind, std::string name) {
    Layer layer;
    layer.uid = uid;
    layer.kind = kind;
    layer.name = std::move(name);
    if (kind == LayerKind::fill) layer.fill = FillContent{};
    return layer;
}

ResourceMeta Meta(Id id, std::string name) {
    ResourceMeta meta;
    meta.id = id;
    meta.name = std::move(name);
    meta.mime = "image/png";
    meta.size = 10;
    meta.usage = "TEXTURE";
    meta.origin = "import";
    meta.imported_at = "2026-10-10T00:00:00Z";
    meta.color_space = "sRGB";
    return meta;
}

std::vector<Id> Ids(std::initializer_list<Id> ids) { return std::vector<Id>(ids); }

// ── 3.1 Snapshot immutability ──────────────────────────────────────────────────────────────

void SnapshotImmutability() {
    Document doc(State());
    const Id a = CommitLayer(doc, "a");
    const Snapshot at_one = doc.snapshot();
    CHECK(at_one.revision == 1);
    CHECK(doc.snapshot().project == at_one.project);  // a snapshot is a pointer copy
    const std::string before = SaveManifest(*at_one.project);

    CommitLayer(doc, "b");
    Execute(doc, Req("rename", doc.revision()), [&](Edit& e) { FindLayer(e.project(), a)->name = "renamed"; });
    Execute(doc, Req("remove", doc.revision()), [&](Edit& e) {
        auto& roots = e.project().texture_sets[0].stacks[0].root_layers;
        std::erase_if(roots, [&](const Layer& l) { return l.uid == a; });
    });
    CHECK(doc.revision() == 4);
    CHECK(at_one.revision == 1);
    CHECK(SaveManifest(*at_one.project) == before);
    CHECK(FindLayer(*at_one.project, a)->name == "a");
    CHECK(FindLayer(*doc.snapshot().project, a) == nullptr);
}

// ── 3.2 Failed mutation ────────────────────────────────────────────────────────────────────

void FailedMutation() {
    Document doc(State());
    Id first = kNoId;
    for (int i = 0; i < 7; ++i) {
        const Id id = CommitLayer(doc, "layer" + std::to_string(i));
        if (i == 0) first = id;
    }
    CHECK(doc.revision() == 7);
    const std::string before = Manifest(doc);

    // A mutation that fails validation (opacity outside 0..1).
    RequestOutcome invalid = Execute(doc, Req("bad", 7), [&](Edit& e) {
        FindLayer(e.project(), first)->blending[ChannelType::BaseColor] = Blending{BlendingMode::Normal, 2.0, {}};
    });
    CHECK(invalid.decision.admission == Admission::execute);
    CHECK(invalid.result->status == ResultStatus::failed);
    CHECK(invalid.result->error_type == "ValueError");
    CHECK(invalid.result->revision == 7);
    CHECK(invalid.result->changes.modified == Ids({first}));
    CHECK(!invalid.committed);
    CHECK(doc.revision() == 7);
    CHECK(Manifest(doc) == before);
    CHECK(!doc.FindOperation("bad"));
    CHECK(doc.operations().size() == 7);

    // A call that throws (an insertion rule).
    RequestOutcome thrown = Execute(doc, Req("bad2", 7), [&](Edit& e) {
        e.Insert(kTop, NodeType::FillLayer, "kept?");
        e.Insert(InsertPosition::Inside(first, NodeStack::Content), NodeType::FillLayer, "x");
    });
    CHECK(thrown.result->status == ResultStatus::failed);
    CHECK(thrown.result->changes.created.size() == 1);  // what would have changed
    CHECK(doc.revision() == 7);
    CHECK(Manifest(doc) == before);
    CHECK(!doc.FindOperation("bad2"));

    // The failed request's retry is an unknown key: with its unexpired precondition it executes.
    RequestOutcome retry = Execute(doc, Req("bad", 7), [&](Edit& e) {
        FindLayer(e.project(), first)->blending[ChannelType::BaseColor] = Blending{BlendingMode::Normal, 0.5, {}};
    });
    CHECK(retry.result->status == ResultStatus::committed);
    CHECK(doc.revision() == 8);
    CHECK(doc.FindOperation("bad")->committed_revision == 8);
}

// ── 3.3 Composite failure ──────────────────────────────────────────────────────────────────

void CompositeFailure() {
    Document doc(State());
    const Id host = CommitLayer(doc, "host");
    const std::string before = Manifest(doc);

    // A detached group whose child holds a compare mask in its content stack: invalid.
    std::vector<Id> subtree_ids;
    RequestOutcome invalid = Execute(doc, Req("smart", doc.revision(), "insert_smart_material"), [&](Edit& e) {
        Layer group = MakeLayer(e.AllocateId(), LayerKind::group, "Smart");
        Layer child = MakeLayer(e.AllocateId(), LayerKind::fill, "Leather");
        Effect compare;
        compare.uid = e.AllocateId();
        compare.kind = EffectKind::compare_mask;
        compare.name = "cmp";
        compare.compare_mask = json::Object{};
        child.content_effects = {compare};
        group.children = {child};
        subtree_ids = {group.uid, child.uid, compare.uid};
        const Id group_uid = group.uid;
        try {
            e.Attach(kTop, std::move(group));
        } catch (const ValueError&) {
            CHECK(FindLayer(e.project(), group_uid) == nullptr);  // nothing attached
            throw;
        }
    });
    CHECK(invalid.result->status == ResultStatus::failed);
    CHECK(invalid.result->changes.created == subtree_ids);
    CHECK(doc.revision() == 1);
    CHECK(Manifest(doc) == before);
    CHECK(FindAllByName(*doc.snapshot().project, "Smart").empty());

    // A valid subtree at a position its root type may not take (a group in a content stack),
    // after an insert the same call made: the result lists both, nothing is committed.
    RequestOutcome misplaced = Execute(doc, Req("smart2", doc.revision(), "insert_smart_material"), [&](Edit& e) {
        const Id pre = e.Insert(kTop, NodeType::PaintLayer, "pre");
        Layer group = MakeLayer(e.AllocateId(), LayerKind::group, "Smart");
        group.children = {MakeLayer(e.AllocateId(), LayerKind::fill, "Leather")};
        subtree_ids = {pre, group.uid, group.children[0].uid};
        e.Attach(InsertPosition::Inside(host, NodeStack::Content), std::move(group));
    });
    CHECK(misplaced.result->status == ResultStatus::failed);
    CHECK(misplaced.result->changes.created == subtree_ids);
    CHECK(misplaced.result->ToJson().at("would_change").IsObject());
    CHECK(doc.revision() == 1);
    CHECK(Manifest(doc) == before);

    // The same subtree attached where it may go: one revision, every id created.
    RequestOutcome attached = Execute(doc, Req("smart3", doc.revision(), "insert_smart_material"), [&](Edit& e) {
        Layer group = MakeLayer(e.AllocateId(), LayerKind::group, "Smart");
        group.children = {MakeLayer(e.AllocateId(), LayerKind::fill, "Leather")};
        Effect levels;
        levels.uid = e.AllocateId();
        levels.kind = EffectKind::levels;
        levels.name = "Levels";
        levels.levels = LevelsParams{ChannelType::Roughness, {LevelsComponent{}}, {}};
        group.children[0].content_effects = {levels};
        subtree_ids = {group.uid, group.children[0].uid, levels.uid};
        e.Attach(InsertPosition::Above(host), std::move(group));
    });
    CHECK(attached.result->status == ResultStatus::committed);
    CHECK(attached.result->changes.created == subtree_ids);
    CHECK(doc.revision() == 2);
    const Project& now = *doc.snapshot().project;
    CHECK(now.texture_sets[0].stacks[0].root_layers.front().uid == subtree_ids[0]);
    CHECK(now.next_id == subtree_ids.back() + 1);
    CHECK(LoadManifest(SaveManifest(now)) == now);
}

// ── 3.4 Native Transaction ─────────────────────────────────────────────────────────────────

void TransactionAtomicity() {
    Document doc(State());
    CommitLayer(doc, "base");
    const std::string before = Manifest(doc);
    const auto insert = [](std::string name) {
        return [name](Edit& e) { e.Insert(kTop, NodeType::FillLayer, name); };
    };
    const auto bad = [](Edit& e) { e.Insert(InsertPosition::Above(999), NodeType::FillLayer, "three"); };

    // Raising mid-way, then rolled back (Python `with uzpainter.Transaction()` leaving by an
    // exception): none of its calls is applied.
    {
        Transaction t(doc, Req("txn", 1, "transaction"));
        CHECK(t.open());
        t.Apply(insert("one"));
        t.Apply(insert("two"));
        CHECK(doc.snapshot().revision == 1);  // readers see the committed revision meanwhile
        EXPECT_THROW(ValueError, t.Apply(bad));
        EXPECT_THROW(std::logic_error, t.Apply(insert("four")));
        t.Rollback();
        CHECK(!t.open());
    }
    CHECK(doc.revision() == 1);
    CHECK(Manifest(doc) == before);
    CHECK(!doc.FindOperation("txn"));

    // Committed after a raising call: a failed result listing what would have changed.
    {
        Transaction t(doc, Req("txn2", 1, "transaction"));
        t.Apply(insert("one"));
        EXPECT_THROW(ValueError, t.Apply(bad));
        const RequestOutcome outcome = t.Commit();
        CHECK(outcome.result->status == ResultStatus::failed);
        CHECK(outcome.result->changes.created.size() == 1);
        CHECK(!outcome.committed);
    }
    CHECK(Manifest(doc) == before);
    CHECK(!doc.FindOperation("txn2"));

    // Destroyed while open: discarded.
    {
        Transaction t(doc, Req("txn3", 1, "transaction"));
        t.Apply(insert("one"));
    }
    CHECK(Manifest(doc) == before);

    // Every call applied: one revision, one record.
    {
        Transaction t(doc, Req("txn4", 1, "transaction"));
        t.Apply(insert("one"));
        t.Apply(insert("two"));
        EXPECT_THROW(std::logic_error, (Transaction(doc, Req("nested", 1))));
        const RequestOutcome outcome = t.Commit();
        CHECK(outcome.result->status == ResultStatus::committed);
        CHECK(outcome.result->changes.created.size() == 2);
        EXPECT_THROW(std::logic_error, t.Commit());
    }
    CHECK(doc.revision() == 2);
    CHECK(doc.operations().size() == 2);
    CHECK(FindAllByName(*doc.snapshot().project, "one").size() == 1);

    // A transaction of another thread waits for the document lock, then finds its precondition
    // stale.
    std::optional<RequestOutcome> other;
    std::atomic<bool> started{false};
    {
        Transaction t(doc, Req("txn5", 2, "transaction"));
        t.Apply(insert("five"));
        std::thread thread([&] {
            started = true;
            other = Execute(doc, Req("other", 2), insert("other"));
        });
        while (!started) std::this_thread::yield();
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        CHECK(!other);
        CHECK(t.Commit().result->status == ResultStatus::committed);
        thread.join();
    }
    CHECK(other && other->decision.admission == Admission::stale_revision);
    CHECK(other->decision.expected_revision == 2);
    CHECK(other->decision.current_revision == 3);
    CHECK(doc.revision() == 3);
}

// ── 2.3 Result change sets; no-op; commit sink ─────────────────────────────────────────────

void ChangeSets() {
    const std::string stored = Sha256Hex("stored bytes");
    const std::string fresh = Sha256Hex("fresh bytes");
    Project base = BaseProject();
    base.resources[stored] = {Meta(base.AllocateId(), "stored.png")};
    Document doc(State(base));
    Id group = kNoId, a = kNoId, b = kNoId, c = kNoId, fx = kNoId;
    Execute(doc, Req("setup", 0), [&](Edit& e) {
        c = e.Insert(kTop, NodeType::FillLayer, "C");
        fx = e.Insert(InsertPosition::Inside(c, NodeStack::Content), NodeType::LevelsEffect, "lv");
        group = e.Insert(kTop, NodeType::GroupLayer, "G");
        b = e.Insert(InsertPosition::Inside(group, NodeStack::Substack), NodeType::FillLayer, "B");
        a = e.Insert(InsertPosition::Inside(group, NodeStack::Substack), NodeType::FillLayer, "A");
    });
    CHECK(doc.revision() == 1);

    Id d = kNoId;
    const RequestOutcome outcome = Execute(doc, Req("edit", 1), [&](Edit& e) {
        Project& p = e.project();
        FindLayer(p, a)->name = "A2";                                  // modified
        FindLayer(p, c)->visible = false;                              // hidden
        auto& children = FindLayer(p, group)->children;                // removed
        std::erase_if(children, [&](const Layer& l) { return l.uid == b; });
        d = e.Insert(InsertPosition::Inside(group, NodeStack::Substack), NodeType::PaintLayer, "D");  // created
        auto& roots = p.texture_sets[0].stacks[0].root_layers;         // reordered: the stack
        std::swap(roots[0], roots[1]);
        FindEffect(p, fx)->visible = false;                            // hidden
        p.resources[fresh] = {Meta(e.AllocateId(), "fresh.png")};     // imported
        p.resources[stored].push_back(Meta(e.AllocateId(), "again.png"));
        e.NoteSkippedResource(stored);                                 // skipped
        e.returned()["node"] = json::Value(d);
    });
    const TransactionResult& r = *outcome.result;
    CHECK(r.status == ResultStatus::committed);
    CHECK(r.changes.created == Ids({d}));
    CHECK(r.changes.modified == Ids({kStack, a}));  // ascending
    CHECK(r.changes.removed == Ids({b}));
    CHECK(r.changes.hidden == Ids({c, fx}));
    CHECK(r.changes.imported == std::vector<std::string>{fresh});
    CHECK(r.changes.skipped == std::vector<std::string>{stored});

    // The stored outcome is the result object.
    const json::Object& json = std::get<json::Object>(outcome.committed->outcome.data);
    CHECK(json == r.ToJson());
    CHECK(json.at("status") == json::Value("committed"));
    CHECK(json.at("committed_revision") == json::Value(2));
    CHECK(json.at("returned") == json::Value(json::Object{{"node", json::Value(d)}}));
    CHECK(json.at("removed") == json::Value(json::Array{json::Value(b)}));

    // Moving a node to another list modifies the node.
    const RequestOutcome moved = Execute(doc, Req("move", 2), [&](Edit& e) {
        Project& p = e.project();
        Layer taken = *FindLayer(p, a);
        auto& children = FindLayer(p, group)->children;
        std::erase_if(children, [&](const Layer& l) { return l.uid == a; });
        p.texture_sets[0].stacks[0].root_layers.push_back(std::move(taken));
    });
    CHECK(moved.result->changes.modified == Ids({a}));

    // A call that changes nothing is a no-op: no revision, no record, distinguished from failure.
    const RequestOutcome noop = Execute(doc, Req("noop", 3), [&](Edit& e) { e.NoteSkippedResource(stored); });
    CHECK(noop.result->status == ResultStatus::no_op);
    CHECK(noop.result->revision == 3);
    CHECK(noop.result->changes.skipped == std::vector<std::string>{stored});
    CHECK(noop.result->ToJson().at("status") == json::Value("no_op"));
    CHECK(!noop.committed);
    CHECK(!doc.FindOperation("noop"));
    CHECK(doc.revision() == 3);
}

void CommitSinkAndCheckpoints() {
    Document doc(State());
    CHECK(doc.NeedsSaving());
    doc.MarkCheckpoint();
    CHECK((doc.checkpoints() == Checkpoints{0, 0, std::nullopt}));
    CHECK(!doc.NeedsSaving());

    std::vector<std::pair<std::int64_t, OperationRecord>> persisted;
    doc.SetCommitSink([&](const Snapshot& snapshot, const OperationRecord& record) {
        CHECK(doc.revision() == snapshot.revision - 1);  // not yet visible
        persisted.emplace_back(snapshot.revision, record);
    });
    const RequestOutcome first = Execute(doc, Req("a", 0), [](Edit& e) { e.Insert(kTop, NodeType::FillLayer, "a"); });
    CHECK(persisted.size() == 1);
    CHECK(persisted[0].first == 1);
    CHECK(persisted[0].second == *first.committed);
    CHECK(persisted[0].second.project_uuid == kUuid);
    CHECK(persisted[0].second.request_hash == Req("a", 0).request_hash());
    CHECK(doc.FindOperation("a") == first.committed);
    CHECK((doc.checkpoints() == Checkpoints{1, 0, std::nullopt}));
    CHECK(doc.NeedsSaving());
    doc.MarkCheckpoint();
    CHECK((doc.checkpoints() == Checkpoints{1, 1, 0}));
    doc.MarkCheckpoint();
    CHECK((doc.checkpoints() == Checkpoints{1, 1, 0}));

    // The store refuses the commit: nothing changes.
    const std::string before = Manifest(doc);
    doc.SetCommitSink([](const Snapshot&, const OperationRecord&) { throw std::runtime_error("disk full"); });
    const RequestOutcome refused = Execute(doc, Req("b", 1), [](Edit& e) { e.Insert(kTop, NodeType::FillLayer, "b"); });
    CHECK(refused.result->status == ResultStatus::failed);
    CHECK(refused.result->error_type == "RuntimeError");
    CHECK(refused.result->error.find("disk full") != std::string::npos);
    CHECK(doc.revision() == 1);
    CHECK(Manifest(doc) == before);
    CHECK(!doc.FindOperation("b"));

    // Opening state is checked.
    DocumentState wrong = State(BaseProject(), 3);
    wrong.named_checkpoint = 2;
    wrong.previous_checkpoint = 2;
    EXPECT_THROW(ValueError, Document{std::move(wrong)});
    DocumentState foreign = State(BaseProject(), 3);
    foreign.operations = {OperationRecord{"another", "k", "h", json::Object{}, 2}};
    EXPECT_THROW(ValueError, Document{std::move(foreign)});
    DocumentState outside = State(BaseProject(), 3);
    outside.operations = {OperationRecord{kUuid, "k", "h", json::Object{}, 4}};
    EXPECT_THROW(ValueError, Document{std::move(outside)});
    EXPECT_THROW(ValueError, Execute(doc, Req("", 1), [](Edit&) {}));
}

// ── 3.5 Idempotency decision table ─────────────────────────────────────────────────────────

void DecisionTable() {
    const OperationRecord known{kUuid, "K", "hash-1", json::Object{}, 5};
    const auto decide = [&](std::optional<OperationRecord> record, std::string hash, std::optional<std::int64_t> expected,
                            std::int64_t current, std::int64_t horizon, bool readable = true) {
        AdmissionInput input;
        input.request_hash = std::move(hash);
        input.expected_revision = expected;
        input.known = std::move(record);
        input.records_readable = readable;
        input.current_revision = current;
        input.horizon_revision = horizon;
        return DecideAdmission(input);
    };
    // Known key, same hash, newer current revision: the stored outcome (before any revision check).
    AdmissionDecision d = decide(known, "hash-1", 4, 9, 0);
    CHECK(d.admission == Admission::stored_outcome);
    CHECK(d.record == known);
    CHECK(decide(known, "hash-1", std::nullopt, 9, 8).admission == Admission::stored_outcome);
    // Known key, different hash.
    d = decide(known, "hash-2", 9, 9, 0);
    CHECK(d.admission == Admission::idempotency_conflict);
    CHECK(d.record->committed_revision == 5);
    // Unknown key, missing precondition.
    d = decide(std::nullopt, "h", std::nullopt, 9, 0);
    CHECK(d.admission == Admission::outcome_unknown);
    CHECK(d.current_revision == 9);
    // Unknown key, expired precondition (below the horizon); at the horizon it is not expired.
    CHECK(decide(std::nullopt, "h", 5, 9, 6).admission == Admission::outcome_unknown);
    CHECK(decide(std::nullopt, "h", 6, 6, 6).admission == Admission::execute);
    // Unknown key, unexpired precondition other than the current revision.
    d = decide(std::nullopt, "h", 7, 9, 6);
    CHECK(d.admission == Admission::stale_revision);
    CHECK(d.expected_revision == 7);
    CHECK(d.current_revision == 9);
    CHECK(decide(std::nullopt, "h", 10, 9, 0).admission == Admission::stale_revision);
    // Unknown key, precondition equal to the current revision.
    CHECK(decide(std::nullopt, "h", 9, 9, 0).admission == Admission::execute);
    // Records that cannot be read: never executed.
    CHECK(decide(known, "hash-1", 9, 9, 0, false).admission == Admission::outcome_unknown);
    CHECK(decide(std::nullopt, "h", 9, 9, 0, false).admission == Admission::outcome_unknown);
    CHECK(ToString(Admission::idempotency_conflict) == "idempotency_conflict");
}

void DocumentIdempotency() {
    Document doc(State());
    for (int i = 0; i < 4; ++i) CommitLayer(doc, "pre" + std::to_string(i));
    const MutationRequest k = Req("K", 4, "layer_insert", json::Object{{"name", "K"}, {"type", "FillLayer"}});
    int runs = 0;
    const auto body = [&](Edit& e) {
        ++runs;
        e.Insert(kTop, NodeType::FillLayer, "K");
    };
    const RequestOutcome committed = Execute(doc, k, body);
    CHECK(committed.result->status == ResultStatus::committed);
    CHECK(doc.revision() == 5);
    for (int i = 0; i < 4; ++i) CommitLayer(doc, "post" + std::to_string(i));
    CHECK(doc.revision() == 9);

    // Known key after the revision advanced: the stored outcome, no new revision.
    const RequestOutcome retry = Execute(doc, k, body);
    CHECK(retry.decision.admission == Admission::stored_outcome);
    CHECK(retry.decision.record == committed.committed);
    CHECK(retry.decision.record->committed_revision == 5);
    CHECK(retry.decision.current_revision == 9);
    CHECK(!retry.result);
    CHECK(runs == 1);
    CHECK(doc.revision() == 9);

    // The same arguments written in another order are the same request.
    MutationRequest reordered = k;
    reordered.arguments = std::get<json::Object>(json::Parse(R"({"type":"FillLayer","name":"K"})").data);
    CHECK(Execute(doc, reordered, body).decision.admission == Admission::stored_outcome);

    // Reused key with different arguments.
    MutationRequest changed = k;
    changed.arguments["name"] = "K2";
    const RequestOutcome conflict = Execute(doc, changed, body);
    CHECK(conflict.decision.admission == Admission::idempotency_conflict);
    CHECK(conflict.decision.record->committed_revision == 5);
    CHECK(runs == 1);

    // Unknown key without a precondition.
    const RequestOutcome unknown = Execute(doc, Req("new", std::nullopt), body);
    CHECK(unknown.decision.admission == Admission::outcome_unknown);
    CHECK(unknown.decision.current_revision == 9);

    // Unknown key with a stale precondition.
    const RequestOutcome stale = Execute(doc, Req("new", 7), body);
    CHECK(stale.decision.admission == Admission::stale_revision);
    CHECK(runs == 1);

    // Compaction collapsed revisions up to 6: K's record is gone, and its retry with its original
    // precondition (4, below the horizon) is never executed again.
    doc.SetOperationHorizon(6);
    CHECK(!doc.FindOperation("K"));
    CHECK(doc.operations().size() == 3);
    const RequestOutcome expired = Execute(doc, k, body);
    CHECK(expired.decision.admission == Admission::outcome_unknown);
    CHECK(runs == 1);
    CHECK(doc.revision() == 9);
    EXPECT_THROW(ValueError, doc.SetOperationHorizon(5));

    // Unknown key at the current revision: executed.
    const RequestOutcome fresh = Execute(doc, Req("new", 9), body);
    CHECK(fresh.result->status == ResultStatus::committed);
    CHECK(runs == 2);
    CHECK(doc.revision() == 10);
}

// ── 3.6 request_hash ───────────────────────────────────────────────────────────────────────

void RequestHashKeyOrder() {
    const auto object = [](std::string_view text) { return std::get<json::Object>(json::Parse(text).data); };
    const json::Object a = object(R"({"name":"x","position":{"stack":3,"set":1},"type":"FillLayer","opacity":0.5})");
    const json::Object b = object(R"({"opacity":0.5,"type":"FillLayer","position":{"set":1,"stack":3},"name":"x"})");
    CHECK(RequestHash("layer_insert", a) == RequestHash("layer_insert", b));
    CHECK(RequestHash("layer_insert", a) ==
          Sha256Hex(R"({"arguments":{"name":"x","opacity":0.5,"position":{"set":1,"stack":3},"type":"FillLayer"},"tool":"layer_insert"})"));
    CHECK(RequestHash("layer_insert", a) != RequestHash("layer_delete", a));
    CHECK(RequestHash("layer_insert", a) != RequestHash("layer_insert", object(R"({"name":"y"})")));
    CHECK(IsSha256Hex(RequestHash("t", {})));
}

// ── 3.7 LAY-06 name addressing ─────────────────────────────────────────────────────────────

void NameAddressing() {
    Document doc(State());
    Id rust = kNoId;
    Execute(doc, Req("rust", 0), [&](Edit& e) { rust = InsertNamed(e, kRoot, NodeType::GroupLayer, "Rust").node; });
    const NameScope in_rust{kSet, kStack, rust, NodeStack::Substack};
    const auto named_fill = [&](Edit& e) {
        const NamedNode node = InsertNamed(e, in_rust, NodeType::FillLayer, "Base");
        e.returned()["node"] = json::Value(node.node);
        e.returned()["created"] = node.created;
    };
    const RequestOutcome first = Execute(doc, Req("base-1", 1, "layer_insert_named"), named_fill);
    CHECK(first.result->status == ResultStatus::committed);
    CHECK(first.result->returned.at("created") == json::Value(true));
    const json::Value base = first.result->returned.at("node");

    // Repeating the named insert (a new key, as after an unknown outcome): no second node.
    const RequestOutcome again = Execute(doc, Req("base-2", 2, "layer_insert_named"), named_fill);
    CHECK(again.result->status == ResultStatus::no_op);
    CHECK(again.result->returned.at("node") == base);
    CHECK(again.result->returned.at("created") == json::Value(false));
    CHECK(doc.revision() == 2);
    CHECK(FindAllByName(*doc.snapshot().project, "Base").size() == 1);

    // Another scope is another name space.
    Execute(doc, Req("base-root", 2), [&](Edit& e) { CHECK(InsertNamed(e, kRoot, NodeType::FillLayer, "Base").created); });
    CHECK(FindAllByName(*doc.snapshot().project, "Base").size() == 2);

    // Ambiguity fails before mutation and lists the candidates.
    Id dup_low = kNoId, dup_high = kNoId;
    Execute(doc, Req("dups", 3), [&](Edit& e) {
        dup_low = e.Insert(kTop, NodeType::FillLayer, "Dup");
        dup_high = e.Insert(kTop, NodeType::FillLayer, "Dup");
    });
    const std::string before = Manifest(doc);
    const RequestOutcome ambiguous = Execute(doc, Req("dup", 4), [&](Edit& e) {
        e.Insert(kTop, NodeType::PaintLayer, "unrelated");
        InsertNamed(e, kRoot, NodeType::FillLayer, "Dup");
    });
    CHECK(ambiguous.result->status == ResultStatus::failed);
    CHECK(ambiguous.result->error_type == "ValueError");
    CHECK(ambiguous.result->error.find(std::to_string(dup_low)) != std::string::npos);
    CHECK(ambiguous.result->error.find(std::to_string(dup_high)) != std::string::npos);
    CHECK(Manifest(doc) == before);
    const Project& p = *doc.snapshot().project;
    try {
        ResolveName(p, kRoot, "Dup");
        CHECK(false);
    } catch (const AmbiguousNameError& error) {
        CHECK(error.candidates() == Ids({dup_high, dup_low}));  // top first
    }
    CHECK(FindByName(p, kRoot, "Dup") == Ids({dup_high, dup_low}));
    CHECK(FindAllByName(p, "Dup") == Ids({dup_high, dup_low}));
    CHECK(!ResolveName(p, kRoot, "missing"));

    // Same name, another type; scopes that do not exist.
    const RequestOutcome mistyped = Execute(doc, Req("x", 4), [&](Edit& e) {
        InsertNamed(e, kRoot, NodeType::FillLayer, "Rust");
    });
    CHECK(mistyped.result->status == ResultStatus::failed);
    CHECK(mistyped.result->error.find("already names GroupLayer") != std::string::npos);
    CHECK(Manifest(doc) == before);
    EXPECT_THROW(ValueError, FindByName(p, NameScope{kSet, 999, kNoId, NodeStack::Substack}, "Base"));
    EXPECT_THROW(ValueError, FindByName(p, NameScope{kSet, kStack, 999, NodeStack::Substack}, "Base"));
    EXPECT_THROW(ValueError, FindByName(p, NameScope{kSet, kStack, dup_low, NodeStack::Substack}, "Base"));
    EXPECT_THROW(ValueError, FindByName(p, NameScope{kSet, kStack, dup_low, NodeStack::Mask}, "Base"));
    CHECK(FindByName(p, NameScope{kSet, kStack, dup_low, NodeStack::Content}, "Base").empty());

    // Save/reopen through the manifest: the same ids resolve, the repeat is still a no-op and new
    // ids continue from next_id.
    const Snapshot saved = doc.snapshot();
    Document reopened(State(LoadManifest(SaveManifest(*saved.project)), saved.revision));
    const Project& r = *reopened.snapshot().project;
    CHECK(json::Value(*ResolveName(r, in_rust, "Base")) == base);
    CHECK(*ResolveName(r, kRoot, "Rust") == rust);
    CHECK(FindByName(r, kRoot, "Dup") == Ids({dup_high, dup_low}));
    const RequestOutcome repeat = Execute(reopened, Req("base-3", saved.revision, "layer_insert_named"), named_fill);
    CHECK(repeat.result->status == ResultStatus::no_op);
    CHECK(repeat.result->returned.at("node") == base);
    Id added = kNoId;
    Execute(reopened, Req("new", saved.revision), [&](Edit& e) { added = InsertNamed(e, kRoot, NodeType::FillLayer, "New").node; });
    CHECK(added == saved.project->next_id);
}

// ── Driver ─────────────────────────────────────────────────────────────────────────────────

int Run(const std::string& only) {
    const std::vector<std::pair<const char*, std::function<void()>>> cases = {
        {"snapshot_immutability", SnapshotImmutability},
        {"failed_mutation", FailedMutation},
        {"composite_failure", CompositeFailure},
        {"transaction_atomicity", TransactionAtomicity},
        {"change_sets", ChangeSets},
        {"commit_sink_and_checkpoints", CommitSinkAndCheckpoints},
        {"decision_table", DecisionTable},
        {"document_idempotency", DocumentIdempotency},
        {"request_hash_key_order", RequestHashKeyOrder},
        {"name_addressing", NameAddressing},
    };
    int failed = 0;
    int ran = 0;
    for (const auto& [name, body] : cases) {
        if (!only.empty() && only != name) continue;
        ++ran;
        try {
            body();
            std::printf("PASS %s\n", name);
        } catch (const Failure& failure) {
            ++failed;
            std::printf("FAIL %s: %s\n", name, failure.message.c_str());
        } catch (const std::exception& error) {
            ++failed;
            std::printf("FAIL %s: unexpected exception: %s\n", name, error.what());
        }
    }
    std::printf("%d cases, %d failed\n", ran, failed);
    return failed == 0 && ran > 0 ? 0 : 1;
}

std::string ReadFile(const char* path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error(std::string("cannot read ") + path);
    std::ostringstream text;
    text << file.rdbuf();
    return text.str();
}

int Command(int argc, char** argv) {
    const std::string command = argc > 1 ? argv[1] : "";
    if (command == "run") return Run(argc > 2 ? argv[2] : "");
    if (command == "request-hash" && argc == 4) {
        const json::Value arguments = json::Parse(ReadFile(argv[3]));
        if (!arguments.IsObject()) throw std::runtime_error("the arguments must be a JSON object");
        std::printf("%s", RequestHash(argv[2], std::get<json::Object>(arguments.data)).c_str());
        return 0;
    }
    std::fprintf(stderr, "usage: uzp-core-transaction-tests run [case] | request-hash <tool> <file>\n");
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        return Command(argc, argv);
    } catch (const ValueError& error) {
        std::fprintf(stderr, "ValueError: %s\n", error.what());
    } catch (const json::ParseError& error) {
        std::fprintf(stderr, "ParseError: %s\n", error.what());
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Error: %s\n", error.what());
    }
    return 3;
}
