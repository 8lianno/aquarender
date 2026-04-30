"""Background TunnelHealthMonitor.

Pings /system_stats every 30s, emits 'tunnel_down'/'tunnel_recovered' events to subscribers.
3-strikes-down before declaring the tunnel dead — flapping doesn't churn the UI.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from aquarender.engine.types import TunnelEvent
from aquarender.errors import TunnelDownError

if TYPE_CHECKING:
    from aquarender.engine.client import RemoteComfyUIClient

Subscriber = Callable[[TunnelEvent], None | Awaitable[None]]


class TunnelHealthMonitor:
    def __init__(
        self,
        client: RemoteComfyUIClient,
        *,
        interval_s: float = 30.0,
        miss_threshold: int = 3,
    ) -> None:
        self._client = client
        self._interval_s = interval_s
        self._miss_threshold = miss_threshold
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._subscribers: list[Subscriber] = []
        self._down = False
        self._misses = 0

    def subscribe(self, callback: Subscriber) -> None:
        self._subscribers.append(callback)

    @property
    def is_down(self) -> bool:
        return self._down

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="tunnel-health-monitor")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, BaseException):
                pass
            self._task = None

    async def rebind(self, client: RemoteComfyUIClient) -> None:
        await self.stop()
        self._client = client
        self._down = False
        self._misses = 0
        await self.start()

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                await self._tick()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_s)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            return

    async def _tick(self) -> None:
        try:
            await self._client.health()
            ok = True
        except TunnelDownError:
            ok = False
        except Exception:
            ok = False

        if ok:
            if self._down:
                self._down = False
                self._misses = 0
                await self._emit(TunnelEvent("tunnel_recovered", self._client.base_url))
            else:
                self._misses = 0
            return

        self._misses += 1
        if self._misses == 1:
            return
        if self._misses == 2 and not self._down:
            await self._emit(TunnelEvent("tunnel_degraded", self._client.base_url))
            return
        if self._misses >= self._miss_threshold and not self._down:
            self._down = True
            await self._emit(TunnelEvent("tunnel_down", self._client.base_url))

    async def _emit(self, event: TunnelEvent) -> None:
        for cb in list(self._subscribers):
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Subscribers must not crash the monitor.
                continue
