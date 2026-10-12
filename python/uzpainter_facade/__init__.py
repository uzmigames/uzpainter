"""The implementation of the `substance_painter` compatibility facade (task phase1.20_pyapi-facade).

`substance_painter` and `substance_painter_plugins` hold Painter's documented symbols only: each
of their modules re-exports names from here, so no private helper is reachable through them
(`docs/architecture/10-python-api.md` §0, §4; `python/FACADE.md`). Everything runs over the
native `uzpainter` module (`src/python/`): this package adds Painter's observable behaviour
(colour rules, the active-channel reset, context errors, insertion rules, inert script state,
Painter-shaped resource ids, `js.evaluate`) and nothing that changes the native contract.
"""
