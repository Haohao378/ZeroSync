import os
import abc
import asyncio
from typing import AsyncGenerator, Optional
from core.types import FSEvent, FileMeta

class BaseMonitor(abc.ABC):

    def __init__(self, watch_dir: str, since_id: Optional[str]=None):
        self.watch_dir = os.path.abspath(watch_dir)
        self.since_id = since_id
        self._current_event_id = since_id or '0'
        self.event_queue: asyncio.Queue[FSEvent] = asyncio.Queue()
        self.is_running = False

    @abc.abstractmethod
    async def listen(self) -> AsyncGenerator[FSEvent, None]:
        pass

    def get_current_event_id(self) -> str:
        return str(self._current_event_id)

    def _get_file_meta(self, path: str) -> Optional[FileMeta]:
        try:
            stat = os.stat(path)
            return FileMeta(inode=stat.st_ino, size=stat.st_size, mtime=stat.st_mtime, is_dir=bool(stat.st_mode & 16384))
        except (FileNotFoundError, PermissionError):
            return None