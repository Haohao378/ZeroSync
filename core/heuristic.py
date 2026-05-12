import asyncio
import logging
import time
import os
from typing import Dict, Callable, Awaitable
from core.types import FSEvent, EventType
logger = logging.getLogger('HeuristicEngine')

class HeuristicEngine:

    def __init__(self, debounce_delay: float=0.5, safe_save_window: float=0.0, file_lock_check_func: Callable[[str], bool]=None):
        self.debounce_delay = debounce_delay
        self._is_file_locked = file_lock_check_func or (lambda path: False)
        self.pending_modifies: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def process_raw_event(self, event: FSEvent, emit_callback: Callable[[FSEvent], Awaitable[None]]):
        async with self._lock:
            if event.event_type == EventType.DELETED:
                keys_to_cancel = [p for p in self.pending_modifies.keys() if p == event.path or p.startswith(event.path + os.sep)]
                for k in keys_to_cancel:
                    self.pending_modifies[k].cancel()
                    del self.pending_modifies[k]
                await emit_callback(event)
            elif event.event_type == EventType.CREATED:
                await emit_callback(event)
            elif event.event_type == EventType.RENAMED:
                keys_to_transfer = [p for p in self.pending_modifies.keys() if p == event.path or p.startswith(event.path + os.sep)]
                for old_p in keys_to_transfer:
                    self.pending_modifies[old_p].cancel()
                    del self.pending_modifies[old_p]
                    new_p = event.target_path if old_p == event.path else event.target_path + old_p[len(event.path):]
                    new_event = FSEvent(event_id=f'rewritten_{time.time()}', event_type=EventType.MODIFIED, path=new_p, target_path=None, timestamp=event.timestamp, meta=None)
                    self.pending_modifies[new_p] = asyncio.create_task(self._wait_and_probe(new_event, emit_callback))
                await emit_callback(event)
            elif event.event_type == EventType.MODIFIED:
                if event.path in self.pending_modifies:
                    self.pending_modifies[event.path].cancel()
                self.pending_modifies[event.path] = asyncio.create_task(self._wait_and_probe(event, emit_callback))

    async def _wait_and_probe(self, event: FSEvent, emit_callback: Callable[[FSEvent], Awaitable[None]]):
        try:
            await asyncio.sleep(self.debounce_delay)
            retries = 0
            while self._is_file_locked(event.path) and retries < 20:
                await asyncio.sleep(0.5)
                retries += 1
            async with self._lock:
                self.pending_modifies.pop(event.path, None)
            await emit_callback(event)
        except asyncio.CancelledError:
            pass