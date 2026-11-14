from pathlib import Path
import pytest
import server

def test_import_basic_svg(tmp_path):
    svg_file = tmp_path / "test_shapes.svg"
    svg_file.write_text("""<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
        <rect x="10" y="10" width="30" height="20" />
        <circle cx="70" cy="70" r="15" />
        <line x1="5" y1="90" x2="95" y2="90" />
    </svg>""", encoding="utf-8")

    server.silhouette_new_design("svg_import_test", width_mm=200, height_mm=200)
    res = server.silhouette_import_svg("svg_import_test", str(svg_file), target_width_mm=80, x_mm=10, y_mm=10)

    assert res["paths_added"] >= 3
    assert res["scale_applied"] > 0
    assert res["bbox_mm"] is not None

    desc = server.silhouette_describe_design("svg_import_test")
    assert desc["shape_count"] >= 3

def test_import_bezier_svg(tmp_path):
    svg_file = tmp_path / "curve.svg"
    svg_file.write_text("""<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
        <path d="M 10 80 C 40 10, 65 10, 95 80 Z" />
    </svg>""", encoding="utf-8")

    server.silhouette_new_design("curve_test", width_mm=200, height_mm=200)
    res = server.silhouette_import_svg("curve_test", str(svg_file))
    assert res["paths_added"] == 1

def test_import_invalid_svg():
    server.silhouette_new_design("invalid_svg_test", width_mm=200, height_mm=200)
    with pytest.raises(ValueError, match="existing .svg file"):
        server.silhouette_import_svg("invalid_svg_test", "nonexistent_file.svg")

