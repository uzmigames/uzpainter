#pragma once

// Shared pieces of the `uzpainter` bindings (uzpainter_module.cpp and bind_*.cpp): handles,
// node resolution, the call wrapper and the per-module `Bind*` functions.
//
// Handles are thin: a node handle holds only its persistent 64-bit id and is resolved again on
// every call against the project the thread reads (`Session::ReadProject`), so a handle to a
// deleted node raises `ValueError` and a fresh `layerstack.get_node_by_uid` sees the same node.
// Handle classes have no instance dictionary (`__slots__ == ()`): assigning an unknown attribute
// raises `AttributeError`.

#include <cstddef>
#include <functional>
#include <optional>
#include <string>

#include <pybind11/eval.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "python/session.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/layers.h"
#include "uzp_core/types/project.h"

namespace uzp::python {

namespace py = pybind11;

// ── Node handles (`uzpainter.layerstack`) ─────────────────────────────────────────────────────

struct Node {
    core::Id uid = core::kNoId;
};
struct LayerNode : Node {};
struct EffectNode : Node {};
struct FillLayerNode : LayerNode {};
struct PaintLayerNode : LayerNode {};
struct GroupLayerNode : LayerNode {};
struct InstanceLayerNode : LayerNode {};
struct FillEffectNode : EffectNode {};
struct PaintEffectNode : EffectNode {};
struct GeneratorEffectNode : EffectNode {};
struct FilterEffectNode : EffectNode {};
struct LevelsEffectNode : EffectNode {};
struct CompareMaskEffectNode : EffectNode {};
struct ColorSelectionEffectNode : EffectNode {};
struct AnchorPointEffectNode : EffectNode {};

/// Where a node is: exactly one of `layer` and `effect` is set (pointers into the project read).
struct NodeInfo {
    const core::Layer* layer = nullptr;
    const core::Effect* effect = nullptr;
    core::Id texture_set = core::kNoId;
    core::Id stack = core::kNoId;
    /// The list holding the node: a stack's root layers (`owner` = the stack id, `Substack`), a
    /// group's sub-layers, a layer's content effects or its mask effects.
    core::Id owner = core::kNoId;
    core::NodeStack owner_stack = core::NodeStack::Substack;
    bool root = false;
    std::size_t index = 0;

    core::NodeType type() const { return layer ? layer->type() : effect->type(); }
    bool in_mask() const { return effect != nullptr && owner_stack == core::NodeStack::Mask; }
};

/// The node `uid` of `project`; `ValueError` when it no longer exists (a stale handle).
NodeInfo Resolve(const core::Project& project, core::Id uid);
/// The handle object of node `uid` (its class follows the node type).
py::object MakeNode(const core::Project& project, core::Id uid);
/// The layer or effect `uid` of a working copy; `ValueError` when it no longer exists.
core::Layer& EditLayer(core::Edit& edit, core::Id uid);
core::Effect& EditEffect(core::Edit& edit, core::Id uid);

// ── Texture sets and stacks (`uzpainter.textureset`) ──────────────────────────────────────────

struct TextureSetHandle {
    core::Id id = core::kNoId;
};
struct StackHandle {
    core::Id texture_set = core::kNoId;
    core::Id stack = core::kNoId;
};

/// The texture set and stack of a handle; `ValueError` when they no longer exist.
const core::TextureSet& ResolveSet(const core::Project& project, core::Id id);
const core::Stack& ResolveStack(const core::Project& project, const StackHandle& stack);
/// The stack argument of a call: the given handle, else the active stack (the default address).
StackHandle StackOrActive(const std::optional<StackHandle>& stack);

// ── Resources (`uzpainter.resource`) ──────────────────────────────────────────────────────────

/// `resource://project/<name>?version=<sha256>` (03-project-model.md §3).
struct ResourceIdHandle {
    std::string context = "project";
    std::string name;
    std::string version;
};
/// The SHA-256 a project resource id names; `ResourceNotFoundError` when the project holds no
/// such entry (or, without a version, several hashes under the name).
std::string ResolveResource(const core::Project& project, const ResourceIdHandle& id);
/// The id of the first entry of `sha256`.
ResourceIdHandle ResourceIdOf(const core::Project& project, const std::string& sha256);

// ── Colour (`uzpainter.colormanagement`) ──────────────────────────────────────────────────────

struct Color {
    std::array<double, 3> value_raw{0.0, 0.0, 0.0};
    std::optional<std::string> color_space;
};

// ── Stored values ───────────────────────────────────────────────────────────────────────────────

/// Painter stores the floats a setter takes as float32 (the Tier 0 readbacks of opacity 0.85 and
/// of a Raw 0.35 are 0.8500000238418579 and 0.3499999940395355); the native API stores them the
/// same way, so a readback equals Painter's. The evaluator casts every value to float32 anyway, so
/// the rounding changes no texture.
inline double F32(double value) { return static_cast<double>(static_cast<float>(value)); }
inline std::array<double, 3> F32(const std::array<double, 3>& v) { return {F32(v[0]), F32(v[1]), F32(v[2])}; }
inline std::array<double, 2> F32(const std::array<double, 2>& v) { return {F32(v[0]), F32(v[1])}; }

// ── Calls ─────────────────────────────────────────────────────────────────────────────────────

/// `Session::Mutate` with the GIL released (the call must not touch Python).
CallResult Mutate(const std::string& tool, core::json::Object arguments, const std::function<void(core::Edit&)>& call);
/// The `Result` object of a call.
py::object ResultObject(const CallResult& result);
/// The project the calling thread reads.
std::shared_ptr<const core::Project> Read();

/// Binds the enumeration `E` with the member names of its `EnumTable`.
template <typename E>
py::enum_<E> BindEnum(py::handle scope, const char* name) {
    py::enum_<E> binding(scope, name);
    for (std::size_t i = 0; i < core::EnumTable<E>::names.size(); ++i) {
        binding.value(core::EnumTable<E>::names[i].data(), static_cast<E>(i));
    }
    return binding;
}

/// Makes a handle class reject unknown attributes visibly: `__slots__ = ()`.
void SealClass(py::handle cls);

// ── Modules ───────────────────────────────────────────────────────────────────────────────────

void BindCore(py::module_& m);          // Result, last_result, Transaction
void BindColor(py::module_& m);         // colormanagement
void BindTextureSet(py::module_& m);    // textureset
void BindResource(py::module_& m);      // resource
void BindLayerStack(py::module_& m, py::module_& source, py::module_& levels);
void BindProject(py::module_& m);       // project
void BindExport(py::module_& m, py::module_& jobs);  // export, jobs
void BindMisc(py::module_& m);          // logging, application, properties, later-phase modules

}  // namespace uzp::python
