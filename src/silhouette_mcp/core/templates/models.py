"""Domain models and parameter validation for parametric packaging templates."""

from __future__ import annotations

from dataclasses import dataclass

from ..exceptions import SilhouetteValueError
from ..validators import _num, _pos

SUPPORTED_BOX_TEMPLATES: tuple[str, ...] = (
    "milk-box-luxo",
    "milk-box",
    "cube-box",
    "pillow-box",
    "gift-tag",
)


@dataclass(frozen=True, slots=True)
class BoxTemplateSpec:
    """Validated specification for a 2D parametric packaging or gift-tag dieline."""

    template: str = "milk-box-luxo"
    x_mm: float = 20.0
    y_mm: float = 15.0
    width_mm: float = 60.0
    depth_mm: float = 60.0
    body_height_mm: float = 90.0
    dashed_score: bool = True

    def __post_init__(self) -> None:
        _num(x_mm=self.x_mm, y_mm=self.y_mm)
        _pos(
            width_mm=self.width_mm,
            depth_mm=self.depth_mm,
            body_height_mm=self.body_height_mm,
        )
        tpl = str(self.template).strip().lower()
        if tpl not in SUPPORTED_BOX_TEMPLATES:
            raise SilhouetteValueError(
                f"Unknown template '{self.template}'. Options: {', '.join(SUPPORTED_BOX_TEMPLATES)}"
            )
        object.__setattr__(self, "template", tpl)
        object.__setattr__(self, "x_mm", float(self.x_mm))
        object.__setattr__(self, "y_mm", float(self.y_mm))
        object.__setattr__(self, "width_mm", float(self.width_mm))
        object.__setattr__(self, "depth_mm", float(self.depth_mm))
        object.__setattr__(self, "body_height_mm", float(self.body_height_mm))
        object.__setattr__(self, "dashed_score", bool(self.dashed_score))

