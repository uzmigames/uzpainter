"""Resource aliases retain the MIME of their shared content blob."""

from tests.python.conftest import Run


def test_texture_alias_of_mesh_bytes_preserves_blob_and_metadata(run: Run) -> None:
    report = run(
        r'''
import hashlib
import sqlite3
from pathlib import Path

original = Path(PLANE).read_bytes()
digest = hashlib.sha256(original).hexdigest()
path = WORK + "/aliases.uzp"
create()
project.save_as(path)

def stored():
    with sqlite3.connect(path) as db:
        blob = db.execute(
            "SELECT mime, size, data FROM blob WHERE sha256 = ?", (digest,)
        ).fetchone()
        aliases = db.execute(
            "SELECT name, usage, origin FROM blob_meta WHERE sha256 = ? ORDER BY name", (digest,)
        ).fetchall()
    return blob, aliases

before, original_aliases = stored()
assert before[0] == "model/obj" and before[1] == len(original)
assert original_aliases
source = Path(WORK) / "not-an-image.png"
source.write_bytes(original)
for name in ("texture-alias", "texture-alias-2"):
    imported = resource.import_project_resource(str(source), resource.Usage.TEXTURE, name)
    assert imported.identifier().version == digest
    assert imported.usages() == ["TEXTURE"]
    assert resource.resource_origin(imported.identifier()) == source.as_posix()
project.save()
project.close()
after, aliases = stored()
assert after == before  # The shared compressed bytes and MIME were not replaced.
assert all(entry in aliases for entry in original_aliases)
for name in ("texture-alias", "texture-alias-2"):
    assert (name, "TEXTURE", source.as_posix()) in aliases

source.write_bytes(b"origin changed after import")
project.open(path)
ids = {entry.name: entry for entry in resource.list_project_resources()}
for name in ("texture-alias", "texture-alias-2"):
    assert ids[name].version == digest
    assert resource.resource_origin(ids[name]) == source.as_posix()
project.save()
project.close()
assert stored() == (after, aliases)
result = {"shared_hash": digest, "alias_count": len(aliases)}
'''
    )
    assert report["status"] == "ok", report.get("error", report)
