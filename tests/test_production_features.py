import concurrent.futures
from pathlib import Path

import anyio
import pytest
from PIL import Image

import server


# ------------------------------------------------------------------ 1. MCP v2 Errors & Annotations


@pytest.mark.anyio
async def test_mcp_v2_preserves_anticipated_error_messages():
    from mcp import Client

    async with Client(server.mcp) as client:
        tools_res = await client.list_tools()
        names = {t.name for t in tools_res.tools}
        assert len(names) == 27
        for expected in (
            "silhouette_add_text",
            "silhouette_offset_shape",
            "silhouette_grid_duplicates",
            "silhouette_add_registration_marks",
            "silhouette_add_box_template",
            "silhouette_render_preview",
        ):
            assert expected in names

        # Annotations presentes nas tools
        list_tool = next(t for t in tools_res.tools if t.name == "silhouette_list_designs")
        assert list_tool.annotations is not None
        assert list_tool.annotations.read_only_hint is True

        # Erro esperado preserva mensagem real ao cliente (nao vira UnexpectedToolError generico)
        res = await client.call_tool("silhouette_get_design", {"design": "nao_existe_123"})
        assert res.is_error is True
        msg = " ".join(c.text for c in res.content)
        assert "does not exist" in msg


def test_exception_dual_inheritance():
    assert issubclass(server.SilhouetteValueError, ValueError)
    assert issubclass(server.SilhouetteValueError, server.ToolError)
    assert issubclass(server.SilhouetteRuntimeError, RuntimeError)
    assert issubclass(server.SilhouetteRuntimeError, server.ToolError)


# ------------------------------------------------------------------ 2. Concurrency & Atomic Replace


@pytest.mark.anyio
async def test_mcp_concurrent_shape_additions_no_lost_updates():
    from mcp import Client

    async with Client(server.mcp) as client:
        await client.call_tool(
            "silhouette_new_design", {"name": "conc_mcp", "preset": "a4", "overwrite": True}
        )
        results = []

        async def add_one(i: int):
            r = await client.call_tool(
                "silhouette_add_circle",
                {"design": "conc_mcp", "cx_mm": 30 + (i % 5) * 20, "cy_mm": 30 + (i // 5) * 20, "radius_mm": 5},
            )
            results.append(r)

        async with anyio.create_task_group() as tg:
            for i in range(30):
                tg.start_soon(add_one, i)

        assert len(results) == 30
        assert all(not r.is_error for r in results)

    raw = server.silhouette_get_design("conc_mcp")
    ids = [s["id"] for s in raw["shapes"]]
    assert len(ids) == 30
    assert sorted(ids) == list(range(1, 31))


def test_thread_pool_concurrency_on_same_design():
    server.silhouette_new_design("conc_threads", width_mm=300, height_mm=300)

    def worker(i: int):
        if i % 2 == 0:
            return server.silhouette_add_circle("conc_threads", 20 + i, 50, 4)
        return server.silhouette_add_rectangle("conc_threads", 20 + i, 80, 8, 8)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        res = list(pool.map(worker, range(30)))

    assert len(res) == 30
    raw = server.silhouette_get_design("conc_threads")
    assert len(raw["shapes"]) == 30
    assert len({s["id"] for s in raw["shapes"]}) == 30


def test_atomic_replace_retries_and_exhaustion(tmp_path, monkeypatch):
    src = tmp_path / "src.tmp"
    dst = tmp_path / "dst.json"
    src.write_text("ok", encoding="utf-8")

    attempts = 0
    real_replace = server.os.replace

    def flaky_replace(s, d):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("Locked by AV")
        return real_replace(s, d)

    monkeypatch.setattr(server.os, "replace", flaky_replace)
    server._atomic_replace(src, dst, retries=5, delay_s=0.001)
    assert attempts == 3
    assert dst.read_text(encoding="utf-8") == "ok"

    # Exaustao de tentativas deve propagar PermissionError e limpar arquivo temporario
    monkeypatch.setattr(server.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("Still locked")))
    target = tmp_path / "fail.svg"
    with pytest.raises(PermissionError, match="Still locked"):
        server._atomic_write_file(target, ".svg.tmp", lambda tmp: tmp.write_text("<svg/>", encoding="utf-8"))
    assert list(tmp_path.glob("*.svg.tmp")) == []


# ------------------------------------------------------------------ 3. Text Vectorization


def test_add_text_system_font_and_alignments():
    server.silhouette_new_design("text_sys", preset="a4")

    res_left = server.silhouette_add_text(
        "text_sys", "LUXO 2026!", x_mm=20, y_mm=20, size_mm=16, font="Arial", align="left"
    )
    assert res_left["contours_added"] >= 5
    assert res_left["layer"] == "CUT"
    assert abs(res_left["bbox_mm"][0] - 20.0) <= 0.05
    assert abs(res_left["bbox_mm"][1] - 20.0) <= 0.05

    res_center = server.silhouette_add_text(
        "text_sys", "MARIA", x_mm=105, y_mm=60, size_mm=14, align="center", letter_spacing_mm=1.5
    )
    cx = (res_center["bbox_mm"][0] + res_center["bbox_mm"][2]) / 2
    assert abs(cx - 105.0) <= 0.05

    res_rot = server.silhouette_add_text(
        "text_sys", "FESTA", x_mm=105, y_mm=90, size_mm=12, align="center", rotation_deg=15
    )
    assert res_rot["contours_added"] >= 5

    res_right = server.silhouette_add_text(
        "text_sys", "VIP", x_mm=190, y_mm=130, size_mm=12, align="right"
    )
    assert abs(res_right["bbox_mm"][2] - 190.0) <= 0.05


def test_add_text_fallback_vector_font_and_font_resolution(tmp_path, monkeypatch):
    server.silhouette_new_design("text_fb", preset="a4")
    all_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ\n0123456789-!?"
    res = server.silhouette_add_text(
        "text_fb", all_chars, x_mm=20, y_mm=20, size_mm=10, font="__fallback__", layer="score"
    )
    assert res["font_used"] == "builtin-vector-fallback"
    assert res["layer"] == "SCORE"
    assert res["contours_added"] > 30

    # Caminho direto para arquivo inexistente e busca em diretorio sem fontes -> fallback
    monkeypatch.setattr(server, "_FONT_DIRS", [tmp_path])
    assert server._resolve_font_path("NonExistentFontXYZ") is None
    res_auto_fb = server.silhouette_add_text("text_fb", "OK", x_mm=20, y_mm=80, size_mm=10, font="NonExistent")
    assert res_auto_fb["font_used"] == "builtin-vector-fallback"

    # Limite MAX_SHAPES no add_text
    monkeypatch.setattr(server, "MAX_SHAPES", len(server.silhouette_get_design("text_fb")["shapes"]) + 1)
    with pytest.raises(ValueError, match="limit of"):
        server.silhouette_add_text("text_fb", "ABCD", x_mm=20, y_mm=110, font="__fallback__")


def test_add_text_validation_and_pen_ops_curves():
    server.silhouette_new_design("text_err", width_mm=200, height_mm=200)
    with pytest.raises(ValueError, match="non-empty string"):
        server.silhouette_add_text("text_err", "   ", 10, 10)
    with pytest.raises(ValueError, match="align must be"):
        server.silhouette_add_text("text_err", "ABC", 10, 10, align="justify")

    # Testa _pen_ops_to_contours diretamente cobrindo cubicas, quadraticas e off-curve loop
    ops = [
        ("moveTo", ((0, 0),)),
        ("lineTo", ((20, 0),)),
        ("curveTo", ((25, 5), (25, 15), (20, 20))),
        ("qCurveTo", ((10, 25), (0, 20))),
        ("closePath", ()),
        ("moveTo", ((0, 0),)),
        ("qCurveTo", ((0, 0), (10, 0), (10, 10), (0, 10), None)),
        ("endPath", ()),
    ]
    contours = server._pen_ops_to_contours(ops)
    assert len(contours) == 2
    assert all(len(c) >= 6 for c in contours)


# ------------------------------------------------------------------ 4. Offset & Transform Flips


def test_offset_shape_circle_and_polygons():
    server.silhouette_new_design("off_test", width_mm=200, height_mm=200)

    # Circulo: +5 e -3
    c = server.silhouette_add_circle("off_test", 100, 100, 20)
    c_out = server.silhouette_offset_shape("off_test", c["shape_id"], offset_mm=5.0, layer="SCORE")
    assert c_out["layer"] == "SCORE"
    assert c_out["bbox_mm"] == [75.0, 75.0, 125.0, 125.0]

    c_in = server.silhouette_offset_shape("off_test", c["shape_id"], offset_mm=-3.0)
    assert c_in["bbox_mm"] == [83.0, 83.0, 117.0, 117.0]

    with pytest.raises(ValueError, match="too large"):
        server.silhouette_offset_shape("off_test", c["shape_id"], offset_mm=-20.0)

    # Retangulo CW: joins round, miter, bevel e offset interno
    r = server.silhouette_add_rectangle("off_test", 40, 40, 40, 30)
    for join in ("round", "miter", "bevel"):
        r_out = server.silhouette_offset_shape("off_test", r["shape_id"], offset_mm=3.0, join=join)
        assert r_out["bbox_mm"] == [37.0, 37.0, 83.0, 73.0]

    r_in = server.silhouette_offset_shape("off_test", r["shape_id"], offset_mm=-4.0, join="miter")
    assert r_in["bbox_mm"] == [44.0, 44.0, 76.0, 66.0]

    # Poligono CCW com aresta colinear (cobre skip colinear) expandindo para fora
    ccw = server.silhouette_add_polyline(
        "off_test", [[120, 40], [120, 55], [120, 70], [160, 70], [160, 40]], closed=True
    )
    ccw_out = server.silhouette_offset_shape("off_test", ccw["shape_id"], offset_mm=2.0, join="round")
    assert ccw_out["bbox_mm"] == [118.0, 38.0, 162.0, 72.0]

    # Triangulo muito agudo para acionar miter_limit
    spike = server.silhouette_add_polyline("off_test", [[20, 120], [80, 121], [20, 122]], closed=True)
    spike_out = server.silhouette_offset_shape("off_test", spike["shape_id"], offset_mm=3.0, join="miter")
    assert spike_out["shape_id"] > 0

    # Poligono de area zero
    flat = server.silhouette_add_polyline("off_test", [[10, 10], [20, 10], [30, 10]], closed=True)
    with pytest.raises(ValueError, match="zero area"):
        server.silhouette_offset_shape("off_test", flat["shape_id"], offset_mm=2.0)

    # Erros de validacao
    open_line = server.silhouette_add_line("off_test", 10, 10, 50, 10)
    with pytest.raises(ValueError, match="closed polygons"):
        server.silhouette_offset_shape("off_test", open_line["shape_id"], offset_mm=2.0)
    with pytest.raises(ValueError, match="non-zero"):
        server.silhouette_offset_shape("off_test", r["shape_id"], offset_mm=0.0)
    with pytest.raises(ValueError, match="join must be"):
        server.silhouette_offset_shape("off_test", r["shape_id"], offset_mm=2.0, join="invalid")
    with pytest.raises(ValueError, match="too large"):
        server.silhouette_offset_shape("off_test", r["shape_id"], offset_mm=-16.0)
    with pytest.raises(ValueError, match="No shape with id 9999"):
        server.silhouette_offset_shape("off_test", 9999, offset_mm=2.0)


def test_transform_flip_x_flip_y_and_scale_rot():
    server.silhouette_new_design("flip_test", width_mm=200, height_mm=200)
    tri = server.silhouette_add_polyline("flip_test", [[20, 20], [60, 20], [20, 50]], closed=True)
    server.silhouette_transform_shape("flip_test", tri["shape_id"], flip_x=True, flip_y=True, scale=1.5, rotation_deg=90)
    raw = server.silhouette_get_design("flip_test")
    assert len(raw["shapes"][0]["points"]) == 3


# ------------------------------------------------------------------ 5. Grid Duplicates & Regmarks


def test_grid_duplicates_and_validation():
    server.silhouette_new_design("grid_test", preset="a4")
    r = server.silhouette_add_rectangle("grid_test", 15, 15, 30, 20)
    res = server.silhouette_grid_duplicates(
        "grid_test", r["shape_id"], cols=3, rows=2, spacing_x_mm=5.0, spacing_y_mm=10.0
    )
    assert res["count"] == 5
    assert len(res["created_ids"]) == 5
    # 3*(30) + 2*(5) = 100 largura -> [15, 115]; 2*(20) + 1*(10) = 50 altura -> [15, 65]
    assert res["grid_bbox_mm"] == [15.0, 15.0, 115.0, 65.0]

    with pytest.raises(ValueError, match="cols and rows"):
        server.silhouette_grid_duplicates("grid_test", r["shape_id"], cols=0, rows=2)
    with pytest.raises(ValueError, match=">= 2"):
        server.silhouette_grid_duplicates("grid_test", r["shape_id"], cols=1, rows=1)
    with pytest.raises(ValueError, match="exceed 500"):
        server.silhouette_grid_duplicates("grid_test", r["shape_id"], cols=25, rows=25)
    with pytest.raises(ValueError, match=">= 0"):
        server.silhouette_grid_duplicates("grid_test", r["shape_id"], cols=2, rows=2, spacing_x_mm=-1)
    with pytest.raises(ValueError, match="No shape with id 9999"):
        server.silhouette_grid_duplicates("grid_test", 9999, cols=2, rows=2)


def test_registration_marks():
    server.silhouette_new_design("reg_test", preset="a4")
    res = server.silhouette_add_registration_marks("reg_test")
    assert len(res["shape_ids"]) == 3
    assert res["layer"] == "REGMARK"
    assert res["safe_print_area_mm"] == [17.0, 17.0, 193.0, 280.0]

    # REGMARK com braco de 1mm nao deve disparar falso aviso de corte fino
    desc = server.silhouette_describe_design("reg_test")
    assert desc["warnings"] == []

    server.silhouette_new_design("tiny_page", width_mm=20, height_mm=20, cut_margin_mm=2)
    with pytest.raises(ValueError, match="Page is too small"):
        server.silhouette_add_registration_marks("tiny_page")


# ------------------------------------------------------------------ 6. Box Templates & Previews


@pytest.mark.parametrize(
    "tpl,w_page,h_page,body_h,dashed",
    [
        ("milk-box-luxo", 297.0, 210.0, 90.0, True),
        ("milk-box", 297.0, 210.0, 90.0, False),
        ("cube-box", 297.0, 210.0, 65.0, True),
        ("pillow-box", 210.0, 297.0, 90.0, True),
        ("gift-tag", 210.0, 297.0, 90.0, True),
    ],
)
def test_box_templates_and_exports(tpl, w_page, h_page, body_h, dashed):
    name = f"tpl_{tpl}"
    server.silhouette_new_design(name, width_mm=w_page, height_mm=h_page, cut_margin_mm=5.0)
    res = server.silhouette_add_box_template(
        name, template=tpl, x_mm=20, y_mm=10, body_height_mm=body_h, dashed_score=dashed
    )
    assert res["template"] == tpl
    assert res["shapes_added"] >= 3
    assert res["warnings"] == []

    exp = server.silhouette_export(name, formats="dxf,svg,png")
    assert Path(exp["files"]["dxf"]).is_file()
    assert Path(exp["files"]["svg"]).is_file()
    assert Path(exp["files"]["png"]).is_file()


def test_box_template_unknown():
    server.silhouette_new_design("bad_tpl", preset="a4")
    with pytest.raises(ValueError, match="Unknown template"):
        server.silhouette_add_box_template("bad_tpl", template="origami-dragon")


def test_render_preview_png_and_delete_png():
    server.silhouette_new_design("png_prev", width_mm=210, height_mm=297)
    with pytest.raises(ValueError, match="no shapes"):
        server.silhouette_render_preview("png_prev")

    server.silhouette_add_rectangle("png_prev", 20, 20, 80, 60, layer="CUT")
    server.silhouette_add_circle("png_prev", 120, 120, 20, layer="CUT")
    server.silhouette_add_line("png_prev", 20, 50, 100, 50, layer="SCORE")

    prev = server.silhouette_render_preview("png_prev", dpi=120)
    png_path = Path(prev["png_path"])
    assert png_path.is_file()
    with Image.open(png_path) as im:
        assert im.format == "PNG"
        assert im.size == (prev["width_px"], prev["height_px"])

    # Testa clamping de imagem grande (>2400px) e pequena (<200px)
    prev_hi = server.silhouette_render_preview("png_prev", dpi=600, filename="png_hi")
    assert max(prev_hi["width_px"], prev_hi["height_px"]) <= 2400

    server.silhouette_new_design("tiny_png", width_mm=20, height_mm=20, cut_margin_mm=2)
    server.silhouette_add_rectangle("tiny_png", 4, 4, 12, 12)
    prev_lo = server.silhouette_render_preview("tiny_png", dpi=40)
    assert max(prev_lo["width_px"], prev_lo["height_px"]) >= 200

    with pytest.raises(ValueError, match="dpi must be"):
        server.silhouette_render_preview("png_prev", dpi=10)

    # list_designs inclui png_exported e delete_design(delete_files=True) apaga o .png tambem
    lst = server.silhouette_list_designs()
    entry = next(d for d in lst["designs"] if d["design"] == "png_prev")
    assert entry["png_exported"] is True

    del_res = server.silhouette_delete_design("png_prev", delete_files=True)
    assert not png_path.exists()
    assert any(p.endswith(".png") for p in del_res["deleted_files"])


# ------------------------------------------------------------------ 7. Strict Validation & Edge Warnings


def test_strict_int_rejects_booleans_and_svg_scaling_and_warnings(tmp_path):
    server.silhouette_new_design("strict_int", width_mm=200, height_mm=200)
    r = server.silhouette_add_rectangle("strict_int", 20, 20, 30, 30)

    with pytest.raises(ValueError, match="must be an integer"):
        server.silhouette_transform_shape("strict_int", shape_id=True, dx_mm=5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sides must be an integer"):
        server.silhouette_add_polygon("strict_int", 50, 50, 10, sides=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="points must be an integer"):
        server.silhouette_add_star("strict_int", 50, 50, 10, 5, points=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="count must be an integer"):
        server.silhouette_duplicate_shape("strict_int", r["shape_id"], count=True)  # type: ignore[arg-type]

    # Avisos: fora da pagina e linha aberta < 2mm
    out_r = server.silhouette_add_rectangle("strict_int", -10, 10, 20, 20)
    assert any("outside the page" in w for w in out_r["warnings"])
    tiny_l = server.silhouette_add_line("strict_int", 50, 50, 51, 50)
    assert any("smaller than 2.0 mm" in w for w in tiny_l["warnings"])

    # SVG com target_width + target_height + rotation + avisos de importacao
    svg_file = tmp_path / "box.svg"
    svg_file.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
        '<rect x="0" y="0" width="100" height="50"/></svg>',
        encoding="utf-8",
    )
    res_h = server.silhouette_import_svg(
        "strict_int", str(svg_file), target_height_mm=40, x_mm=20, y_mm=20, rotation_deg=90, layer=" score "
    )
    w_box = res_h["bbox_mm"][2] - res_h["bbox_mm"][0]
    h_box = res_h["bbox_mm"][3] - res_h["bbox_mm"][1]
    assert abs(w_box - 40.0) <= 0.1
    assert abs(h_box - 80.0) <= 0.1

    res_wh = server.silhouette_import_svg(
        "strict_int", str(svg_file), target_width_mm=50, target_height_mm=25, x_mm=-5, y_mm=20
    )
    assert any("placement/size warnings" in w for w in res_wh["warnings"])

    empty_svg = tmp_path / "empty.svg"
    empty_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="1">hi</text></svg>', encoding="utf-8")
    with pytest.raises(ValueError, match="No outlines found"):
        server.silhouette_import_svg("strict_int", str(empty_svg))

    with pytest.raises(ValueError, match="must be >= 0"):
        server.silhouette_import_svg("strict_int", str(svg_file), target_width_mm=-5)


def test_additional_edge_cases_and_platform_paths(tmp_path, monkeypatch):
    # 1. _rotate(deg=0), open polyline < 2mm warning, >20000 points error
    assert server._rotate([(1, 2)], 0, 0, 0) == [(1.0, 2.0)]
    server.silhouette_new_design("edge_extra", width_mm=200, height_mm=200)
    tiny_open = server.silhouette_add_polyline("edge_extra", [[20, 20], [21, 20]], closed=False)
    assert any("smaller than 2.0 mm" in w for w in tiny_open["warnings"])

    with pytest.raises(ValueError, match="Too many points"):
        server.silhouette_add_polyline("edge_extra", [[i * 0.01, 10] for i in range(20001)], closed=False)

    # 2. _offset_polygon com vertices duplicados (<3 distintos) e cubo sem pontilhado
    with pytest.raises(ValueError, match="at least 3 distinct vertices"):
        server._offset_polygon([(0, 0), (0, 0), (10, 0)], 2.0, "round")
    server.silhouette_add_box_template("edge_extra", template="cube-box", x_mm=10, y_mm=10, width_mm=30, depth_mm=30, body_height_mm=40, dashed_score=False)

    # 3. _resolve_font_path com caminho direto e busca parcial em subpasta
    arial_path = server._resolve_font_path("Arial")
    if arial_path:
        assert server._resolve_font_path(str(arial_path)) == arial_path
        fake_font = tmp_path / "CustomDisplay.ttf"
        fake_font.write_bytes(b"")
        monkeypatch.setattr(server, "_FONT_DIRS", [tmp_path])
        assert server._resolve_font_path("customdisplay") == fake_font

    # 4. MAX_SHAPES em duplicate_shape, grid_duplicates e import_svg
    r = server.silhouette_add_rectangle("edge_extra", 20, 20, 10, 10)
    cur_count = len(server.silhouette_get_design("edge_extra")["shapes"])
    monkeypatch.setattr(server, "MAX_SHAPES", cur_count + 2)
    dup_cap = server.silhouette_duplicate_shape("edge_extra", r["shape_id"], dx_mm=12, count=5)
    assert dup_cap["count"] == 2
    with pytest.raises(ValueError, match="limit of"):
        server.silhouette_grid_duplicates("edge_extra", r["shape_id"], cols=2, rows=2)

    svg_many = tmp_path / "many.svg"
    svg_many.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "MAX_SHAPES", cur_count + 2)
    with pytest.raises(ValueError, match="too many paths"):
        server.silhouette_import_svg("edge_extra", str(svg_many))

    # 5. silhouette_open_in_studio: reveal_in_explorer, fallback startfile, macOS e Linux
    server.silhouette_export("edge_extra", formats="dxf")
    launched = []
    monkeypatch.setattr(server.subprocess, "Popen", lambda args: launched.append(args))
    monkeypatch.setattr(server, "_find_studio_exe", lambda: r"C:\fake\Silhouette Studio.exe")
    monkeypatch.setattr(server.sys, "platform", "win32")
    server.silhouette_open_in_studio("edge_extra", reveal_in_explorer=True)
    assert any("explorer.exe" in cmd[0] for cmd in launched)

    started = []
    monkeypatch.setattr(server, "_find_studio_exe", lambda: "")
    monkeypatch.setattr(server.os, "startfile", lambda p: started.append(p), raising=False)
    res_assoc = server.silhouette_open_in_studio("edge_extra")
    assert "default file association" in res_assoc["method"]
    assert len(started) == 1

    monkeypatch.setattr(server.sys, "platform", "darwin")
    res_mac = server.silhouette_open_in_studio("edge_extra")
    assert "Silhouette Studio" in res_mac["method"]

    monkeypatch.setattr(server.sys, "platform", "linux")
    with pytest.raises(ValueError, match="Windows and macOS"):
        server.silhouette_open_in_studio("edge_extra")

