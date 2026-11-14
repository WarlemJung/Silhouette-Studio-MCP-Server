"""Direct unit tests for the application `services` layer without MCP overhead."""

from __future__ import annotations

from pathlib import Path
import pytest

from silhouette_mcp.core.exceptions import SilhouetteValueError
from silhouette_mcp.services import (
    document_service,
    export_service,
    geometry_service,
    import_service,
    nesting_service,
    template_service,
)


def test_document_and_geometry_services_flow(isolated_output_dir):
    presets = document_service.list_page_presets()
    assert "a4" in presets

    created = document_service.new_design("svc_doc", preset="a4")
    assert created["design"] == "svc_doc"

    # Non-existent list error case handled gracefully; valid listing shows created doc
    listed = document_service.list_designs()
    assert any(item["design"] == "svc_doc" for item in listed["designs"])

    r = geometry_service.add_rectangle("svc_doc", 15, 15, 40, 25, corner_radius_mm=3)
    c = geometry_service.add_circle("svc_doc", 90, 60, 12)
    e = geometry_service.add_ellipse("svc_doc", 140, 60, 15, 10, rotation_deg=30)
    p = geometry_service.add_polygon("svc_doc", 50, 120, 15, sides=6)
    st = geometry_service.add_star("svc_doc", 100, 120, 18, 8, points=5)
    ln = geometry_service.add_line("svc_doc", 15, 160, 80, 160, layer="SCORE")
    pl = geometry_service.add_polyline("svc_doc", [[100, 160], [120, 180], [90, 190]], closed=True)
    tx = geometry_service.add_text("svc_doc", "AB", 15, 210, size_mm=10, font="__fallback__")
    rm = geometry_service.add_registration_marks("svc_doc")

    assert all("design" in item for item in (r, c, e, p, st, ln, pl, tx, rm))

    transformed = geometry_service.transform_shape("svc_doc", r["shape_id"], dx_mm=5, rotation_deg=15)
    assert transformed["shape_id"] == r["shape_id"]

    off = geometry_service.offset_shape("svc_doc", c["shape_id"], offset_mm=2.0)
    assert off["source_id"] == c["shape_id"]

    dup = geometry_service.duplicate_shape("svc_doc", c["shape_id"], dx_mm=20, count=2)
    assert dup["count"] == 2

    grid = geometry_service.grid_duplicates("svc_doc", p["shape_id"], cols=2, rows=2)
    assert grid["count"] == 3

    desc = document_service.describe_design("svc_doc")
    assert desc["shape_count"] >= 12

    removed = document_service.remove_shape("svc_doc", pl["shape_id"])
    assert removed["removed"] == pl["shape_id"]

    cleared = document_service.clear_shapes("svc_doc")
    assert cleared["shape_count"] == 0

    with pytest.raises(SilhouetteValueError):
        document_service.remove_shape("svc_doc", 9999)

    deleted = document_service.delete_design("svc_doc", delete_files=True)
    assert deleted["deleted_design"] == "svc_doc"


def test_nesting_export_import_and_template_services(fixtures_dir, monkeypatch):
    document_service.new_design("svc_full", width_mm=250, height_mm=250)
    template_service.add_box_template("svc_full", template="gift-tag", x_mm=15, y_mm=15, width_mm=40, body_height_mm=60)
    template_service.add_box_template("svc_full", template="pillow-box", x_mm=70, y_mm=15, width_mm=45, body_height_mm=55)
    template_service.add_box_template("svc_full", template="cube-box", x_mm=15, y_mm=90, width_mm=30, depth_mm=30, body_height_mm=35)

    svg_file = fixtures_dir / "sample_shapes.svg"
    imp = import_service.import_svg("svc_full", str(svg_file), target_width_mm=50, x_mm=150, y_mm=150)
    assert imp["paths_added"] >= 1

    nest_dry = nesting_service.nest_shapes("svc_full", spacing_mm=2.0, dry_run=True)
    assert nest_dry["dry_run"] is True and nest_dry["placed_count"] >= 1

    nest_real = nesting_service.nest_shapes("svc_full", spacing_mm=2.0, dry_run=False)
    assert nest_real["dry_run"] is False and nest_real["placed_count"] >= 1

    exp = export_service.export_design("svc_full", formats="dxf,svg,png")
    assert all(Path(p).is_file() for p in exp["files"].values())

    prev = export_service.render_preview("svc_full", dpi=100, filename="svc_preview")
    assert Path(prev["png_path"]).is_file()

    cal = export_service.make_calibration_file()
    assert Path(cal["files"]["dxf"]).is_file()

    launched: list[list[str]] = []
    monkeypatch.setattr("subprocess.Popen", lambda args: launched.append(args))
    monkeypatch.setattr("silhouette_mcp.server._find_studio_exe", lambda: r"C:\fake\Silhouette Studio.exe")
    monkeypatch.setattr("sys.platform", "win32")
    opened = export_service.open_in_studio("svc_full")
    assert opened["process_launched"] is True
    assert launched

