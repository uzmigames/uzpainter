"""Committed materialized textures, stable content keys and bounded native observation."""

from tests.python.conftest import Run


def test_unmaterialized_channels_do_not_require_an_evaluator_base(run: Run) -> None:
    report = run(
        r"""
from uzpainter import event
stack = create()
group = ls.insert_group(top(stack))
stack.add_channel(CT.BaseDiffuseRoughness, ts.ChannelFormat.L32F)
empty = event._texture_state_snapshot()
assert empty["textures"] == () and not empty["errors"], empty
stack.remove_channel(CT.BaseDiffuseRoughness)
fill = ls.insert_fill(ls.InsertPosition.inside_node(group, ls.NodeStack.Substack))
fill.active_channels = {CT.BaseColor}
before = event._texture_state_snapshot()
assert len(before["textures"]) == 1 and not before["errors"], before
token = event._texture_state_subscribe()
stack.add_channel(CT.BaseDiffuseRoughness, ts.ChannelFormat.L32F)
notice, = event._texture_state_drain(token)
assert not notice["errors"] and notice["textures"] == before["textures"], notice
group.set_visible(False)
notice, = event._texture_state_drain(token)
assert not notice["errors"] and notice["textures"] == (), notice
group.set_visible(True)
notice, = event._texture_state_drain(token)
assert not notice["errors"] and notice["textures"] == before["textures"], notice
event._texture_state_unsubscribe(token)
fill.active_channels = {CT.BaseColor, CT.BaseDiffuseRoughness}
fill.set_source(CT.BaseDiffuseRoughness, cm.Color(0.2, 0.2, 0.2, "Working"))
unsupported = event._texture_state_snapshot()
assert any("BaseDiffuseRoughness" in error for error in unsupported["errors"]), unsupported
fill.active_channels = {CT.BaseColor}
assert not event._texture_state_snapshot()["errors"]
project.close()
result = {"unmaterialized": "passed"}
"""
    )
    assert report["status"] == "ok", report.get("error", report)


def test_texture_snapshot_content_and_restart(run: Run) -> None:
    first = run(
        r"""
from uzpainter import event
stack = create()
assert event._texture_state_snapshot()["textures"] == ()
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor}
fill.set_source(CT.BaseColor, cm.Color(0.2, 0.3, 0.4, "Working"))
def texture():
    state = event._texture_state_snapshot()
    assert not state["errors"], state
    assert len(state["textures"]) == 1, state
    value = state["textures"][0]
    assert value["channel_type"] == CT.BaseColor
    assert value["tile_indices"] == (0, 0)
    assert -(1 << 63) <= value["cache_key"] < (1 << 63)
    return value
before = texture()
fill.set_name("renamed")
project.Metadata("texture-test").set("unused", 42)
resource.import_project_resource(IMAGES + "/checker-16.png", resource.Usage.TEXTURE)
assert texture() == before
fill.set_source(CT.BaseColor, cm.Color(0.5, 0.3, 0.4, "Working"))
changed = texture()
assert changed["digest"] != before["digest"]
assert changed["cache_key"] != before["cache_key"]
stack.material().set_resolution(ts.Resolution(512, 512))
resized = texture()
assert resized["digest"] != changed["digest"]
assert resized["cache_key"] != changed["cache_key"]
project.save_as(WORK + "/texture.uzp")
generation = event._texture_state_snapshot()["generation"]
project.close()
project.open(WORK + "/texture.uzp")
assert event._texture_state_snapshot()["generation"] != generation
assert texture() == resized
project.close()
result = {"digest": resized["digest"], "key": resized["cache_key"]}
"""
    )
    assert first["status"] == "ok", first.get("error", first)
    second = run(
        r"""
from uzpainter import event
project.open(WORK + "/texture.uzp")
state = event._texture_state_snapshot()
assert not state["errors"]
value = state["textures"][0]
result = {"digest": value["digest"], "key": value["cache_key"]}
project.close()
"""
    )
    assert second["status"] == "ok", second.get("error", second)
    assert second["result"] == first["result"]


def test_texture_notices_transactions_noops_and_visibility(run: Run) -> None:
    report = run(
        r"""
from uzpainter import event
stack = create()
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor, CT.Height}
color = cm.Color(0.2, 0.3, 0.4, "Working")
fill.set_source(CT.BaseColor, color)
token = event._texture_state_subscribe()
before = event._texture_state_snapshot()
revision = project.revision()
fill.set_source(CT.BaseColor, color)
assert project.revision() == revision
notice, = event._texture_state_drain(token)
assert notice["textures"] == before["textures"]
assert len(notice["invalidated"]) == 1 and notice["invalidated"][0][-1] == CT.BaseColor
assert event._texture_state_drain(token) == ()
try:
    with uzpainter.Transaction("rollback"):
        fill.set_source(CT.BaseColor, cm.Color(0.8, 0.8, 0.8, "Working"))
        assert event._texture_state_snapshot()["textures"] == before["textures"]
        assert event._texture_state_drain(token) == ()
        raise ValueError("abort")
except ValueError:
    pass
assert event._texture_state_drain(token) == ()
assert event._texture_state_snapshot()["textures"] == before["textures"]
with uzpainter.Transaction("commit"):
    fill.set_source(CT.BaseColor, cm.Color(0.7, 0.7, 0.7, "Working"))
    fill.set_source(CT.BaseColor, cm.Color(0.6, 0.6, 0.6, "Working"))
    assert event._texture_state_drain(token) == ()
notice, = event._texture_state_drain(token)
assert notice["revision"] == revision + 1
assert len(notice["invalidated"]) == 1
assert event._texture_state_drain(token) == ()
assert raises(fill.set_source, CT.BaseColor, "invalid source") is not None
assert event._texture_state_drain(token) == ()
for i in range(30):
    fill.set_source(CT.BaseColor, cm.Color(i / 100, 0.2, 0.3, "Working"))
notice, = event._texture_state_drain(token)
assert notice["revision"] == project.revision()
assert len(notice["invalidated"]) == 1
assert event._texture_state_drain(token) == ()
fill.set_visible(False)
notice, = event._texture_state_drain(token)
assert notice["textures"] == ()
fill.set_visible(True)
notice, = event._texture_state_drain(token)
assert len(notice["textures"]) == 2
fill.set_visible(False)
fill.set_visible(True)
removed, added = event._texture_state_drain(token)
assert removed["textures"] == () and len(added["textures"]) == 2
ls.delete_node(fill)
notice, = event._texture_state_drain(token)
assert notice["textures"] == ()
project.close()
closed, = event._texture_state_drain(token)
assert closed["generation"] != before["generation"] and closed["textures"] == ()
event._texture_state_unsubscribe(token)
result = {"notices": "passed"}
"""
    )
    assert report["status"] == "ok", report.get("error", report)


def test_texture_structural_overflow_is_explicit(run: Run) -> None:
    report = run(
        r"""
from uzpainter import event
stack = create()
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor}
token = event._texture_state_subscribe()
for i in range(66):
    fill.set_visible(i % 2 == 1)
notice, = event._texture_state_drain(token)
assert any("overflow" in error for error in notice["errors"]), notice
fill.set_visible(False)
assert event._texture_state_drain(token) == ()
event._texture_state_unsubscribe(token)
token = event._texture_state_subscribe()
assert not event._texture_state_snapshot()["errors"]
fill.set_visible(True)
notice, = event._texture_state_drain(token)
assert len(notice["textures"]) == 1 and not notice["errors"]
event._texture_state_unsubscribe(token)
project.close()
result = {"overflow": "explicit"}
"""
    )
    assert report["status"] == "ok", report.get("error", report)


def test_texture_drain_wake_and_unsubscribe_release_gil(run: Run) -> None:
    report = run(
        r"""
from uzpainter import event
import threading
for unsubscribe in (False, True):
    token = event._texture_state_subscribe()
    ready = threading.Event()
    done = threading.Event()
    values = []
    def waiter():
        ready.set()
        values.append(event._texture_state_drain(token, 30.0))
        done.set()
    worker = threading.Thread(target=waiter)
    worker.start()
    assert ready.wait(5)
    if unsubscribe:
        event._texture_state_unsubscribe(token)
    else:
        event._texture_state_wake(token)
    assert done.wait(5), "native drain held the GIL or lost the wake"
    worker.join()
    assert values == [()]
    event._texture_state_unsubscribe(token)
result = {"wake": "passed"}
"""
    )
    assert report["status"] == "ok", report.get("error", report)
