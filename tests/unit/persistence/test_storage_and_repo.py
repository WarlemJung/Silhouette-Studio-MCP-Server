"""Unit tests for `persistence.storage` and `persistence.repository`."""

from __future__ import annotations

import json
import os
import time

import pytest

from silhouette_mcp.core.exceptions import SilhouetteValueError
from silhouette_mcp.persistence import repository, storage
from silhouette_mcp.persistence.repository import load_design, save_design
from silhouette_mcp.persistence.storage import (
    _LOCK,
    _atomic_write_file,
    _backup_path,
    _cleanup_stale_temp_files,
    _design_path,
)


def _sample_doc(name: str = "repo_unit", *, revision: int = 0) -> dict:
    return {
        "name": name,
        "width_mm": 210.0,
        "height_mm": 297.0,
        "cut_margin_mm": 5.0,
        "next_id": 2,
        "revision": revision,
        "shapes": [
            {
                "id": 1,
                "label": "rect",
                "layer": "CUT",
                "kind": "poly",
                "closed": True,
                "points": [[10, 10], [30, 10], [30, 30], [10, 30]],
            }
        ],
    }


def test_repository_save_backup_and_corruption_recovery(isolated_output_dir):
    doc = _sample_doc()
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


def test_save_rejects_invalid_document_without_mutating_revision_or_disk(isolated_output_dir):
    doc = _sample_doc("invalid_guard")
    with _LOCK:
        save_design(doc)
    assert doc["revision"] == 1

    # Non-finite coordinate must fail before writing or incrementing revision.
    doc["shapes"][0]["points"][0] = [float("nan"), 10.0]
    with _LOCK:
        with pytest.raises(SilhouetteValueError, match="Corrupted design"):
            save_design(doc)

    assert doc["revision"] == 1
    assert json.loads(_design_path("invalid_guard").read_text(encoding="utf-8"))["revision"] == 1
    assert json.loads(_backup_path("invalid_guard").read_text(encoding="utf-8"))["revision"] == 1
    assert list(isolated_output_dir.glob("*.tmp")) == []

    # Invalid revision type must also fail cleanly without mutation.
    bad_rev = _sample_doc("invalid_guard")
    bad_rev["revision"] = True  # type: ignore[assignment]
    with _LOCK:
        with pytest.raises(SilhouetteValueError, match="invalid 'revision'"):
            save_design(bad_rev)
    assert bad_rev["revision"] is True


def test_save_failure_during_replace_or_fsync_preserves_revision_and_cleans_tmp(
    isolated_output_dir, monkeypatch
):
    doc = _sample_doc("atomic_rollback")
    with _LOCK:
        save_design(doc)
    assert doc["revision"] == 1

    # Remove .bak first so we also verify pre-replace backup preservation when primary already exists.
    bak = _backup_path("atomic_rollback")
    bak.unlink()

    def failing_replace(src, dst, retries=6, delay_s=0.015):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(repository, "_atomic_replace", failing_replace)
    with _LOCK:
        with pytest.raises(OSError, match="simulated atomic replace failure"):
            save_design(doc)

    assert doc["revision"] == 1
    assert json.loads(_design_path("atomic_rollback").read_text(encoding="utf-8"))["revision"] == 1
    assert bak.is_file()
    assert json.loads(bak.read_text(encoding="utf-8"))["revision"] == 1
    assert list(isolated_output_dir.glob("*.tmp")) == []

    monkeypatch.undo()

    def failing_fsync(_fd):
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with _LOCK:
        with pytest.raises(OSError, match="simulated fsync failure"):
            save_design(doc)

    assert doc["revision"] == 1
    assert list(isolated_output_dir.glob("*.tmp")) == []


def test_save_backup_failure_preserves_committed_primary_and_prior_backup(
    isolated_output_dir, monkeypatch
):
    doc = _sample_doc("backup_preserve")
    with _LOCK:
        save_design(doc)
    assert doc["revision"] == 1

    real_atomic_write = storage._atomic_write_file

    def fail_on_backup(target_path, suffix, writer):
        if suffix == ".bak.tmp":
            raise OSError("simulated backup disk full")
        return real_atomic_write(target_path, suffix, writer)

    monkeypatch.setattr(repository, "_atomic_write_file", fail_on_backup)

    with _LOCK:
        save_design(doc)

    assert doc["revision"] == 2
    assert json.loads(_design_path("backup_preserve").read_text(encoding="utf-8"))["revision"] == 2
    assert json.loads(_backup_path("backup_preserve").read_text(encoding="utf-8"))["revision"] == 1


def test_cleanup_stale_temp_files_and_recovery_write_failure(isolated_output_dir, monkeypatch):
    stale_tmp = isolated_output_dir / "abandoned.tmp"
    fresh_tmp = isolated_output_dir / "active.tmp"
    stale_tmp.write_text("stale", encoding="utf-8")
    fresh_tmp.write_text("fresh", encoding="utf-8")
    old_ts = time.time() - 7200.0
    os.utime(stale_tmp, (old_ts, old_ts))

    doc = _sample_doc("cleanup_and_recover")
    with _LOCK:
        save_design(doc)

    # Stale tmp (>1h) was cleaned during save, fresh tmp remains untouched.
    assert not stale_tmp.exists()
    assert fresh_tmp.is_file()
    assert _cleanup_stale_temp_files(isolated_output_dir, max_age_s=0.0) == 1
    assert not fresh_tmp.exists()

    # Corrupt primary and force recovery write failure during load_design.
    _design_path("cleanup_and_recover").write_text("{broken", encoding="utf-8")

    def fail_recovery(target_path, suffix, writer):
        raise OSError("read-only recovery target")

    monkeypatch.setattr(repository, "_atomic_write_file", fail_recovery)
    with pytest.raises(SilhouetteValueError, match="backup recovery failed"):
        load_design("cleanup_and_recover")
