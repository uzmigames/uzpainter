"""Read-only extension executed in a copy of uzp_probes; no state operations or acceptance."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any


def collect_filter_context(args: dict[str, Any]) -> dict[str, Any]:
    namespace = globals()
    spec = namespace["FILTER_CONTEXT_SPEC"]
    conditions = namespace["FILTER_CONTEXT_CONDITIONS"]
    if (
        set(args) != {"boundary", "condition"}
        or args["boundary"] not in conditions
        or args["condition"] != conditions[args["boundary"]]
    ):
        raise ValueError("invalid F context boundary")
    painter = namespace["substance_painter"]
    describe = namespace["describe"]
    resolve = namespace["resolve"]
    outputs: list[dict[str, Any]] = []

    def read(
        call: str,
        selector: dict[str, Any],
        getter: Callable[[], Any],
        parameters: dict[str, Any] | None = None,
        serialize: Callable[[Any], Any] | None = None,
    ) -> Any:
        output: dict[str, Any] = {
            "output_id": f"context/{args['boundary']}/{len(outputs):04d}-{call.rsplit('.', 1)[1]}",
            "kind": "api_readback",
            "call": call,
            "args": {"selector": selector, "parameters": parameters or {}},
            "value": None,
        }
        raw = None
        try:
            raw = getter()
            output["value"] = (serialize or describe)(raw)
        except Exception as error:
            output["raised"] = namespace["raised"](error)
        outputs.append(output)
        return raw

    for call in spec["project"][:-1]:
        method = call.rsplit(".", 1)[1]
        read(
            call,
            {},
            getattr(painter.project, method),
            serialize=str if method == "get_uuid" else None,
        )
    sets = read(spec["project"][-1], {}, painter.textureset.all_texture_sets)

    def member_value(obj: Any, name: str) -> Any:
        member = getattr(obj, name)
        return member() if callable(member) else member

    def member_call(obj: Any, name: str, argument: Any) -> Any:
        return getattr(obj, name)(argument)

    def input_source(source_args: dict[str, Any], identifier: str) -> Any:
        return namespace["substance_source"](source_args).get_source(identifier)

    def node_read(node: Any, selector: dict[str, Any], channels: dict[Any, Any]) -> None:
        uid = node.uid()
        current = read(
            "substance_painter.layerstack.get_node_by_uid",
            selector,
            lambda: resolve(uid),
            {"uid": uid},
        )
        if current is None:
            return
        parent = None
        for call in spec["node"]:
            value = read(call, selector, getattr(current, call.rsplit(".", 1)[1]))
            if call.endswith(".get_parent"):
                parent = value
        if parent is not None:
            read("substance_painter.layerstack.Node.uid", {**selector, "parent": True}, parent.uid)
        if isinstance(current, painter.layerstack.LayerNode):
            for call in spec["layer"]:
                read(call, selector, getattr(current, call.rsplit(".", 1)[1]))
        if isinstance(current, painter.layerstack.FillLayerNode):
            for call in spec["fill"]:
                method = call.rsplit(".", 1)[1]
                read(call, selector, partial(member_value, current, method))
        if isinstance(current, painter.layerstack.FilterEffectNode):
            read(spec["filter"][0], selector, lambda: current.active_channels)
        if isinstance(current, painter.layerstack.GroupLayerNode):
            read(
                "substance_painter.layerstack.GroupLayerNode.sub_layers",
                selector,
                current.sub_layers,
            )
        for channel in channels:
            for call in spec["blend"]:
                read(
                    call,
                    selector,
                    partial(member_call, current, call.rsplit(".", 1)[1], channel),
                    {"channel": describe(channel)},
                )
        # Traversal establishes paths; parent UID is a separate real getter above.
        for kind, children in namespace["child_lists"](current):
            for index, child in enumerate(children):
                node_read(child, {**selector, "path": [*selector["path"], [kind, index]]}, channels)

    for set_index, texture_set in enumerate(sets or []):
        selected = {"set": set_index}
        stacks = None
        for call in spec["set"]:
            method = call.rsplit(".", 1)[1]
            value = read(call, selected, partial(member_value, texture_set, method))
            if method == "all_stacks":
                stacks = value
        for stack_index, stack in enumerate(stacks or []):
            selected_stack = {**selected, "stack": stack_index}
            read(spec["stack"][0], selected_stack, stack.name)
            channels = read(spec["stack"][1], selected_stack, stack.all_channels)
            for kind, channel in (channels or {}).items():
                channel_selector = {**selected_stack, "channel": describe(kind)}
                for call in spec["channel"]:
                    read(call, channel_selector, getattr(channel, call.rsplit(".", 1)[1]))
            roots = read(
                spec["stack"][2],
                selected_stack,
                partial(painter.layerstack.get_root_layer_nodes, stack),
            )
            for index, node in enumerate(roots or []):
                node_read(node, {**selected_stack, "path": [["Root", index]]}, channels or {})
    if args["boundary"] != "after-create":
        for role, step in (("host", 3), ("filter", 6)):
            uid = namespace["PROBE_NODES"][step].uid()
            node = read(
                "substance_painter.layerstack.get_node_by_uid",
                {"role": role},
                partial(resolve, uid),
                {"uid": uid},
            )
            if node is not None:
                read("substance_painter.layerstack.Node.uid", {"role": role}, node.uid)
            source_args = (
                {"node_step": step, "channel": "User0"}
                if role == "host"
                else {"node_step": step, "effect": True}
            )
            source_selector = {"role": role, "source": True}
            inputs = None
            for call in spec["source"]:
                # substance_read resolves the node and source afresh for each documented getter.
                value = read(
                    call, source_selector, partial(namespace["substance_read"], call, source_args)
                )
                if call.endswith(".image_inputs"):
                    inputs = value
            for identifier in inputs or []:
                read(
                    "substance_painter.source.SourceSubstance.get_source",
                    source_selector,
                    partial(input_source, source_args, identifier),
                    {"input_identifier": identifier},
                )
    return {"schema": namespace["FILTER_CONTEXT_SCHEMA"], **args, "outputs": outputs}


if "OPERATIONS" in globals():
    if "filter_context_read" in globals()["OPERATIONS"]:
        raise ValueError("filter context operation already registered")
    globals()["OPERATIONS"]["filter_context_read"] = collect_filter_context
