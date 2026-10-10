"""`ChannelType` lists every documented member (phase1.2_docmodel-capability-manifest).

The document model (`src/uzp_core/types/enums.h`), the manifest schema and the capability
manifest's documented-symbol record (`tools/parity/recorder/documented_symbols.json`, A-PYDOC)
name the same 85 members.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tools.parity.recorder.provenance import documented_symbols

REPO_ROOT = Path(__file__).resolve().parents[2]
ENUMS_H = REPO_ROOT / "src" / "uzp_core" / "types" / "enums.h"
SCHEMA_PATH = REPO_ROOT / "src" / "uzp_core" / "schema" / "manifest.schema.json"
PREFIX = "substance_painter.textureset.ChannelType."


def documented_members() -> list[str]:
    return sorted(s.removeprefix(PREFIX) for s in documented_symbols() if s.startswith(PREFIX))


def enum_table(name: str) -> list[str]:
    text = ENUMS_H.read_text(encoding="utf-8")
    match = re.search(rf"UZP_ENUM_TABLE\({name},(.*?)\);", text, re.S)
    assert match is not None
    return re.findall(r'"([^"]+)"', match.group(1))


def enum_members(name: str) -> list[str]:
    text = ENUMS_H.read_text(encoding="utf-8")
    match = re.search(rf"enum class {name} \{{(.*?)\}};", text, re.S)
    assert match is not None
    return [m.strip() for m in match.group(1).split(",") if m.strip()]


def test_every_documented_channel_type_is_recorded() -> None:
    members = documented_members()
    assert len(members) == 85
    assert {f"User{i}" for i in range(32)} <= set(members)
    for symbol in (PREFIX + m for m in members):
        assert documented_symbols()[symbol] == {
            "documented_as": "substance_painter.textureset.ChannelType",
            "page": "substance_painter/textureset/index.html",
        }


def test_document_model_and_schema_name_the_documented_members() -> None:
    members = documented_members()
    assert enum_members("ChannelType") == enum_table("ChannelType") == members
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$defs"]["channelType"]["enum"] == members
