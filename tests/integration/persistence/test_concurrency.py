"""Integration tests for re-entrant locking and concurrent persistence serialization."""

from __future__ import annotations

import concurrent.futures

from silhouette_mcp.services import document_service, geometry_service


def test_concurrent_thread_updates_preserve_all_shapes_and_revisions(isolated_output_dir):
    document_service.new_design("concurrent_threads", width_mm=300, height_mm=300)

    def add_circle_worker(idx: int) -> int:
        res = geometry_service.add_circle(
            "concurrent_threads",
            cx_mm=20.0 + (idx % 5) * 30.0,
            cy_mm=20.0 + (idx // 5) * 30.0,
            radius_mm=8.0,
            label=f"c-{idx}",
        )
        return res["shape_id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        shape_ids = list(pool.map(add_circle_worker, range(20)))

    assert len(set(shape_ids)) == 20
    doc = document_service.get_design("concurrent_threads")
    assert len(doc["shapes"]) == 20
    assert doc["revision"] == 21  # 1 create + 20 serialized shape saves

