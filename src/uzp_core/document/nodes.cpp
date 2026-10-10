#include "uzp_core/document/nodes.h"

#include <vector>

namespace uzp::core {

namespace {

void VisitLayers(const std::vector<Layer>& layers, Id owner, Id texture_set, Id stack,
                 const std::function<void(const NodeVisit&)>& visit) {
    for (std::size_t i = 0; i < layers.size(); ++i) {
        const Layer& layer = layers[i];
        visit(NodeVisit{&layer, nullptr, owner, NodeStack::Substack, i, texture_set, stack});
        for (std::size_t e = 0; e < layer.content_effects.size(); ++e) {
            visit(NodeVisit{nullptr, &layer.content_effects[e], layer.uid, NodeStack::Content, e, texture_set, stack});
        }
        if (layer.mask) {
            for (std::size_t e = 0; e < layer.mask->effects.size(); ++e) {
                visit(NodeVisit{nullptr, &layer.mask->effects[e], layer.uid, NodeStack::Mask, e, texture_set, stack});
            }
        }
        VisitLayers(layer.children, layer.uid, texture_set, stack, visit);
    }
}

Layer* FindIn(std::vector<Layer>& layers, Id uid) {
    for (Layer& layer : layers) {
        if (layer.uid == uid) return &layer;
        if (Layer* found = FindIn(layer.children, uid)) return found;
    }
    return nullptr;
}

Effect* FindEffectIn(std::vector<Layer>& layers, Id uid) {
    for (Layer& layer : layers) {
        for (Effect& effect : layer.content_effects) {
            if (effect.uid == uid) return &effect;
        }
        if (layer.mask) {
            for (Effect& effect : layer.mask->effects) {
                if (effect.uid == uid) return &effect;
            }
        }
        if (Effect* found = FindEffectIn(layer.children, uid)) return found;
    }
    return nullptr;
}

}  // namespace

void ForEachNode(const Project& project, const std::function<void(const NodeVisit&)>& visit) {
    for (const TextureSet& set : project.texture_sets) {
        for (const Stack& stack : set.stacks) VisitLayers(stack.root_layers, stack.id, set.id, stack.id, visit);
    }
}

const Stack* FindStack(const Project& project, Id texture_set, Id stack) {
    for (const TextureSet& set : project.texture_sets) {
        if (set.id != texture_set) continue;
        for (const Stack& candidate : set.stacks) {
            if (candidate.id == stack) return &candidate;
        }
    }
    return nullptr;
}

Layer* FindLayer(Project& project, Id uid) {
    if (uid == kNoId) return nullptr;
    for (TextureSet& set : project.texture_sets) {
        for (Stack& stack : set.stacks) {
            if (Layer* found = FindIn(stack.root_layers, uid)) return found;
        }
    }
    return nullptr;
}

const Layer* FindLayer(const Project& project, Id uid) {
    return FindLayer(const_cast<Project&>(project), uid);
}

Effect* FindEffect(Project& project, Id uid) {
    if (uid == kNoId) return nullptr;
    for (TextureSet& set : project.texture_sets) {
        for (Stack& stack : set.stacks) {
            if (Effect* found = FindEffectIn(stack.root_layers, uid)) return found;
        }
    }
    return nullptr;
}

const Layer* FindLayer(const Stack& stack, Id uid) {
    if (uid == kNoId) return nullptr;
    return FindIn(const_cast<std::vector<Layer>&>(stack.root_layers), uid);
}

}  // namespace uzp::core
