"""Grunge and noise certification tooling (`phase3.2_proc-grunge-families`).

- `requests.py` writes the recording requests of the grunge goldens: one Painter project on the
  authored plane at one resolution, each case one grunge as the mask source of a white fill on its
  own User channel.
- `goldens.py` lists the goldens.
- `evidence.py` reads the admitted goldens from the private store and prints numbers only.
"""
