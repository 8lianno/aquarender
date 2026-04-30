from __future__ import annotations

from aquarender.engine.types import ImageRef
from aquarender.engine.workflows import WorkflowBuilder, default_template_path
from aquarender.params import (
    ControlNetParams,
    LoraParams,
    ModelParams,
    OutputParams,
    PromptParams,
    ResolvedParams,
    SamplerParams,
)


def _params() -> ResolvedParams:
    return ResolvedParams(
        model=ModelParams(checkpoint="sd_xl_base_1.0.safetensors"),
        lora=LoraParams(name="my.safetensors", weight=0.7),
        controlnet=ControlNetParams(
            model="cn.safetensors", preprocessor="lineart_realistic", strength=0.5
        ),
        sampler=SamplerParams(name="dpmpp_2m_sde", scheduler="karras", steps=20, cfg=4.0, denoise=0.4),
        prompt=PromptParams(positive="hello", negative="world"),
        output=OutputParams(width=1024, height=1024),
    )


def test_build_substitutes_inputs() -> None:
    wb = WorkflowBuilder(default_template_path())
    wf = wb.build(ImageRef(name="abc.png"), _params(), seed=12345)

    assert wf["1"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"
    assert wf["2"]["inputs"]["lora_name"] == "my.safetensors"
    assert wf["2"]["inputs"]["strength_model"] == 0.7
    assert wf["3"]["inputs"]["text"] == "hello"
    assert wf["4"]["inputs"]["text"] == "world"
    assert wf["5"]["inputs"]["image"] == "abc.png"
    assert wf["7"]["inputs"]["control_net_name"] == "cn.safetensors"
    assert wf["8"]["inputs"]["seed"] == 12345
    assert wf["8"]["inputs"]["denoise"] == 0.4
    assert wf["10"]["inputs"]["strength"] == 0.5


def test_build_does_not_mutate_template() -> None:
    wb = WorkflowBuilder(default_template_path())
    wf1 = wb.build(ImageRef(name="a.png"), _params(), seed=1)
    wf2 = wb.build(ImageRef(name="b.png"), _params(), seed=2)
    assert wf1["5"]["inputs"]["image"] == "a.png"
    assert wf2["5"]["inputs"]["image"] == "b.png"
    assert wf1["8"]["inputs"]["seed"] == 1
    assert wf2["8"]["inputs"]["seed"] == 2
