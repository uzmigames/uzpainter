"""Procedural calibration and held-out certification harness (decision 222, decision 303).

A permitted slice of `phase3.1_proc-backend-seam` item 2.7 (`docs/architecture/05-procedural-
content.md` §6): a batch pins a calibration set and a held-out set by hash before fitting; a
fitter sees only the calibration set, inside a fence that refuses every file access to the store,
the held-out root and the reports; a candidate is exact only when every texel of every case of
both sets equals its oracle; a missing oracle is `oracle_unavailable`. Reports hold hashes and
residual statistics only, never oracle values. Nothing here certifies a Painter asset.
"""
