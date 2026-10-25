"""Observed default colour spaces of bitmap sources (`python/uzpainter_facade/bitmap_defaults.py`).

The pure module is checked on the host (no native module). The facade replays the setup steps of
the two admitted R-322 probes (`tier0/api-probes/source-bitmap-defaults-unreal-legacy` and
`-ocio`: same template, channels, authored images, mesh maps, Normal blending and opacity) and
compares every `SourceBitmap.get_color_space` readback with both recordings, typed, after a save
and reopen too. Messages carry steps and digests only; recorded values stay private.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.python.conftest import Run
from tests.python.recorded_probe import ENVELOPE, recorded_readbacks
from tests.python.test_snapshot_capture_replay import recorder_code
from tools.parity.feasibility import png
from tools.parity.schemas import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "python"))
from uzpainter_facade import bitmap_defaults as bd

PROBES = ("source-bitmap-defaults-unreal-legacy", "source-bitmap-defaults-unreal-ocio")
# Painter's substance config where Painter installs it; hashed by the facade, never copied.
PAINTER_OCIO_CONFIG = Path(
    r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\ocio\substance\config.ocio"
)
# The probes' get_source readbacks (36 over both recordings and sessions) are out of this
# test's scope: only the 9 typed get_color_space readbacks per recording are compared.
OUT_OF_SCOPE_READS = ("FillLayerNode.get_source",)


def manifest(name: str) -> dict[str, Any]:
    path = ENVELOPE / "manifests/tier0/api-probes" / f"{name}.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def image(name: str, input_id: str) -> bytes:
    inputs = {i["input_id"]: i for i in manifest(name)["inputs"]}
    path: str = inputs[input_id]["path"]
    return (REPO_ROOT / path).read_bytes()


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def test_describe_png_is_strict() -> None:
    data = image(PROBES[0], "field-a")
    described = bd.describe_png(data)
    assert described == bd.PngDescriptor(
        256, 256, 16, 2, 0, 0, 0, ("IHDR", "IDAT", "IEND"), scanlines_verified=True
    )
    grey = bd.describe_png(image(PROBES[0], "grey-a"))
    assert grey is not None and grey.color_type == 0
    ihdr_end = 8 + 12 + 13
    with_iccp = data[:ihdr_end] + chunk(b"iCCP", b"x\x00\x00") + data[ihdr_end:]
    iccp = bd.describe_png(with_iccp)
    assert iccp is not None and iccp.chunks == ("IHDR", "iCCP", "IDAT", "IEND")
    broken = bytearray(data)
    broken[ihdr_end - 1] ^= 0xFF  # the IHDR CRC
    assert bd.describe_png(bytes(broken)) is None
    assert bd.describe_png(data[:-12]) is None  # no IEND
    assert bd.describe_png(data[:-12] + chunk(b"IEND", b"x")) is None  # IEND with a payload
    assert bd.describe_png(b"not a png") is None
    # Valid chunks and CRCs, but not the expected scanlines: never the observed domain.
    head, idat = data[:ihdr_end], zlib.decompress(data[ihdr_end + 8 : -16])
    tail = chunk(b"IEND", b"")
    variants = {
        "corrupt zlib": bytes([0x78, 0x9C]) + bytes([0xFF]) * 40,
        "trailing data": zlib.compress(idat) + bytes([0]),
        "short stream": zlib.compress(idat[:-1]),
        "filter byte 5": zlib.compress(bytes([5]) + idat[1:]),
    }
    context = bd.DefaultContext(
        "legacy", None, "pbr-metallic-roughness-alpha-blend", "BaseColor", "sRGB8"
    )
    for label, stream in variants.items():
        variant = bd.describe_png(head + chunk(b"IDAT", stream) + tail)
        assert variant is not None and not variant.scanlines_verified, label
        assert bd.lookup(context, variant) is None, label
    rebuilt = bd.describe_png(head + chunk(b"IDAT", zlib.compress(idat)) + tail)
    assert rebuilt is not None and rebuilt.scanlines_verified


def test_lookup_hits_only_the_exact_observed_context() -> None:
    rgb = bd.describe_png(image(PROBES[0], "field-a"))
    grey = bd.describe_png(image(PROBES[0], "grey-a"))
    legacy = bd.DefaultContext(
        "legacy", None, "pbr-metallic-roughness-alpha-blend", "BaseColor", "sRGB8"
    )
    ocio = bd.DefaultContext("ocio", bd.PAINTER_OCIO_CONFIG_SHA256, "default", "Height", "L16F")
    hit = bd.lookup(legacy, rgb)
    assert hit is not None and bd.native_tag(hit, "legacy") == f"{hit.kind}.{hit.name}"
    assert bd.lookup(ocio, grey) is not None
    misses = [
        (legacy, grey),  # a grey bitmap on BaseColor: not observed here
        (bd.DefaultContext("legacy", None, "default", "BaseColor", "sRGB8"), rgb),  # template
        (bd.DefaultContext("ocio", "0" * 64, "default", "Height", "L16F"), grey),  # config
        (
            bd.DefaultContext(
                "legacy", None, "pbr-metallic-roughness-alpha-blend", "BaseColor", "RGB8"
            ),
            rgb,
        ),
        (legacy, None),
    ]
    for context, descriptor in misses:
        assert bd.lookup(context, descriptor) is None
    eight_bit = bd.PngDescriptor(256, 256, 8, 2, 0, 0, 0, ("IHDR", "IDAT", "IEND"), True)
    interlaced = bd.PngDescriptor(256, 256, 16, 2, 0, 0, 1, ("IHDR", "IDAT", "IEND"), True)
    for descriptor in (eight_bit, interlaced):
        assert bd.lookup(legacy, descriptor) is None
    assert bd.native_tag(bd.SpaceIdentity("str", "sRGB"), "ocio") == "OcioColorSpace.sRGB"
    assert bd.native_tag(bd.SpaceIdentity("str", "sRGB"), "legacy") == "sRGB"
    assert bd.native_tag(bd.SpaceIdentity("str", "Rec709"), "ocio") == "Rec709"
    assert bd.native_tag(bd.SpaceIdentity("DataColorSpace", "Data"), "ocio") == "Data"


def replay_script(name: str) -> str:
    """The facade replay of a probe's setup steps, then fresh get_color_space reads, a save,
    close and reopen, and the same reads (recordings r1 and r2)."""
    data = manifest(name)
    inputs = {i["input_id"]: i for i in data["inputs"]}
    steps = {s["step"]: s for s in data["instruction_sequence"]["steps"]}
    lines = ["import os", "from uzpainter_facade.textureset import _CHANNEL_ALIASES"]
    lines.append("def ch(name): return getattr(CT, _CHANNEL_ALIASES.get(name, name))")
    reads: list[tuple[str, str]] = []
    ocio = any(s["name"] == "OCIO" for s in data["applied_settings"])
    lines.append("os.environ.pop('OCIO', None); os.environ.pop('PAINTER_ACE_CONFIG', None)")
    if ocio:
        lines.append(f"os.environ['OCIO'] = {str(PAINTER_OCIO_CONFIG)!r}")
    for step in sorted(steps):
        s, args = steps[step], steps[step]["args"]
        call = s["call"]
        if call.endswith("project.create"):
            mesh = (REPO_ROOT / inputs[args["mesh"]]["path"]).as_posix()
            template = "None"
            if "template" in args:
                # The facade checks the template file by its name only: an empty file of that
                # name directly in the existing WORK folder (no directory is created).
                name_ = args["template"].rsplit("/", 1)[-1]
                lines.append(f"open(WORK + '/' + {name_!r}, 'w').close()")
                template = f"WORK + '/' + {name_!r}"
            lines.append(
                f"project.create({mesh!r}, template_file_path={template}, "
                "settings=project.Settings("
                f"normal_map_format=project.NormalMapFormat.{args['normal_map_format']}, "
                f"default_texture_resolution={args['default_texture_resolution']}))"
            )
            lines.append("stack = ts.get_active_stack()")
        elif call.endswith("Stack.add_channel"):
            lines.append(
                f"stack.add_channel(ch({args['channel']!r}), ts.ChannelFormat.{args['format']})"
            )
        elif call.endswith("import_project_resource"):
            path = (REPO_ROOT / inputs[args["input"]]["path"]).as_posix()
            lines.append(
                f"r{step} = resource.import_project_resource("
                f"{path!r}, resource.Usage.{args['usage']})"
            )
        elif call.endswith("set_mesh_map_resource"):
            lines.append(
                f"ts.all_texture_sets()[0].set_mesh_map_resource(ts.MeshMapUsage.{args['usage']}, "
                f"r{args['resource_step']}.identifier())"
            )
        elif call.endswith("insert_fill"):
            lines.append("node = ls.insert_fill(ls.InsertPosition.from_textureset_stack(stack))")
        elif call.endswith("active_channels"):
            lines.append(f"node.active_channels = {{ch(c) for c in {args['channels']!r}}}")
        elif call.endswith("FillLayerNode.set_source"):
            lines.append(
                f"node.set_source(ch({args['channel']!r}), r{args['resource_step']}.identifier())"
            )
        elif call.endswith("set_blending_mode"):
            lines.append(
                f"node.set_blending_mode(ls.BlendingMode.{args['blending_mode']}, "
                f"ch({args['channel']!r}))"
            )
        elif call.endswith("set_opacity"):
            lines.append(f"node.set_opacity({args['opacity']!r}, ch({args['channel']!r}))")
        elif call.endswith("get_color_space"):
            reads.append((f"s{step}", args["channel"]))
        elif not call.endswith(OUT_OF_SCOPE_READS):
            # An unknown step would change the setup: refused, never skipped.
            raise ValueError(f"step {step}: {call} is not replayed by this test")
    lines.append(f"READS = {reads!r}")
    # The recorder's own typed serializer (painter_side.colour_space_value), verbatim.
    lines.append("import substance_painter")
    lines.append("from typing import Any")
    lines.append(recorder_code(("colour_space_value",)))
    lines.append(
        """
def read_all():
    root = ls.get_root_layer_nodes(ts.get_active_stack())[0]
    return {key: {"value": colour_space_value(root.get_source(ch(channel)).get_color_space())}
            for key, channel in READS}

first = read_all()
project.save_as(WORK + "/defaults.spp")
project.close()
project.open(WORK + "/defaults.spp")
second = read_all()
project.close()
os.environ.pop("OCIO", None)
result = [first, second]
"""
    )
    return "\n".join(lines)


@pytest.mark.parametrize("name", PROBES)
def test_facade_defaults_equal_the_recorded_painter_defaults(
    private_facade: Run, name: str
) -> None:
    if name.endswith("ocio") and not PAINTER_OCIO_CONFIG.is_file():
        pytest.skip("Painter's substance OCIO config is not installed on this machine")
    recordings = recorded_readbacks(name)
    report = private_facade(replay_script(name))
    if report["status"] != "ok":
        error = report.get("error") or {}
        if (
            name.endswith("ocio")
            and error.get("type") == "NotYetSupported"
            and "decision 190" in str(error.get("message"))
        ):
            # A real, separate blocker, not a pass: the evaluator refuses a 16-bit colour bitmap
            # under OCIO (decision 190), so this exact replay cannot run yet.
            pytest.xfail(
                "blocked: 16-bit colour bitmaps under OCIO are a release gap (decision 190)"
            )
        pytest.fail(f"replay script failed: {error.get('type')} (details kept privately)", False)
    observed = report["result"]
    steps = {s["step"]: s for s in manifest(name)["instruction_sequence"]["steps"]}
    reads = {f"s{step}" for step, s in steps.items() if s["call"].endswith("get_color_space")}
    # Exactly the 9 reads per recording on both sides before any comparison: no missing or empty
    # read can pass.
    recorded_reads = [
        {k.split("/", 1)[0]: v for k, v in r.items() if k.endswith("/get_color_space")}
        for r in recordings
    ]
    if len(reads) != 9 or any(set(r) != reads for r in recorded_reads):
        pytest.fail("the recordings do not hold exactly the probe's 9 get_color_space reads", False)
    if (
        not isinstance(observed, list)
        or len(observed) != 2
        or any(not isinstance(r, dict) or set(r) != reads for r in observed)
    ):
        pytest.fail("the replay did not return exactly the 9 reads of each recording", False)
    problems: list[str] = []
    for condition, (recorded, actual) in enumerate(zip(recorded_reads, observed, strict=True), 1):
        for key in sorted(reads):
            want, got = recorded[key], actual[key]
            if got != want:
                channel = steps[int(key[1:])]["args"]["channel"]
                digest = hashlib.sha256(json.dumps(want, sort_keys=True).encode()).hexdigest()[:10]
                problems.append(f"r{condition} {key} {channel}: recorded {digest} differs")
    if problems:
        pytest.fail("\n".join([f"{len(problems)} differences:", *problems]), pytrace=False)


OCIO_STRING_ROUNDTRIP = """
import os
os.environ.pop('PAINTER_ACE_CONFIG', None)
os.environ['OCIO'] = CONFIG
stack = create(128)
os.environ.pop('OCIO', None)
image = resource.import_project_resource(WORK + '/rgb8.png', resource.Usage.TEXTURE)
node = ls.insert_fill(top(stack))
node.active_channels = {CT.BaseColor}
node.set_source(CT.BaseColor, image.identifier())
native_node = uzpainter.layerstack.get_root_layer_nodes(uzpainter.textureset.get_active_stack())[0]

def read():
    space = node.get_source(CT.BaseColor).get_color_space()
    return [type(space).__name__, space if isinstance(space, str) else space.name,
            native_node.get_source(CT.BaseColor).get_color_space()]

out = {}
node.get_source(CT.BaseColor).set_color_space("sRGB")
out["string"] = read()
node.get_source(CT.BaseColor).set_color_space(cm.GenericColorSpace.sRGB)
out["generic"] = read()
node.get_source(CT.BaseColor).set_color_space("sRGB")
project.save_as(WORK + "/ocio-string.spp")
project.close()
project.open(WORK + "/ocio-string.spp")
node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
native_node = uzpainter.layerstack.get_root_layer_nodes(uzpainter.textureset.get_active_stack())[0]
out["reopened"] = read()
project.close()
result = out
"""


def test_ocio_configuration_string_keeps_its_identity(facade: Run, tmp_path: Path) -> None:
    """Under the pinned OCIO profile, the configuration string "sRGB" and GenericColorSpace.sRGB
    are bound with different native tags (the qualified one evaluates as the plain one; the
    evaluator test checks that) and each reads back as itself, also after save and reopen. Authored
    8-bit RGB bitmap at the texture set's size (the Session O domain, decision 190)."""
    if not PAINTER_OCIO_CONFIG.is_file():
        pytest.skip("Painter's substance OCIO config is not installed on this machine")
    codes = np.arange(128 * 128 * 3, dtype=np.int64).reshape(128, 128, 3) % 256
    (tmp_path / "rgb8.png").write_bytes(png.encode(codes, 8))
    report = facade(f"CONFIG = {str(PAINTER_OCIO_CONFIG)!r}\n" + OCIO_STRING_ROUNDTRIP)
    assert report["status"] == "ok", (report.get("error") or {}).get("message")
    assert report["result"] == {
        "string": ["str", "sRGB", "OcioColorSpace.sRGB"],
        "generic": ["GenericColorSpace", "sRGB", "sRGB"],
        "reopened": ["str", "sRGB", "OcioColorSpace.sRGB"],
    }


CORRUPT_DESCRIPTORS = """
from uzpainter_facade import resource as facade_resource
native_resource = uzpainter.resource
metadata = uzpainter.project.Metadata(facade_resource.RESOURCE_METADATA)
key = facade_resource.DESCRIPTOR_KEY
create(128)
image = resource.import_project_resource(WORK + '/rgb8.png', resource.Usage.TEXTURE)
import hashlib
sha = hashlib.sha256(open(WORK + '/rgb8.png', 'rb').read()).hexdigest()
good = metadata.get(key)
record = dict(good[sha])
corruptions = {
    "not_a_map": "corrupt",
    "chunks_string": {**good, sha: {**record, "chunks": "IHDRIDATIEND"}},
    "chunks_dict": {**good, sha: {**record, "chunks": {"IHDR": 0, "IDAT": 1, "IEND": 2}}},
}
node = ls.insert_fill(top(ts.get_active_stack()))
out = {"recorded": sorted(good) == [sha]}
for case, value in corruptions.items():
    metadata.set(key, value)
    before = uzpainter.project.revision()
    held = len(native_resource.list_project_resources())
    out[case] = {
        "set_source": raises(node.set_source, CT.BaseColor, image.identifier()),
        "inactive": CT.BaseColor not in node.active_channels,
        "import": raises(resource.import_project_resource, WORK + '/other.png',
                         resource.Usage.TEXTURE),
        "no_new_resource": len(native_resource.list_project_resources()) == held,
        "unchanged": uzpainter.project.revision() == before,
    }
metadata.set(key, good)
node.set_source(CT.BaseColor, image.identifier())
out["restored"] = CT.BaseColor in node.active_channels
project.close()
result = out
"""


def test_corrupt_descriptor_map_refuses_before_any_change(facade: Run, tmp_path: Path) -> None:
    """A stored descriptor map that is no map, or a record whose chunks are a string or a mapping
    (which would pass a per-item check after conversion), is an error, never a miss: `set_source`
    refuses before its implicit channel activation, and an import refuses before the native import
    (no new resource, no new revision). A valid map binds again afterwards."""
    codes = np.arange(128 * 128 * 3, dtype=np.int64).reshape(128, 128, 3) % 256
    (tmp_path / "rgb8.png").write_bytes(png.encode(codes, 8))
    (tmp_path / "other.png").write_bytes(png.encode((codes + 1) % 256, 8))
    report = facade(CORRUPT_DESCRIPTORS)
    assert report["status"] == "ok", (report.get("error") or {}).get("message")
    result = report["result"]
    assert result.pop("recorded") is True
    assert result.pop("restored") is True
    for case, outcome in result.items():
        for call in ("set_source", "import"):
            assert outcome[call] is not None and outcome[call].startswith("ValueError: "), (
                case,
                call,
                outcome[call],
            )
        assert outcome["inactive"] and outcome["no_new_resource"] and outcome["unchanged"], case
