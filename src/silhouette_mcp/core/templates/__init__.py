"""Pure 2D parametric packaging template domain subpackage."""

from .generators import (
    _build_cube_box,
    _build_gift_tag,
    _build_milk_box,
    _build_pillow_box,
    generate_box_template_shapes,
)
from .geometry import _bow_arc, _milk_arch_pts
from .models import SUPPORTED_BOX_TEMPLATES, BoxTemplateSpec

__all__ = [
    "BoxTemplateSpec",
    "SUPPORTED_BOX_TEMPLATES",
    "_bow_arc",
    "_build_cube_box",
    "_build_gift_tag",
    "_build_milk_box",
    "_build_pillow_box",
    "_milk_arch_pts",
    "generate_box_template_shapes",
]

