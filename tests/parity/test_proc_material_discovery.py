"""The material survey's publisher (`tools.parity.proc_materials.discovery`, decision 432).

Authored surveys only: the private survey stays on the owner's machine. Checks that the
smart-material families are found as the single source under the recipe's pattern layer (its own
sources or those of its effects), that the document publishes the declared default and range but
never the smart material's current value or its layers, and that a family without a single
pattern source is reported, not guessed.
"""

from __future__ import annotations

from typing import Any

from tools.parity.proc_materials.discovery import families, markdown, pattern_sources


def described(url: str, value: Any, default: Any) -> dict[str, Any]:
    return {
        "resource_url": url,
        "presets": [],
        "image_inputs": [],
        "image_outputs": ["output"],
        "properties": {
            "balance": {
                "value": value,
                "label": "Balance",
                "widget_type": "Slider",
                "properties": {"defaultValue": default, "min": 0, "max": 1},
            }
        },
    }


def effect(name: str, url: str) -> dict[str, Any]:
    return {"name": name, "type": "FillEffect", "source": described(url, 0, 0)}


GRUNGE = "resource://starter_assets.x/grunge/grunge?version=1.sbsar"
WEAVE = "resource://starter_assets.y/weave/weave?version=2.sbsar"
SPOTS = "resource://starter_assets.y/spots/spots?version=3.sbsar"


def survey(burlap_structure: Any) -> dict[str, Any]:
    leather = {
        "name": "Leather Damaged",
        "type": "GroupLayer",
        "sub_layers": [
            {"name": "Base Color", "type": "FillLayer", "sources": {"BaseColor": {"source": None}}},
            {
                "name": "Secret Layer Name Pattern",
                "type": "FillLayer",
                "sources": {
                    "BaseColor": described(GRUNGE, 0.45, 0.5),
                    "Height": described(GRUNGE, 0.45, 0.5),
                },
            },
        ],
    }
    material = {"source_mode": "Material", "active_channels": ["BaseColor", "Height"]}
    return {
        "materials": {"felt": {**material, "material": described(SPOTS, 0.25, 0.75)}},
        "smart_materials": {
            "burlap": {
                "gui_name": "Fabric Burlap",
                "matches": ["u"],
                "described": burlap_structure,
            },
            "leather-pattern": {
                "gui_name": "Leather Damaged",
                "matches": ["v"],
                "described": {"structure": leather},
            },
        },
    }


def test_a_pattern_layer_source_is_found_on_the_layer_or_its_effects() -> None:
    structure = {
        "name": "Fabric Burlap",
        "type": "GroupLayer",
        "sub_layers": [
            {
                "name": "Surface Details",
                "type": "FillLayer",
                "mask_effects": [effect("Spots", SPOTS)],
            },
            {
                "name": "Pattern",
                "type": "FillLayer",
                "sources": {"BaseColor": {"source": {"uniform_color_working": [0.1, 0.1, 0.1]}}},
                "mask_effects": [effect("Weave", WEAVE)],
            },
        ],
    }
    assert [s["resource_url"] for s in pattern_sources(structure)] == [WEAVE]
    found = families(survey({"structure": structure}))
    assert found["burlap"]["source"]["resource_url"] == WEAVE
    assert found["leather-pattern"]["source"]["resource_url"] == GRUNGE
    assert found["leather-pattern"]["pattern_sources"] == 1


def test_the_document_publishes_defaults_and_ranges_never_values_or_layers() -> None:
    text = markdown(families(survey({"structure": {"name": "g", "type": "GroupLayer"}})), "ab", "b")
    # Declared defaults (0.75, 0.5) and ranges are public; the observed values are not.
    assert "| `balance` | Balance | Slider | 0.75 | 0 | 1 |" in text
    assert "| `balance` | Balance | Slider | 0.5 | 0 | 1 |" in text
    assert "0.45" not in text and "0.25" not in text
    assert "Secret Layer Name" not in text and "Base Color" not in text
    # A smart material without one pattern source is reported, not guessed.
    assert "No single Substance source was found (0 pattern-layer sources" in text
