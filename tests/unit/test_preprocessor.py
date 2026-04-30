from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from aquarender.core.preprocessor import ImagePreprocessor
from aquarender.errors import ImageTooSmallError, ZipTooManyFilesError


def test_validate_resizes_huge_image(tmp_path: Path) -> None:
    p = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000)).save(p, "PNG")
    out = ImagePreprocessor().validate(p)
    assert max(out.size) <= 2048


def test_validate_rejects_tiny(small_png: Path) -> None:
    with pytest.raises(ImageTooSmallError):
        ImagePreprocessor().validate(small_png)


def test_validate_strips_alpha(tmp_path: Path) -> None:
    p = tmp_path / "rgba.png"
    Image.new("RGBA", (1024, 1024), (10, 20, 30, 200)).save(p, "PNG")
    out = ImagePreprocessor().validate(p)
    assert out.mode == "RGB"


def test_extract_zip_rejects_many_files(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(1001):
            zf.writestr(f"img_{i}.png", b"data")
    with pytest.raises(ZipTooManyFilesError):
        ImagePreprocessor().extract_zip(buf.getvalue(), tmp_path / "extracted")


def test_extract_zip_only_supported(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        Image.new("RGB", (1024, 1024)).save(buf2 := io.BytesIO(), "PNG")
        zf.writestr("ok.png", buf2.getvalue())
        zf.writestr("notes.txt", b"hello")
    files = ImagePreprocessor().extract_zip(buf.getvalue(), tmp_path / "x")
    assert len(files) == 1
    assert files[0].suffix == ".png"


def test_validate_bytes_path(tmp_path: Path, sample_png: Path) -> None:
    pre = ImagePreprocessor()
    out = pre.validate(sample_png.read_bytes())
    assert out.size == (1024, 768)
