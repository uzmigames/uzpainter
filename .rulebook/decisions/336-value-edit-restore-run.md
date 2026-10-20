# 336. A run of value edits that restores every value it changed leaves the project as saved; replacing a mesh map's resource rebinds every mesh map bound to it

Date: 2026-10-20. Status: accepted (Claude and Codex; routine technical choice delegated by the owner).
Refines decision 111 §6 (the rename run) and lifts the facade half of decision 111 §7's mesh-map refusal.
Related: phase1.24_python-api-facade item 4.1; goldens `tier0/api-probes/phase1-restored-values` (P22-C) and `phase1-mesh-map-update` (P22-A), admitted under decision 180.

## Context

- **P22-C:** after an edit that returns a value to its saved state, `needs_saving()` reads False in Painter at s12, s16, s20 and s28. Before this decision, the facade only applied this to consecutive `set_name` calls (the rename run of decision 111 §6). Decision 111 had rejected comparing content before P22-C was recorded.
- **P22-A:** `update_layer_stack_resource` on a resource bound as a mesh map rebinds that mesh map. Decision 111 §7 had refused this until P22-A was recorded.

## Decision

1. **Restore run.**
   - Value edits made while the project is as saved form one run until any other edit. The value edits are `set_name`, `set_opacity`, `set_visible` and `set_blending_mode`.
   - The project counts as saved again once every value the run changed reads back its saved value.
   - A no-op value edit from a saved state leaves the project saved, as the rename run did. Painter's answer for that case is unrecorded.
2. **Mesh-map replacement.** The facade's `update_layer_stack_resource` rebinds, in one transaction, every mesh map bound to the replaced resource, matched by given name and content, then runs the native layer-stack rebind.
   - The native `uzpainter.resource.update_layer_stack_resource @ mesh-map` stays a release gap; its refusal is in `src/python/edits.cpp`.
   - The P22-A replay excludes only `s12/uid`, because a uid's value is Painter's own allocation (the existing `UID_VALUE` reason).

## Consequences

- Both P22-A and P22-C replay exactly in both recordings, under the named rules.
- The facade context `substance_painter.resource.update_layer_stack_resource @ mesh-map` leaves the release-gap list. Its conformance refusal recipe goes with it.
