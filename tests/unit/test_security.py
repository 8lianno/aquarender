"""Smoke tests that codify the security posture documented in SECURITY.md.

If any of these fail, treat it as a regression — read SECURITY.md before
relaxing them.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from aquarender.config import Settings
from aquarender.core.preprocessor import (
    MAX_LONG_SIDE,
    MIN_SHORT_SIDE,
    ZIP_MAX_FILES,
    ImagePreprocessor,
)
from aquarender.errors import ImageTooSmallError, ZipTooManyFilesError


def test_settings_repr_redacts_engine_secret(monkeypatch) -> None:
    monkeypatch.setenv("AQUARENDER_ENGINE_SECRET", "super-secret-token")
    cfg = Settings.from_env()
    assert "super-secret-token" not in repr(cfg)
    # The value is still accessible by name — just not via repr.
    assert cfg.engine_secret == "super-secret-token"


def test_zip_extract_rejects_zip_slip(tmp_path: Path) -> None:
    """A zip containing `../escape.png` must not write outside dest."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        Image.new("RGB", (1024, 1024)).save(p := io.BytesIO(), "PNG")
        zf.writestr("../../escape.png", p.getvalue())
        zf.writestr("ok.png", p.getvalue())

    extracted = ImagePreprocessor().extract_zip(buf.getvalue(), tmp_path / "x")
    # Only the safe entry survives, contained under tmp_path/x.
    for path in extracted:
        assert tmp_path in path.parents
    # The traversal entry is silently dropped.
    assert not (tmp_path.parent / "escape.png").exists()


def test_zip_extract_rejects_too_many_files(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(ZIP_MAX_FILES + 1):
            zf.writestr(f"img_{i}.png", b"data")
    with pytest.raises(ZipTooManyFilesError):
        ImagePreprocessor().extract_zip(buf.getvalue(), tmp_path / "x")


def test_image_too_small_is_typed_error(tmp_path: Path) -> None:
    p = tmp_path / "tiny.png"
    Image.new("RGB", (MIN_SHORT_SIDE - 1, MIN_SHORT_SIDE)).save(p, "PNG")
    with pytest.raises(ImageTooSmallError):
        ImagePreprocessor().validate(p)


def test_huge_image_is_resized_not_rejected(tmp_path: Path) -> None:
    """Up to MAX_LONG_SIDE we resize, only above that do we reject."""
    p = tmp_path / "ok.png"
    Image.new("RGB", (3000, 2000)).save(p, "PNG")
    out = ImagePreprocessor().validate(p)
    assert max(out.size) <= 2048
    assert max(out.size) <= MAX_LONG_SIDE
