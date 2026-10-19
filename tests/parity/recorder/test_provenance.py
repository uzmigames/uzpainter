"""Provenance test (task 3.1): documented `substance_painter` symbols only, no private
attribute, no community MCP bridge (spec `oracle-recorder`, Documented-API-only recording)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.parity.recorder import vocabulary
from tools.parity.recorder.job import STATE_CALLS
from tools.parity.recorder.provenance import (
    check_files,
    check_source,
    documented_symbols,
    inventory_problems,
    recorder_sources,
)

PYTHON_DOC_ENV = "UZP_PAINTER_PYTHON_DOC"
DEFAULT_INVENTORY = Path(
    r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\python-doc\objects.inv"
)

PAINTER_IMPORTS = "import substance_painter.project\nimport substance_painter.layerstack\n"


def problems_of(source: str) -> list[str]:
    return [str(p) for p in check_source(source, "candidate.py")]


def test_recorder_sources_are_documented_api_only() -> None:
    sources = recorder_sources()
    assert any(p.name == "painter_side.py" for p in sources)
    assert [str(p) for p in check_files(sources)] == []


def test_private_attribute_of_a_painter_object_is_rejected_and_named() -> None:
    source = PAINTER_IMPORTS + (
        "def f():\n"
        "    node = substance_painter.layerstack.insert_fill(None)\n"
        "    return node._handle\n"
    )
    problems = problems_of(source)
    assert len(problems) == 1
    assert "_handle" in problems[0]


def test_private_module_attribute_is_rejected_and_named() -> None:
    problems = problems_of(PAINTER_IMPORTS + "x = substance_painter.project._internal_call()\n")
    assert any("_internal_call" in p for p in problems)


def test_undocumented_symbol_is_rejected_and_named() -> None:
    problems = problems_of(PAINTER_IMPORTS + "substance_painter.project.secret_reset()\n")
    assert problems == [
        "candidate.py:3: undocumented substance_painter symbol "
        "substance_painter.project.secret_reset"
    ]


def test_undocumented_symbol_through_an_alias_is_rejected() -> None:
    source = PAINTER_IMPORTS + "project = substance_painter.project\nproject.hidden()\n"
    assert any("substance_painter.project.hidden" in p for p in problems_of(source))


def test_undocumented_member_of_a_returned_object_is_rejected() -> None:
    source = PAINTER_IMPORTS + (
        "node = substance_painter.layerstack.insert_fill(None)\nnode.raw_engine_handle()\n"
    )
    assert any(".raw_engine_handle" in p for p in problems_of(source))


def test_undocumented_symbol_in_the_instruction_vocabulary_is_rejected() -> None:
    problems = problems_of('CALL = "substance_painter.layerstack.Node.set_secret"\n')
    assert any("substance_painter.layerstack.Node.set_secret" in p for p in problems)


def test_dynamic_attribute_access_is_rejected() -> None:
    source = PAINTER_IMPORTS + 'getattr(substance_painter.project, "close")()\n'
    assert any("getattr" in p for p in problems_of(source))


@pytest.mark.parametrize(
    "source",
    [
        "import substance_painter_mcp\n",
        "from painter_mcp_client import PainterClient\n",
        "import mcp.client\n",
        "from tools.bridge import mcp_tools\n",
        'BRIDGE = "SubstancePainterMCP"\n',
    ],
)
def test_bridge_import_is_rejected(source: str) -> None:
    assert any("MCP bridge" in p for p in problems_of(source))


def test_vocabulary_calls_are_documented_symbols() -> None:
    symbols = documented_symbols()
    getters = [
        vocabulary.GET_SOURCE,
        vocabulary.GET_ACTIVE_CHANNELS,
        vocabulary.GET_BLENDING_MODE,
        vocabulary.GET_OPACITY,
        vocabulary.GET_RESOLUTION,
    ]
    assert sorted(c for c in set(STATE_CALLS) | set(getters) if c not in symbols) == []


def test_symbol_entries_name_their_documenting_object() -> None:
    for symbol, entry in documented_symbols().items():
        anchor = entry["documented_as"]
        # The plugins page documents `substance_painter_plugins` (decision 297).
        page = entry["page"]
        assert page.startswith(("substance_painter/", "plugins/")) and page.endswith(".html")
        assert (
            symbol == anchor
            or symbol.startswith(anchor + ".")
            or anchor == symbol.replace(".", "/")
        ), symbol


def test_symbol_list_matches_the_python_doc_inventory() -> None:
    """Every listed symbol is documented in Painter 12.1.0's python-doc (A-PYDOC).

    Runs where the public documentation is available: `UZP_PAINTER_PYTHON_DOC` names its
    `objects.inv`, or Painter is installed at the default location (the owner's machine).
    """
    inventory = Path(os.environ.get(PYTHON_DOC_ENV, DEFAULT_INVENTORY))
    if not inventory.is_file():
        pytest.skip(f"python-doc inventory not available ({inventory})")
    assert inventory_problems(inventory) == []
