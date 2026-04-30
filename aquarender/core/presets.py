"""Preset CRUD + slider→params merge."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from aquarender.db.repo import PresetRepository
from aquarender.errors import (
    ImmutableBuiltinError,
    PresetNotFoundError,
    PresetValidationError,
)
from aquarender.params import (
    SLIDER_TO_PARAMS,
    LoraParams,
    ResolvedParams,
    SliderOverrides,
)

_USER_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")


@dataclass(slots=True, frozen=True)
class Preset:
    id: str
    name: str
    description: str | None
    params: ResolvedParams
    is_builtin: bool


class PresetService:
    def __init__(self, repo: PresetRepository) -> None:
        self._repo = repo

    # ── read ──

    def list(self, *, include_user: bool = True) -> list[Preset]:
        return [_to_preset(row) for row in self._repo.list(include_user=include_user)]

    def get(self, preset_id: str) -> Preset:
        row = self._repo.get(preset_id)
        if row is None:
            raise PresetNotFoundError(preset_id)
        return _to_preset(row)

    # ── write ──

    def create(
        self,
        *,
        preset_id: str,
        name: str,
        params: ResolvedParams,
        description: str | None = None,
    ) -> Preset:
        if not _USER_ID_RE.match(preset_id):
            raise PresetValidationError(
                f"Invalid preset id {preset_id!r}; lowercase, digits, underscores, ≤ 64 chars."
            )
        existing = self._repo.get(preset_id)
        if existing is not None:
            raise PresetValidationError(f"Preset {preset_id!r} already exists.")
        row = self._repo.create(
            preset_id=preset_id,
            name=name,
            description=description,
            params=params.model_dump(),
            is_builtin=False,
        )
        return _to_preset(row)

    def update(self, preset_id: str, params: ResolvedParams) -> Preset:
        row = self._repo.get(preset_id)
        if row is None:
            raise PresetNotFoundError(preset_id)
        if row.is_builtin:
            raise ImmutableBuiltinError(preset_id)
        updated = self._repo.update_params(preset_id, params.model_dump())
        assert updated is not None
        return _to_preset(updated)

    def delete(self, preset_id: str) -> None:
        row = self._repo.get(preset_id)
        if row is None:
            raise PresetNotFoundError(preset_id)
        if row.is_builtin:
            raise ImmutableBuiltinError(preset_id)
        self._repo.delete(preset_id)

    # ── import/export ──

    def export(self, preset_id: str) -> dict[str, Any]:
        preset = self.get(preset_id)
        return {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
            "params": preset.params.model_dump(),
        }

    def import_(self, data: dict[str, Any]) -> Preset:
        try:
            params = ResolvedParams.model_validate(data["params"])
        except Exception as e:
            raise PresetValidationError(f"Invalid imported preset: {e}") from e
        raw_id = str(data.get("id", "imported"))
        new_id = (
            raw_id if raw_id.startswith("user_") else f"user_{re.sub(r'[^a-z0-9_]', '_', raw_id.lower())}"
        )
        if not _USER_ID_RE.match(new_id):
            raise PresetValidationError(f"Imported preset id is not safe: {new_id!r}")
        # Disambiguate if collision
        candidate = new_id
        suffix = 2
        while self._repo.get(candidate) is not None:
            candidate = f"{new_id}_{suffix}"
            suffix += 1
        return self.create(
            preset_id=candidate,
            name=str(data.get("name", candidate)),
            description=data.get("description"),
            params=params,
        )

    # ── merge sliders into params ──

    def merge(self, preset: Preset, overrides: SliderOverrides | None) -> ResolvedParams:
        params = preset.params.model_copy(deep=True)
        if overrides is None:
            return params

        if overrides.watercolor_strength is not None:
            mapping = SLIDER_TO_PARAMS["watercolor_strength"][overrides.watercolor_strength]
            params.sampler.denoise = mapping["denoise"]
            params.lora.weight = mapping["lora_weight"]

        if overrides.structure_preservation is not None:
            mapping = SLIDER_TO_PARAMS["structure_preservation"][overrides.structure_preservation]
            params.controlnet.strength = mapping["cn_strength"]

        if overrides.output_size is not None:
            params.output.width = overrides.output_size
            params.output.height = overrides.output_size

        if overrides.custom_lora is not None and overrides.custom_lora.strip():
            params.lora = LoraParams(name=overrides.custom_lora.strip(), weight=params.lora.weight)

        return params


def _to_preset(row) -> Preset:  # type: ignore[no-untyped-def]
    raw = json.loads(row.params_json)
    return Preset(
        id=row.id,
        name=row.name,
        description=row.description,
        params=ResolvedParams.model_validate(raw),
        is_builtin=bool(row.is_builtin),
    )
