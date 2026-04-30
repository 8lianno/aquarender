"""Validate / orient / resize incoming images. Pure CPU, pure CPython.

CLAUDE.md gotcha: iPhone EXIF orientation must be applied.
PIL.MAX_IMAGE_PIXELS guards us against decompression-bomb pings.
"""
from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from aquarender.errors import (
    ImageTooLargeError,
    ImageTooSmallError,
    UnsupportedFormatError,
    ZipTooLargeError,
    ZipTooManyFilesError,
)

# 30 MP cap on raw pixel count; matches MAX_IMAGE_PIXELS we set globally.
Image.MAX_IMAGE_PIXELS = 30_000_000

SUPPORTED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP", "MPO", "BMP", "GIF"})
SUPPORTED_SUFFIXES: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
)
MIN_SHORT_SIDE = 256
MAX_LONG_SIDE = 4096
RESIZE_TARGET_LONG_SIDE = 2048

ZIP_MAX_BYTES = 1_000_000_000  # 1 GB uncompressed
ZIP_MAX_FILES = 1000


class ImagePreprocessor:
    """Pure-Python image validator. No GPU, no network."""

    def validate(self, image: bytes | Path | Image.Image) -> Image.Image:
        pil = self._load(image)
        pil = ImageOps.exif_transpose(pil)
        if pil.mode != "RGB":
            pil = pil.convert("RGB")

        w, h = pil.size
        short_side = min(w, h)
        long_side = max(w, h)

        if short_side < MIN_SHORT_SIDE:
            raise ImageTooSmallError(w, h, MIN_SHORT_SIDE)

        if long_side > MAX_LONG_SIDE:
            raise ImageTooLargeError(
                f"Image {w}x{h} exceeds {MAX_LONG_SIDE}px long side."
            )

        if long_side > RESIZE_TARGET_LONG_SIDE:
            scale = RESIZE_TARGET_LONG_SIDE / long_side
            pil = pil.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

        return pil

    # ── helpers ──

    def _load(self, image: bytes | Path | Image.Image) -> Image.Image:
        if isinstance(image, Image.Image):
            return image
        if isinstance(image, Path):
            try:
                return Image.open(image)
            except UnidentifiedImageError as e:
                raise UnsupportedFormatError(image.suffix) from e
        if isinstance(image, (bytes, bytearray)):
            try:
                return Image.open(io.BytesIO(bytes(image)))
            except UnidentifiedImageError as e:
                raise UnsupportedFormatError(None) from e
        raise UnsupportedFormatError(type(image).__name__)

    def enumerate_dir(self, path: Path) -> list[Path]:
        if not path.exists() or not path.is_dir():
            return []
        out: list[Path] = []
        for entry in sorted(path.rglob("*")):
            if entry.is_file() and entry.suffix.lower() in SUPPORTED_SUFFIXES:
                out.append(entry)
        return out

    def extract_zip(self, zip_bytes: bytes, dest: Path) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            infos = [zi for zi in zf.infolist() if not zi.is_dir()]
            if len(infos) > ZIP_MAX_FILES:
                raise ZipTooManyFilesError(
                    f"Zip contains {len(infos)} files (max {ZIP_MAX_FILES})."
                )
            total = sum(zi.file_size for zi in infos)
            if total > ZIP_MAX_BYTES:
                raise ZipTooLargeError(
                    f"Zip uncompressed size {total} bytes exceeds {ZIP_MAX_BYTES}."
                )

            extracted: list[Path] = []
            dest_resolved = dest.resolve()
            for info in infos:
                # Defend against zip-slip
                target = (dest / info.filename).resolve()
                try:
                    target.relative_to(dest_resolved)
                except ValueError:
                    continue
                if Path(info.filename).suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(64 * 1024):
                        out.write(chunk)
                extracted.append(target)
            return sorted(extracted)


def to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def iter_paths(paths: Iterable[Path]) -> list[Path]:
    return [p for p in paths if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
