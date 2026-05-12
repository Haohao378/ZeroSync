import os
import uuid
import asyncio
import threading
import time
import logging
import win32file
import win32con
from typing import AsyncGenerator, Optional
from monitor.base import BaseMonitor
from core.types import FSEvent, EventType
logger = logging.getLogger('WinMonitor')

class WindowsMonitor(BaseMonitor):

    def __init__(self, watch_dir: str, since_id: Optional[str]=None):
        super().__init__(watch_dir, since_id)
        self.watch_dir = os.path.normpath(os.path.abspath(watch_dir))

    def _polling_worker(self, loop):
        h_dir = win32file.CreateFile(self.watch_dir, win32con.GENERIC_READ, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE, None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_BACKUP_SEMANTICS, None)
        if h_dir == win32file.INVALID_HANDLE_VALUE:
            logger.error(f'Failed to open directory handle for {self.watch_dir}')
            return
        action_map = {1: EventType.CREATED, 2: EventType.DELETED, 3: EventType.MODIFIED}

        def emit_event(e_type, path, target=None):
            meta = self._get_file_meta(path) if e_type != EventType.DELETED else None
            fs_event = FSEvent(event_id=uuid.uuid4().hex, event_type=e_type, path=path, target_path=target, timestamp=time.time(), meta=meta)
            asyncio.run_coroutine_threadsafe(self.event_queue.put(fs_event), loop)
        self._pending_old_path = None
        while self.is_running:
            try:
                results = win32file.ReadDirectoryChangesW(h_dir, 131072, True, win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_DIR_NAME | win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES | win32con.FILE_NOTIFY_CHANGE_SIZE | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE, None, None)
                for action, file_name in results:
                    full_path = os.path.join(self.watch_dir, file_name)
                    if action in action_map:
                        emit_event(action_map[action], full_path)
                        if action == 1:
                            emit_event(EventType.MODIFIED, full_path)
                            if os.path.isdir(full_path):
                                for root, dirs, files in os.walk(full_path):
                                    for d in dirs:
                                        dir_path = os.path.join(root, d)
                                        emit_event(EventType.CREATED, dir_path)
                                    for f in files:
                                        child_path = os.path.join(root, f)
                                        emit_event(EventType.CREATED, child_path)
                                        emit_event(EventType.MODIFIED, child_path)
                    elif action == 4:
                        if self._pending_old_path:
                            emit_event(EventType.DELETED, self._pending_old_path)
                        self._pending_old_path = full_path
                    elif action == 5:
                        if self._pending_old_path:
                            emit_event(EventType.RENAMED, self._pending_old_path, full_path)
                            self._pending_old_path = None
                        else:
                            emit_event(EventType.CREATED, full_path)
                            emit_event(EventType.MODIFIED, full_path)
                            if os.path.isdir(full_path):
                                for root, dirs, files in os.walk(full_path):
                                    for d in dirs:
                                        dir_path = os.path.join(root, d)
                                        emit_event(EventType.CREATED, dir_path)
                                    for f in files:
                                        child_path = os.path.join(root, f)
                                        emit_event(EventType.CREATED, child_path)
                                        emit_event(EventType.MODIFIED, child_path)
                if self._pending_old_path:
                    emit_event(EventType.DELETED, self._pending_old_path)
                    self._pending_old_path = None
            except Exception as e:
                if self.is_running:
                    logger.error(f'Directory monitor error: {e}')
                    self._pending_old_path = None
                    time.sleep(1)
        win32file.CloseHandle(h_dir)

    async def listen(self) -> AsyncGenerator[FSEvent, None]:
        self.is_running = True
        loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._polling_worker, args=(loop,), daemon=True)
        self._thread.start()
        logger.info(f'Windows Live Monitor started on {self.watch_dir}')
        while self.is_running:
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue

    def stop(self):
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=2.0)