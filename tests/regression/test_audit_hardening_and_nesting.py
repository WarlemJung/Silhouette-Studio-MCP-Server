import json
import math
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from silhouette_mcp import server


# ------------------------------------------------ 1. Inter-Process Lock & Recovery


def test_multiprocess_concurrent_writes_no_lost_updates(isolated_output_dir):
    server.silhouette_new_design("mp_shared", preset="a4", overwrite=True)

    worker_code = (
        "import os, sys\n"
        f"sys.path.insert(0, {repr(str(Path(server.__file__).resolve().parents[1]))})\n"
        "from silhouette_mcp import server\n"
        "wid = int(sys.argv[1])\n"
        "for i in range(10):\n"
        "    server.silhouette_add_rectangle('mp_shared', 10 + i, 10 + wid * 15, 8, 8)\n"
    )

    env = os.environ.copy()
    env["SILHOUETTE_OUTPUT_DIR"] = str(isolated_output_dir)

    procs = [subprocess.Popen([sys.executable, "-c", worker_code, str(w)], env=env) for w in range(4)]
    exit_codes = [p.wait(timeout=30) for p in procs]
    assert exit_codes == [0, 0, 0, 0]

    raw = server.silhouette_get_design("mp_shared")
    assert len(raw["shapes"]) == 40
    assert sorted(s["id"] for s in raw["shapes"]) == list(range(1, 41))
    assert raw["revision"] == 41


def test_backup_recovery_on_corrupted_primary_and_delete_cleans_backup(isolated_output_dir):
    server.silhouette_new_design("recover_me", width_mm=200, height_mm=200)
    server.silhouette_add_rectangle("recover_me", 20, 20, 40, 30)
    server.silhouette_add_circle("recover_me", 100, 100, 15)

    primary = isolated_output_dir / "recover_me.design.json"
    backup = isolated_output_dir / "recover_me.design.json.bak"
    assert primary.is_file()
    assert backup.is_file()

    # Simula gravacao interrompida / JSON corrompido no arquivo principal
    primary.write_text('{"name": "recover_me", "shapes": [CORRUPT', encoding="utf-8")

    recovered = server.silhouette_get_design("recover_me")
    assert len(recovered["shapes"]) == 2
    assert recovered["revision"] >= 3
    # Arquivo principal deve ter sido restaurado de forma integra
    reloaded = json.loads(primary.read_text(encoding="utf-8"))
    assert len(reloaded["shapes"]) == 2

    # Se ambos primario e backup estiverem corrompidos, deve falhar claramente
    primary.write_text("not-json", encoding="utf-8")
    backup.write_text("also-corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="backup recovery failed"):
        server.silhouette_get_design("recover_me")

    # Mesmo primario valido + delete remove o backup junto para nao ressuscitar depois
    server.silhouette_new_design("del_bak", width_mm=150, height_mm=150)
    assert (isolated_output_dir / "del_bak.design.json.bak").is_file()
    server.silhouette_delete_design("del_bak")
    assert not (isolated_output_dir / "del_bak.design.json.bak").exists()
    with pytest.raises(ValueError, match="does not exist"):
        server.silhouette_get_design("del_bak")


def test_validate_design_dict_and_lock_timeout(isolated_output_dir, monkeypatch):
    with pytest.raises(ValueError, match="JSON object"):
        server._validate_design_dict([])
    with pytest.raises(ValueError, match="missing field"):
        server._validate_design_dict({"name": "x"})
    with pytest.raises(ValueError, match="'shapes' must be a list"):
        server._validate_design_dict({
            "name": "x", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 1, "shapes": {}
        })
    with pytest.raises(ValueError, match="invalid 'next_id'"):
        server._validate_design_dict({
            "name": "x", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": True, "shapes": []
        })

    # Simula timeout ao tentar adquirir lock ocupado por outro processo
    monkeypatch.setattr(server, "LOCK_TIMEOUT_S", 0.05)
    lock_obj = server._InterProcessLock()
    if sys.platform.startswith("win"):
        monkeypatch.setattr(server.msvcrt, "locking", lambda fd, mode, size: (_ for _ in ()).throw(OSError("busy")))
        with pytest.raises(RuntimeError, match="Timed out waiting for inter-process lock"):
            with lock_obj:
                pass


# -------------------------------------------- 2. Computational Geometry & Offsets


def test_concave_l_shape_u_shape_star_and_self_intersection_offsets():
    server.silhouette_new_design("geom_hard", width_mm=300, height_mm=300)

    # L-shape 60x60 com recorte 30x30 no canto superior direito
    l_pts = [[20, 20], [50, 20], [50, 50], [80, 50], [80, 80], [20, 80]]
    l_shape = server.silhouette_add_polyline("geom_hard", l_pts, closed=True, label="L")

    l_out = server.silhouette_offset_shape("geom_hard", l_shape["shape_id"], offset_mm=3.0, join="miter")
    l_in = server.silhouette_offset_shape("geom_hard", l_shape["shape_id"], offset_mm=-3.0, join="round")
    raw = server.silhouette_get_design("geom_hard")
    pts_out = [(p[0], p[1]) for p in next(s["points"] for s in raw["shapes"] if s["id"] == l_out["shape_id"])]
    pts_in = [(p[0], p[1]) for p in next(s["points"] for s in raw["shapes"] if s["id"] == l_in["shape_id"])]

    assert not server._has_self_intersection(pts_out, closed=True)
    assert not server._has_self_intersection(pts_in, closed=True)
    orig_area = abs(server._polygon_area2([(float(x), float(y)) for x, y in l_pts])) * 0.5
    assert abs(server._polygon_area2(pts_out)) * 0.5 > orig_area
    assert abs(server._polygon_area2(pts_in)) * 0.5 < orig_area
    assert all(server._point_in_polygon(p, [(float(x), float(y)) for x, y in l_pts], boundary_tol=1e-3) for p in pts_in)

    # Canal em U estreito (largura do canal = 8mm) expandido +6mm (paredes internas se cruzam -> pruning)
    u_pts = [[100, 20], [115, 20], [115, 60], [123, 60], [123, 20], [138, 20], [138, 80], [100, 80]]
    u_shape = server.silhouette_add_polyline("geom_hard", u_pts, closed=True, label="U")
    u_out = server.silhouette_offset_shape("geom_hard", u_shape["shape_id"], offset_mm=6.0, join="round")
    raw = server.silhouette_get_design("geom_hard")
    pts_u_out = [(p[0], p[1]) for p in next(s["points"] for s in raw["shapes"] if s["id"] == u_out["shape_id"])]
    assert not server._has_self_intersection(pts_u_out, closed=True)

    # Estrela de 5 pontas: offset externo e interno moderado funcionam; interno excessivo falha
    star = server.silhouette_add_star("geom_hard", 200, 120, outer_radius_mm=35, inner_radius_mm=15, points=5)
    star_out = server.silhouette_offset_shape("geom_hard", star["shape_id"], offset_mm=2.5, join="round")
    star_in = server.silhouette_offset_shape("geom_hard", star["shape_id"], offset_mm=-1.5, join="miter")
    raw = server.silhouette_get_design("geom_hard")
    assert not server._has_self_intersection(next(s["points"] for s in raw["shapes"] if s["id"] == star_out["shape_id"]))
    assert not server._has_self_intersection(next(s["points"] for s in raw["shapes"] if s["id"] == star_in["shape_id"]))

    with pytest.raises(ValueError, match="too large"):
        server.silhouette_offset_shape("geom_hard", star["shape_id"], offset_mm=-20.0)

    # Poligono auto-intersectante ("gravata-borboleta") deve ser rejeitado
    bowtie = [[10, 10], [50, 50], [50, 10], [10, 50]]
    with pytest.raises(ValueError, match="self-intersecting"):
        server.silhouette_add_polyline("geom_hard", bowtie, closed=True)
    with pytest.raises(ValueError, match="self-intersecting"):
        server._offset_polygon(bowtie, 2.0, "round")


def test_geometry_cleanup_and_property_invariants():
    # Limpeza de vertices colineares e spike 180 graus
    dirty = [(0, 0), (10, 0), (20, 0), (20, 10), (15, 10), (20, 10), (0, 10)]
    cleaned = server._clean_polygon(dirty)
    assert len(cleaned) == 4
    assert not server._has_self_intersection(cleaned, closed=True)

    # Property-based seeded checks: invariancia de area sob rotacao e qualidade de offsets em poligonos aleatorios
    rng = random.Random(20261113)
    for trial in range(25):
        n_sides = rng.randint(4, 16)
        radius = rng.uniform(15.0, 50.0)
        angle_offset = rng.uniform(0.0, 360.0)
        cx, cy = rng.uniform(60.0, 200.0), rng.uniform(60.0, 200.0)
        pts = [
            (
                cx + radius * math.cos(math.radians(angle_offset) + 2 * math.pi * k / n_sides),
                cy + radius * math.sin(math.radians(angle_offset) + 2 * math.pi * k / n_sides),
            )
            for k in range(n_sides)
        ]
        area0 = abs(server._polygon_area2(pts)) * 0.5
        rot_pts = server._rotate(pts, cx, cy, rng.uniform(-180.0, 180.0))
        area_rot = abs(server._polygon_area2(rot_pts)) * 0.5
        assert math.isclose(area0, area_rot, rel_tol=1e-6)

        d_out = rng.uniform(0.5, 4.0)
        off_out = server._offset_polygon(pts, d_out, rng.choice(["round", "miter", "bevel"]))
        assert not server._has_self_intersection(off_out, closed=True)
        assert abs(server._polygon_area2(off_out)) * 0.5 > area0

        d_in = -rng.uniform(0.5, radius * 0.3)
        off_in = server._offset_polygon(pts, d_in, "miter")
        assert not server._has_self_intersection(off_in, closed=True)
        assert abs(server._polygon_area2(off_in)) * 0.5 < area0
        assert all(server._point_in_polygon(p, pts, boundary_tol=1e-4) for p in off_in)


# ------------------------------------- 3. Atomic MAX_SHAPES & Bounds Validation


def test_atomic_max_shapes_enforcement_on_batch_tools(monkeypatch):
    server.silhouette_new_design("atomic_limits", width_mm=300, height_mm=300)
    server.silhouette_add_rectangle("atomic_limits", 20, 20, 30, 30)
    server.silhouette_add_rectangle("atomic_limits", 60, 20, 30, 30)

    monkeypatch.setattr(server, "MAX_SHAPES", 4)
    # Regmarks precisa de 3 formas (2 + 3 = 5 > 4): deve falhar antes de salvar qualquer marca
    with pytest.raises(ValueError, match="limit of 4"):
        server.silhouette_add_registration_marks("atomic_limits")
    assert server.silhouette_describe_design("atomic_limits")["shape_count"] == 2

    # Dashed line que gera > 2 segmentos falha sem inserir parcial
    with pytest.raises(ValueError, match="limit of 4"):
        server.silhouette_add_line("atomic_limits", 20, 100, 120, 100, dashed=True, dash_len_mm=5, gap_len_mm=5)
    assert server.silhouette_describe_design("atomic_limits")["shape_count"] == 2

    # Box template milk-box-luxo gera > 15 formas -> atomicamente rejeitado sem poluir o design
    monkeypatch.setattr(server, "MAX_SHAPES", 10)
    with pytest.raises(ValueError, match="limit of 10"):
        server.silhouette_add_box_template("atomic_limits", template="milk-box-luxo", width_mm=40, depth_mm=40, body_height_mm=50)
    assert server.silhouette_describe_design("atomic_limits")["shape_count"] == 2


def test_input_limits_security_and_svg_protections(tmp_path, monkeypatch):
    # Limites de pagina e coordenadas
    with pytest.raises(ValueError, match="must be between"):
        server.silhouette_new_design("tiny_pg", width_mm=5, height_mm=50)
    with pytest.raises(ValueError, match="must be between"):
        server.silhouette_new_design("huge_pg", width_mm=6000, height_mm=100)

    server.silhouette_new_design("sec_test", width_mm=200, height_mm=200)
    with pytest.raises(ValueError, match="maximum coordinate magnitude"):
        server.silhouette_add_rectangle("sec_test", 150000, 20, 10, 10)
    with pytest.raises(ValueError, match="must be a finite number"):
        server.silhouette_add_circle("sec_test", 50, float("inf"), 10)

    # Limite de texto e extensao de fonte invalida
    with pytest.raises(ValueError, match="maximum length"):
        server.silhouette_add_text("sec_test", "A" * (server.MAX_TEXT_LENGTH + 1), 20, 20)
    not_font = tmp_path / "secret.txt"
    not_font.write_text("secret", encoding="utf-8")
    with pytest.raises(ValueError, match="ttf, .otf, or .ttc"):
        server._resolve_font_path(str(not_font))

    # Protecoes SVG: XXE / DOCTYPE / script / URL externa / XML invalido / profundidade excessiva
    bad_entity = tmp_path / "xxe.svg"
    bad_entity.write_text(
        '<!DOCTYPE svg [<!ENTITY ext SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="DOCTYPE/ENTITY"):
        server.silhouette_import_svg("sec_test", str(bad_entity))

    bad_script = tmp_path / "script.svg"
    bad_script.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', encoding="utf-8")
    with pytest.raises(ValueError, match="DOCTYPE/ENTITY/script"):
        server.silhouette_import_svg("sec_test", str(bad_script))

    bad_url = tmp_path / "ext_ref.svg"
    bad_url.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://evil.example/a.png" width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="external URL"):
        server.silhouette_import_svg("sec_test", str(bad_url))

    bad_css = tmp_path / "css_ref.svg"
    bad_css.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10" style="fill:url(http://evil.example/x)"/></svg>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="DOCTYPE/ENTITY/script"):
        server.silhouette_import_svg("sec_test", str(bad_css))

    wrong_root = tmp_path / "wrong.svg"
    wrong_root.write_text('<html><body>not svg</body></html>', encoding="utf-8")
    with pytest.raises(ValueError, match="root XML element must be <svg>"):
        server.silhouette_import_svg("sec_test", str(wrong_root))

    deep_svg = tmp_path / "deep.svg"
    depth = 70
    deep_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">' + "<g>" * depth + '<rect width="5" height="5"/>' + "</g>" * depth + "</svg>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="maximum depth"):
        server.silhouette_import_svg("sec_test", str(deep_svg))

    # Limite de vertices SVG e Studio Popen retorno nao-zero + null byte
    svg_ok = tmp_path / "tiny.svg"
    svg_ok.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50"><rect x="0" y="0" width="20" height="20"/></svg>', encoding="utf-8")
    monkeypatch.setattr(server, "MAX_SVG_TOTAL_POINTS", 2)
    with pytest.raises(ValueError, match="too many vertices"):
        server.silhouette_import_svg("sec_test", str(svg_ok))

    with pytest.raises(ValueError, match="valid non-empty file path"):
        server.silhouette_open_in_studio("bad\x00name.dxf")

    server.silhouette_add_rectangle("sec_test", 20, 20, 40, 40)
    server.silhouette_export("sec_test", formats="dxf")

    class DeadProc:
        def poll(self):
            return 1

    monkeypatch.setattr(server, "_find_studio_exe", lambda: r"C:\fake\Silhouette Studio.exe")
    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.subprocess, "Popen", lambda args: DeadProc())
    with pytest.raises(RuntimeError, match="exited immediately with code 1"):
        server.silhouette_open_in_studio("sec_test")

    class LiveProc:
        def poll(self):
            return None

    monkeypatch.setattr(server.subprocess, "Popen", lambda args: LiveProc())
    opened = server.silhouette_open_in_studio("sec_test")
    assert opened["process_launched"] is True
    assert opened["homologated_import"] is False


# --------------------------------------------------------- 4. 2D Nesting Engine


def _boxes_min_gap(a: list[float], b: list[float]) -> float:
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    if dx > 0 or dy > 0:
        return max(dx, dy)
    return 0.0


def test_nest_shapes_determinism_rotation_clearance_and_regmarks():
    server.silhouette_new_design("nest_demo", width_mm=120, height_mm=120, cut_margin_mm=5.0)
    # Adiciona pecas sobrepostas intencionalmente e em tamanhos variados
    ids = []
    ids.append(server.silhouette_add_rectangle("nest_demo", 10, 10, 80, 20, label="bar-1")["shape_id"])
    ids.append(server.silhouette_add_rectangle("nest_demo", 10, 10, 20, 80, label="bar-2")["shape_id"])
    ids.append(server.silhouette_add_rectangle("nest_demo", 10, 10, 30, 30, label="sq-1")["shape_id"])
    ids.append(server.silhouette_add_circle("nest_demo", 50, 50, 12, label="circ-1")["shape_id"])

    dry = server.silhouette_nest_shapes("nest_demo", spacing_mm=3.0, dry_run=True)
    dry2 = server.silhouette_nest_shapes("nest_demo", spacing_mm=3.0, dry_run=True)
    assert dry == dry2
    assert dry["placed_count"] == 4
    assert dry["unplaced_count"] == 0
    assert 0 < dry["utilization_pct"] <= 100.0
    assert dry["true_area_utilization_pct"] <= dry["utilization_pct"]

    real = server.silhouette_nest_shapes("nest_demo", spacing_mm=3.0, dry_run=False)
    assert real["placements"] == dry["placements"]

    # Valida todas as colocacoes no documento salvo: dentro da area util e sem sobreposicao
    raw = server.silhouette_get_design("nest_demo")
    ux0, uy0, ux1, uy1 = real["usable_area_bbox_mm"]
    bboxes = [server._bbox(s) for s in raw["shapes"]]
    for b in bboxes:
        assert b[0] >= ux0 - 1e-3 and b[1] >= uy0 - 1e-3
        assert b[2] <= ux1 + 1e-3 and b[3] <= uy1 + 1e-3
    for i in range(len(bboxes)):
        for j in range(i + 1, len(bboxes)):
            assert _boxes_min_gap(list(bboxes[i]), list(bboxes[j])) >= 3.0 - 1e-3

    # Com marcas de registro Print & Cut, nesting evita sobrepor as marcas
    server.silhouette_new_design("nest_reg", preset="a4", cut_margin_mm=5.0)
    server.silhouette_add_registration_marks("nest_reg", inset_mm=10.0)
    for k in range(6):
        server.silhouette_add_rectangle("nest_reg", 15 + k, 15 + k, 50, 40, label=f"tag-{k}")

    nested_reg = server.silhouette_nest_shapes("nest_reg", spacing_mm=4.0)
    assert nested_reg["placed_count"] == 6
    raw_reg = server.silhouette_get_design("nest_reg")
    reg_boxes = [server._bbox(s) for s in raw_reg["shapes"] if s["layer"] == "REGMARK"]
    cut_boxes = [server._bbox(s) for s in raw_reg["shapes"] if s["layer"] != "REGMARK"]
    for cb in cut_boxes:
        for rb in reg_boxes:
            # Disjuntos com folga minima
            assert max(cb[0] - rb[2], rb[0] - cb[2], cb[1] - rb[3], rb[1] - cb[3]) >= 1.0 - 1e-3

    # Peca maior que a folha aparece em unplaced_ids sem quebrar
    big = server.silhouette_add_rectangle("nest_reg", 20, 20, 205, 290, label="too-big")["shape_id"]
    partial = server.silhouette_nest_shapes("nest_reg", shape_ids=[big], spacing_mm=2.0)
    assert partial["placed_count"] == 0
    assert partial["unplaced_ids"] == [big]

    # Erros de validacao do nesting
    with pytest.raises(ValueError, match="spacing_mm"):
        server.silhouette_nest_shapes("nest_demo", spacing_mm=-1.0)
    with pytest.raises(ValueError, match="duplicate"):
        server.silhouette_nest_shapes("nest_demo", shape_ids=[ids[0], ids[0]])
    with pytest.raises(ValueError, match="Unknown shape_id"):
        server.silhouette_nest_shapes("nest_demo", shape_ids=[99999])


def test_nesting_property_invariants_random_batches():
    rng = random.Random(998877)
    server.silhouette_new_design("nest_prop", preset="mat-12x12", cut_margin_mm=5.0)
    for idx in range(20):
        w = round(rng.uniform(20.0, 75.0), 1)
        h = round(rng.uniform(15.0, 65.0), 1)
        server.silhouette_add_rectangle("nest_prop", 10, 10, w, h, label=f"p{idx}")

    res = server.silhouette_nest_shapes("nest_prop", spacing_mm=4.0, allow_rotation=True)
    assert res["placed_count"] == 20
    ux0, uy0, ux1, uy1 = res["usable_area_bbox_mm"]
    boxes = [p["bbox_mm"] for p in res["placements"]]
    for b in boxes:
        assert b[0] >= ux0 - 1e-3 and b[1] >= uy0 - 1e-3
        assert b[2] <= ux1 + 1e-3 and b[3] <= uy1 + 1e-3
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert _boxes_min_gap(boxes[i], boxes[j]) >= 4.0 - 1e-3


def test_stdio_stdout_clean_even_with_logging(capsys):
    orig_level = server.logger.level
    try:
        server.logger.setLevel(server.logging.DEBUG)
        server.silhouette_new_design("stdio_clean", preset="a4")
        server.silhouette_add_rectangle("stdio_clean", 20, 20, 40, 30)
        server.logger.warning("operational diagnostic test message")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "operational diagnostic test message" in captured.err
    finally:
        server.logger.setLevel(orig_level)


def test_additional_coverage_for_geometry_svg_and_nesting(tmp_path, monkeypatch):
    # 1. Design corrompido sem backup disponivel
    server.silhouette_new_design("no_bak", preset="a4")
    (server.OUTPUT_DIR / "no_bak.design.json").write_text("{corrupt", encoding="utf-8")
    (server.OUTPUT_DIR / "no_bak.design.json.bak").unlink()
    with pytest.raises(ValueError, match="no backup is available"):
        server.silhouette_get_design("no_bak")

    # 2. _segments_intersect paralelos/colineares e _point_to_segment_dist degenerado
    assert server._segments_intersect((0, 0), (10, 0), (0, 2), (10, 2)) == (False, None)
    assert server._segments_intersect((0, 0), (0, 10), (0, 5), (0, 15)) == (True, None)
    assert server._segments_intersect((0, 0), (0, 4), (0, 6), (0, 10)) == (False, None)
    assert math.isclose(server._point_to_segment_dist((3, 4), (0, 0), (0, 0)), 5.0)
    assert server._point_to_polygon_dist((1, 1), []) == float("inf")

    # 3. _clean_polygon e _has_self_intersection para dobra 180 graus (backtracking)
    spike_fold = [(0, 0), (10, 0), (0, 0), (0, 10)]
    assert server._has_self_intersection(spike_fold, closed=True) is True
    cleaned_quad = server._clean_polygon([(0, 0), (10, 0), (5, 0), (10, 10), (0, 10)])
    assert len(cleaned_quad) == 4
    assert not server._has_self_intersection(cleaned_quad, closed=True)

    # 4. Offset interno maior que o inraio de triangulo retangulo 10x10 (inraio ~ 2.93 mm) deve falhar
    with pytest.raises(ValueError, match="too large"):
        server._offset_polygon([[10, 10], [20, 20], [10, 20]], -3.5, "round")

    # 5. SVG UTF-8 invalido, XML malformado, excesso de elementos e path nulo
    server.silhouette_new_design("cov_extra", preset="a4")
    server.silhouette_add_rectangle("cov_extra", 20, 20, 40, 25)

    bad_utf8 = tmp_path / "bad_utf8.svg"
    bad_utf8.write_bytes(b"\xff\xfe<svg/>")
    with pytest.raises(ValueError, match="valid UTF-8"):
        server.silhouette_import_svg("cov_extra", str(bad_utf8))

    bad_xml = tmp_path / "malformed.svg"
    bad_xml.write_text("<svg><unclosed></svg>", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid or unsafe SVG"):
        server.silhouette_import_svg("cov_extra", str(bad_xml))

    with pytest.raises(ValueError, match="existing .svg file"):
        server.silhouette_import_svg("cov_extra", "bad\x00.svg")

    many_el_svg = tmp_path / "many_el.svg"
    many_el_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">' + '<rect width="5" height="5"/>' * 20 + "</svg>",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "MAX_SVG_ELEMENTS", 10)
    with pytest.raises(ValueError, match="too many XML elements"):
        server.silhouette_import_svg("cov_extra", str(many_el_svg))

    # 6. Nesting edge cases: allow_rotation=False, rotation_step_deg invalido, margin invalido, sem formas
    res_norot = server.silhouette_nest_shapes("cov_extra", allow_rotation=False, dry_run=True)
    assert res_norot["placed_count"] == 1
    with pytest.raises(ValueError, match="rotation_step_deg"):
        server.silhouette_nest_shapes("cov_extra", rotation_step_deg=0.5)
    with pytest.raises(ValueError, match="shape_ids"):
        server.silhouette_nest_shapes("cov_extra", shape_ids=[])
    with pytest.raises(ValueError, match="margin_mm"):
        server.silhouette_nest_shapes("cov_extra", margin_mm=150.0)
    server.silhouette_clear_shapes("cov_extra")
    with pytest.raises(ValueError, match="No shapes selected"):
        server.silhouette_nest_shapes("cov_extra")


def test_real_stdio_mcp_client_end_to_end(tmp_path):
    """Integracao real sem mocks via protocolo MCP STDIO com server.py em subprocesso."""
    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    out_dir = tmp_path / "stdio_out"
    out_dir.mkdir()
    err_log_path = tmp_path / "stdio_stderr.log"

    async def _run_session():
        env = os.environ.copy()
        env["SILHOUETTE_OUTPUT_DIR"] = str(out_dir)
        env["SILHOUETTE_LOG_LEVEL"] = "INFO"
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(Path(server.__file__).resolve())],
            cwd=str(Path(server.__file__).resolve().parents[2]),
            env=env,
        )
        with err_log_path.open("w", encoding="utf-8") as err_f:
            async with stdio_client(params, errlog=err_f) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    init_res = await session.initialize()
                    assert init_res.server_info.name == "silhouette-studio"
                    assert init_res.server_info.version == "1.1.0"

                    tools_res = await session.list_tools()
                    names = {t.name for t in tools_res.tools}
                    assert len(names) == 28
                    assert "silhouette_nest_shapes" in names

                    new_res = await session.call_tool(
                        "silhouette_new_design",
                        {"name": "stdio_e2e", "preset": "a4", "overwrite": True},
                    )
                    assert not new_res.is_error

                    rect_res = await session.call_tool(
                        "silhouette_add_rectangle",
                        {"design": "stdio_e2e", "x_mm": 15, "y_mm": 15, "width_mm": 60, "height_mm": 40},
                    )
                    assert not rect_res.is_error

                    txt_res = await session.call_tool(
                        "silhouette_add_text",
                        {"design": "stdio_e2e", "text": "MCP OK", "x_mm": 80, "y_mm": 25, "size_mm": 12},
                    )
                    assert not txt_res.is_error
                    txt_payload = json.loads(txt_res.content[0].text)
                    expected_total = 1 + len(txt_payload["shape_ids"])

                    nest_res = await session.call_tool(
                        "silhouette_nest_shapes",
                        {"design": "stdio_e2e", "spacing_mm": 3.0},
                    )
                    assert not nest_res.is_error
                    nest_payload = json.loads(nest_res.content[0].text)
                    assert nest_payload["placed_count"] == expected_total
                    assert nest_payload["unplaced_count"] == 0

                    exp_res = await session.call_tool(
                        "silhouette_export",
                        {"design": "stdio_e2e", "formats": "dxf,svg,png"},
                    )
                    assert not exp_res.is_error
                    exp_payload = json.loads(exp_res.content[0].text)
                    for fmt in ("dxf", "svg", "png"):
                        fpath = Path(exp_payload["files"][fmt])
                        assert fpath.is_file()
                        assert fpath.stat().st_size > 0

                    del_res = await session.call_tool(
                        "silhouette_delete_design",
                        {"design": "stdio_e2e", "delete_files": True},
                    )
                    assert not del_res.is_error

    anyio.run(_run_session)
    assert err_log_path.is_file()


def test_modular_package_structure_and_exports():
    import importlib
    from pathlib import Path
    import anyio
    from mcp import Client

    modules = (
        "silhouette_mcp",
        "silhouette_mcp.config",
        "silhouette_mcp.config.settings",
        "silhouette_mcp.core",
        "silhouette_mcp.core.exceptions",
        "silhouette_mcp.core.validators",
        "silhouette_mcp.core.models",
        "silhouette_mcp.core.geometry_engine",
        "silhouette_mcp.core.templates",
        "silhouette_mcp.core.templates.models",
        "silhouette_mcp.core.templates.geometry",
        "silhouette_mcp.core.templates.generators",
        "silhouette_mcp.core.nesting",
        "silhouette_mcp.core.nesting.models",
        "silhouette_mcp.core.nesting.collision",
        "silhouette_mcp.core.nesting.maxrects",
        "silhouette_mcp.core.nesting.metrics",
        "silhouette_mcp.persistence",
        "silhouette_mcp.persistence.storage",
        "silhouette_mcp.persistence.repository",
        "silhouette_mcp.exporters",
        "silhouette_mcp.exporters.dxf",
        "silhouette_mcp.exporters.svg",
        "silhouette_mcp.exporters.png",
        "silhouette_mcp.integrations",
        "silhouette_mcp.integrations.silhouette_studio",
        "silhouette_mcp.services",
        "silhouette_mcp.services.document_service",
        "silhouette_mcp.services.geometry_service",
        "silhouette_mcp.services.nesting_service",
        "silhouette_mcp.services.export_service",
        "silhouette_mcp.services.import_service",
        "silhouette_mcp.services.template_service",
        "silhouette_mcp.tools",
        "silhouette_mcp.tools.document",
        "silhouette_mcp.tools.geometry",
        "silhouette_mcp.tools.text",
        "silhouette_mcp.tools.registration",
        "silhouette_mcp.tools.templates",
        "silhouette_mcp.tools.import_export",
        "silhouette_mcp.server",
    )
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None

    pkg_server = importlib.import_module("silhouette_mcp.server")
    assert len(pkg_server.TOOL_REGISTRATIONS) == 28

    async def _list_pkg_tools():
        async with Client(pkg_server.mcp) as client:
            tools_res = await client.list_tools()
            return {t.name for t in tools_res.tools}

    registered_names = anyio.run(_list_pkg_tools)
    expected_names = {fn.__name__ for fn, _ in pkg_server.TOOL_REGISTRATIONS}
    assert len(registered_names) == 28
    assert registered_names == expected_names

    project_root = Path(__file__).resolve().parents[2]
    assert (project_root / "src" / "silhouette_mcp" / "server.py").is_file()
    assert not (project_root / "server.py").exists()
    for subdir in (
        "unit",
        "unit/core",
        "unit/services",
        "unit/tools",
        "unit/exporters",
        "unit/persistence",
        "integration",
        "integration/mcp",
        "integration/persistence",
        "integration/studio",
        "regression",
        "performance",
        "fixtures",
    ):
        assert (project_root / "tests" / subdir).is_dir()

    assert server.mcp is pkg_server.mcp
    for fn, _ in pkg_server.TOOL_REGISTRATIONS:
        assert getattr(server, fn.__name__) is fn
        assert getattr(pkg_server, fn.__name__) is fn


def test_audit_v110_remediation_regressions(tmp_path, monkeypatch):
    from pathlib import Path
    from silhouette_mcp import server as pkg_server
    from silhouette_mcp.config import settings
    from silhouette_mcp.core import models as core_models
    from silhouette_mcp.persistence import repository
    from silhouette_mcp.tools import geometry as tool_geometry

    # 1. Partial nesting respects unselected non-REGMARK obstacles (AUDIT-002)
    pkg_server.silhouette_new_design("rem_partial", width_mm=200, height_mm=200, cut_margin_mm=5.0)
    fixed = pkg_server.silhouette_add_rectangle("rem_partial", 5, 5, 50, 50, label="fixed")
    movable = pkg_server.silhouette_add_rectangle("rem_partial", 10, 10, 30, 20, label="movable")
    partial_res = pkg_server.silhouette_nest_shapes(
        "rem_partial", shape_ids=[movable["shape_id"]], spacing_mm=5.0
    )
    assert partial_res["placed_ids"] == [movable["shape_id"]]
    assert _boxes_min_gap(fixed["bbox_mm"], partial_res["placements"][0]["bbox_mm"]) >= 5.0 - 1e-3
    assert any("unselected shape" in w for w in partial_res["warnings"])

    # 2. Open lines & composite grouping: box-template + geometric holes/engrave (AUDIT-003)
    pkg_server.silhouette_new_design("rem_open", width_mm=150, height_mm=150, cut_margin_mm=5.0)
    open_line = pkg_server.silhouette_add_line("rem_open", 20, 20, 70, 20, layer="CUT", label="slit")
    open_nest = pkg_server.silhouette_nest_shapes("rem_open", spacing_mm=3.0)
    assert open_nest["placed_ids"] == [open_line["shape_id"]]

    pkg_server.silhouette_new_design("rem_comp", preset="a4", cut_margin_mm=5.0)
    tpl_res = pkg_server.silhouette_add_box_template(
        "rem_comp", template="gift-tag", x_mm=40, y_mm=40, width_mm=50, body_height_mm=70, dashed_score=False
    )
    # Also test geometric containment without explicit parent_id (polygon + circle parents)
    outer_cut = pkg_server.silhouette_add_rectangle("rem_comp", 100, 100, 60, 50, label="plate")
    inner_hole = pkg_server.silhouette_add_circle("rem_comp", 130, 125, 8, layer="CUT", label="hole")
    inner_mark = pkg_server.silhouette_add_rectangle("rem_comp", 110, 110, 15, 10, layer="ENGRAVE", label="mark")
    circ_cut = pkg_server.silhouette_add_circle("rem_comp", 40, 200, 25, layer="CUT", label="disc")
    circ_hole = pkg_server.silhouette_add_circle("rem_comp", 40, 200, 6, layer="CUT", label="disc-hole")
    circ_score = pkg_server.silhouette_add_line("rem_comp", 25, 200, 55, 200, layer="SCORE", label="disc-fold")
    nested_comp = pkg_server.silhouette_nest_shapes("rem_comp", spacing_mm=3.0)
    assert nested_comp["placed_count"] == tpl_res["shapes_added"] + 6
    assert nested_comp["utilization_pct"] <= 100.0
    comp_doc = pkg_server.silhouette_get_design("rem_comp")
    comp_by_id = {s["id"]: s for s in comp_doc["shapes"]}
    plate_b = pkg_server._bbox(comp_by_id[outer_cut["shape_id"]])
    for cid in (inner_hole["shape_id"], inner_mark["shape_id"]):
        cb = pkg_server._bbox(comp_by_id[cid])
        assert cb[0] >= plate_b[0] - 1e-3 and cb[1] >= plate_b[1] - 1e-3
        assert cb[2] <= plate_b[2] + 1e-3 and cb[3] <= plate_b[3] + 1e-3
    disc_b = pkg_server._bbox(comp_by_id[circ_cut["shape_id"]])
    for cid in (circ_hole["shape_id"], circ_score["shape_id"]):
        cb = pkg_server._bbox(comp_by_id[cid])
        assert cb[0] >= disc_b[0] - 1e-3 and cb[1] >= disc_b[1] - 1e-3
        assert cb[2] <= disc_b[2] + 1e-3 and cb[3] <= disc_b[3] + 1e-3

    # 3. SVG hardening: MAX_POINTS_PER_SHAPE, scaled bounds, degenerate, self-intersection (AUDIT-004)
    pkg_server.silhouette_new_design("rem_svg", preset="a4")
    circ_svg = tmp_path / "circle.svg"
    circ_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"><circle cx="20" cy="20" r="15"/></svg>',
        encoding="utf-8",
    )
    orig_max_pts = settings.MAX_POINTS_PER_SHAPE
    monkeypatch.setattr(settings, "MAX_POINTS_PER_SHAPE", 6)
    with pytest.raises(ValueError, match="too many points"):
        pkg_server.silhouette_import_svg("rem_svg", str(circ_svg))
    monkeypatch.setattr(settings, "MAX_POINTS_PER_SHAPE", orig_max_pts)

    sq_svg = tmp_path / "sq.svg"
    sq_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect x="0" y="0" width="10" height="10"/></svg>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="maximum coordinate magnitude"):
        pkg_server.silhouette_import_svg("rem_svg", str(sq_svg), target_width_mm=settings.MAX_COORD_MM, x_mm=1000)

    collinear_svg = tmp_path / "collinear.svg"
    collinear_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
        '<polygon points="0,0 10,0 20,0"/></svg>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="zero area"):
        pkg_server.silhouette_import_svg("rem_svg", str(collinear_svg))

    bowtie_svg = tmp_path / "bowtie.svg"
    bowtie_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
        '<polygon points="0,0 30,20 20,0 0,20"/></svg>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="self-intersecting"):
        pkg_server.silhouette_import_svg("rem_svg", str(bowtie_svg))

    # 4. Transform collapse/overflow and duplicate/grid overflow (AUDIT-005)
    pkg_server.silhouette_new_design("rem_trans", width_mm=200, height_mm=200)
    c_id = pkg_server.silhouette_add_circle("rem_trans", 50, 50, 5)["shape_id"]
    with pytest.raises(ValueError, match="collapsed"):
        pkg_server.silhouette_transform_shape("rem_trans", c_id, scale=1e-6)
    with pytest.raises(ValueError, match="exceeds maximum coordinate magnitude"):
        pkg_server.silhouette_transform_shape("rem_trans", c_id, dx_mm=settings.MAX_COORD_MM)
    r_id = pkg_server.silhouette_add_rectangle("rem_trans", 20, 20, 40, 30)["shape_id"]
    with pytest.raises(ValueError, match="collapsed"):
        pkg_server.silhouette_transform_shape("rem_trans", r_id, scale=1e-6)
    with pytest.raises(ValueError, match="maximum coordinate magnitude"):
        pkg_server.silhouette_transform_shape("rem_trans", r_id, dx_mm=settings.MAX_COORD_MM)
    l_id = pkg_server.silhouette_add_line("rem_trans", 10, 10, 50, 10)["shape_id"]
    with pytest.raises(ValueError, match="collapsed"):
        pkg_server.silhouette_transform_shape("rem_trans", l_id, scale=1e-6)
    with pytest.raises(ValueError, match="exceeds maximum coordinate magnitude"):
        pkg_server.silhouette_duplicate_shape("rem_trans", c_id, count=3, dx_mm=settings.MAX_COORD_MM * 0.4, dy_mm=0)
    with pytest.raises(ValueError, match="exceeds maximum coordinate magnitude"):
        pkg_server.silhouette_grid_duplicates("rem_trans", c_id, cols=3, rows=1, spacing_x_mm=settings.MAX_COORD_MM * 0.6)

    # 5. Design schema corruption detection + backup recovery (AUDIT-006)
    invalid_payloads = [
        {"name": "   ", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 1, "shapes": []},
        {"name": "bad", "width_mm": -10, "height_mm": 100, "cut_margin_mm": 5, "next_id": 1, "shapes": []},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": -1, "next_id": 1, "shapes": []},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 1, "shapes": [], "revision": -1},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 2, "shapes": ["not-a-dict"]},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 2, "shapes": [{"id": 0, "kind": "circle", "cx": 10, "cy": 10, "r": 5}]},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 2, "shapes": [{"id": 1, "kind": "circle", "cx": float("nan"), "cy": 10, "r": 5}]},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 2, "shapes": [{"id": 1, "kind": "circle", "cx": 10, "cy": 10, "r": 0}]},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 2, "shapes": [{"id": 1, "kind": "poly", "points": []}]},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 2, "shapes": [{"id": 1, "kind": "poly", "points": [[1]]}]},
        {"name": "bad", "width_mm": 100, "height_mm": 100, "cut_margin_mm": 5, "next_id": 2, "shapes": [{"id": 1, "kind": "mesh"}]},
    ]
    for bad_payload in invalid_payloads:
        with pytest.raises(ValueError, match="Corrupted design"):
            pkg_server._validate_design_dict(bad_payload)
    pkg_server.silhouette_new_design("rem_bak", width_mm=100, height_mm=100)
    pkg_server.silhouette_add_rectangle("rem_bak", 10, 10, 20, 20)
    d_path = pkg_server.OUTPUT_DIR / "rem-bak.design.json"
    d_path.write_text('{"name":"rem_bak","width_mm":0,"height_mm":100,"cut_margin_mm":5,"next_id":2,"shapes":[]}', encoding="utf-8")
    recovered = repository.load_design("rem_bak")
    assert recovered["width_mm"] == 100

    # 6. Describe design revision/layers, inner_arm_safe_area_mm, and calibration alias (AUDIT-008, AUDIT-009)
    reg_res = pkg_server.silhouette_add_registration_marks("rem_bak")
    assert "safe_print_area_mm" in reg_res and "inner_arm_safe_area_mm" in reg_res
    assert reg_res["inner_arm_safe_area_mm"][0] > reg_res["safe_print_area_mm"][0]
    desc = pkg_server.silhouette_describe_design("rem_bak")
    assert desc["revision"] >= 2
    assert desc["layers"].get("CUT") == 1 and desc["layers"].get("REGMARK") == 3

    pkg_server.silhouette_make_calibration_file()
    launched_cmds: list[list[str]] = []

    class _DummyProc:
        def poll(self):
            return None

    monkeypatch.setattr(pkg_server.sys, "platform", "win32")
    monkeypatch.setattr(pkg_server, "_find_studio_exe", lambda: r"C:\fake\Silhouette Studio.exe")
    monkeypatch.setattr(
        "silhouette_mcp.integrations.silhouette_studio.subprocess.Popen",
        lambda args: launched_cmds.append(args) or _DummyProc(),
    )
    alias_res = pkg_server.silhouette_open_in_studio("calibracao_100x100mm.dxf")
    assert Path(alias_res["opened"]).name == "calibration-100mm.dxf"

    # 7. UNC rejection and macOS .app bundle discovery/launch (AUDIT-011)
    with pytest.raises(ValueError, match="UNC"):
        pkg_server.silhouette_import_svg("rem_svg", r"\\evil-host\share\a.svg")
    with pytest.raises(ValueError, match="UNC"):
        pkg_server._resolve_font_path(r"\\evil-host\share\font.ttf")
    with pytest.raises(ValueError, match="UNC"):
        pkg_server.silhouette_open_in_studio(r"\\evil-host\share\cut.dxf")

    fake_app = tmp_path / "Silhouette Studio.app"
    fake_app.mkdir()
    monkeypatch.setattr(pkg_server.sys, "platform", "darwin")
    monkeypatch.setattr(settings, "STUDIO_EXE", str(fake_app))
    monkeypatch.setattr(pkg_server, "STUDIO_EXE", str(fake_app))
    monkeypatch.setattr(
        pkg_server,
        "_find_studio_exe",
        __import__("silhouette_mcp.integrations.silhouette_studio", fromlist=["_find_studio_exe"])._find_studio_exe,
    )
    assert pkg_server._find_studio_exe() == str(fake_app)
    launched_cmds.clear()
    mac_res = pkg_server.silhouette_open_in_studio("calibration-100mm.dxf")
    assert mac_res["process_launched"] is True
    assert launched_cmds[-1][:3] == ["open", "-a", str(fake_app)]

    fake_bin = tmp_path / "silhouette-bin"
    fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(settings, "STUDIO_EXE", str(fake_bin))
    monkeypatch.setattr(pkg_server, "STUDIO_EXE", str(fake_bin))
    assert pkg_server._find_studio_exe() == str(fake_bin)
    launched_cmds.clear()
    mac_bin_res = pkg_server.silhouette_open_in_studio("calibration-100mm.dxf")
    assert mac_bin_res["method"] == f"launched {fake_bin}"
    assert launched_cmds[-1][0] == str(fake_bin)

    # 8. Packaging and layer boundary hygiene (AUDIT-010, AUDIT-013)
    project_root = Path(__file__).resolve().parents[2]
    assert (project_root / "LICENSE").is_file()
    assert "defusedxml" in (project_root / "pyproject.toml").read_text(encoding="utf-8")
    assert hasattr(core_models, "_add_line_to_doc")
    assert "_add_line_to_doc" not in tool_geometry.__all__




