from pathlib import Path
import pytest
import ezdxf
from silhouette_mcp import server

def test_export_dxf_and_svg():
    server.silhouette_new_design("export_sample", width_mm=210, height_mm=297)
    server.silhouette_add_rectangle("export_sample", 20, 20, 80, 50, layer="CUT", label="base")
    server.silhouette_add_circle("export_sample", 60, 45, 15, layer="CUT", label="hole")
    server.silhouette_add_line("export_sample", 20, 45, 100, 45, layer="SCORE", label="fold")

    res = server.silhouette_export("export_sample", formats="dxf,svg")
    assert "dxf" in res["files"]
    assert "svg" in res["files"]

    dxf_path = Path(res["files"]["dxf"])
    svg_path = Path(res["files"]["svg"])
    assert dxf_path.is_file()
    assert svg_path.is_file()

    # Valida documento DXF
    doc = ezdxf.readfile(str(dxf_path))
    assert doc.header.get("$INSUNITS") == 4  # mm
    assert doc.header.get("$MEASUREMENT") == 1  # metric
    assert "CUT" in doc.layers
    assert "SCORE" in doc.layers

    msp = doc.modelspace()
    entities = list(msp)
    assert len(entities) == 3

    # Valida documento SVG
    svg_content = svg_path.read_text(encoding="utf-8")
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in svg_content
    assert 'id="CUT"' in svg_content
    assert 'id="SCORE"' in svg_content

def test_export_empty_design_raises():
    server.silhouette_new_design("empty_design", width_mm=100, height_mm=100)
    with pytest.raises(ValueError, match="no shapes to export"):
        server.silhouette_export("empty_design")

def test_calibration_file_creation():
    cal = server.silhouette_make_calibration_file()
    assert "files" in cal
    assert "dxf" in cal["files"]
    dxf_path = Path(cal["files"]["dxf"])
    assert dxf_path.exists()

    doc = ezdxf.readfile(str(dxf_path))
    assert doc.header.get("$INSUNITS") == 4
    assert len(list(doc.modelspace())) >= 4  # square, circle, pill, score dashes

def test_export_dxf_r12_polyline_and_invalid_version(monkeypatch):
    monkeypatch.setattr(server, "DXF_VERSION", "R12")
    server.silhouette_new_design("r12_valid", width_mm=100, height_mm=100)
    server.silhouette_add_rectangle("r12_valid", 10, 10, 40, 20, layer="CUT")
    res = server.silhouette_export("r12_valid", formats="dxf")
    dxf_path = Path(res["files"]["dxf"])
    doc = ezdxf.readfile(str(dxf_path))
    assert doc.dxfversion == "AC1009"  # R12
    entities = list(doc.modelspace())
    assert len(entities) == 1
    assert entities[0].dxftype() == "POLYLINE"

    monkeypatch.setattr(server, "DXF_VERSION", "R2018")
    with pytest.raises(ValueError, match="Unsupported DXF version"):
        server.silhouette_export("r12_valid", formats="dxf")

def test_export_svg_sanitizes_layer_id():
    server.silhouette_new_design("svg_sanitize", width_mm=100, height_mm=100)
    server.silhouette_add_rectangle(
        "svg_sanitize", 10, 10, 30, 30, layer='my "bad" <layer>'
    )
    res = server.silhouette_export("svg_sanitize", formats="svg")
    svg_text = Path(res["files"]["svg"]).read_text(encoding="utf-8")
    assert 'id="MY-BAD-LAYER"' in svg_text
    assert '<layer>' not in svg_text

