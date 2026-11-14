import pytest
import server

def test_list_presets():
    res = server.silhouette_list_page_presets()
    assert "mat-12x12" in res
    assert "a4" in res
    assert res["mat-12x12"]["width_mm"] == 304.8
    assert res["mat-12x12"]["height_mm"] == 304.8

def test_design_lifecycle():
    # Cria design com preset
    d1 = server.silhouette_new_design("box_project", preset="mat-12x12")
    assert d1["design"] == "box_project"
    assert d1["width_mm"] == 304.8

    # Nao pode duplicar sem overwrite=True
    with pytest.raises(ValueError, match="already exists"):
        server.silhouette_new_design("box_project")

    # Pode sobrescrever
    d2 = server.silhouette_new_design("box_project", width_mm=200, height_mm=200, overwrite=True)
    assert d2["width_mm"] == 200

    # Consulta
    raw = server.silhouette_get_design("box_project")
    assert raw["name"] == "box_project"
    assert len(raw["shapes"]) == 0

    # Lista designs
    lst = server.silhouette_list_designs()
    assert any(d["design"] == "box_project" for d in lst["designs"])

    # Deleta design
    del_res = server.silhouette_delete_design("box_project")
    assert del_res["deleted_design"] == "box_project"

    with pytest.raises(ValueError, match="does not exist"):
        server.silhouette_get_design("box_project")

def test_add_shapes_and_layers():
    server.silhouette_new_design("shapes_test", width_mm=300, height_mm=300)

    # Retangulo com rotacao e camada
    r = server.silhouette_add_rectangle(
        "shapes_test", x_mm=20, y_mm=20, width_mm=60, height_mm=40,
        corner_radius_mm=5, rotation_deg=45, layer="CUT", label="my_rect"
    )
    assert r["shape_id"] == 1
    assert r["layer"] == "CUT"

    # Circulo
    c = server.silhouette_add_circle(
        "shapes_test", cx_mm=150, cy_mm=150, radius_mm=30, layer="CUT", label="center_hole"
    )
    assert c["shape_id"] == 2

    # Elipse
    e = server.silhouette_add_ellipse(
        "shapes_test", cx_mm=200, cy_mm=50, rx_mm=20, ry_mm=10, rotation_deg=30, layer="CUT"
    )
    assert e["shape_id"] == 3

    # Poligono
    p = server.silhouette_add_polygon(
        "shapes_test", cx_mm=50, cy_mm=200, radius_mm=25, sides=6, layer="CUT"
    )
    assert p["shape_id"] == 4

    # Estrela
    s = server.silhouette_add_star(
        "shapes_test", cx_mm=150, cy_mm=250, outer_radius_mm=30, inner_radius_mm=12, points=5, layer="CUT"
    )
    assert s["shape_id"] == 5

    # Polilinha customizada
    pl = server.silhouette_add_polyline(
        "shapes_test", points=[[10, 10], [50, 10], [30, 40]], closed=True, layer="CUT"
    )
    assert pl["shape_id"] == 6

    # Descreve design
    desc = server.silhouette_describe_design("shapes_test")
    assert desc["shape_count"] == 6
    assert desc["width_mm"] == 300

def test_add_line_simple_and_dashed():
    server.silhouette_new_design("line_test", width_mm=200, height_mm=200)

    # Linha simples de corte
    l1 = server.silhouette_add_line("line_test", 10, 10, 100, 10, layer="CUT", label="cut_line")
    assert l1["shape_id"] == 1
    assert l1["layer"] == "CUT"

    # Linha pontilhada de vinco (score)
    l2 = server.silhouette_add_line(
        "line_test", 10, 50, 100, 50, dashed=True, dash_len_mm=4, gap_len_mm=2, layer="SCORE"
    )
    assert l2["segments_added"] > 1
    assert l2["layer"] == "SCORE"

    desc = server.silhouette_describe_design("line_test")
    assert desc["shape_count"] > 2

def test_transform_and_duplicate():
    server.silhouette_new_design("trans_test", width_mm=200, height_mm=200)
    c = server.silhouette_add_circle("trans_test", cx_mm=50, cy_mm=50, radius_mm=10)
    sid = c["shape_id"]

    # Transform: move +10, +20 e escala 1.5
    tr = server.silhouette_transform_shape("trans_test", shape_id=sid, dx_mm=10, dy_mm=20, scale=1.5)
    assert tr["bbox_mm"] == [45.0, 55.0, 75.0, 85.0]

    # Duplicate: faz 3 copias deslocadas de 20mm no eixo X
    dup = server.silhouette_duplicate_shape("trans_test", shape_id=sid, dx_mm=20, dy_mm=0, count=3)
    assert dup["count"] == 3
    assert len(dup["created_ids"]) == 3

    desc = server.silhouette_describe_design("trans_test")
    assert desc["shape_count"] == 4

def test_remove_and_clear_shapes():
    server.silhouette_new_design("clear_test", width_mm=200, height_mm=200)
    s1 = server.silhouette_add_circle("clear_test", 50, 50, 10)
    s2 = server.silhouette_add_circle("clear_test", 80, 50, 10)

    # Remove 1
    rem = server.silhouette_remove_shape("clear_test", shape_id=s1["shape_id"])
    assert rem["removed"] == s1["shape_id"]
    assert rem["shape_count"] == 1

    # Limpa tudo
    clr = server.silhouette_clear_shapes("clear_test")
    assert clr["shape_count"] == 0
    desc = server.silhouette_describe_design("clear_test")
    assert desc["shape_count"] == 0

def test_shape_warnings_fine_details_and_margins():
    server.silhouette_new_design("warn_test", width_mm=100, height_mm=100, cut_margin_mm=10)

    # Fora da margem de 10mm (x=5)
    r1 = server.silhouette_add_rectangle("warn_test", 5, 20, 20, 20)
    assert any("inside the 10.0 mm safety margin" in w for w in r1["warnings"])

    # Elemento minusculo (< 2mm)
    r2 = server.silhouette_add_rectangle("warn_test", 20, 20, 1.0, 1.0)
    assert any("smaller than 2.0 mm" in w for w in r2["warnings"])

    # Linha aberta longa (comprimento 50mm, largura 0mm) NAO deve dar falso aviso de < 2mm
    l = server.silhouette_add_line("warn_test", 20, 20, 70, 20)
    assert not any("smaller than 2.0 mm" in w for w in l["warnings"])

    # Formas curtas (< 2mm) na camada FOLD nao devem disparar alerta de detalhe fino
    f_seg = server.silhouette_add_line("warn_test", 20, 30, 21.0, 30, layer="FOLD")
    assert not any("smaller than 2.0 mm" in w for w in f_seg["warnings"])

def test_add_line_dashed_batch_io_and_max_shapes(monkeypatch):
    server.silhouette_new_design("batch_line", width_mm=200, height_mm=200)
    save_calls = 0
    orig_save = server._save

    def counting_save(d):
        nonlocal save_calls
        save_calls += 1
        return orig_save(d)

    monkeypatch.setattr(server, "_save", counting_save)

    res = server.silhouette_add_line(
        "batch_line", 10, 20, 110, 20, dashed=True, dash_len_mm=5.0, gap_len_mm=5.0, layer=" fold "
    )
    assert save_calls == 1
    assert res["layer"] == "FOLD"
    assert res["segments_added"] == 10
    assert res["shape_ids"] == list(range(1, 11))

    # Simula limite MAX_SHAPES pequeno para validar bloqueio antes de gravar no disco
    monkeypatch.setattr(server, "MAX_SHAPES", 12)
    with pytest.raises(ValueError, match="limit of 12 shapes"):
        server.silhouette_add_line(
            "batch_line", 10, 40, 110, 40, dashed=True, dash_len_mm=5.0, gap_len_mm=5.0
        )
    # O arquivo salvo deve permanecer intacto com apenas 10 formas
    assert server.silhouette_describe_design("batch_line")["shape_count"] == 10

def test_duplicate_shape_deep_isolation():
    server.silhouette_new_design("dup_iso", width_mm=200, height_mm=200)
    r = server.silhouette_add_rectangle("dup_iso", 10, 10, 20, 20)
    dup = server.silhouette_duplicate_shape("dup_iso", r["shape_id"], dx_mm=30, count=1)
    copy_id = dup["created_ids"][0]

    # Transforma apenas a copia e garante que o original nao e afetado
    server.silhouette_transform_shape("dup_iso", copy_id, dy_mm=50)
    raw = server.silhouette_get_design("dup_iso")
    orig_pts = next(s["points"] for s in raw["shapes"] if s["id"] == r["shape_id"])
    copy_pts = next(s["points"] for s in raw["shapes"] if s["id"] == copy_id)
    assert orig_pts != copy_pts
    assert orig_pts[0][1] == 10.0
    assert copy_pts[0][1] == 60.0

def test_atomic_save_no_residual_tmp_files(isolated_output_dir, monkeypatch):
    server.silhouette_new_design("atomic_ok", width_mm=100, height_mm=100)
    assert list(isolated_output_dir.glob("*.tmp")) == []

    # Simula falha durante os.replace para verificar remocao do arquivo .tmp
    def failing_replace(src, dst):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr(server.os, "replace", failing_replace)
    with pytest.raises(OSError, match="Simulated disk failure"):
        server._save({"name": "atomic_fail", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5.0, "next_id": 1, "shapes": []})
    assert list(isolated_output_dir.glob("*.tmp")) == []

