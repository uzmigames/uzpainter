"""Session offsets cover resource URL authorities without hiding resource changes."""

from tests.python.test_pyapi_facade_tier0 import normalised


def test_resource_urls_share_context_offset_and_keep_resource_identity() -> None:
    values = {
        "readback": {
            "value": [
                {"context": "project20", "name": "project20"},
                {"resource_url": "resource://project21/image-project20?version=abc"},
                {"resource_url": "resource://shelf/image?version=xyz"},
            ]
        }
    }
    assert normalised(values) == {
        "readback": {
            "value": [
                {"context": "project0", "name": "project20"},
                {"resource_url": "resource://project1/image-project20?version=abc"},
                {"resource_url": "resource://shelf/image?version=xyz"},
            ]
        }
    }
    assert values["readback"]["value"][1]["resource_url"].startswith("resource://project21/")


def test_resource_urls_supply_offset_without_context_fields() -> None:
    assert normalised({"a": {"resource_url": "resource://project20/image?version=abc"}}) == {
        "a": {"resource_url": "resource://project0/image?version=abc"}
    }
    assert normalised({"a": {"resource_url": "resource://project20/image?version=abc"}}) != (
        normalised({"a": {"resource_url": "resource://project20/image?version=changed"}})
    )
