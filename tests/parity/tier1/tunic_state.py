r"""The Tunic current round's state before its production export, through typed MCP reads
(`mcp_round.drive_native(..., state=TUNIC_CURRENT)`; decisions 194, 196 and 300 item 7).

    expected = expected_state(TUNIC_CURRENT, job, stack, ocio)    # before any call
    summary = check_listing(expected, listing, synced, fresh_uids=True)   # after the sync
    check_recipe(expected, dump); check_shader(shader, display)

Painter's supplementary record of this round
(`parity/reports/phase2/tunic-v10-current-reference.md`) observes 21 mask bindings on 17 Data
resources, F03 and C07 on distinct resources, the Height blends `Forro` Normal and
`Tecido externo` LinearDodge with the titled group LinearDodge, and one hidden default layer.
UzPainter's rebuild is checked for the same state from its committed snapshot:

- **The bindings.** Each expected hash is the manifest pin (`PinnedInput.sha256`) of the bitmap
  the pinned stack names: never a name, a resource entry or a file name rewritten. A mask is a
  Black mask, enabled, whose `params.mask.effects` link names exactly one fill effect; that
  effect's parent is the masked node, in its Mask slot, and its `params.fill.source` is a bitmap
  of the expected SHA-256 in the Data colour space. A `base_tex` is a BaseColor bitmap in sRGB.
  `resource_list` is not binding evidence and is not read.
- **The counts.** The stack's nodes hold exactly the scenario's bitmap sources, on its number of
  distinct hashes, its mask bindings all in Data; F03 and C07 each hold their own expected hash.
- **The Height blends** (`params.blending.Height.mode`): the scenario's, which must also be what
  the stack's `replace_height` gives.
- **The roots.** The visible titled group and exactly one other root, a hidden layer in the
  stack's layer slot: the one the sync reported hiding, its single `hidden` entry (by uid in the
  first snapshot; no Painter layer kind is assumed for it). The titled group holds exactly the
  stack's groups and each group exactly its layers, by name and kind, in the order the sync
  stacks them (the stack's lists reversed: `children` are listed top first), since order changes
  the composition.
- **The recipe** (`project_recipe`): the six create settings and the colour configuration as
  persisted (`recipe.settings` and the rebuild block), and the mesh by its SHA-256.
- **Decision 196.** `shader_get` holds `double_sided` true and `display_get` reports parity false.

Handles are fresh: in each snapshot every node is found through the hierarchy (the root, then
the `children` and `mask.effects` uid links of that listing). Only the first snapshot, right after
the sync, matches uids against the sync's reply; after the reopen no earlier uid is used. The
reopened reads must then equal the first ones literally: nothing is renumbered, because no
renumbering is proved necessary (a project file stores its uids), and no binding, version or
state is stripped.
Assumption: `layer_list`, `project_recipe`, `shader_get` and `display_get` return equal values
after a save and reopen, uids and every node's `params` included. No run of UzPainter backs this
here; a field that legitimately changes on reopen would refuse the round, and only a proof of it
may relax the comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from tools.parity.recorder.script_run import NativeJob


class StateMismatch(Exception):
    """The scenario does not fit the job, or the observed state is not the expected one."""


@dataclass(frozen=True)
class StateScenario:
    """What the round must hold, named explicitly: the golden, the bindings and resources, the
    mask bindings in Data, the two layers that must not share a resource (the override layer
    first), each group's Height blend and the titled group's."""

    golden_id: str
    bindings: int
    resources: int
    data_bindings: int
    distinct: tuple[str, str]
    height: tuple[tuple[str, str], ...]
    root_height: str = "LinearDodge"


TUNIC_CURRENT = StateScenario(
    golden_id="phase2/tier1/tunic-v10-current",
    bindings=21,
    resources=17,
    data_bindings=21,
    distinct=("F03", "C07"),
    height=(("Forro", "Normal"), ("Tecido externo", "LinearDodge")),
)


@dataclass(frozen=True)
class ExpectedLayer:
    layer_id: str
    mask: str | None  # the expected SHA-256 of its mask's bitmap
    base_tex: str | None  # the expected SHA-256 of its BaseColor bitmap


@dataclass(frozen=True)
class ExpectedGroup:
    key: str
    mask: str | None
    height: str
    layers: dict[str, ExpectedLayer]  # by name


@dataclass(frozen=True)
class Expected:
    scenario: StateScenario
    title: str
    groups: dict[str, ExpectedGroup]  # by name
    settings: dict[str, Any]
    mesh_sha256: str
    ocio_config_hash: str


def expected_state(
    scenario: StateScenario, job: NativeJob, stack: dict[str, Any], ocio: str
) -> Expected:
    """The state `scenario` expects of `job`, its pinned `stack` and colour configuration;
    refused unless the scenario fits the job (counts, override layer, distinct hashes, Height
    blends), before any call."""
    if job.golden_id != scenario.golden_id:
        raise StateMismatch(f"the scenario is {scenario.golden_id}'s, not {job.golden_id}'s")
    hashes = {PurePosixPath(m.name).stem: m.sha256 for m in job.sync.masks}

    def pinned(name: str | None) -> str | None:
        if name is None:
            return None
        if name not in hashes:
            raise StateMismatch(f"the stack names the bitmap {name!r}, which no input pins")
        return hashes[name]

    height = dict(scenario.height)
    groups: dict[str, ExpectedGroup] = {}
    masks: list[str] = []
    textures: list[str] = []
    by_id: dict[str, ExpectedLayer] = {}
    for group in stack["groups"]:
        name = group["name"]
        derived = "Normal" if group.get("replace_height") else "LinearDodge"
        if height.get(name) != derived:
            raise StateMismatch(
                f"the scenario blends {name!r} Height as {height.get(name)!r}, the stack {derived}"
            )
        layers: dict[str, ExpectedLayer] = {}
        for layer in stack["layers"]:
            if layer["group"] != group["key"]:
                continue
            expected = ExpectedLayer(
                layer["id"], pinned(layer.get("mask")), pinned(layer.get("base_tex"))
            )
            if layer["name"] in layers or layer["id"] in by_id:
                raise StateMismatch(f"the stack names {layer['name']!r} or {layer['id']} twice")
            layers[layer["name"]] = by_id[layer["id"]] = expected
            masks += [expected.mask] if expected.mask else []
            textures += [expected.base_tex] if expected.base_tex else []
        mask = pinned(group.get("mask"))
        masks += [mask] if mask else []
        if name in groups:
            raise StateMismatch(f"the stack names the group {name!r} twice")
        groups[name] = ExpectedGroup(group["key"], mask, derived, layers)
    if set(height) != set(groups):
        raise StateMismatch(f"the scenario's groups {sorted(height)} are not {sorted(groups)}")
    counts = (len(masks) + len(textures), len(set(masks + textures)), len(masks))
    wanted = (scenario.bindings, scenario.resources, scenario.data_bindings)
    if counts != wanted:
        raise StateMismatch(
            f"the stack gives (bindings, resources, Data) {counts}, the scenario {wanted}"
        )
    first, second = scenario.distinct
    if job.sync.args.get("override_layer") != first:
        overridden = job.sync.args.get("override_layer")
        raise StateMismatch(f"the sync overrides {overridden}, not {first}")
    pair = [by_id[x].mask if x in by_id else None for x in scenario.distinct]
    if None in pair or pair[0] == pair[1]:
        raise StateMismatch(f"{first} and {second} do not bind two distinct pinned masks")
    return Expected(
        scenario,
        stack["title"],
        groups,
        dict(job.create.settings),
        job.create.mesh.sha256,
        ocio,
    )


def field(value: Any, *keys: str) -> Any:
    """`value[k1][k2]...`, or None where a level is no object or lacks the key."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def bitmaps(value: Any) -> list[dict[str, Any]]:
    """Every bitmap source under `value`."""
    if isinstance(value, list):
        return [b for item in value for b in bitmaps(item)]
    if not isinstance(value, dict):
        return []
    own = [value] if value.get("type") == "bitmap" else []
    return own + [b for item in value.values() for b in bitmaps(item)]


def check_listing(
    expected: Expected, listing: dict[str, Any], synced: dict[str, Any], fresh_uids: bool
) -> None:
    """`listing` (`layer_list` of the texture set) holds the expected state, each node found
    afresh through the hierarchy's uid links; with `fresh_uids` (the first snapshot, right after
    the sync) each node also carries the uid the sync reported."""
    nodes = listing.get("nodes")
    if not isinstance(nodes, list) or not all(isinstance(n, dict) for n in nodes):
        raise StateMismatch("layer_list returned no node list")
    by_uid: dict[int, dict[str, Any]] = {}
    for node in nodes:
        if type(node.get("uid")) is not int or node["uid"] in by_uid:
            raise StateMismatch(f"layer_list holds a node without a single uid: {node.get('uid')}")
        by_uid[node["uid"]] = node

    def resolve(uid: Any, parent: int, slot: str, where: str) -> dict[str, Any]:
        node = by_uid.get(uid) if type(uid) is int else None
        if node is None or node.get("parent") != parent or node.get("slot") != slot:
            raise StateMismatch(f"{where}: {uid} is no node of {parent}'s {slot} slot")
        return node

    def layer(node: dict[str, Any], kind: str, name: str, where: str) -> dict[str, Any]:
        if (node.get("node"), node.get("kind"), node.get("name")) != ("layer", kind, name):
            raise StateMismatch(f"{where}: {node.get('kind')} {node.get('name')!r}, not {kind}")
        if node.get("visible") is not True:
            raise StateMismatch(f"{where} is hidden")
        params = node.get("params")
        if not isinstance(params, dict):
            raise StateMismatch(f"{where} has no params")
        return params

    def height(params: dict[str, Any], mode: str, where: str) -> None:
        found = field(params, "blending", "Height", "mode")
        if found != mode:
            raise StateMismatch(f"{where} blends Height as {found!r}, not {mode}")

    def mask(node: dict[str, Any], sha256: str | None, where: str) -> str | None:
        """The SHA-256 the node's mask binds, refused unless it is `sha256`."""
        held = field(node, "params", "mask")
        if sha256 is None:
            if held is not None:
                raise StateMismatch(f"{where} has a mask the stack does not give it")
            return None
        if (
            not isinstance(held, dict)
            or held.get("background") != "Black"
            or held.get("enabled") is not True
            or not isinstance(held.get("effects"), list)
            or len(held["effects"]) != 1
        ):
            raise StateMismatch(f"{where} has no enabled Black mask linking exactly one effect")
        effect = resolve(held["effects"][0], node["uid"], "Mask", f"{where}/mask")
        if (effect.get("node"), effect.get("kind"), effect.get("visible")) != (
            "effect",
            "fill",
            True,
        ):
            raise StateMismatch(f"{where}/mask is no visible fill effect")
        return bitmap(field(effect, "params", "fill", "source"), sha256, "Data", f"{where}/mask")

    def bitmap(source: Any, sha256: str, space: str, where: str) -> str:
        if not isinstance(source, dict) or source.get("type") != "bitmap":
            raise StateMismatch(f"{where} binds no bitmap")
        found = field(source, "resource", "sha256")
        if found != sha256:
            raise StateMismatch(f"{where} binds {found}, not the pinned {sha256}")
        if source.get("color_space") != space:
            raise StateMismatch(
                f"{where} reads its bitmap as {source.get('color_space')!r}, not {space}"
            )
        return sha256

    def uid_of(node: dict[str, Any], reported: Any, where: str) -> None:
        if fresh_uids and node["uid"] != reported:
            raise StateMismatch(f"{where} has the uid {node['uid']}, not the sync's {reported}")

    roots = [n for n in nodes if n.get("parent") is None]
    titled = [n for n in roots if n.get("name") == expected.title]
    others = [n for n in roots if n.get("name") != expected.title]
    hidden = synced.get("hidden")
    if (
        len(titled) != 1
        or len(others) != 1
        or not isinstance(hidden, list)
        or len(hidden) != 1
        or not isinstance(hidden[0], dict)
    ):
        raise StateMismatch(
            "the stack's roots are not the titled group and the one default layer the sync hid"
        )
    default, reported = others[0], hidden[0]
    if (
        (default.get("node"), default.get("slot"), default.get("parent"))
        != ("layer", "Substack", None)
        or default.get("name") != reported.get("name")
        or default.get("visible") is not False
    ):
        raise StateMismatch(
            f"the other root {default.get('node')} {default.get('name')!r} is not the hidden "
            f"default layer the sync reported ({reported.get('name')!r})"
        )
    uid_of(default, reported.get("uid"), f"/{default.get('name')}")
    root = titled[0]
    where = f"/{expected.title}"
    params = layer(root, "group", expected.title, where)
    uid_of(root, synced.get("root_uid"), where)
    mask(root, None, where)
    height(params, expected.scenario.root_height, where)
    reported_groups = {field(g, "key"): field(g, "uid") for g in synced.get("groups") or []}
    reported_layers = {
        (field(x, "group"), field(x, "name")): field(x, "uid") for x in synced.get("layers") or []
    }
    children = [resolve(u, root["uid"], "Substack", where) for u in params.get("children") or []]
    # The sync inserts each group, and each layer of a group, at the top of its list as it reads
    # the stack's lists in order, and `layer_list` gives `children` as stored: top first, so the
    # stack's order reversed (`src/python/stack_sync.cpp`, `manifest.cpp` `Write(Layer)`).
    order = list(reversed(expected.groups))
    if [c.get("name") for c in children] != order:
        raise StateMismatch(
            f"{where} holds {[c.get('name') for c in children]} top first, not {order}"
        )
    observed: dict[str, str] = {}
    for child in children:
        group = expected.groups[child["name"]]
        at = f"{where}/{child['name']}"
        found = layer(child, "group", child["name"], at)
        uid_of(child, reported_groups.get(group.key), at)
        mask(child, group.mask, at)
        height(found, group.height, at)
        fills = [resolve(u, child["uid"], "Substack", at) for u in found.get("children") or []]
        stacked = list(reversed(group.layers))
        if [f.get("name") for f in fills] != stacked:
            raise StateMismatch(
                f"{at} holds {[f.get('name') for f in fills]} top first, not {stacked}"
            )
        for fill in fills:
            spec = group.layers[fill["name"]]
            path = f"{at}/{fill['name']}"
            content = layer(fill, "fill", fill["name"], path)
            uid_of(fill, reported_layers.get((group.key, fill["name"])), path)
            if content.get("content_effects") != []:
                raise StateMismatch(f"{path} holds a content effect")
            bound_mask = mask(fill, spec.mask, path)
            if spec.base_tex is not None:
                source = field(content, "fill", "sources", "BaseColor")
                bitmap(source, spec.base_tex, "sRGB", f"{path}/BaseColor")
            if bound_mask is not None:
                observed[spec.layer_id] = bound_mask
    first, second = expected.scenario.distinct
    if first not in observed or second not in observed or observed[first] == observed[second]:
        raise StateMismatch(f"{first} and {second} are not bound to two distinct resources")
    bound = bitmaps([n.get("params") for n in nodes])
    hashes = [field(b, "resource", "sha256") for b in bound]
    scenario = expected.scenario
    totals = (len(bound), len(set(hashes)), sum(b.get("color_space") == "Data" for b in bound))
    wanted = (scenario.bindings, scenario.resources, scenario.data_bindings)
    if totals != wanted:
        raise StateMismatch(f"the stack holds (bindings, resources, Data) {totals}, not {wanted}")


def check_recipe(expected: Expected, dump: dict[str, Any]) -> None:
    """The persisted recipe (`project_recipe`) holds the create's six settings and colour
    configuration, and the staged mesh by its SHA-256, as concrete values."""
    recipe, rebuild = field(dump, "recipe"), field(dump, "rebuild")
    settings = field(recipe, "settings")
    given = expected.settings
    resolution = given["default_texture_resolution"]
    found = {
        "normal_map_format": field(settings, "normal_map_format"),
        "tangent_space_mode": field(settings, "tangent_space"),
        "project_workflow": field(settings, "workflow"),
        "default_texture_resolution": field(rebuild, "/settings/default_resolution"),
        "import_cameras": field(rebuild, "/settings/import_cameras"),
        "mesh_unit_scale": field(rebuild, "/settings/mesh_unit_scale"),
    }
    wanted = {**given, "default_texture_resolution": {"width": resolution, "height": resolution}}
    if found != wanted:
        raise StateMismatch(f"the recipe persists the settings {found}, not {wanted}")
    colour = field(settings, "color_management", "config_hash")
    if colour != expected.ocio_config_hash:
        raise StateMismatch(f"the recipe's colour configuration is {colour}")
    mesh = field(recipe, "mesh", "resource")
    if mesh != expected.mesh_sha256:
        raise StateMismatch(f"the recipe's mesh is {mesh}, not {expected.mesh_sha256}")


def check_shader(shader: dict[str, Any], display: dict[str, Any]) -> None:
    """Decision 196: `double_sided` true is stored, and the display reports parity false."""
    if field(shader, "parameters", "double_sided") is not True:
        raise StateMismatch("shader_get does not hold double_sided true")
    shown = field(display, "shader", "parameters", "double_sided")
    if display.get("parity") is not False or shown is not True:
        raise StateMismatch(
            f"display_get reports parity {display.get('parity')!r} with double_sided {shown!r}, "
            "not parity false with double_sided true"
        )
