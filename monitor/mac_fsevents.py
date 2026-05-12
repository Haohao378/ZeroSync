import os
import threading
import asyncio
import logging
import time
from typing import AsyncGenerator, Optional
try:
    from fsevents import Observer, Stream
    import fsevents
except ImportError:
    pass
from monitor.base import BaseMonitor
from core.types import FSEvent, EventType
logger = logging.getLogger('MacFSEventsMonitor')

class MacFSEventsMonitor(BaseMonitor):

    def __init__(self, watch_dir: str, since_id: Optional[str]=None):
        super().__init__(watch_dir, since_id)
        self.observer = None
        self.mac_since_id = int(self.since_id) if self.since_id else fsevents.FSEventsGetCurrentEventId()

    def _fsevents_callback(self, file_event):
        mask = file_event.mask
        path = file_event.name

        def emit_event(e_type, p, target=None):
            meta = self._get_file_meta(p) if e_type != EventType.DELETED else None
            fs_event = FSEvent(event_id=str(self.mac_since_id + 1), event_type=e_type, path=p, target_path=target, timestamp=time.time(), meta=meta)
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(self.event_queue.put(fs_event), loop)
            except RuntimeError:
                pass
            self._current_event_id = fs_event.event_id
            self.mac_since_id += 1
        if mask & fsevents.IN_CREATE:
            emit_event(EventType.CREATED, path)
            emit_event(EventType.MODIFIED, path)
            if os.path.isdir(path):
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        emit_event(EventType.CREATED, os.path.join(root, d))
                    for f in files:
                        child_path = os.path.join(root, f)
                        emit_event(EventType.CREATED, child_path)
                        emit_event(EventType.MODIFIED, child_path)
        elif mask & fsevents.IN_DELETE:
            emit_event(EventType.DELETED, path)
        elif mask & fsevents.IN_MODIFY:
            emit_event(EventType.MODIFIED, path)
        elif mask & fsevents.IN_RENAME:
            if os.path.exists(path):
                emit_event(EventType.CREATED, path)
                emit_event(EventType.MODIFIED, path)
                if os.path.isdir(path):
                    for root, dirs, files in os.walk(path):
                        for d in dirs:
                            emit_event(EventType.CREATED, os.path.join(root, d))
                        for f in files:
                            child_path = os.path.join(root, f)
                            emit_event(EventType.CREATED, child_path)
                            emit_event(EventType.MODIFIED, child_path)
            else:
                emit_event(EventType.DELETED, path)

    async def listen(self) -> AsyncGenerator[FSEvent, None]:
        self.is_running = True
        stream = Stream(self._fsevents_callback, self.watch_dir, file_events=True, sinceWhen=self.mac_since_id)
        self.observer = Observer()
        self.observer.schedule(stream)
        self.observer.start()
        logger.info(f'Mac FSEvents Monitor started on {self.watch_dir} from EventID {self.mac_since_id}')
        while self.is_running:
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue

    def stop(self):
        self.is_running = False
        if self.observer:
            self.observer.unschedule_all()
            self.observer.stop()
            self.observer.join()