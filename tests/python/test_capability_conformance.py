"""The capability manifest against what the API does (task phase1.22_pyapi-cli-capabilities items
2.6 and 3.5; decision 112).

- `supported` (context `any`): the entry cites exactly the Tier 0 goldens whose compared replays
  exercised the symbol, a member of it or, for a module or a class, one of its members
  (`tools/capabilities/tier0-trace.json`, kept by the Tier 0 tests on the owner's machine,
  `capability_trace.py`); and every symbol a compared replay exercised is `supported`.
- Every public name of `substance_painter`, `substance_painter_plugins` and `uzpainter` has an
  entry; every `supported`, `pending-evidence` or `desktop-only-omitted` symbol exists.
- `desktop-only-omitted`: using the symbol raises `UnsupportedInUzPainter`.
- `release-gap`: an absent symbol raises `AttributeError` (decision 107 §1); a present one raises
  `NotYetSupported` (or its subclasses `UnsupportedProcedural`, `ReleaseGap`) with the project's
  revision unchanged, called with placeholder arguments or through the call that uses it
  (`RECIPES`). Two kinds of gap are refused elsewhere and listed in `ELSEWHERE`: the compositor
  contexts (the evaluator's support check, `tests/evaluator/evaluator_test.cpp`
  `not-yet-supported`, decisions 081 and 082) and material layering, which no documented call
  requests.

CPU only: every lane runs these.
"""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from typing import Any

import pytest

from tests.python.capability_trace import SOURCE, load_trace
from tests.python.conftest import Run
from tools.capabilities.generate_capabilities import generate

# Gaps whose refusal is not a Python API call (see the module docstring), by context.
ELSEWHERE = {
    "material-layering": "no documented call creates a second stack in a texture set; a project "
    "or template holding one is refused when opened",
}
COMPOSITOR = "compositor"

# The call that uses a symbol, after `setup`, for gaps and desktop-only members a placeholder call
# cannot reach. `(symbol, context)` or a symbol (any context). Names available: the facade
# modules, `uzpainter`, `nls` (uzpainter.layerstack), `stack`, `fill` and `masked` (facade fills,
# the second with a mask), their native handles `nstack`, `nfill`, `nmasked`, `top`, `ntop`.
NATIVE_PAINT_EFFECT = (
    "nls.insert_paint(nls.InsertPosition.inside_node(nmasked, nls.NodeStack.Mask))"
)
PAINT_EFFECT = "ls.insert_paint(ls.InsertPosition.inside_node(masked, ls.NodeStack.Mask))"
UV = "fill.set_projection_mode(ls.ProjectionMode.UV)"
NATIVE_UV = "nfill.set_projection_mode(nls.ProjectionMode.UV)"
SHELF = "shelf = resource.Shelves.add('p22-' + str(len(resource.Shelves.all())), WORK)"
TEXTURE = "resource.Usage.TEXTURE"
CLOSED = "project.close()"


def export_call(
    file_format: str,
    map_name: str = "height",
    bit_depth: str = "8",
    module: str = "export",
    components: str = "L",
    others: str | None = None,
) -> str:
    """An export of the document map `map_name` (its `components`, L or RGB; the components after
    the first read the document map `others` when given) in `file_format` at `bit_depth`, every
    parameter the export requires given (`src/export/EXPORT.md`), through the facade's `export`
    (or `module`, with its own texture set listing)."""
    config = {
        "exportShaderParams": False,
        "defaultExportPreset": "p",
        "exportPresets": [
            {
                "name": "p",
                "maps": [
                    {
                        "fileName": f"$textureSet_{map_name}",
                        "channels": [
                            {
                                "destChannel": c,
                                "srcChannel": c,
                                "srcMapType": "documentMap",
                                "srcMapName": map_name if i == 0 or others is None else others,
                            }
                            for i, c in enumerate(components)
                        ],
                    }
                ],
            }
        ],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": file_format,
                    "bitDepth": bit_depth,
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }
    sets = "ts" if module == "export" else "uzpainter.textureset"
    return (
        f"{module}.export_project_textures(dict(json.loads({json.dumps(config)!r}), "
        "exportPath=WORK + '/export', "
        f"exportList=[{{'rootPath': t.name()}} for t in {sets}.all_texture_sets()]))"
    )


def recipes() -> dict[Any, tuple[str, str]]:
    r: dict[Any, tuple[str, str]] = {}
    for root, lsname, nodes, top_, mask_, fill_ in (
        ("substance_painter", "ls", "ls", "top(stack)", "masked", "fill"),
        ("uzpainter", "nls", "nls", "ntop", "nmasked", "nfill"),
    ):
        layerstack = f"{root}.layerstack"
        inside_mask = f"{nodes}.InsertPosition.inside_node({mask_}, {nodes}.NodeStack.Mask)"
        inside_content = f"{nodes}.InsertPosition.inside_node({fill_}, {nodes}.NodeStack.Content)"
        anchor = (
            f"{lsname}.insert_anchor_point_effect({inside_content}, 'anchor')"
            if root == "substance_painter"
            else f"{lsname}.insert_anchor_point_effect({inside_content})"
        )
        paint = f"{lsname}.insert_paint({top_})"
        paint_effect = PAINT_EFFECT if root == "substance_painter" else NATIVE_PAINT_EFFECT
        selection = f"{lsname}.insert_color_selection_effect({inside_mask})"
        compare = f"{lsname}.insert_compare_mask_effect({inside_mask})"
        calls = {
            "AnchorPointEffectNode": anchor,
            "insert_anchor_point_effect": anchor,
            "ColorSelectionEffectNode": selection,
            "CompareMaskEffectNode": compare,
            "FilterEffectNode": f"{lsname}.insert_filter_effect({top_}, None)",
            "GeneratorEffectNode": f"{lsname}.insert_generator_effect({top_}, None)",
            "InstanceLayerNode": f"{lsname}.instantiate({top_}, {fill_})",
            "instantiate": f"{lsname}.instantiate({top_}, {fill_})",
            "PaintLayerNode": paint,
            "insert_paint": paint,
            "PaintEffectNode": paint_effect,
        }
        if root == "uzpainter":  # the facade's two inserts are supported (insertion rules)
            calls["insert_color_selection_effect"] = selection
            calls["insert_compare_mask_effect"] = compare
        else:  # the Painter contexts of paint nodes
            content = "bitmap-or-projection-content"
            r[(f"{layerstack}.PaintLayerNode", content)] = ("", paint)
            r[(f"{layerstack}.PaintEffectNode", content)] = ("", paint_effect)
        for name, call in calls.items():
            r[f"{layerstack}.{name}"] = ("", call)
        uv = UV if root == "substance_painter" else NATIVE_UV
        for mode in ("Cylindrical", "Planar", "Spherical", "Triplanar", "UVSetToUVSet", "Warp"):
            call = f"{fill_}.set_projection_mode({nodes}.ProjectionMode.{mode})"
            r[f"{layerstack}.ProjectionMode.{mode}"] = ("", call)
        for mode in ("CustomPhysicalSize", "MaterialPhysicalSize"):
            params = (
                f"{nodes}.UVProjectionParams(uv_transformation={nodes}.UVTransformationParams("
                f"scale_mode={nodes}.ScaleMode.{mode}, scale=[1.0, 1.0], rotation=0.0, "
                "offset=[0.0, 0.0]))"
            )
            r[f"{layerstack}.ScaleMode.{mode}"] = (
                uv,
                f"{fill_}.set_projection_parameters({params})",
            )
        for mode in ("RepeatHorizontally", "RepeatVertically"):
            params = f"{nodes}.UVProjectionParams(uv_wrapping_mode={nodes}.UVWrapMode.{mode})"
            r[f"{layerstack}.UVWrapMode.{mode}"] = (
                uv,
                f"{fill_}.set_projection_parameters({params})",
            )
        for workflow in ("UVTile", "TextureSetPerUVTile"):
            member = f"{root}.project.ProjectWorkflow.{workflow}"
            settings = f"{root}.project.Settings(project_workflow={member})"
            create = (
                f"project.create(PLANE, settings={settings})"
                if root == "substance_painter"
                else f"uzpainter.project.create(PLANE, {settings})"
            )
            r[f"{root}.project.ProjectWorkflow.{workflow}"] = (CLOSED, create)
    r["substance_painter.layerstack.FillLayerNode.set_material_source"] = (
        "",
        "fill.set_material_source(None)",
    )
    r["substance_painter.layerstack.FillEffectNode.set_material_source"] = (
        "effect = ls.insert_fill(ls.InsertPosition.inside_node(masked, ls.NodeStack.Mask))",
        "effect.set_material_source(None)",
    )
    r["uzpainter.layerstack.FillLayerNode.set_material_source"] = (
        "",
        "nfill.set_material_source(None)",
    )
    # The capture mode `painter_iray` (decision 148): refused first, with any arguments.
    r[("uzpainter.render.capture", "mode:painter_iray")] = (
        "",
        "uzpainter.render.capture(WORK + '/iray.png', 'painter_iray')",
    )
    r["uzpainter.layerstack.FillEffectNode.set_material_source"] = (
        "neffect = nls.get_node_by_uid(ls.insert_fill("
        "ls.InsertPosition.inside_node(masked, ls.NodeStack.Mask)).uid())",
        "neffect.set_material_source(None)",
    )
    for field, value in (
        ("mesh_settings", "object()"),
        ("auto_unwrap_settings", "object()"),
    ):
        r[f"substance_painter.project.Settings.{field}"] = (
            CLOSED,
            f"project.create(PLANE, settings=project.Settings({field}={value}))",
        )
    for field in ("mesh_settings", "auto_unwrap_settings"):
        r[f"substance_painter.project.MeshReloadingSettings.{field}"] = (
            "",
            f"project.reload_mesh(PLANE, project.MeshReloadingSettings({field}=object()), print)",
        )
    r["substance_painter.resource.Shelf.can_import_resources"] = (
        SHELF,
        "shelf.can_import_resources()",
    )
    r["substance_painter.resource.Shelf.import_resource"] = (SHELF, "shelf.import_resource(PLANE)")
    r["substance_painter.resource.Shelf.resources"] = (SHELF, "shelf.resources()")
    # A Painter name: the shipped asset library certifies no family yet (decision 324).
    r["substance_painter.resource.search"] = (
        "",
        "resource.search('s:starterassets u:filter n:Blur=')",
    )
    for file_format in ("tiff", "psd", "webp", "j2k"):
        r[("substance_painter.export.export_project_textures", f"file-format:{file_format}")] = (
            "",
            export_call(file_format),
        )
    # The PNG export of Dota 2's L8 Specular in a file whose G and B read BaseColor (decision 204):
    # only the RGB and L files of the one L8 channel are recorded; refused before writing.
    for symbol, module, create in (
        (
            "substance_painter.export.export_project_textures",
            "export",
            # The facade maps a shipped template by its file name; the file must exist and is
            # never read (decision 116).
            "open(WORK + '/Dota 2.spt', 'wb').close()\n"
            "project.create(PLANE, template_file_path=WORK + '/Dota 2.spt')",
        ),
        (
            "uzpainter.export.export_project_textures",
            "uzpainter.export",
            "uzpainter.project.create(PLANE, uzpainter.project.Settings(template='dota-2'))",
        ),
    ):
        r[(symbol, "l8-material-channel-png-unrecorded")] = (
            f"{CLOSED}\n{create}",
            export_call("png", "specular", "16", module, "RGB", "basecolor"),
        )
    # The bake parameters' refusals (decision 323): the texture set's baking state setters, the
    # UV-tile members and the meta properties, through either package; a value refused by context.
    for root, sets in (("substance_painter", "ts"), ("uzpainter", "uzpainter.textureset")):
        first = f"{sets}.all_texture_sets()[0]"
        params = f"b = {root}.baking.BakingParameters.from_texture_set({first})"
        usage = f"{sets}.MeshMapUsage.AO"
        method = f"b.set_curvature_method({root}.baking.CurvatureMethod.FromMesh)"
        for name, call in (
            ("set_textureset_enabled", "b.set_textureset_enabled(False)"),
            ("set_enabled_bakers", f"b.set_enabled_bakers([{usage}])"),
            ("is_baker_enabled", f"b.is_baker_enabled({usage})"),
            ("set_baker_enabled", f"b.set_baker_enabled({usage}, False)"),
            ("set_curvature_method", method),
            ("get_enabled_uv_tiles", "b.get_enabled_uv_tiles()"),
            ("set_enabled_uv_tiles", "b.set_enabled_uv_tiles([])"),
            ("is_uv_tile_enabled", "b.is_uv_tile_enabled(None)"),
            ("set_uv_tile_enabled", "b.set_uv_tile_enabled(None, True)"),
        ):
            r[f"{root}.baking.BakingParameters.{name}"] = (params, call)
        meta = "b.common()['CageMode'].properties()"
        r[f"{root}.properties.Property.properties"] = (params, meta)
    facade_params = "b = sp.baking.BakingParameters.from_texture_set(ts.all_texture_sets()[0])"
    r[("substance_painter.properties.Property.value", "default-unestablished")] = (
        facade_params,
        "b.common()['OutputSize'].value()",
    )
    r[("substance_painter.baking.BakingParameters.set", "out-of-range")] = (
        facade_params,
        "sp.baking.BakingParameters.set({b.common()['DilationWidth']: 100000})",
    )
    r[("substance_painter.baking.BakingParameters.set", "baker-other-than-ao")] = (
        facade_params,
        "sp.baking.BakingParameters.set({b.baker(ts.MeshMapUsage.Curvature)['AutoMinMax']: False})",
    )
    r["substance_painter.resource.Resource.show_in_ui"] = (
        f"r = resource.import_project_resource(IMAGES + '/checker-16.png', {TEXTURE}, 'a')",
        "r.show_in_ui()",
    )
    return r


CHECK = """
import importlib, inspect
import substance_painter
nls = uzpainter.layerstack
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
REFUSALS = {"release-gap": uzpainter.NotYetSupported,
            "desktop-only-omitted": uzpainter.UnsupportedInUzPainter}
# Contexts whose refusal must name what settles it.
NAMED = {"l8-material-channel-png-unrecorded": "decision 204"}


def resolve(symbol):
    parts = symbol.split(".")
    obj, i = importlib.import_module(parts[0]), 1
    while i < len(parts):
        try:
            obj = importlib.import_module(".".join(parts[: i + 1]))
            i += 1
        except ImportError:
            break
    static = False
    for name in parts[i:]:
        if inspect.isclass(obj):
            raw = inspect.getattr_static(obj, name)
            static = isinstance(raw, (staticmethod, classmethod))
            plain = inspect.isfunction(raw) or type(raw).__name__ == "instancemethod"
            obj = getattr(obj, name)
            if plain:
                return obj, "method"
        else:
            obj = getattr(obj, name)
    return obj, "static" if static else "member"


def placeholder_call(obj):
    try:
        params = inspect.signature(obj).parameters.values()
    except (TypeError, ValueError):
        return obj()
    args = [None for p in params
            if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return obj(*args)


def fresh():
    if project.is_open():
        project.close()
    stack = create()
    fill = ls.insert_fill(top(stack))
    masked = ls.insert_fill(top(stack))
    masked.add_mask(ls.MaskBackground.Black)
    nstack = uzpainter.textureset.get_active_stack()
    return {"stack": stack, "fill": fill, "masked": masked, "nstack": nstack,
            "ntop": nls.InsertPosition.from_textureset_stack(nstack),
            "nfill": nls.get_node_by_uid(fill.uid()), "nmasked": nls.get_node_by_uid(masked.uid())}


def check(symbol, context, status, recipe):
    expected = REFUSALS[status]
    try:
        obj, kind = resolve(symbol)
    except AttributeError:
        return "absent" if status == "release-gap" else "absent, but " + status
    names = dict(globals())
    names.update(fresh())
    try:
        if recipe is not None:
            exec(recipe[0], names)
        before = uzpainter.project.revision() if project.is_open() else None
        if recipe is not None:
            exec(recipe[1], names)
        elif kind == "method" or not callable(obj):
            return "no call reaches it"
        else:
            placeholder_call(obj)
    except expected as error:
        after = uzpainter.project.revision() if project.is_open() else None
        if after != before:
            return f"refused after a change: revision {before} -> {after}"
        if NAMED.get(context, "") not in str(error):
            return f"refused without naming {NAMED[context]}: {error}"
        return "refused"
    except BaseException as error:
        return f"raised {type(error).__name__}: {error}"
    return "did not raise"


outcomes = {}
for symbol, context, status, recipe in PAYLOAD:
    outcomes[symbol + " @ " + context] = check(symbol, context, status, recipe)
if project.is_open():
    project.close()
result = outcomes
"""

SURFACE = """
TRACE = {"__name__": "uzp_capability_trace"}
exec(compile(base64.b64decode("__SOURCE__").decode("utf-8"), "capability_trace.py", "exec"), TRACE)
result = TRACE["public_symbols"]()
"""


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return generate()


def entries(manifest: dict[str, Any], status: str) -> list[dict[str, Any]]:
    return [e for e in manifest["entries"] if e["status"] == status]


def run_checks(facade: Run, checks: list[list[Any]]) -> dict[str, str]:
    payload = base64.b64encode(json.dumps(checks).encode("utf-8")).decode("ascii")
    report = facade("import base64\n" + CHECK.replace("__PAYLOAD__", payload))
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    outcomes: dict[str, str] = report["result"]
    return outcomes


def test_supported_entries_equal_the_tier0_trace(manifest: dict[str, Any]) -> None:
    """3.5: no `supported` entry without the Tier 0 evidence of a compared replay, and no exercised
    symbol left without the entry that cites it."""
    exercised: dict[str, set[str]] = defaultdict(set)
    for replay in load_trace().values():
        for symbol in replay["symbols"]:
            parts = symbol.split(".")
            for i in range(1, len(parts) + 1):
                exercised[".".join(parts[:i])].add(replay["golden"])
    claimed = {
        e["symbol"]: set(e["tier_evidence"])
        for e in entries(manifest, "supported")
        if e["context"] == "any"
    }
    wrong = sorted(s for s in claimed.keys() & exercised.keys() if claimed[s] != exercised[s])
    assert sorted(claimed.keys() - exercised.keys()) == [], "supported without a compared replay"
    assert sorted(exercised.keys() - claimed.keys()) == [], "exercised but not supported"
    assert wrong == [], "tier_evidence differs from the goldens whose replays exercised it"


def test_every_public_symbol_has_an_entry(facade: Run, manifest: dict[str, Any]) -> None:
    """2.6, 3.5: every public name of both packages has an entry, and nothing the manifest says
    works is missing."""
    source = base64.b64encode(SOURCE.encode("utf-8")).decode("ascii")
    report = facade("import base64\n" + SURFACE.replace("__SOURCE__", source))
    assert report["status"] == "ok", report.get("error", {}).get("traceback", report)
    public = set(report["result"])
    listed = {e["symbol"] for e in manifest["entries"]}
    assert sorted(public - listed) == [], "public symbols without a manifest entry"
    claimed = {
        e["symbol"]
        for e in manifest["entries"]
        if e["status"] in ("supported", "pending-evidence", "desktop-only-omitted")
    }
    assert sorted(claimed - public) == [], "entries claiming a symbol that does not exist"


def test_pending_evidence_entries_name_their_owner(manifest: dict[str, Any]) -> None:
    """Decision 112: an implemented symbol without Tier 0 evidence says so and who settles it."""
    for entry in entries(manifest, "pending-evidence"):
        assert entry["context"] == "any" and not entry["tier_evidence"], entry["symbol"]
        assert "without Tier 0 evidence" in entry["notes"], entry["symbol"]


def test_desktop_only_entries_raise_unsupported_in_uzpainter(
    facade: Run, manifest: dict[str, Any]
) -> None:
    """3.5: every desktop-only member raises `UnsupportedInUzPainter`."""
    table = recipes()
    checks = [
        [e["symbol"], e["context"], e["status"], table.get(e["symbol"])]
        for e in entries(manifest, "desktop-only-omitted")
    ]
    outcomes = run_checks(facade, checks)
    failures = [f"{k}: {v}" for k, v in outcomes.items() if v != "refused"]
    assert failures == [], chr(10).join(failures)


def test_release_gaps_raise_not_yet_supported_before_mutation(
    facade: Run, manifest: dict[str, Any]
) -> None:
    """3.5: every release gap the Python API reaches raises `NotYetSupported` with the revision
    unchanged, or is absent; the others are refused where `ELSEWHERE` says."""
    table = recipes()
    checks = []
    for e in entries(manifest, "release-gap"):
        context = e["context"]
        if context.split(":")[0] == COMPOSITOR or context in ELSEWHERE:
            continue
        recipe = table.get((e["symbol"], context)) or (
            table.get(e["symbol"]) if context == "any" else None
        )
        checks.append([e["symbol"], context, e["status"], recipe])
    outcomes = run_checks(facade, checks)
    failures = [f"{k}: {v}" for k, v in outcomes.items() if v not in ("refused", "absent")]
    assert failures == [], chr(10).join(failures)
    unused = set(table) - {(c[0], c[1]) for c in checks} - {c[0] for c in checks}
    desktop = {e["symbol"] for e in entries(manifest, "desktop-only-omitted")}
    assert unused <= desktop, sorted(map(str, unused - desktop))
