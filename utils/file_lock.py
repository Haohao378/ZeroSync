import os
import sys
import logging
import time
logger = logging.getLogger('FileLock')

def check_file_lock(filepath: str) -> bool:
    if not os.path.exists(filepath):
        return False
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            GENERIC_READ = 2147483648
            GENERIC_WRITE = 1073741824
            OPEN_EXISTING = 3
            FILE_ATTRIBUTE_NORMAL = 128
            FILE_SHARE_NONE = 0
            handle = ctypes.windll.kernel32.CreateFileW(str(filepath), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_NONE, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
            if handle == wintypes.HANDLE(-1).value:
                return True
            else:
                ctypes.windll.kernel32.CloseHandle(handle)
                return False
        except Exception as e:
            logger.debug(f'Windows API lock check failed, using fallback: {e}')
            try:
                with open(filepath, 'a'):
                    pass
                return False
            except IOError:
                return True
    else:
        try:
            import fcntl
            try:
                with open(filepath, 'a') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (BlockingIOError, IOError):
                return True
            stat1 = os.stat(filepath)
            time.sleep(0.05)
            stat2 = os.stat(filepath)
            if stat1.st_size != stat2.st_size or stat1.st_mtime != stat2.st_mtime:
                return True
            return False
        except FileNotFoundError:
            return False
        except Exception as e:
            logger.warning(f'POSIX lock check encountered an error: {e}')
            return True