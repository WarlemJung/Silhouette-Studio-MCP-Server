import pytest
from pathlib import Path
import server

def test_export_r12(monkeypatch):
    monkeypatch.setattr(server, "DXF_VERSION", "R12")
    server.silhouette_new_design("r12_test", width_mm=100, height_mm=100)
    server.silhouette_add_rectangle("r12_test", 10, 10, 30, 30)
    res = server.silhouette_export("r12_test", formats="dxf")
    dxf_path = Path(res["files"]["dxf"])
    assert dxf_path.is_file()

def test_new_design_invalid_margin():
    with pytest.raises(ValueError, match="cut_margin_mm"):
        server.silhouette_new_design("bad_margin", width_mm=50, height_mm=50, cut_margin_mm=30)
    with pytest.raises(ValueError, match="Unknown preset"):
        server.silhouette_new_design("bad_preset", preset="mat-non-existent")

def test_add_line_invalid_length():
    server.silhouette_new_design("line_err", width_mm=100, height_mm=100)
    with pytest.raises(ValueError, match="greater than zero"):
        server.silhouette_add_line("line_err", 10, 10, 10, 10)

def test_add_polygon_invalid_sides():
    server.silhouette_new_design("poly_err", width_mm=100, height_mm=100)
    with pytest.raises(ValueError, match="sides must be an integer between 3 and 64"):
        server.silhouette_add_polygon("poly_err", 50, 50, 20, sides=2)

def test_add_star_invalid():
    server.silhouette_new_design("star_err", width_mm=100, height_mm=100)
    with pytest.raises(ValueError, match="inner_radius_mm must be smaller"):
        server.silhouette_add_star("star_err", 50, 50, outer_radius_mm=20, inner_radius_mm=25)
    with pytest.raises(ValueError, match="points must be an integer between 3 and 64"):
        server.silhouette_add_star("star_err", 50, 50, outer_radius_mm=20, inner_radius_mm=10, points=2)

def test_add_polyline_invalid():
    server.silhouette_new_design("pline_err", width_mm=100, height_mm=100)
    with pytest.raises(ValueError, match="points must be a list"):
        server.silhouette_add_polyline("pline_err", "not-a-list")  # type: ignore
    with pytest.raises(ValueError, match="Need at least 3 points"):
        server.silhouette_add_polyline("pline_err", [[0, 0], [10, 10]], closed=True)
    with pytest.raises(ValueError, match="Need at least 2 points"):
        server.silhouette_add_polyline("pline_err", [[0, 0]], closed=False)

def test_transform_and_duplicate_errors():
    server.silhouette_new_design("trans_err", width_mm=100, height_mm=100)
    with pytest.raises(ValueError, match="scale must be > 0"):
        server.silhouette_transform_shape("trans_err", shape_id=1, scale=-1)
    with pytest.raises(ValueError, match="No shape with id 999"):
        server.silhouette_transform_shape("trans_err", shape_id=999, scale=1.0)
    with pytest.raises(ValueError, match="count must be an integer between 1 and 100"):
        server.silhouette_duplicate_shape("trans_err", shape_id=1, count=0)
    with pytest.raises(ValueError, match="No shape with id 999"):
        server.silhouette_duplicate_shape("trans_err", shape_id=999, count=2)

def test_remove_shape_missing():
    server.silhouette_new_design("rem_err", width_mm=100, height_mm=100)
    with pytest.raises(ValueError, match="No shape with id 999"):
        server.silhouette_remove_shape("rem_err", shape_id=999)

def test_delete_design_with_exported_files():
    server.silhouette_new_design("del_full", width_mm=100, height_mm=100)
    server.silhouette_add_circle("del_full", 50, 50, 10)
    exp = server.silhouette_export("del_full", formats="dxf,svg")
    assert Path(exp["files"]["dxf"]).exists()
    assert Path(exp["files"]["svg"]).exists()

    res = server.silhouette_delete_design("del_full", delete_files=True)
    assert not Path(exp["files"]["dxf"]).exists()
    assert not Path(exp["files"]["svg"]).exists()
    assert len(res["deleted_files"]) >= 3

def test_svg_import_skipped_elements(tmp_path):
    svg_file = tmp_path / "skipped.svg"
    svg_file.write_text("""<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
        <text x="10" y="20">Hello Silhouette</text>
        <image href="logo.png" x="0" y="0" width="10" height="10" />
        <rect x="5" y="5" width="20" height="20" />
    </svg>""", encoding="utf-8")

    server.silhouette_new_design("svg_skip", width_mm=100, height_mm=100)
    res = server.silhouette_import_svg("svg_skip", str(svg_file))
    assert res["paths_added"] == 1
    assert any("skipped" in w for w in res["warnings"])

def test_open_svg_in_studio(monkeypatch):
    launched = []
    monkeypatch.setattr(server.subprocess, "Popen", lambda args: launched.append(args))
    server.silhouette_new_design("svg_open", width_mm=100, height_mm=100)
    server.silhouette_add_circle("svg_open", 50, 50, 10)
    exp = server.silhouette_export("svg_open", formats="svg")
    res = server.silhouette_open_in_studio("svg_open.svg")
    assert "opened" in res

def test_export_invalid_format():
    server.silhouette_new_design("inv_fmt", width_mm=100, height_mm=100)
    server.silhouette_add_circle("inv_fmt", 50, 50, 10)
    with pytest.raises(ValueError, match="formats must be a comma-separated list of: dxf, svg"):
        server.silhouette_export("inv_fmt", formats="pdf,png")

