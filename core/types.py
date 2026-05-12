import enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

class EventType(enum.Enum):
    CREATED = 'CREATED'
    MODIFIED = 'MODIFIED'
    DELETED = 'DELETED'
    RENAMED = 'RENAMED'

@dataclass
class FileMeta:
    inode: int
    size: int
    mtime: float
    is_dir: bool = False

@dataclass
class FSEvent:
    event_id: str
    event_type: EventType
    path: str
    timestamp: float
    target_path: Optional[str] = None
    meta: Optional[FileMeta] = None

@dataclass
class ChunkMeta:
    offset: int
    length: int
    blake3_hash: bytes
    is_matched: bool = False

@dataclass
class DeltaPatch:
    offset: int
    length: int
    compressed_data: bytes

@dataclass
class SyncTask:
    task_id: str
    event: FSEvent
    retry_count: int = 0
    max_retries: int = 3
    context: Dict[str, Any] = field(default_factory=dict)