from __future__ import annotations

import pytest

from aquarender.core.presets import PresetService
from aquarender.errors import (
    ImmutableBuiltinError,
    PresetNotFoundError,
    PresetValidationError,
)
from aquarender.params import SliderOverrides


def test_list_builtins(seeded_preset_service: PresetService) -> None:
    presets = seeded_preset_service.list()
    ids = {p.id for p in presets}
    assert ids == {"soft_watercolor", "ink_watercolor", "childrens_book", "product_watercolor"}
    assert all(p.is_builtin for p in presets)


def test_get_unknown_raises(seeded_preset_service: PresetService) -> None:
    with pytest.raises(PresetNotFoundError):
        seeded_preset_service.get("nope")


def test_merge_strong_watercolor(seeded_preset_service: PresetService) -> None:
    preset = seeded_preset_service.get("soft_watercolor")
    merged = seeded_preset_service.merge(
        preset, SliderOverrides(watercolor_strength="Strong")
    )
    assert merged.sampler.denoise == 0.65
    assert merged.lora.weight == 1.0


def test_merge_low_preservation(seeded_preset_service: PresetService) -> None:
    preset = seeded_preset_service.get("soft_watercolor")
    merged = seeded_preset_service.merge(
        preset, SliderOverrides(structure_preservation="Low")
    )
    assert merged.controlnet.strength == 0.5


def test_merge_custom_lora(seeded_preset_service: PresetService) -> None:
    preset = seeded_preset_service.get("soft_watercolor")
    merged = seeded_preset_service.merge(
        preset, SliderOverrides(custom_lora="my_custom_lora.safetensors")
    )
    assert merged.lora.name == "my_custom_lora.safetensors"


def test_cannot_modify_builtin(seeded_preset_service: PresetService) -> None:
    preset = seeded_preset_service.get("soft_watercolor")
    with pytest.raises(ImmutableBuiltinError):
        seeded_preset_service.update("soft_watercolor", preset.params)
    with pytest.raises(ImmutableBuiltinError):
        seeded_preset_service.delete("soft_watercolor")


def test_create_invalid_id(seeded_preset_service: PresetService) -> None:
    preset = seeded_preset_service.get("soft_watercolor")
    with pytest.raises(PresetValidationError):
        seeded_preset_service.create(
            preset_id="BAD ID", name="x", params=preset.params
        )


def test_export_roundtrip(seeded_preset_service: PresetService) -> None:
    exported = seeded_preset_service.export("soft_watercolor")
    # Re-import lands as a user_ preset
    imported = seeded_preset_service.import_(exported)
    assert imported.id.startswith("user_")
    assert imported.params.lora.weight == exported["params"]["lora"]["weight"]
