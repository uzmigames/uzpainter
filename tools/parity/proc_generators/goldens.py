"""The generator goldens of `phase3.2_proc-generator-families` (2026-11-09).

Parameter names are the ones the documented `Property` API reports (item 2.1,
`docs/analysis/proc-generator-families/01-parameter-discovery.md`); the values are authored here.

**Diagnostic** (one golden, never a calibration or held-out case of any batch): the generators
whose defaults are not a per-texel function of the mesh maps, each at Painter's defaults, the
seeded ones also at seed 1, on the rounded cube at 1024. It records the separating evidence for
Curvature and Mask Editor (multi-scale curvature processing at their defaults) and for Dirt,
Metal Edge Wear and Mask Builder - Legacy (Painter's own seeded grunge at their defaults).

**Ambient Occlusion batch** (item 2.7). Certified editable domain, declared before calibration:
`ao_invert` and `global_invert` in {0, 1}, every other parameter at Painter's default (not
editable), the single listed seed 0 (the generator has no `$randomseed`), the AO mesh map, one
UV tile, output 1024/2048/4096 float32 linear mono. The §6 matrix: the authored sphere, the
authored rounded cube and the hat v8 low mesh (hat v6 low is lost, decision 260) x
{1024, 2048, 4096} x {defaults, the Tunic v10 recipe set (`global_invert` 1,
`Assets3D .../18-Tunica/report.json`, the "Cavidades - AO high" mask), two boundary sets}. The
held-out set: the knob cube (a mesh outside the calibration set) at 2048 with the same four sets.

The knob cube's set was spent on 2026-11-09 (candidate `be93c9a9...`, held-out ledger) and failed
on the single-invert sets. The candidate was refitted on the calibration set alone (2026-11-10)
and fixed in its commit before a new held-out set was recorded: the Tunic v10 low mesh, the mesh
of the recipe set and outside the calibration set, at 1024 and 4096 with the same four sets.
The spent knob cube set joins the calibration set as regression cases (decision 222 §2; the root
review of decision 424, 2026-11-10); it never enters a held-out set again.
"""

from __future__ import annotations

from tools.parity.proc_generators.requests import GeneratorCase, Golden

DIAGNOSTIC = Golden(
    "diagnostic",
    "mixed",
    "rounded-cube",
    1024,
    (
        GeneratorCase("curvature-defaults", "Curvature"),
        GeneratorCase("mask-editor-defaults", "Mask Editor"),
        GeneratorCase("dirt-defaults", "Dirt"),
        GeneratorCase("dirt-seed-1", "Dirt", seed=1),
        GeneratorCase("edge-wear-defaults", "Metal Edge Wear"),
        GeneratorCase("edge-wear-seed-1", "Metal Edge Wear", seed=1),
        GeneratorCase("mask-builder-defaults", "Mask Builder - Legacy"),
        GeneratorCase("mask-builder-seed-1", "Mask Builder - Legacy", seed=1),
    ),
)

OCCLUSION = "Ambient Occlusion"
# (set id, role, ao_invert, global_invert)
OCCLUSION_SETS = (
    ("defaults", "defaults", 0, 0),
    ("recipe-tunic-v10", "recipe", 0, 1),
    ("boundary-ao-invert", "boundary", 1, 0),
    ("boundary-both-inverts", "boundary", 1, 1),
)
CALIBRATION_MESHES = ("sphere", "rounded-cube", "hat-v8")
RESOLUTIONS = (1024, 2048, 4096)
SPENT_HELD_OUT = (("knob-cube", 2048),)  # spent 2026-11-09 (decision 423)
HELD_OUT = (("tunic-v10", 1024), ("tunic-v10", 4096))
# The AO map is the input; the World Space Normals map, baked with no dilation, marks Painter's
# UV coverage: outside it an export with `passthrough` padding holds no defined generator output
# (the diagnostic golden's two recordings differ only there), so Tier 2a compares the covered
# texels.
MAPS = ("AO", "WorldSpaceNormal")


def occlusion_cases() -> tuple[GeneratorCase, ...]:
    # Every declared parameter is set, the defaults included, so each case names its full point.
    return tuple(
        GeneratorCase(set_id, OCCLUSION, (("ao_invert", ao), ("global_invert", glob)))
        for set_id, _, ao, glob in OCCLUSION_SETS
    )


def occlusion_goldens() -> tuple[Golden, ...]:
    calibration = tuple(
        Golden("calibration", "occlusion", mesh, resolution, occlusion_cases(), MAPS, 0)
        for mesh in CALIBRATION_MESHES
        for resolution in RESOLUTIONS
    )
    held_out = tuple(
        Golden("held-out", "occlusion", mesh, resolution, occlusion_cases(), MAPS, 0)
        for mesh, resolution in (*SPENT_HELD_OUT, *HELD_OUT)
    )
    return (*calibration, *held_out)


def spent_held_out(goldens: tuple[Golden, ...]) -> tuple[Golden, ...]:
    """The spent held-out goldens: calibration regression cases of the current batch."""
    spent = set(SPENT_HELD_OUT)
    return tuple(g for g in goldens if g.stage == "held-out" and (g.mesh, g.resolution) in spent)


def current_held_out(goldens: tuple[Golden, ...]) -> tuple[Golden, ...]:
    """The held-out goldens of the current batch: the spent set's are left out."""
    spent = set(SPENT_HELD_OUT)
    return tuple(
        g for g in goldens if g.stage == "held-out" and (g.mesh, g.resolution) not in spent
    )


def goldens() -> tuple[Golden, ...]:
    return (DIAGNOSTIC, *occlusion_goldens())
