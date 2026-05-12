import os
import struct
import threading
import asyncio
import logging
import time
from typing import AsyncGenerator, Optional
try:
    import win32file
    import win32con
    import winioctlcon
    import win32api
except ImportError:
    pass
from monitor.base import BaseMonitor
from core.types import FSEvent, EventType
logger = logging.getLogger('WinUSNMonitor')
USN_REASON_DATA_OVERWRITE = 1
USN_REASON_DATA_EXTEND = 2
USN_REASON_FILE_CREATE = 256
USN_REASON_FILE_DELETE = 512
USN_REASON_RENAME_OLD_NAME = 4096
USN_REASON_RENAME_NEW_NAME = 8192
USN_REASON_CLOSE = 2147483648

class WindowsUSNMonitor(BaseMonitor):

    def __init__(self, watch_dir: str, since_id: Optional[str]=None):
        super().__init__(watch_dir, since_id)
        drive = os.path.splitdrive(self.watch_dir)[0]
        if not drive:
            raise ValueError('Windows watch_dir must contain a drive letter (e.g., C:\\)')
        self.volume_path = f'\\\\.\\{drive}'
        self._thread: Optional[threading.Thread] = None

    def _get_volume_handle(self):
        try:
            return win32file.CreateFile(self.volume_path, win32con.GENERIC_READ, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE, None, win32con.OPEN_EXISTING, 0, None)
        except Exception as e:
            logger.critical('Failed to open volume. Administrator privileges are required to read USN Journal.')
            raise e

    def _usn_polling_worker(self, loop: asyncio.AbstractEventLoop):
        h_vol = self._get_volume_handle()
        start_usn = int(self.since_id) if self.since_id else 0
        reason_mask = 4294967295
        return_only_on_close = 0
        timeout = 0
        bytes_to_wait_for = 0
        journal_id = 0
        read_buffer_size = 4096
        while self.is_running:
            in_data = struct.pack('<QIIQQQ', start_usn, reason_mask, return_only_on_close, timeout, bytes_to_wait_for, journal_id)
            try:
                out_buffer = win32file.DeviceIoControl(h_vol, winioctlcon.FSCTL_READ_USN_JOURNAL, in_data, read_buffer_size)
            except Exception as e:
                time.sleep(0.1)
                continue
            if len(out_buffer) < 8:
                continue
            next_usn = struct.unpack('<Q', out_buffer[:8])[0]
            offset = 8
            while offset < len(out_buffer):
                record_len, major_version = struct.unpack('<HH', out_buffer[offset:offset + 4])
                if record_len == 0:
                    break
                if major_version == 2:
                    file_ref, parent_ref, usn, timestamp, reason = struct.unpack('<QQQQI', out_buffer[offset + 8:offset + 48])
                    name_len, name_offset = struct.unpack('<HH', out_buffer[offset + 56:offset + 60])
                    filename_bytes = out_buffer[offset + name_offset:offset + name_offset + name_len]
                    filename = filename_bytes.decode('utf-16le')
                    event_type = None
                    if reason & USN_REASON_FILE_CREATE:
                        event_type = EventType.CREATED
                    elif reason & USN_REASON_FILE_DELETE:
                        event_type = EventType.DELETED
                    elif reason & USN_REASON_RENAME_NEW_NAME:
                        event_type = EventType.RENAMED
                    elif reason & USN_REASON_CLOSE and (reason & USN_REASON_DATA_OVERWRITE or reason & USN_REASON_DATA_EXTEND):
                        event_type = EventType.MODIFIED
                    if event_type:
                        full_path = os.path.join(self.watch_dir, filename)
                        if full_path.startswith(self.watch_dir):
                            fs_event = FSEvent(event_id=str(usn), event_type=event_type, path=full_path, timestamp=time.time(), meta=self._get_file_meta(full_path))
                            asyncio.run_coroutine_threadsafe(self.event_queue.put(fs_event), loop)
                offset += record_len
            start_usn = next_usn
            self._current_event_id = str(start_usn)
            time.sleep(0.05)
        win32file.CloseHandle(h_vol)

    async def listen(self) -> AsyncGenerator[FSEvent, None]:
        self.is_running = True
        loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._usn_polling_worker, args=(loop,), daemon=True)
        self._thread.start()
        logger.info(f'Windows USN Monitor started on {self.watch_dir} from USN {self.since_id}')
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