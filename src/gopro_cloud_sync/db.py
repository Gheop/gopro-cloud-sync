import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import MediaItem

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "gopro-cloud-sync"
DB_FILE = DATA_DIR / "sync.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    capture_time TEXT NOT NULL,
    media_type   TEXT NOT NULL,
    local_path   TEXT,
    file_size    INTEGER DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'pending',
    error_msg    TEXT,
    downloaded_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_status ON media(status);
CREATE INDEX IF NOT EXISTS idx_capture_time ON media(capture_time);
"""


class SyncDB:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_FILE
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def upsert_media(self, item: MediaItem) -> None:
        self.conn.execute(
            """INSERT INTO media (id, filename, capture_time, media_type, file_size, status)
               VALUES (?, ?, ?, ?, ?, 'pending')
               ON CONFLICT(id) DO NOTHING""",
            (
                item.id,
                item.filename,
                item.capture_time.isoformat(),
                item.media_type,
                item.file_size,
            ),
        )
        self.conn.commit()

    def get_pending(self) -> list[MediaItem]:
        rows = self.conn.execute(
            "SELECT id, filename, capture_time, media_type, file_size FROM media WHERE status = 'pending'"
        ).fetchall()
        items = []
        for r in rows:
            items.append(
                MediaItem(
                    id=r[0],
                    filename=r[1],
                    capture_time=datetime.fromisoformat(r[2]),
                    media_type=r[3],
                    file_size=r[4],
                    width=0,
                    height=0,
                )
            )
        return items

    def mark_downloading(self, media_id: str) -> None:
        self.conn.execute("UPDATE media SET status = 'downloading' WHERE id = ?", (media_id,))
        self.conn.commit()

    def mark_done(self, media_id: str, local_path: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE media SET status = 'done', local_path = ?, downloaded_at = ? WHERE id = ?",
            (local_path, now, media_id),
        )
        self.conn.commit()

    def mark_error(self, media_id: str, msg: str) -> None:
        self.conn.execute(
            "UPDATE media SET status = 'error', error_msg = ? WHERE id = ?",
            (msg, media_id),
        )
        self.conn.commit()

    def get_stats(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) FROM media GROUP BY status").fetchall()
        stats = {"total": 0, "pending": 0, "downloading": 0, "done": 0, "error": 0}
        for status, count in rows:
            stats[status] = count
            stats["total"] += count
        return stats

    def is_downloaded(self, media_id: str) -> bool:
        row = self.conn.execute("SELECT status FROM media WHERE id = ?", (media_id,)).fetchone()
        return row is not None and row[0] == "done"

    def reset_all(self) -> int:
        cursor = self.conn.execute("UPDATE media SET status = 'pending', error_msg = NULL WHERE status != 'pending'")
        self.conn.commit()
        return cursor.rowcount
