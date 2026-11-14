import pytest
from silhouette_mcp import server


def test_import_basic_svg(fixtures_dir):
    svg_file = fixtures_dir / "sample_shapes.svg"

    server.silhouette_new_design("svg_import_test", width_mm=200, height_mm=200)
    res = server.silhouette_import_svg("svg_import_test", str(svg_file), target_width_mm=80, x_mm=10, y_mm=10)

    assert res["paths_added"] >= 3
    assert res["scale_applied"] > 0
    assert res["bbox_mm"] is not None

    desc = server.silhouette_describe_design("svg_import_test")
    assert desc["shape_count"] >= 3


def test_import_bezier_svg(fixtures_dir):
    svg_file = fixtures_dir / "sample_bezier.svg"

    server.silhouette_new_design("curve_test", width_mm=200, height_mm=200)
    res = server.silhouette_import_svg("curve_test", str(svg_file))
    assert res["paths_added"] == 1


def test_import_invalid_svg():
    server.silhouette_new_design("invalid_svg_test", width_mm=200, height_mm=200)
    with pytest.raises(ValueError, match="existing .svg file"):
        server.silhouette_import_svg("invalid_svg_test", "nonexistent_file.svg")
