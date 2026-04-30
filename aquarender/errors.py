"""Domain error hierarchy. Every error has a stable `code` so UI/API can map it."""
from __future__ import annotations


class AquaRenderError(Exception):
    code: str = "aquarender.error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)


# ── Preset errors ──────────────────────────────────────────────────────────────


class PresetError(AquaRenderError):
    code = "preset.error"


class PresetNotFoundError(PresetError):
    code = "preset.not_found"

    def __init__(self, preset_id: str) -> None:
        super().__init__(f"Preset '{preset_id}' does not exist.")
        self.preset_id = preset_id


class ImmutableBuiltinError(PresetError):
    code = "preset.immutable_builtin"

    def __init__(self, preset_id: str) -> None:
        super().__init__(f"Preset '{preset_id}' is built-in and cannot be modified.")
        self.preset_id = preset_id


class PresetValidationError(PresetError):
    code = "preset.invalid"


# ── Image errors ───────────────────────────────────────────────────────────────


class InvalidImageError(AquaRenderError):
    code = "image.invalid"


class UnsupportedFormatError(InvalidImageError):
    code = "image.unsupported_format"

    def __init__(self, fmt: str | None) -> None:
        super().__init__(f"Unsupported image format: {fmt!r}")
        self.format = fmt


class ImageTooSmallError(InvalidImageError):
    code = "image.too_small"

    def __init__(self, w: int, h: int, min_side: int) -> None:
        super().__init__(f"Image {w}x{h} below minimum short side of {min_side}px.")
        self.width = w
        self.height = h
        self.min_side = min_side


class ImageTooLargeError(InvalidImageError):
    code = "image.too_large"


class ZipTooLargeError(InvalidImageError):
    code = "zip.too_large"


class ZipTooManyFilesError(InvalidImageError):
    code = "zip.too_many_files"


# ── Engine errors ──────────────────────────────────────────────────────────────


class EngineNotConnectedError(AquaRenderError):
    code = "engine.not_connected"


class TunnelDownError(AquaRenderError):
    code = "engine.tunnel_down"

    def __init__(self, base_url: str, reason: str) -> None:
        super().__init__(f"Engine at {base_url} unreachable: {reason}")
        self.base_url = base_url
        self.reason = reason


class EngineError(AquaRenderError):
    code = "engine.error"

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class GenerationTimeoutError(EngineError):
    code = "engine.timeout"


class GenerationFailedError(EngineError):
    code = "engine.generation_failed"


class CheckpointMissingError(EngineError):
    code = "engine.checkpoint_missing"

    def __init__(self, name: str) -> None:
        super().__init__(f"Checkpoint '{name}' not loaded on remote engine.")
        self.name = name


class LoraMissingError(EngineError):
    code = "engine.lora_missing"

    def __init__(self, name: str) -> None:
        super().__init__(f"LoRA '{name}' not loaded on remote engine.")
        self.name = name


class ControlNetMissingError(EngineError):
    code = "engine.controlnet_missing"

    def __init__(self, name: str) -> None:
        super().__init__(f"ControlNet '{name}' not loaded on remote engine.")
        self.name = name


# ── Job errors ─────────────────────────────────────────────────────────────────


class JobNotFoundError(AquaRenderError):
    code = "job.not_found"

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job '{job_id}' not found.")
        self.job_id = job_id


class JobCannotResumeError(AquaRenderError):
    code = "job.cannot_resume"
