"""`uzpainter.project.dump_recipe` and `rebuild_from_recipe` (phase2.1_recipe-dump-manifest-blocks
items 2.2, 2.5, 3.1, 3.2 and 3.4; decision 122).

Each test runs scripts in `uzp-pyapi-tests.exe` (conftest.py) on the plane fixture. CPU only. The
`inspect` side of the recipe (item 3.3) is in test_pyapi_cli.py, which runs `UzPainter.exe`.
"""

from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from tests.mesh.mesh_fixtures import GltfNode, Primitive, gltf_document
from tests.python.conftest import REPO_ROOT, Run
from tests.python.test_pyapi_native import CONFIG_EXPRESSION, ok
from tools.parity.recorder.job import canonical_json

SCHEMA = REPO_ROOT / "src" / "uzp_core" / "schema" / "recipe.schema.json"

# A stack of the kinds the native API inserts in Phase 2: fills with uniform and bitmap sources, a
# group with a child, a content levels effect, a mask with a bitmap fill; then the helpers that
# save every resource the dump stores under its hash.
BUILD = """
import hashlib, shutil
stack = create()
mask_image = resource.import_project_resource(
    IMAGES + "/mask-left-half.png", resource.Usage.TEXTURE
)
base = ls.insert_fill(top(stack))
base.set_name("base")
base.active_channels = {CT.BaseColor, CT.Height}
base.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
group = ls.insert_group(top(stack))
group.set_name("group")
child = ls.insert_fill(ls.InsertPosition.inside_node(group, ls.NodeStack.Substack))
child.active_channels = {CT.Height}
child.set_source(CT.Height, cm.Color(0.75, 0.75, 0.75, "Raw"))
child.set_opacity(0.5, CT.Height)
child.add_mask(ls.MaskBackground.Black)
mask_fill = ls.insert_fill(ls.InsertPosition.inside_node(child, ls.NodeStack.Mask))
mask_fill.set_source(None, mask_image.identifier())
ls.insert_levels_effect(ls.InsertPosition.inside_node(base, ls.NodeStack.Content))

def save_resources(dump, sources, folder):
    os.makedirs(folder, exist_ok=True)
    stored = {}
    for path in sources:
        data = open(path, "rb").read()
        stored[hashlib.sha256(data).hexdigest()] = path
    for sha in dump["rebuild"]["/resource_catalog"]:
        shutil.copyfile(stored[sha], folder + "/" + sha + os.path.splitext(stored[sha])[1])
    return sorted(os.listdir(folder))

def export_files(folder):
    config = __CONFIG__
    config["exportPath"] = folder
    out = export.export_project_textures(config)
    return {f["relative_path"]: f["path"] for f in out["files"]}
"""


def script(body: str) -> str:
    return (BUILD + textwrap.dedent(body)).replace("__CONFIG__", CONFIG_EXPRESSION)


def test_dump_recipe_is_deterministic_and_moves_only_with_the_output(run: Run, facade: Run) -> None:
    """2.2, 3.1, 3.2: the dump validates against the schema; repeated dumps, save and reopen, and a
    new process give one digest; collapsing a group, the active stack and the facade's selection
    change it not (the group's collapse is a commit: the revision moves); an opacity edit does."""
    first = ok(
        run(
            script("""
        a = project.dump_recipe()
        b = project.dump_recipe()
        project.save_as(WORK + "/recipe.uzp")
        group.set_collapsed(True)
        collapsed = project.dump_recipe()
        ts.set_active_stack(stack)
        project.save()
        project.close()
        project.open(WORK + "/recipe.uzp")
        reopened = project.dump_recipe()
        with uzpainter.Transaction():
            ls.get_node_by_uid(child.uid()).set_opacity(0.25, CT.Height)
            inside = project.dump_recipe()
        edited = project.dump_recipe()
        project.save()
        result = {"a": a, "b": b, "collapsed": collapsed, "reopened": reopened,
                  "inside": inside, "edited": edited}
        """)
        )
    )
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    a = first["a"]
    assert [e.message for e in validator.iter_errors(a)] == []
    assert a["digest"] == hashlib.sha256(canonical_json(a["recipe"])).hexdigest()
    assert a == first["b"]
    assert first["collapsed"]["revision"] > a["revision"]
    assert first["collapsed"]["digest"] == a["digest"]
    assert first["collapsed"]["rebuild"] != a["rebuild"]  # the collapse is kept for a rebuild
    assert first["reopened"]["digest"] == a["digest"]
    assert first["inside"] == first["reopened"]  # a Transaction's working copy is never dumped
    assert first["edited"]["digest"] != a["digest"]
    assert a["app_version"] and a["compat_profile"] == "painter-12.1-api-0.3.7"
    assert set(a["resource_hashes"]) == set(a["recipe"]["resources"])
    assert len(a["resource_hashes"]) == 2  # the mesh and the mask image
    layers = a["recipe"]["texture_sets"][0]["stacks"][0]["root_layers"]
    assert [layer["name"] for layer in layers] == ["group", "base"]
    assert all(
        len(channel["base"]) == 3
        for channel in a["recipe"]["texture_sets"][0]["stacks"][0]["channels"].values()
    )

    # A new process (session) and the facade's selection.
    second = ok(
        facade("""
        project.open(WORK + "/recipe.uzp")
        before = uzpainter.project.dump_recipe()["digest"]
        node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
        ls.set_selected_nodes([node])
        selected = len(ls.get_selected_nodes(ts.get_active_stack()))
        result = {"before": before, "after": uzpainter.project.dump_recipe()["digest"],
                  "selected": selected}
        """)
    )
    assert second["before"] == first["edited"]["digest"]
    assert second["after"] == second["before"] and second["selected"] == 1


def test_rebuild_from_recipe_exports_byte_identical_files(run: Run, tmp_path: Path) -> None:
    """2.5, 3.4: a project rebuilt from its dump and the stored resources (one transaction, a new
    untitled project) has the dump's digest and rebuild block and exports byte-identical files; a
    missing or wrong resource file, an open project and a release gap are refused before anything
    is created."""
    result = ok(
        run(
            script("""
        child.set_name("child")
        original_files = export_files(WORK + "/original")
        dump = project.dump_recipe()
        listed = save_resources(dump, [PLANE, IMAGES + "/mask-left-half.png"], WORK + "/res")
        json.dump(dump, open(WORK + "/dump.json", "w"))
        open_refused = raises(project.rebuild_from_recipe, dump, WORK + "/res")
        project.close()

        os.makedirs(WORK + "/partial", exist_ok=True)
        missing = raises(project.rebuild_from_recipe, dump, WORK + "/partial")
        os.makedirs(WORK + "/wrong", exist_ok=True)
        for name in listed:
            shutil.copyfile(WORK + "/res/" + name, WORK + "/wrong/" + name)
        mesh_sha = dump["recipe"]["mesh"]["resource"]
        wrong_name = [n for n in listed if n.startswith(mesh_sha)][0]
        open(WORK + "/wrong/" + wrong_name, "ab").write(b" ")
        wrong = raises(project.rebuild_from_recipe, dump, WORK + "/wrong")
        nothing_open = project.is_open()

        project.rebuild_from_recipe(WORK + "/dump.json", WORK + "/res")
        rebuilt = project.dump_recipe()
        rebuilt_files = export_files(WORK + "/rebuilt")
        names = [n.get_name() for n in ls.get_root_layer_nodes(ts.get_active_stack())]
        project.close()
        result = {"dump": dump, "rebuilt": rebuilt, "listed": listed,
                  "original": original_files, "rebuilt_files": rebuilt_files,
                  "open_refused": open_refused, "missing": missing, "wrong": wrong,
                  "nothing_open": nothing_open, "names": names}
        """)
        )
    )
    dump, rebuilt = result["dump"], result["rebuilt"]
    assert rebuilt["digest"] == dump["digest"]
    assert rebuilt["recipe"] == dump["recipe"] and rebuilt["rebuild"] == dump["rebuild"]
    assert result["names"] == ["group", "base"]
    assert result["original"] and set(result["original"]) == set(result["rebuilt_files"])
    for relative, path in result["original"].items():
        assert Path(result["rebuilt_files"][relative]).read_bytes() == Path(path).read_bytes(), (
            relative
        )
    assert (
        result["open_refused"].startswith("ProjectError")
        and "already open" in result["open_refused"]
    )
    assert result["missing"].startswith("ProjectError") and "is not in" in result["missing"]
    assert (
        result["wrong"].startswith("ProjectError") and "does not hold the bytes" in result["wrong"]
    )
    assert result["nothing_open"] is False


def external_gltf(folder: Path) -> Path:
    """The plane as a `.gltf` whose buffer is the external file `plane.bin`."""
    corners = [(-10.0, 0.0, 10.0), (10.0, 0.0, 10.0), (10.0, 0.0, -10.0), (-10.0, 0.0, -10.0)]
    primitive = Primitive(
        positions=corners,
        indices=[0, 1, 2, 0, 2, 3],
        normals=[(0.0, 1.0, 0.0)] * 4,
        uvs=[(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)],
        material=0,
    )
    document, blob = gltf_document(
        [[primitive]], [GltfNode("uzp_plane", mesh=0)], ["uzp_plane"], [0]
    )
    document["buffers"][0]["uri"] = "plane.bin"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plane.bin").write_bytes(blob)
    path = folder / "plane.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_gltf_with_an_external_buffer_is_stored_and_rebuilt_without_its_folder(
    run: Run, tmp_path: Path
) -> None:
    """SAV-01, 2.5: a glTF's external buffer is stored with the mesh and listed in its import
    report and in the recipe's resources; after the source folder is gone, the reopened project
    exports and its dump rebuilds from the stored resources alone, to byte-identical files."""
    mesh = external_gltf(tmp_path / "source")
    bin_sha = hashlib.sha256((tmp_path / "source" / "plane.bin").read_bytes()).hexdigest()
    first = ok(
        run(f"""
        project.create({mesh.as_posix()!r}, project.Settings(default_texture_resolution=256))
        fill = ls.insert_fill(top(ts.get_active_stack()))
        fill.active_channels = {{CT.Height}}
        fill.set_source(CT.Height, cm.Color(0.25, 0.25, 0.25, "Raw"))
        project.save_as(WORK + "/gltf.uzp")
        project.close()
        result = None
        """)
    )
    assert first is None
    for name in ("plane.gltf", "plane.bin"):
        (tmp_path / "source" / name).rename(tmp_path / name)
    second = ok(
        run(
            f"""
        import hashlib, shutil
        def export_files(folder):
            config = {CONFIG_EXPRESSION}
            config["exportPath"] = folder
            out = export.export_project_textures(config)
            return {{f["relative_path"]: f["path"] for f in out["files"]}}
        project.open(WORK + "/gltf.uzp")
        original = export_files(WORK + "/original")
        receipt = json.load(open(WORK + "/original/generations/000001/receipt.json"))
        dump = project.dump_recipe()
        project.close()
        os.makedirs(WORK + "/res", exist_ok=True)
        for name in ("plane.gltf", "plane.bin"):
            data = open(WORK + "/" + name, "rb").read()
            open(WORK + "/res/" + hashlib.sha256(data).hexdigest(), "wb").write(data)
        project.rebuild_from_recipe(dump, WORK + "/res")
        rebuilt = export_files(WORK + "/rebuilt")
        digest = project.dump_recipe()["digest"]
        project.close()
        result = {{"dump": dump, "original": original, "rebuilt": rebuilt, "digest": digest,
                   "receipt_hashes": receipt["resource_hashes"]}}
        """
        )
    )
    dump: dict[str, Any] = second["dump"]
    report = dump["recipe"]["mesh"]["import_report"]
    assert report["external_files"] == [
        {"uri": "plane.bin", "sha256": bin_sha, "size": (tmp_path / "plane.bin").stat().st_size}
    ]
    assert bin_sha in dump["resource_hashes"]
    # The export receipt names the buffer it read with the mesh (ReceiptInvalidated sees it).
    assert {dump["recipe"]["mesh"]["resource"], bin_sha} <= set(second["receipt_hashes"])
    assert second["digest"] == dump["digest"]
    assert second["original"] and set(second["original"]) == set(second["rebuilt"])
    for relative, path in second["original"].items():
        assert Path(second["rebuilt"][relative]).read_bytes() == Path(path).read_bytes(), relative
