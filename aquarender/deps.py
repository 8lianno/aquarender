"""Dependency wiring used by CLI and Streamlit. The only place that builds the graph.

UI layer should call helpers here instead of touching engine/ or db/ directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aquarender.config import Settings
from aquarender.core.metadata import EngineContext, MetadataWriter
from aquarender.core.orchestrator import JobOrchestrator
from aquarender.core.preprocessor import ImagePreprocessor
from aquarender.core.presets import PresetService
from aquarender.db.repo import (
    EngineSessionRepository,
    JobRepository,
    OutputRepository,
    PresetRepository,
)
from aquarender.db.session import make_engine, make_session_factory
from aquarender.engine.client import RemoteComfyUIClient
from aquarender.engine.types import EngineInfo
from aquarender.engine.workflows import WorkflowBuilder, default_template_path


@dataclass(slots=True)
class AquaRenderContext:
    settings: Settings
    orchestrator: JobOrchestrator
    preset_service: PresetService
    workflow_path: Path


def build_context(settings: Settings | None = None) -> AquaRenderContext:
    cfg = settings or Settings.from_env()
    cfg.ensure_dirs()

    engine = make_engine(cfg.db_url)
    factory = make_session_factory(engine)
    db_session = factory()  # process-long; SQLite single-writer is fine here

    preset_repo = PresetRepository(db_session)
    job_repo = JobRepository(db_session)
    output_repo = OutputRepository(db_session)
    session_repo = EngineSessionRepository(db_session)

    presets = PresetService(preset_repo)
    preprocessor = ImagePreprocessor()
    metadata = MetadataWriter(cfg.outputs_dir)
    template = default_template_path()
    workflow = WorkflowBuilder(template)

    orchestrator = JobOrchestrator(
        client=None,
        preset_service=presets,
        preprocessor=preprocessor,
        metadata_writer=metadata,
        workflow_builder=workflow,
        job_repo=job_repo,
        output_repo=output_repo,
        session_repo=session_repo,
        outputs_dir=cfg.outputs_dir,
        commit=db_session.commit,
    )

    return AquaRenderContext(
        settings=cfg,
        orchestrator=orchestrator,
        preset_service=presets,
        workflow_path=template,
    )


async def connect_engine(
    ctx: AquaRenderContext, *, url: str, secret: str | None = None
) -> tuple[EngineInfo, EngineContext]:
    """Build a remote ComfyUI client, hand it to the orchestrator, return health info.

    UI calls this instead of constructing RemoteComfyUIClient itself.
    """
    client = RemoteComfyUIClient(url, secret=secret)
    engine_ctx = await ctx.orchestrator.connect(client)
    info = await client.health()
    return info, engine_ctx
