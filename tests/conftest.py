"""Shared test fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from aquarender.core.metadata import MetadataWriter
from aquarender.core.orchestrator import JobOrchestrator
from aquarender.core.preprocessor import ImagePreprocessor
from aquarender.core.presets import PresetService
from aquarender.db.models import Base
from aquarender.db.repo import (
    EngineSessionRepository,
    JobRepository,
    OutputRepository,
    PresetRepository,
)
from aquarender.db.session import make_engine, make_session_factory
from aquarender.engine.fakes import FakeRemoteComfyUIClient
from aquarender.engine.workflows import WorkflowBuilder, default_template_path


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(db_url)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def preset_service(db_session: Session) -> PresetService:
    repo = PresetRepository(db_session)
    # Seed builtin presets

    return PresetService(repo)


@pytest.fixture
def seeded_preset_service(db_session: Session) -> PresetService:
    """Preset service with the four built-in presets present."""
    import json
    from importlib import resources

    repo = PresetRepository(db_session)
    pkg = resources.files("aquarender.presets")
    for filename in (
        "soft_watercolor.json",
        "ink_watercolor.json",
        "childrens_book.json",
        "product_watercolor.json",
    ):
        with (pkg / filename).open("r") as f:
            data = json.load(f)
        repo.create(
            preset_id=data["id"],
            name=data["name"],
            description=data.get("description"),
            params=data["params"],
            is_builtin=True,
        )
    db_session.commit()
    return PresetService(repo)


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """A 1024x768 PNG fixture."""
    p = tmp_path / "sample.png"
    img = Image.new("RGB", (1024, 768), color=(120, 160, 200))
    img.save(p, "PNG")
    return p


@pytest.fixture
def small_png(tmp_path: Path) -> Path:
    """100x100 — too small."""
    p = tmp_path / "small.png"
    Image.new("RGB", (100, 100)).save(p, "PNG")
    return p


@pytest.fixture
def fake_client(tmp_path: Path) -> FakeRemoteComfyUIClient:
    fixture = tmp_path / "fake_output.png"
    Image.new("RGB", (1024, 1024), color=(180, 200, 220)).save(fixture, "PNG")
    return FakeRemoteComfyUIClient(fixture_image=fixture)


@pytest.fixture
def orchestrator(
    tmp_path: Path,
    db_session: Session,
    seeded_preset_service: PresetService,
    fake_client: FakeRemoteComfyUIClient,
) -> JobOrchestrator:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    job_repo = JobRepository(db_session)
    output_repo = OutputRepository(db_session)
    session_repo = EngineSessionRepository(db_session)
    metadata = MetadataWriter(outputs)
    preprocessor = ImagePreprocessor()
    workflow = WorkflowBuilder(default_template_path())

    orch = JobOrchestrator(
        client=None,
        preset_service=seeded_preset_service,
        preprocessor=preprocessor,
        metadata_writer=metadata,
        workflow_builder=workflow,
        job_repo=job_repo,
        output_repo=output_repo,
        session_repo=session_repo,
        outputs_dir=outputs,
        commit=db_session.commit,
    )

    import asyncio

    asyncio.run(orch.connect(fake_client, engine_type_hint="kaggle"))
    return orch
