"""In-process log bus: keeps the last N lines and fans them out to WebSocket subscribers."""

from __future__ import annotations

import asyncio
import collections
import logging
import threading
import time
from typing import Callable, Deque, Dict, List, Optional, Tuple


class LogBus:
    def __init__(self, maxlen: int = 5000):
        self.lines: Deque[Dict] = collections.deque(maxlen=maxlen)
        self._subs: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        self.listeners: List[Callable[[Dict], None]] = []

    def publish(self, line: Dict) -> None:
        line.setdefault("ts", time.time())
        with self._lock:
            self.lines.append(line)
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put_nowait, q, line)
            except RuntimeError:
                pass
        for fn in self.listeners:
            try:
                fn(line)
            except Exception:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(l, s) for (l, s) in self._subs if s is not q]

    def recent(self, limit: int = 500, level: Optional[str] = None, source: Optional[str] = None) -> List[Dict]:
        order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        with self._lock:
            items = list(self.lines)
        if level:
            lv = order.index(level.upper()) if level.upper() in order else 0
            items = [x for x in items if order.index(x.get("level", "INFO")) >= lv]
        if source:
            items = [x for x in items if x.get("source", "").startswith(source)]
        return items[-limit:]


def _put_nowait(q: asyncio.Queue, item) -> None:
    try:
        q.put_nowait(item)
    except asyncio.QueueFull:
        pass


class LogBusHandler(logging.Handler):
    def __init__(self, bus: LogBus):
        super().__init__()
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "from_worker", False):
            return
        name = record.name
        source = name[len("station."):] if name.startswith("station.") else name
        self.bus.publish({"ts": record.created, "level": record.levelname, "source": source,
                          "message": record.getMessage()})
