from __future__ import annotations

import asyncio

import pytest

from aquarender.engine.fakes import FakeRemoteComfyUIClient
from aquarender.engine.tunnel import TunnelHealthMonitor


@pytest.mark.asyncio
async def test_emits_tunnel_down_after_three_misses() -> None:
    client = FakeRemoteComfyUIClient()
    monitor = TunnelHealthMonitor(client, interval_s=0.01, miss_threshold=3)
    events: list[str] = []
    monitor.subscribe(lambda e: events.append(e.kind))

    await monitor.start()
    await asyncio.sleep(0.05)
    client.simulate_tunnel_down()
    # wait for >=3 misses
    await asyncio.sleep(0.2)
    await monitor.stop()

    assert "tunnel_down" in events


@pytest.mark.asyncio
async def test_recovers_after_reconnect() -> None:
    client = FakeRemoteComfyUIClient()
    monitor = TunnelHealthMonitor(client, interval_s=0.01, miss_threshold=2)
    events: list[str] = []
    monitor.subscribe(lambda e: events.append(e.kind))

    await monitor.start()
    client.simulate_tunnel_down()
    await asyncio.sleep(0.1)
    client.simulate_tunnel_up()
    await asyncio.sleep(0.1)
    await monitor.stop()

    assert "tunnel_down" in events
    assert "tunnel_recovered" in events
