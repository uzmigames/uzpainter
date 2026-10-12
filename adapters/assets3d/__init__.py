"""The UzmiGames Assets3D pipeline adapter (`MIGRATIONS.md`; `docs/architecture/10-python-api.md`
§2 and §6; task phase1.23_pyapi-pipeline-adapter).

Not part of the `substance_painter` facade: it lets Assets3D's pipeline scripts drive UzPainter
byte-unchanged, replacing only their transport (`painter_mcp_client.py execute_python`) with
`UzPainter.exe run`, and serves the pipeline's one private Painter call through a shim visible
only to the scripts it runs.
"""
