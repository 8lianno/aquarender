"""Click CLI entry point: aquarender start|doctor|migrate."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from aquarender import __version__
from aquarender.config import Settings
from aquarender.deps import build_context
from aquarender.logging_setup import configure_logging, get_logger

log = get_logger(__name__)


@click.group(invoke_without_command=False)
@click.version_option(__version__, prog_name="aquarender")
def cli() -> None:
    """AquaRender — local control plane for the remote ComfyUI engine."""
    configure_logging()


@cli.command()
@click.option("--port", default=8501, type=int, help="Streamlit port.")
@click.option("--host", default="localhost", help="Streamlit bind address.")
@click.option(
    "--external-comfy",
    default=None,
    help="Skip Connect tab and pre-fill this engine URL.",
)
def start(port: int, host: str, external_comfy: str | None) -> None:
    """Run the Streamlit UI on localhost:8501 by default."""
    if external_comfy:
        os.environ["AQUARENDER_ENGINE_URL"] = external_comfy
    app_path = Path(__file__).parent / "ui" / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        f"--server.port={port}",
        f"--server.address={host}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    click.echo(f"→ {' '.join(cmd)}")
    sys.exit(subprocess.call(cmd))


@cli.command()
def migrate() -> None:
    """Run alembic upgrade head."""
    cfg = Settings.from_env()
    os.environ.setdefault("AQUARENDER_DB_URL", cfg.db_url)
    cmd = [sys.executable, "-m", "alembic", "upgrade", "head"]
    click.echo(f"→ {' '.join(cmd)}")
    sys.exit(subprocess.call(cmd))


@cli.command()
def doctor() -> None:
    """Verify env, DB, outputs dir, optional engine connectivity."""
    cfg = Settings.from_env()
    cfg.ensure_dirs()

    click.echo(f"AquaRender {__version__}")
    click.echo(f"  Python:        {sys.version.split()[0]}")
    click.echo(f"  DB URL:        {cfg.db_url}")
    click.echo(f"  Outputs dir:   {cfg.outputs_dir}  (writable: {os.access(cfg.outputs_dir, os.W_OK)})")
    click.echo(f"  Inputs dir:    {cfg.inputs_dir}")

    # Disk free
    if shutil.which("df"):
        try:
            usage = shutil.disk_usage(cfg.outputs_dir)
            click.echo(f"  Disk free:     {usage.free / 1e9:.1f} GB")
        except OSError:
            pass

    # Run import-time wiring as a smoke test
    try:
        build_context(cfg)
        click.echo("  Wiring:        ok")
    except Exception as e:
        click.echo(f"  Wiring:        FAILED ({e})", err=True)
        sys.exit(1)

    # Optional engine probe
    engine_url = cfg.engine_url
    if engine_url:
        click.echo(f"\nEngine probe → {engine_url}")
        import asyncio

        from aquarender.engine.client import RemoteComfyUIClient
        from aquarender.errors import TunnelDownError

        async def _probe() -> None:
            client = RemoteComfyUIClient(engine_url, secret=cfg.engine_secret)
            try:
                info = await client.health()
                click.echo(f"  GPU:           {info.gpu_name}")
                click.echo(f"  ComfyUI:       {info.comfyui_version}")
                click.echo(
                    f"  Models:        {len(info.available_checkpoints)} ckpts, "
                    f"{len(info.available_loras)} loras, "
                    f"{len(info.available_controlnets)} controlnets"
                )
            finally:
                await client.aclose()

        try:
            asyncio.run(_probe())
        except TunnelDownError as e:
            click.echo(f"  Engine:        UNREACHABLE ({e.reason})", err=True)
            sys.exit(2)
        except Exception as e:
            click.echo(f"  Engine:        ERROR ({e})", err=True)
            sys.exit(2)
    else:
        click.echo("\nNo AQUARENDER_ENGINE_URL set — skipping live engine probe.")
        click.echo("Run the Kaggle notebook, paste the tunnel URL into the Connect tab,")
        click.echo("or export AQUARENDER_ENGINE_URL=https://... before re-running doctor.")

    click.echo("\nAll local checks passed.")


@cli.command(name="list-presets")
def list_presets() -> None:
    """Print built-in and user presets."""
    ctx = build_context()
    for p in ctx.preset_service.list():
        kind = "builtin" if p.is_builtin else "user"
        click.echo(f"[{kind}] {p.id}  — {p.name}")


def main() -> None:  # pragma: no cover
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
