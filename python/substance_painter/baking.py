"""Painter's documented `substance_painter.baking` module: the facade over the native `uzpainter`
module. The bake parameters (phase3.1_baker-request-model, decision 323) and the bake jobs
(phase3.3_baker-evidence-publication, decision 355) are implemented; the link groups are release
gaps (phase3.5_embree-bakers: every call raises NotYetSupported).
Documented symbols only; the implementation is `uzpainter_facade` (`python/FACADE.md`)."""

from uzpainter.baking import (
    get_link_group,
    get_link_group_common_parameters,
    get_linked_texture_sets,
    get_linked_texture_sets_common_parameters,
    set_linked_group,
    set_linked_group_common_parameters,
    unlink_all,
    unlink_all_common_parameters,
)
from uzpainter_facade.baking import (
    BakingParameters,
    BakingStatus,
    CurvatureMethod,
    bake_async,
    bake_selected_textures_async,
)

__all__ = [
    "BakingParameters",
    "BakingStatus",
    "CurvatureMethod",
    "bake_async",
    "bake_selected_textures_async",
    "get_link_group",
    "get_link_group_common_parameters",
    "get_linked_texture_sets",
    "get_linked_texture_sets_common_parameters",
    "set_linked_group",
    "set_linked_group_common_parameters",
    "unlink_all",
    "unlink_all_common_parameters",
]
