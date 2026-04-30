"""Ping the remote every N minutes during active batches to defeat Kaggle idle timeout."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aquarender.engine.client import RemoteComfyUIClient


class KeepaliveTask:
    def __init__(self, client: RemoteComfyUIClient, *, interval_s: float = 240.0) -> None:
        self._client = client
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="keepalive-task")

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
        was_running = self.running
        await self.stop()
        self._client = client
        if was_running:
            await self.start()

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_s)
                except TimeoutError:
                    pass
                if self._stop_event.is_set():
                    return
                await self._client.keepalive_ping()
        except asyncio.CancelledError:
            return
