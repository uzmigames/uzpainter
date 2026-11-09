"""Mesh-map generator certification tooling (`phase3.2_proc-generator-families`).

- `discovery.py` publishes, from the private generator survey (`tools.parity.recorder.
  generator_survey`), the public parameter semantics of each generator (item 2.1).
- `requests.py` writes the recording requests of the generators' goldens: one Painter project per
  mesh, resolution and generator, the mesh maps baked by Painter and exported with the generator
  outputs, so the inputs a candidate reads are exactly the maps the generator read.
"""
