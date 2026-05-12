import mmap
import os
import logging
from typing import List, Protocol, Set
from core.types import DeltaPatch
from delta.hasher import FastCDC, HashUtils
from storage.local_db import SQLiteManager
logger = logging.getLogger('DeltaCalculator')

class DBChunkProtocol(Protocol):

    def get_file_hashes(self, inode: int) -> Set[bytes]:
        ...

class DeltaCalculator:

    def __init__(self, db: DBChunkProtocol):
        self.db = db

def calculate_delta_worker(db_path: str, path: str, inode: int) -> List[DeltaPatch]:
    if not os.path.isfile(path):
        return []
    file_size = os.path.getsize(path)
    local_db = SQLiteManager(db_path=db_path)
    remote_hashes: Set[bytes] = local_db.get_file_hashes(inode)
    chunker = FastCDC(min_size=16 * 1024, avg_size=64 * 1024, max_size=256 * 1024)
    patches: List[DeltaPatch] = []
    if file_size > 0:
        fd = -1
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
            with mmap.mmap(fd, 0, access=mmap.ACCESS_READ) as mm:
                with memoryview(mm) as mem_view:
                    for offset, length in chunker.generate_chunks(mem_view):
                        with mem_view[offset:offset + length] as chunk_view:
                            current_hash = HashUtils.blake3_hash(chunk_view)
                            if current_hash not in remote_hashes:
                                compressed_data = HashUtils.compress(chunk_view)
                                patches.append(DeltaPatch(offset=offset, length=length, compressed_data=compressed_data))
        except PermissionError:
            raise
        except Exception as e:
            logging.error(f'Error in delta worker: {e}')
            raise
        finally:
            if fd != -1:
                os.close(fd)
    patches.append(DeltaPatch(offset=file_size, length=0, compressed_data=b''))
    return patches