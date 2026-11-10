"""The Unreal Engine 5.6 side of the consumer fixture (`tools/consumers/unreal.py`).

It runs inside `UnrealEditor-Cmd.exe <project> -run=pythonscript -script=<this file>`, the
editor's documented Python commandlet (Python Editor Script Plugin), and reads the request JSON
the host wrote, named by the environment variable `UZP_UE_REQUEST`. It imports only through the
editor's documented asset tools (`unreal.AssetImportTask`, `AssetTools.import_asset_tasks`), so
UE 5.6 picks its own importer for each file, exactly as an artist's drag-and-drop does.

For each staged file it records the texture's settings as UE 5.6 imported them, then applies the
binding the request states (sRGB, compression settings, green channel) and records them again,
exports the texture's source through UE's own exporter (`unreal.AssetExportTask`), and builds one
material whose texture samples bind BaseColor, the ORM's R, G and B, the Normal and the Emissive.
A request without bindings or material (`consume_generation`) only imports and exports.
Every outcome, failures included, is written to the request's `result` file; the host judges it.
Standard library and `unreal` only.
"""

from __future__ import annotations

import json
import os
import traceback
from typing import Any

import unreal  # type: ignore[import-not-found]  # only inside the editor

SAMPLERS = {
    "color": "SAMPLERTYPE_COLOR",
    "linear_color": "SAMPLERTYPE_LINEAR_COLOR",
    "normal": "SAMPLERTYPE_NORMAL",
    "masks": "SAMPLERTYPE_MASKS",
}
PROPERTIES = {
    "base_color": "MP_BASE_COLOR",
    "ambient_occlusion": "MP_AMBIENT_OCCLUSION",
    "roughness": "MP_ROUGHNESS",
    "metallic": "MP_METALLIC",
    "normal": "MP_NORMAL",
    "emissive_color": "MP_EMISSIVE_COLOR",
}


def _name(value: Any) -> str:
    """An enum member's name (`TextureCompressionSettings.TC_MASKS` -> `TC_MASKS`)."""
    return str(value).rsplit(".", 1)[-1].split(":")[0].strip("<> ")


def _settings(texture: Any) -> dict[str, Any]:
    return {
        "class": texture.get_class().get_name(),
        "srgb": bool(texture.get_editor_property("srgb")),
        "compression": _name(texture.get_editor_property("compression_settings")),
        "flip_green_channel": bool(texture.get_editor_property("flip_green_channel")),
        "lod_group": _name(texture.get_editor_property("lod_group")),
        "size": [int(texture.blueprint_get_size_x()), int(texture.blueprint_get_size_y())],
    }


def _import(path: str, destination: str, name: str, factory: Any = None) -> Any:
    """The imported object paths and the loaded texture (None when UE imported nothing); a
    `factory` (the legacy `TextureFactory`) replaces UE's default importer."""
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", path)
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", True)
    if factory is not None:
        task.set_editor_property("factory", factory)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    paths = list(task.get_editor_property("imported_object_paths") or [])
    if not paths:
        return [], None
    asset = unreal.EditorAssetLibrary.load_asset(paths[0])
    if asset is None:
        raise RuntimeError(f"UE could not load the imported {paths[0]}")
    return paths, asset


def _bind(texture: Any, binding: dict[str, Any]) -> None:
    texture.set_editor_property("srgb", bool(binding["srgb"]))
    texture.set_editor_property(
        "compression_settings",
        getattr(unreal.TextureCompressionSettings, binding["compression"]),
    )
    texture.set_editor_property("flip_green_channel", bool(binding["flip_green_channel"]))
    if not unreal.EditorAssetLibrary.save_loaded_asset(texture, only_if_is_dirty=False):
        raise RuntimeError(f"UE could not save {texture.get_path_name()}")


def _export_source(texture: Any, filename: str) -> bool:
    task = unreal.AssetExportTask()
    task.set_editor_property("object", texture)
    task.set_editor_property("filename", filename)
    task.set_editor_property("automated", True)
    task.set_editor_property("prompt", False)
    task.set_editor_property("replace_identical", True)
    return bool(unreal.Exporter.run_asset_export_task(task))


def _material(request: dict[str, Any], textures: dict[str, Any]) -> dict[str, Any]:
    spec = request["material"]
    path = f"{request['destination']}/{spec['name']}"
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(
        spec["name"], request["destination"], unreal.Material, unreal.MaterialFactoryNew()
    )
    library = unreal.MaterialEditingLibrary
    samples: dict[str, Any] = {}
    for row, sample in enumerate(spec["samples"]):
        expression = library.create_material_expression(
            material, unreal.MaterialExpressionTextureSample, -600, row * 300
        )
        expression.set_editor_property("texture", textures[sample["slot"]])
        expression.set_editor_property(
            "sampler_type", getattr(unreal.MaterialSamplerType, SAMPLERS[sample["sampler"]])
        )
        samples[sample["slot"]] = expression
    for link in spec["links"]:
        connected = library.connect_material_property(
            samples[link["slot"]],
            link["output"],
            getattr(unreal.MaterialProperty, PROPERTIES[link["property"]]),
        )
        if not connected:
            raise RuntimeError(f"UE refused the link {link}")
    library.recompile_material(material)
    if not unreal.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False):
        raise RuntimeError(f"UE could not save {path}")
    read_back = []
    for link in spec["links"]:
        prop = getattr(unreal.MaterialProperty, PROPERTIES[link["property"]])
        node = library.get_material_property_input_node(material, prop)
        output = library.get_material_property_input_node_output_name(material, prop)
        texture = node.get_editor_property("texture") if node is not None else None
        read_back.append(
            {
                "property": link["property"],
                "texture": texture.get_path_name() if texture is not None else None,
                "output": str(output),
                "sampler": _name(node.get_editor_property("sampler_type")) if node else None,
            }
        )
    return {"path": material.get_path_name(), "links": read_back}


def main() -> None:
    request_path = os.environ["UZP_UE_REQUEST"]
    with open(request_path, encoding="utf-8") as stream:
        request = json.load(stream)
    result: dict[str, Any] = {
        "schema": "uzpainter/unreal-import-result/1",
        "engine_version": str(unreal.SystemLibrary.get_engine_version()),
        "destination": request["destination"],
        "textures": {},
    }
    try:
        destination = request["destination"]
        if unreal.EditorAssetLibrary.does_directory_exist(destination):
            unreal.EditorAssetLibrary.delete_directory(destination)
        textures: dict[str, Any] = {}
        refused = []
        for item in request["files"]:
            paths, texture = _import(item["path"], destination, item["asset"])
            entry: dict[str, Any] = {"file": os.path.basename(item["path"])}
            if texture is None:
                # UE's default importer imported nothing; its legacy TextureFactory states why in
                # the log (the host reads it) and never stands in for the default importer.
                unreal.log_warning(f"UZFIXTURE refused by the default importer: {item['path']}")
                retried, _ = _import(
                    item["path"], destination, item["asset"] + "_legacy", unreal.TextureFactory()
                )
                entry.update(
                    imported_object_paths=[], legacy_factory_paths=[str(p) for p in retried]
                )
                result["textures"][item["slot"]] = entry
                refused.append(item["slot"])
                continue
            entry["imported_object_paths"] = [str(p) for p in paths]
            entry["as_imported"] = _settings(texture)
            if "binding" in item:
                _bind(texture, item["binding"])
                entry["as_bound"] = _settings(texture)
            exported = os.path.join(request["export_dir"], item["asset"] + ".png")
            entry["source_export"] = exported if _export_source(texture, exported) else None
            result["textures"][item["slot"]] = entry
            textures[item["slot"]] = texture
        if refused:
            result["status"] = "refused"
            result["refused"] = refused
        else:
            if request.get("material"):
                result["material"] = _material(request, textures)
            result["status"] = "imported"
    except Exception:  # every failure is reported to the host, never swallowed
        result["status"] = "error"
        result["error"] = traceback.format_exc()
    with open(request["result"], "w", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)


main()
