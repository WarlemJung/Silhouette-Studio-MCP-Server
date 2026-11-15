"""Unit tests for the pure packaging template domain package `core.templates`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from silhouette_mcp.core.exceptions import SilhouetteValueError
from silhouette_mcp.core.templates import (
    SUPPORTED_BOX_TEMPLATES,
    BoxTemplateSpec,
    _bow_arc,
    _milk_arch_pts,
    generate_box_template_shapes,
)
from silhouette_mcp.services import template_service


def _blank_doc(
    name: str,
    width_mm: float,
    height_mm: float,
    cut_margin_mm: float = 5.0,
) -> dict:
    return {
        "name": name,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "cut_margin_mm": cut_margin_mm,
        "next_id": 1,
        "revision": 0,
        "shapes": [],
    }


def test_supported_templates_and_spec_validation():
    assert SUPPORTED_BOX_TEMPLATES == (
        "milk-box-luxo",
        "milk-box",
        "cube-box",
        "pillow-box",
        "gift-tag",
    )

    spec = BoxTemplateSpec(template="  CUBE-BOX ", dashed_score=0)
    assert spec.template == "cube-box"
    assert spec.dashed_score is False

    with pytest.raises(FrozenInstanceError):
        spec.width_mm = 99.0  # type: ignore[misc]

    with pytest.raises(SilhouetteValueError, match="Unknown template"):
        BoxTemplateSpec(template="invalid-box")

    with pytest.raises(SilhouetteValueError, match="must be > 0"):
        BoxTemplateSpec(template="gift-tag", width_mm=0.0)

    with pytest.raises(SilhouetteValueError, match="finite"):
        BoxTemplateSpec(template="gift-tag", x_mm=float("nan"))


def test_pure_curve_primitives_symmetry_and_endpoints():
    arch = _milk_arch_pts(10.0, y_peak=15.0, y_valley=19.5, width=60.0)
    assert arch[0] == (10.0, 19.5)
    assert arch[-1] == pytest.approx((70.0, 19.5))
    min_y = min(y for _, y in arch)
    assert min_y == pytest.approx(15.0, abs=1e-6)

    arc = _bow_arc(0.0, 80.0, y_base=50.0, dy=-12.0, n=16)
    assert arc[0] == (0.0, 50.0)
    assert arc[-1] == (80.0, 50.0)
    assert arc[8] == pytest.approx((40.0, 38.0), abs=1e-6)


@pytest.mark.parametrize("tpl", SUPPORTED_BOX_TEMPLATES)
@pytest.mark.parametrize("dashed", [True, False])
def test_generate_box_template_shapes_all_variants(tpl, dashed):
    doc_a = _blank_doc(f"{tpl}_{dashed}", 400.0, 400.0, 5.0)
    doc_b = _blank_doc(f"{tpl}_{dashed}", 400.0, 400.0, 5.0)
    spec = BoxTemplateSpec(
        template=tpl,
        x_mm=15.0,
        y_mm=15.0,
        width_mm=50.0,
        depth_mm=50.0,
        body_height_mm=80.0,
        dashed_score=dashed,
    )

    added_a = generate_box_template_shapes(doc_a, spec)
    added_b = generate_box_template_shapes(doc_b, spec)
    assert added_a == added_b
    assert len(added_a) >= 3

    cut_shapes = [s for s in added_a if s["layer"] == "CUT"]
    score_shapes = [s for s in added_a if s["layer"] == "SCORE"]
    assert len(cut_shapes) >= 1
    assert len(score_shapes) >= 1

    outer = cut_shapes[0]
    assert all(s.get("parent_id") == outer["id"] for s in added_a if s["id"] != outer["id"])

    labels = {s["label"] for s in added_a}
    if tpl == "milk-box-luxo":
        assert any(lbl.startswith("rasgo-fita-") for lbl in labels)
    elif tpl == "milk-box":
        assert any(lbl.startswith("furo-fita-") for lbl in labels)
    elif tpl == "pillow-box":
        assert "vinco-topo-p1" in labels and "vinco-base-p2" in labels
    elif tpl == "gift-tag":
        assert {"tag-contorno", "tag-furo"}.issubset(labels)


def test_gift_tag_omits_fold_when_too_short_and_service_reexports():
    doc = _blank_doc("short_tag", 200.0, 200.0, 5.0)
    added = generate_box_template_shapes(
        doc,
        BoxTemplateSpec(template="gift-tag", width_mm=30.0, depth_mm=10.0, body_height_mm=12.0),
    )
    assert [s["label"] for s in added] == ["tag-contorno", "tag-furo"]

    for attr in (
        "BoxTemplateSpec",
        "SUPPORTED_BOX_TEMPLATES",
        "_milk_arch_pts",
        "_bow_arc",
        "_build_milk_box",
        "_build_cube_box",
        "_build_pillow_box",
        "_build_gift_tag",
        "generate_box_template_shapes",
        "add_box_template",
    ):
        assert hasattr(template_service, attr)
