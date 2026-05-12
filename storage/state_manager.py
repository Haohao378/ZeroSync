import os
import blake3
import logging
from typing import Optional
from storage.local_db import SQLiteManager
logger = logging.getLogger('StateManager')

class StateManager:
    EVENT_CURSOR_KEY = 'last_os_event_id'

    def __init__(self, db_path: str='.zerosync.db'):
        self.db = SQLiteManager(db_path)

    def get_db(self) -> SQLiteManager:
        return self.db

    def save_last_event_id(self, event_id: str) -> None:
        self.db.set_kv(self.EVENT_CURSOR_KEY, event_id)

    def get_last_event_id(self) -> Optional[str]:
        return self.db.get_kv(self.EVENT_CURSOR_KEY)

    def update_merkle_tree(self, path: str, force_rehash: bool=False) -> None:
        if not os.path.exists(path):
            self.db.delete_file_record(path)
            parent_dir = os.path.dirname(path)
            self._update_dir_hash_recursive(parent_dir)
            return
        if os.path.isfile(path) and force_rehash:
            try:
                file_hash = self._calculate_file_hash(path)
                stat = os.stat(path)
                parent_dir = os.path.dirname(path)
                with self.db._write_lock:
                    with self.db._get_conn() as conn:
                        conn.execute('DELETE FROM files WHERE path = ? AND inode != ?', (path, stat.st_ino))
                        conn.execute('\n                            INSERT INTO files (inode, path, parent_path, is_dir, mtime, size, merkle_hash)\n                            VALUES (?, ?, ?, 0, ?, ?, ?)\n                            ON CONFLICT(inode) DO UPDATE SET \n                            path=EXCLUDED.path, mtime=EXCLUDED.mtime, size=EXCLUDED.size, merkle_hash=EXCLUDED.merkle_hash, parent_path=EXCLUDED.parent_path\n                        ', (stat.st_ino, path, parent_dir, stat.st_mtime, stat.st_size, file_hash))
                        conn.commit()
            except PermissionError:
                logger.warning(f'Merkle tree skip updating file (locked): {path}')
                return
        parent_dir = os.path.dirname(path)
        self._update_dir_hash_recursive(parent_dir)

    def _calculate_file_hash(self, path: str) -> bytes:
        hasher = blake3.blake3()
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
                    hasher.update(chunk)
            return hasher.digest()
        except Exception as e:
            logger.error(f'Hash calc error for {path}: {e}')
            return b''

    def _update_dir_hash_recursive(self, dir_path: str):
        if not dir_path or not os.path.isdir(dir_path):
            return
        parent_dir = os.path.dirname(dir_path)
        if dir_path == parent_dir:
            return
        if not os.path.exists(dir_path):
            self._update_dir_hash_recursive(parent_dir)
            return
        with self.db._get_conn() as conn:
            cur = conn.execute('\n                SELECT path, merkle_hash FROM files \n                WHERE parent_path = ? AND merkle_hash IS NOT NULL\n                ORDER BY path ASC\n            ', (dir_path,))
            children = cur.fetchall()
        hasher = blake3.blake3()
        for child in children:
            hasher.update(child['path'].encode('utf-8'))
            hasher.update(bytes(child['merkle_hash']))
        dir_hash = hasher.digest()
        stat = os.stat(dir_path)
        parent_dir = os.path.dirname(dir_path)
        with self.db._write_lock:
            with self.db._get_conn() as conn:
                conn.execute('\n                    INSERT INTO files (path, parent_path, is_dir, mtime, size, merkle_hash)\n                    VALUES (?, ?, 1, ?, 0, ?)\n                    ON CONFLICT(path) DO UPDATE SET \n                    merkle_hash=?, mtime=?\n                ', (dir_path, parent_dir, stat.st_mtime, dir_hash, dir_hash, stat.st_mtime))
                conn.commit()
        self._update_dir_hash_recursive(parent_dir)