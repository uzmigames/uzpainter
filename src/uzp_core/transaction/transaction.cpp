#include "uzp_core/transaction/transaction.h"

#include <algorithm>
#include <map>
#include <stdexcept>
#include <type_traits>
#include <utility>

#include "uzp_core/document/nodes.h"
#include "uzp_core/types/errors.h"

namespace uzp::core {

namespace {

using ListKey = std::pair<Id, NodeStack>;

/// Where every layer, effect, texture set and stack of a project is.
struct Index {
    std::map<Id, const Layer*> layers;
    std::map<Id, const Effect*> effects;
    std::map<Id, ListKey> placement;
    std::map<ListKey, std::vector<Id>> lists;
    std::map<Id, const TextureSet*> sets;
    std::map<Id, const Stack*> stacks;
};

Index BuildIndex(const Project& project) {
    Index index;
    for (const TextureSet& set : project.texture_sets) {
        index.sets[set.id] = &set;
        for (const Stack& stack : set.stacks) index.stacks[stack.id] = &stack;
    }
    ForEachNode(project, [&](const NodeVisit& visit) {
        const Id uid = visit.layer != nullptr ? visit.layer->uid : visit.effect->uid;
        if (visit.layer != nullptr) {
            index.layers[uid] = visit.layer;
        } else {
            index.effects[uid] = visit.effect;
        }
        const ListKey key{visit.owner, visit.owner_stack};
        index.placement[uid] = key;
        index.lists[key].push_back(uid);
    });
    return index;
}

/// A node's own fields: its sub-lists emptied and its visibility set aside.
Layer Own(const Layer& layer) {
    Layer own = layer;
    own.children.clear();
    own.content_effects.clear();
    if (own.mask) own.mask->effects.clear();
    own.visible = true;
    return own;
}

Effect Own(const Effect& effect) {
    Effect own = effect;
    own.visible = true;
    return own;
}

TextureSet Own(const TextureSet& set) {
    TextureSet own = set;
    own.stacks.clear();
    return own;
}

Stack Own(const Stack& stack) {
    Stack own = stack;
    own.root_layers.clear();
    return own;
}

template <typename T>
bool OwnChanged(const T& before, const T& after) {
    return !(before == after) && !(Own(before) == Own(after));
}

/// Created, removed and own-field changes of one kind of id.
template <typename T>
void DiffMap(const std::map<Id, const T*>& before, const std::map<Id, const T*>& after, ChangeSet& changes) {
    for (const auto& [id, node] : after) {
        const auto old = before.find(id);
        if (old == before.end()) {
            changes.created.push_back(id);
            continue;
        }
        if (OwnChanged(*old->second, *node)) changes.modified.push_back(id);
        if constexpr (std::is_same_v<T, Layer> || std::is_same_v<T, Effect>) {
            if (old->second->visible && !node->visible) changes.hidden.push_back(id);
            if (!old->second->visible && node->visible) changes.modified.push_back(id);
        }
    }
    for (const auto& [id, node] : before) {
        if (!after.contains(id)) changes.removed.push_back(id);
    }
}

std::vector<Id> Kept(const std::vector<Id>& list, const std::map<Id, ListKey>& other, const ListKey& key) {
    std::vector<Id> kept;
    for (const Id id : list) {
        const auto found = other.find(id);
        if (found != other.end() && found->second == key) kept.push_back(id);
    }
    return kept;
}

template <typename T>
void SortUnique(std::vector<T>& values) {
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
}

void CollectIds(const Layer& layer, std::vector<Id>& out) {
    out.push_back(layer.uid);
    for (const Effect& effect : layer.content_effects) out.push_back(effect.uid);
    if (layer.mask) {
        for (const Effect& effect : layer.mask->effects) out.push_back(effect.uid);
    }
    for (const Layer& child : layer.children) CollectIds(child, out);
}

json::Array IdArray(const std::vector<Id>& ids) {
    json::Array out;
    for (const Id id : ids) out.emplace_back(static_cast<std::uint64_t>(id));
    return out;
}

json::Array StringArray(const std::vector<std::string>& values) {
    return json::Array(values.begin(), values.end());
}

}  // namespace

// ── ChangeSet ─────────────────────────────────────────────────────────────────────────────────

bool ChangeSet::empty() const {
    return created.empty() && modified.empty() && removed.empty() && hidden.empty() && imported.empty() &&
           skipped.empty();
}

json::Object ChangeSet::ToJson() const {
    return json::Object{
        {"created", IdArray(created)},   {"hidden", IdArray(hidden)},     {"imported", StringArray(imported)},
        {"modified", IdArray(modified)}, {"removed", IdArray(removed)},   {"skipped", StringArray(skipped)},
    };
}

ChangeSet Diff(const Project& before, const Project& after) {
    const Index old_index = BuildIndex(before);
    const Index new_index = BuildIndex(after);
    ChangeSet changes;
    DiffMap(old_index.layers, new_index.layers, changes);
    DiffMap(old_index.effects, new_index.effects, changes);
    DiffMap(old_index.sets, new_index.sets, changes);
    DiffMap(old_index.stacks, new_index.stacks, changes);
    for (const auto& [id, key] : new_index.placement) {
        const auto old = old_index.placement.find(id);
        if (old != old_index.placement.end() && old->second != key) changes.modified.push_back(id);
    }
    // A list whose surviving members changed order: its owner (a stack or a layer) is modified.
    for (const auto& [key, list] : new_index.lists) {
        const auto old = old_index.lists.find(key);
        if (old == old_index.lists.end()) continue;
        if (Kept(old->second, new_index.placement, key) != Kept(list, old_index.placement, key)) {
            changes.modified.push_back(key.first);
        }
    }
    for (const auto& [hash, entries] : after.resources) {
        if (!before.resources.contains(hash)) changes.imported.push_back(hash);
    }
    SortUnique(changes.created);
    SortUnique(changes.modified);
    SortUnique(changes.removed);
    SortUnique(changes.hidden);
    SortUnique(changes.imported);
    return changes;
}

json::Object TransactionResult::ToJson() const {
    json::Object out{
        {"status", json::Value(ToString(status))},
        {"revision", revision},
        {"returned", returned},
    };
    if (status == ResultStatus::failed) {
        out["error"] = json::Object{{"type", error_type}, {"message", error}};
        out["would_change"] = changes.ToJson();
        return out;
    }
    if (status == ResultStatus::committed) out["committed_revision"] = revision;
    for (auto& [key, value] : changes.ToJson()) out[key] = std::move(value);
    return out;
}

// ── Edit ──────────────────────────────────────────────────────────────────────────────────────

Edit::Edit(std::shared_ptr<const Project> base) : base_(std::move(base)), working_(*base_) {}

Id Edit::Insert(const InsertPosition& position, NodeType type, std::string name, Id instance_source) {
    return InsertNode(working_, position, type, std::move(name), instance_source);
}

template <typename Node>
void Edit::AttachNode(const InsertPosition& position, Node node, const std::vector<Id>& ids) {
    try {
        // Place a default node of the root's type under the documented insertion rules, then
        // swap the detached node in and validate the whole candidate.
        Project candidate = working_;
        const Id next_id = candidate.next_id;
        Id instance_source = kNoId;
        if constexpr (std::is_same_v<Node, Layer>) instance_source = node.instance_source;
        const Id placeholder = InsertNode(candidate, position, node.type(), node.name, instance_source);
        candidate.next_id = next_id;
        if constexpr (std::is_same_v<Node, Layer>) {
            *FindLayer(candidate, placeholder) = std::move(node);
        } else {
            *FindEffect(candidate, placeholder) = std::move(node);
        }
        Validate(candidate);
        working_ = std::move(candidate);
    } catch (const ValueError&) {
        unattached_.insert(unattached_.end(), ids.begin(), ids.end());
        throw;
    }
}

void Edit::Attach(const InsertPosition& position, Layer subtree) {
    std::vector<Id> ids;
    CollectIds(subtree, ids);
    AttachNode(position, std::move(subtree), ids);
}

void Edit::Attach(const InsertPosition& position, Effect effect) {
    const std::vector<Id> ids{effect.uid};
    AttachNode(position, std::move(effect), ids);
}

// ── Transaction ───────────────────────────────────────────────────────────────────────────────

Transaction::Transaction(Document& document, MutationRequest request)
    : document_(document), request_(std::move(request)) {
    if (request_.tool.empty()) throw ValueError("transaction: the request names no tool");
    if (request_.idempotency_key.empty()) throw ValueError("transaction: the request has no idempotency key");
    request_hash_ = request_.request_hash();
    if (document_.lock_owner_.load() == std::this_thread::get_id()) {
        throw std::logic_error("transaction: this thread already holds an open transaction of the document");
    }
    lock_ = std::unique_lock(document_.document_lock_);
    document_.lock_owner_ = std::this_thread::get_id();
    try {
        AdmissionInput input;
        Snapshot base;
        {
            std::lock_guard state(document_.state_mutex_);
            base = document_.current_;
            const auto known = document_.operations_.find(request_.idempotency_key);
            if (known != document_.operations_.end()) input.known = known->second;
            input.horizon_revision = document_.horizon_;
        }
        input.request_hash = request_hash_;
        input.expected_revision = request_.expected_revision;
        input.current_revision = base.revision;
        decision_ = DecideAdmission(input);
        if (decision_.admission != Admission::execute) {
            Release();
            return;
        }
        base_revision_ = base.revision;
        edit_.reset(new Edit(std::move(base.project)));
    } catch (...) {
        Release();
        throw;
    }
}

Transaction::~Transaction() { Rollback(); }

void Transaction::Release() {
    if (!lock_.owns_lock()) return;
    document_.lock_owner_ = std::thread::id{};
    lock_.unlock();
}

TransactionResult Transaction::Failed(std::string type, std::string message, ChangeSet would_change) const {
    TransactionResult result;
    result.status = ResultStatus::failed;
    result.revision = base_revision_;
    result.changes = std::move(would_change);
    result.error_type = std::move(type);
    result.error = std::move(message);
    return result;
}

void Transaction::Apply(const std::function<void(Edit&)>& call) {
    if (!open()) throw std::logic_error("transaction: not open");
    if (failure_) throw std::logic_error("transaction: an earlier call failed; nothing can be applied");
    const auto would_change = [&] {
        ChangeSet changes = Diff(edit_->base(), edit_->working_);
        changes.created.insert(changes.created.end(), edit_->unattached_.begin(), edit_->unattached_.end());
        SortUnique(changes.created);
        changes.skipped.assign(edit_->skipped_.begin(), edit_->skipped_.end());
        return changes;
    };
    try {
        call(*edit_);
    } catch (const ValueError& error) {
        failure_ = Failed("ValueError", error.what(), would_change());
        throw;
    } catch (const std::exception& error) {
        failure_ = Failed("RuntimeError", error.what(), would_change());
        throw;
    } catch (...) {
        failure_ = Failed("RuntimeError", "unknown exception", would_change());
        throw;
    }
}

RequestOutcome Transaction::Commit() {
    RequestOutcome outcome;
    outcome.decision = decision_;
    if (decision_.admission != Admission::execute) return outcome;
    if (!open()) throw std::logic_error("transaction: already committed or rolled back");

    const Project& base = edit_->base();
    Project& working = edit_->working_;
    ChangeSet changes = Diff(base, working);
    changes.skipped.assign(edit_->skipped_.begin(), edit_->skipped_.end());

    TransactionResult result;
    if (failure_) {
        result = *failure_;
    } else {
        try {
            Validate(working);
        } catch (const ValueError& error) {
            result = Failed("ValueError", error.what(), changes);
            failure_ = result;
        }
    }
    if (!failure_ && working == base) {
        result.status = ResultStatus::no_op;
        result.revision = base_revision_;
        result.changes = changes;
        result.returned = edit_->returned_;
    } else if (!failure_) {
        result.status = ResultStatus::committed;
        result.revision = base_revision_ + 1;
        result.changes = changes;
        result.returned = edit_->returned_;
        OperationRecord record{document_.project_uuid_, request_.idempotency_key, request_hash_, result.ToJson(),
                               result.revision};
        const Snapshot next{result.revision, std::make_shared<const Project>(std::move(working))};
        CommitSink sink;
        {
            std::lock_guard state(document_.state_mutex_);
            sink = document_.sink_;
        }
        try {
            if (sink) sink(next, record);
            std::lock_guard state(document_.state_mutex_);
            document_.current_ = next;
            document_.operations_[record.idempotency_key] = record;
            outcome.committed = std::move(record);
        } catch (const std::exception& error) {
            result = Failed("RuntimeError", std::string("commit failed: ") + error.what(), changes);
        }
    }
    outcome.result = std::move(result);
    edit_.reset();
    Release();
    return outcome;
}

void Transaction::Rollback() {
    edit_.reset();
    Release();
}

RequestOutcome Execute(Document& document, MutationRequest request, const std::function<void(Edit&)>& call) {
    Transaction transaction(document, std::move(request));
    if (transaction.open()) {
        try {
            transaction.Apply(call);
        } catch (...) {
            // Recorded by Apply; the commit reports the failure and changes nothing.
        }
    }
    return transaction.Commit();
}

}  // namespace uzp::core
