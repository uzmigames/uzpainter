"""Real native invalidations through facade lifecycle and dispatcher delivery."""

from tests.python.conftest import Run


def test_texture_events_reopen_noop_pause_resume_and_close(facade: Run) -> None:
    report = facade(
        r"""
import datetime
import threading
from substance_painter import application, event
from uzpainter_facade import texture_state

observed = []
updated = threading.Event()
def listen(value):
    assert threading.get_ident() == uzpainter.event.dispatcher_thread_id()
    observed.append((value.action.name, value.channel_type.name,
                     project.is_open(), project.is_busy(), value.cache_key))
    if value.action == event.TextureStateEventAction.UPDATE:
        updated.set()

event.DISPATCHER.connect_strong(event.TextureStateEvent, listen)
event.TextureStateEvent.set_cache_key_invalidation_throttling_period(
    datetime.timedelta(milliseconds=500))
stack = create()
fill = ls.insert_fill(top(stack))
fill.active_channels = {CT.BaseColor}
color = cm.Color(0.2, 0.3, 0.4, cm.GenericColorSpace.Working)
fill.set_source(CT.BaseColor, color)
texture_state.synchronize()
uzpainter.event.flush()
project.save_as(WORK + "/texture.spp")
project.close()
observed.clear()
project.open(WORK + "/texture.spp")
assert [(a, c, opened, busy) for a, c, opened, busy, key in observed] == [
    ("ADD", "BaseColor", True, True)], observed
key = observed[0][-1]
fill = ls.get_root_layer_nodes(ts.get_active_stack())[0]
observed.clear()
updated.clear()
revision = uzpainter.project.revision()
fill.set_source(CT.BaseColor, color)
texture_state.synchronize()
uzpainter.event.flush()
assert uzpainter.project.revision() == revision
assert [(a, c) for a, c, *_ in observed] == [("UPDATE", "BaseColor")], observed
assert observed[0][-1] == key

application.enable_engine_computations(False)
observed.clear()
updated.clear()
fill.get_source(CT.BaseColor).set_color(
    cm.Color(0.7, 0.3, 0.4, cm.GenericColorSpace.Working))
texture_state.synchronize()
uzpainter.event.flush()
assert observed == [], observed
application.enable_engine_computations(True)
assert updated.wait(5), "resumed texture update was not delivered"
texture_state.synchronize()
uzpainter.event.flush()
assert [(a, c) for a, c, *_ in observed] == [("UPDATE", "BaseColor")], observed
assert observed[0][-1] != key
observed.clear()
project.close()
assert [(a, c, opened, busy) for a, c, opened, busy, key in observed] == [
    ("REMOVE", "BaseColor", True, True)], observed
result = {"lifecycle": "passed"}
"""
    )
    assert report["status"] == "ok", report.get("error", report)
