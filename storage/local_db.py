import sqlite3
import threading
import logging
from typing import Set, List, Optional, Tuple
logger = logging.getLogger('SQLiteManager')

class SQLiteManager:

    def __init__(self, db_path: str='.zerosync.db'):
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA synchronous=NORMAL;')
        conn.execute('PRAGMA foreign_keys=ON;')
        return conn

    def _init_db(self):
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute('\n                    CREATE TABLE IF NOT EXISTS sys_kv (\n                        key TEXT PRIMARY KEY,\n                        value TEXT\n                    )\n                ')
                conn.execute('\n                    CREATE TABLE IF NOT EXISTS files (\n                        inode INTEGER PRIMARY KEY,\n                        path TEXT UNIQUE NOT NULL,\n                        parent_path TEXT,\n                        is_dir BOOLEAN,\n                        mtime REAL,\n                        size INTEGER,\n                        merkle_hash BLOB\n                    )\n                ')
                conn.execute('\n                    CREATE TABLE IF NOT EXISTS chunks (\n                        inode INTEGER,\n                        chunk_index INTEGER,\n                        offset INTEGER,\n                        length INTEGER,\n                        blake3_hash BLOB,\n                        PRIMARY KEY (inode, chunk_index),\n                        FOREIGN KEY (inode) REFERENCES files(inode) ON DELETE CASCADE\n                    )\n                ')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);')
                conn.execute('CREATE INDEX IF NOT EXISTS idx_files_parent ON files(parent_path);')
                conn.commit()

    def set_kv(self, key: str, value: str):
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute('INSERT INTO sys_kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=?', (key, value, value))
                conn.commit()

    def get_kv(self, key: str) -> Optional[str]:
        with self._get_conn() as conn:
            cur = conn.execute('SELECT value FROM sys_kv WHERE key = ?', (key,))
            row = cur.fetchone()
            return row['value'] if row else None

    def save_file_chunks(self, inode: int, path: str, parent_path: str, size: int, chunks: List[Tuple[int, int, int, bytes]]):
        with self._write_lock:
            with self._get_conn() as conn:
                try:
                    conn.execute('DELETE FROM files WHERE path = ? AND inode != ?', (path, inode))
                    conn.execute('\n                        INSERT INTO files (inode, path, parent_path, is_dir, size) \n                        VALUES (?, ?, ?, 0, ?)\n                        ON CONFLICT(inode) DO UPDATE SET path=?, parent_path=?, size=?\n                    ', (inode, path, parent_path, size, path, parent_path, size))
                    conn.execute('DELETE FROM chunks WHERE inode = ?', (inode,))
                    conn.executemany('INSERT INTO chunks (inode, chunk_index, offset, length, blake3_hash) VALUES (?, ?, ?, ?, ?)', [(inode, c[0], c[1], c[2], c[3]) for c in chunks])
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.error(f'Failed to save chunks for {path}: {e}')
                    raise

    def get_file_hashes(self, inode: int) -> Set[bytes]:
        with self._get_conn() as conn:
            cur = conn.execute('SELECT blake3_hash FROM chunks WHERE inode = ?', (inode,))
            return {bytes(row['blake3_hash']) for row in cur.fetchall()}

    def delete_file_record(self, path: str):
        with self._write_lock:
            with self._get_conn() as conn:
                conn.execute('DELETE FROM files WHERE path = ?', (path,))
                conn.commit()