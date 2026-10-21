"""No brush-stroke symbol anywhere UzPainter exposes operations (task phase4.1_nodes-paint-layers
item 3.7; owner Q5, decisions 019 and 348).

Paint layers receive content only through typed bitmap operations: no stroke engine is built and
no stroke operation exists. The test enumerates, live, every public name reachable from the native
`uzpainter` module, the `substance_painter` facade and `substance_painter_plugins` (modules,
classes, functions, members and enum values, recursively), and the MCP tool list the build
registers (`tools/capabilities/mcp-tools.json`, which `tests/supervisor/test_operation_matrix.py`
keeps equal to a live worker's listing): tool names, the operations they declare and the argument
values they gate. CPU only.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tests.python.conftest import REPO_ROOT, Run

STROKE = re.compile(r"stroke", re.IGNORECASE)

SURFACE = """
import enum, importlib, inspect, pkgutil, types

def public(name):
    return not name.startswith("_")

seen = set()
names = []

def walk(path, obj, depth):
    if id(obj) in seen or depth > 6:
        return
    seen.add(id(obj))
    for name in dir(obj):
        if not public(name):
            continue
        try:
            member = getattr(obj, name)
        except Exception:
            continue
        names.append(path + "." + name)
        if isinstance(member, types.ModuleType):
            if member.__name__.split(".")[0] in ROOTS:
                walk(member.__name__, member, depth + 1)
        elif inspect.isclass(member) and getattr(member, "__module__", "").split(".")[0] in OWNERS:
            walk(path + "." + name, member, depth + 1)

ROOTS = {"uzpainter", "substance_painter", "substance_painter_plugins"}
OWNERS = ROOTS | {"_uzpainter", "uzpainter_facade"}
for root in sorted(ROOTS):
    module = importlib.import_module(root)
    walk(root, module, 0)
    for info in pkgutil.walk_packages(getattr(module, "__path__", []), root + "."):
        sub = importlib.import_module(info.name)
        walk(info.name, sub, 1)
result = sorted(set(names))
"""


def test_no_stroke_symbol_in_the_python_apis(facade: Run) -> None:
    report = facade(SURFACE)
    assert report["status"] == "ok", report.get("error", report)
    names: list[str] = report["result"]
    roots = {name.split(".")[0] for name in names}
    assert roots == {"uzpainter", "substance_painter", "substance_painter_plugins"}, roots
    assert "substance_painter.layerstack.insert_paint" in names  # the walk reaches the layer stack
    assert "uzpainter.layerstack.PaintLayerNode" in names
    assert [name for name in names if STROKE.search(name)] == []


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*strings(k), *strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def test_no_stroke_operation_in_the_mcp_tool_list() -> None:
    listing = json.loads(
        (REPO_ROOT / "tools" / "capabilities" / "mcp-tools.json").read_text(encoding="utf-8")
    )
    tools = listing["tools"]
    assert any(tool["name"] == "layer_insert" for tool in tools)
    assert [s for tool in tools for s in strings(tool) if STROKE.search(s)] == []
