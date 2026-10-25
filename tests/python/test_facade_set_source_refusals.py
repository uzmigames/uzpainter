"""`FillLayerNode.set_source` refuses before its implicit channel activation (facade).

A refusal the caller catches inside an enclosing `uzpainter.Transaction` must leave nothing to
commit: neither the activation of the target channel nor a source. Authored inputs only (the plane
and the checker image of the api-probe fixtures); no Painter value is involved.
"""

from __future__ import annotations

from tests.python.conftest import Run
from tests.python.test_pyapi_native import ok

SCRIPT = """
stack = create(256)
node = ls.insert_fill(top(stack))
node.active_channels = {CT.BaseColor}
stack.add_channel(CT.Opacity, ts.ChannelFormat.L8)
image = resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
node.set_source(CT.BaseColor, image.identifier())

def state():
    return (uzpainter.project.revision(), sorted(c.name for c in node.active_channels),
            node.get_source(CT.BaseColor).resource_id.url())

def caught(call, *args):
    try:
        call(*args)
    except Exception as error:
        return type(error).__name__
    return None

before = state()
outcomes = []
with uzpainter.Transaction("refused sources inside a transaction"):
    # Legacy's default space of a bitmap on Opacity is unrecorded: NotYetSupported.
    outcomes.append(caught(node.set_source, CT.Opacity, image.identifier()))
    # Not a source at all: ValueError.
    outcomes.append(caught(node.set_source, CT.Opacity, 42))
after_refusals = state()
# The success path is unchanged: an implicit activation and its source commit together.
stack.add_channel(CT.User0, ts.ChannelFormat.L8)
revision = uzpainter.project.revision()
with uzpainter.Transaction("accepted source"):
    node.set_source(CT.User0, image.identifier())
result = {
    "outcomes": outcomes,
    "unchanged": after_refusals == before,
    "opacity_inactive": CT.Opacity not in node.active_channels,
    "accepted": [CT.User0 in node.active_channels, uzpainter.project.revision() > revision,
                 node.get_source(CT.User0).resource_id.url() == before[2]],
}
"""


def test_caught_refusals_commit_no_activation(facade: Run) -> None:
    assert ok(facade(SCRIPT)) == {
        "outcomes": ["NotYetSupported", "ValueError"],
        "unchanged": True,
        "opacity_inactive": True,
        "accepted": [True, True, True],
    }
