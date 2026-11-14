"""Automated latency and scale sanity benchmarks across core workflows."""

from __future__ import annotations

import time
from pathlib import Path

from silhouette_mcp.services import (
    document_service,
    export_service,
    geometry_service,
    nesting_service,
)


def test_benchmark_nesting_40_shapes_with_rotation(isolated_output_dir):
    document_service.new_design("bench_nest", width_mm=304.8, height_mm=304.8)
    for i in range(40):
        w = 18.0 + (i % 5) * 4.0
        h = 12.0 + (i % 3) * 5.0
        geometry_service.add_rectangle("bench_nest", 10.0, 10.0, w, h, label=f"p{i}")

    t0 = time.perf_counter()
    res = nesting_service.nest_shapes(
        "bench_nest", spacing_mm=2.0, allow_rotation=True, rotation_step_deg=45.0
    )
    elapsed_s = time.perf_counter() - t0

    assert res["placed_count"] == 40
    assert elapsed_s < 5.0


def test_benchmark_exports_and_preview_generation(isolated_output_dir):
    document_service.new_design("bench_export", width_mm=304.8, height_mm=304.8)
    for i in range(60):
        x = 15.0 + (i % 10) * 26.0
        y = 15.0 + (i // 10) * 26.0
        if i % 2 == 0:
            geometry_service.add_rectangle("bench_export", x, y, 20.0, 18.0, corner_radius_mm=2.0, layer="CUT")
        else:
            geometry_service.add_circle("bench_export", x + 10.0, y + 9.0, 8.0, layer="SCORE")

    t0 = time.perf_counter()
    exp = export_service.export_design("bench_export", formats="dxf,svg,png")
    export_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    prev = export_service.render_preview("bench_export", dpi=150, filename="bench_preview")
    preview_s = time.perf_counter() - t1

    assert all(Path(p).is_file() for p in exp["files"].values())
    assert Path(prev["png_path"]).is_file()
    assert export_s < 8.0
    assert preview_s < 8.0


def test_benchmark_persistence_roundtrip_250_shapes(isolated_output_dir):
    document_service.new_design("bench_persist", width_mm=500.0, height_mm=500.0)
    r = geometry_service.add_rectangle("bench_persist", 15, 15, 12, 12)
    geometry_service.grid_duplicates("bench_persist", r["shape_id"], cols=16, rows=16, spacing_x_mm=3.0, spacing_y_mm=3.0)

    t0 = time.perf_counter()
    desc = document_service.describe_design("bench_persist")
    elapsed_s = time.perf_counter() - t0

    assert desc["shape_count"] == 256
    assert elapsed_s < 3.0

