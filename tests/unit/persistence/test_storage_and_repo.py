"""Unit tests for `persistence.storage` and `persistence.repository`."""

from __future__ import annotations

import json
import pytest

from silhouette_mcp.core.exceptions import SilhouetteValueError
from silhouette_mcp.persistence.repository import load_design, save_design
from silhouette_mcp.persistence.storage import _LOCK, _atomic_write_file, _backup_path, _design_path


def test_repository_save_backup_and_corruption_recovery(isolated_output_dir):
    doc = {
        "name": "repo_unit",
        "width_mm": 210.0,
        "height_mm": 297.0,
        "cut_margin_mm": 5.0,
        "next_id": 2,
        "revision": 0,
        "shapes": [
            {"id": 1, "label": "rect", "layer": "CUT", "kind": "poly", "closed": True, "points": [[10, 10], [30, 10], [30, 30], [10, 30]]}
        ],
    }
    with _LOCK:
        save_design(doc)

    p = _design_path("repo_unit")
    bak = _backup_path("repo_unit")
    assert p.is_file()
    assert bak.is_file()
    assert json.loads(p.read_text(encoding="utf-8"))["revision"] == 1

    # Corrupt primary JSON -> load_design must automatically heal from .bak
    p.write_text("{corrupt-json", encoding="utf-8")
    recovered = load_design("repo_unit")
    assert recovered["name"] == "repo_unit"
    assert len(recovered["shapes"]) == 1
    # Primary must be healed back to valid JSON
    assert json.loads(p.read_text(encoding="utf-8"))["name"] == "repo_unit"

    # Corrupt both primary and backup -> clear domain error
    p.write_text("{bad", encoding="utf-8")
    bak.write_text("{bad", encoding="utf-8")
    with pytest.raises(SilhouetteValueError, match="corrupted"):
        load_design("repo_unit")


def test_atomic_write_file_cleans_up_temp_on_failure(isolated_output_dir):
    target = isolated_output_dir / "atomic_target.json"

    def broken_writer(tmp_path):
        tmp_path.write_text("partial", encoding="utf-8")
        raise RuntimeError("boom during write")

    with pytest.raises(RuntimeError, match="boom during write"):
        _atomic_write_file(target, ".unit.tmp", broken_writer)

    assert not target.exists()
    assert list(isolated_output_dir.glob("*.unit.tmp")) == []

