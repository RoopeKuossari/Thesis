"""
Persistent session history using SQLite + on-disk JPEG frames.

Schema
------
sessions   — one row per surveillance session
highlights — one row per highlight event, foreign-keyed to sessions

File layout
-----------
storage/
    history.db
    sessions/
        <session_id>/          e.g. 2026-04-10_12-10-00
            frames/
                <unix_ms>.jpg
            highlights/
                <id>.jpg
"""
import shutil
import sqlite3
import time
from pathlib import Path

STORAGE_ROOT   = Path('storage')
DB_PATH        = STORAGE_ROOT / 'history.db'
RETENTION_DAYS = 7


class HistoryDB:
    """
    SQLite-backed store for surveillance session metadata and highlight events.
    Frame JPEGs and highlight thumbnails are kept on disk under STORAGE_ROOT.
    """

    def __init__(self):
        STORAGE_ROOT.mkdir(exist_ok=True)
        self._con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute('PRAGMA journal_mode=WAL')
        self._con.execute('PRAGMA foreign_keys=ON')
        self._create_schema()

    def _create_schema(self):
        self._con.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id              TEXT    PRIMARY KEY,
                started_at      INTEGER NOT NULL,
                ended_at        INTEGER,
                frame_count     INTEGER DEFAULT 0,
                highlight_count INTEGER DEFAULT 0,
                alert_count     INTEGER DEFAULT 0,
                frames_dir      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS highlights (
                id          TEXT    NOT NULL,
                session_id  TEXT    NOT NULL
                                REFERENCES sessions(id) ON DELETE CASCADE,
                t           INTEGER NOT NULL,
                end_t       INTEGER,
                category    TEXT    NOT NULL,
                name        TEXT,
                thumb_path  TEXT    NOT NULL,
                PRIMARY KEY (session_id, id)
            );
        """)
        # Migration for older DBs that pre-date the end_t column
        cols = {row['name'] for row in self._con.execute('PRAGMA table_info(highlights)')}
        if 'end_t' not in cols:
            self._con.execute('ALTER TABLE highlights ADD COLUMN end_t INTEGER')
        self._con.commit()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, session_id: str, started_at: int) -> Path:
        """
        Insert a new session row and create the on-disk directory tree.

        Returns the frames directory path so SurveillanceSystem can write
        JPEG files directly without going through HistoryDB again.
        """
        session_dir = STORAGE_ROOT / 'sessions' / session_id
        frames_dir  = session_dir / 'frames'
        frames_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / 'highlights').mkdir(exist_ok=True)

        self._con.execute(
            'INSERT OR IGNORE INTO sessions (id, started_at, frames_dir) VALUES (?, ?, ?)',
            (session_id, started_at, str(frames_dir)),
        )
        self._con.commit()
        return frames_dir

    def end_session(
        self,
        session_id:      str,
        ended_at:        int,
        frame_count:     int,
        highlight_count: int,
        alert_count:     int,
    ) -> None:
        self._con.execute(
            """UPDATE sessions
               SET ended_at=?, frame_count=?, highlight_count=?, alert_count=?
               WHERE id=?""",
            (ended_at, frame_count, highlight_count, alert_count, session_id),
        )
        self._con.commit()

    # ------------------------------------------------------------------
    # Highlights
    # ------------------------------------------------------------------

    def highlight_thumb_dir(self, session_id: str) -> Path:
        return STORAGE_ROOT / 'sessions' / session_id / 'highlights'

    def add_highlight(
        self,
        session_id:   str,
        highlight_id: str,
        t:            int,
        category:     str,
        name:         str | None,
        thumb_path:   Path,
        end_t:        int | None = None,
    ) -> None:
        self._con.execute(
            """INSERT OR IGNORE INTO highlights
               (id, session_id, t, end_t, category, name, thumb_path)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (highlight_id, session_id, t, end_t, category, name, str(thumb_path)),
        )
        self._con.commit()

    def update_highlight(
        self,
        session_id:   str,
        highlight_id: str,
        end_t:        int | None       = None,
        category:     str | None       = None,
        name:         str | None       = None,
        thumb_path:   Path | None      = None,
    ) -> None:
        """
        Update the live-changing fields of an active highlight: end_t,
        category, primary name, thumbnail path. Only non-None args are
        written so callers can update individual fields.
        """
        sets, params = [], []
        if end_t is not None:
            sets.append('end_t=?');      params.append(end_t)
        if category is not None:
            sets.append('category=?');   params.append(category)
        if name is not None:
            sets.append('name=?');       params.append(name)
        if thumb_path is not None:
            sets.append('thumb_path=?'); params.append(str(thumb_path))
        if not sets:
            return
        params.extend([session_id, highlight_id])
        self._con.execute(
            f'UPDATE highlights SET {", ".join(sets)} WHERE session_id=? AND id=?',
            params,
        )
        self._con.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        """Return all completed sessions, newest first."""
        rows = self._con.execute(
            'SELECT * FROM sessions WHERE ended_at IS NOT NULL ORDER BY started_at DESC'
        ).fetchall()
        return [self._public_session(r) for r in rows]

    def get_session(self, session_id: str) -> dict | None:
        row = self._con.execute(
            'SELECT * FROM sessions WHERE id=?', (session_id,)
        ).fetchone()
        return self._public_session(row) if row else None

    def get_highlights(self, session_id: str) -> list[dict]:
        rows = self._con.execute(
            'SELECT id, session_id, t, end_t, category, name FROM highlights '
            'WHERE session_id=? ORDER BY t',
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_highlight_thumb_path(self, session_id: str, highlight_id: str) -> Path | None:
        row = self._con.execute(
            'SELECT thumb_path FROM highlights WHERE session_id=? AND id=?',
            (session_id, highlight_id),
        ).fetchone()
        if row is None:
            return None
        p = Path(row['thumb_path'])
        return p if p.exists() else None

    def get_frame_at(self, session_id: str, timestamp_ms: int) -> Path | None:
        """
        Return the path of the stored JPEG frame whose timestamp is closest
        to `timestamp_ms`. Frame files are named <unix_ms>.jpg.
        """
        row = self._con.execute(
            'SELECT frames_dir FROM sessions WHERE id=?', (session_id,)
        ).fetchone()
        if row is None:
            return None
        frames_dir = Path(row['frames_dir'])
        if not frames_dir.exists():
            return None
        files = list(frames_dir.glob('*.jpg'))
        if not files:
            return None
        return min(files, key=lambda f: abs(int(f.stem) - timestamp_ms))

    # ------------------------------------------------------------------
    # Retention — called once per session start
    # ------------------------------------------------------------------

    def purge_old_sessions(self) -> int:
        """Delete sessions older than RETENTION_DAYS and their on-disk files."""
        cutoff = int((time.time() - RETENTION_DAYS * 24 * 3600) * 1000)
        rows = self._con.execute(
            'SELECT id FROM sessions WHERE started_at < ?', (cutoff,)
        ).fetchall()

        for row in rows:
            session_dir = STORAGE_ROOT / 'sessions' / row['id']
            shutil.rmtree(session_dir, ignore_errors=True)

        if rows:
            self._con.execute('DELETE FROM sessions WHERE started_at < ?', (cutoff,))
            self._con.commit()
            print(f'[history] Purged {len(rows)} session(s) older than {RETENTION_DAYS} days.')

        return len(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _public_session(row: sqlite3.Row) -> dict:
        """Strip internal server paths before returning session data to callers."""
        d = dict(row)
        d.pop('frames_dir', None)
        return d
