"""
Authentication helpers: user storage, bcrypt password hashing, JWT tokens.

Users are stored in a `users` table inside the existing SQLite database
(storage/history.db). Passwords are never stored in plain text — only the
bcrypt hash is persisted. Even with full database access an attacker cannot
recover passwords from bcrypt hashes without an exhaustive brute-force search.

Environment variables
---------------------
JWT_SECRET_KEY   — secret used to sign tokens; MUST be set in production.
                   Generate a strong value with: python -c "import secrets; print(secrets.token_hex(32))"
SECURE_COOKIES   — set to "true" when running behind HTTPS (required for
                   port-forwarding / production). Defaults to "false" for
                   local development.
"""
import os
import sqlite3
import time
from pathlib import Path

import bcrypt
from jose import JWTError, jwt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STORAGE_ROOT = Path('storage')
DB_PATH      = STORAGE_ROOT / 'history.db'

_raw_secret = os.environ.get('JWT_SECRET_KEY', '')
if not _raw_secret:
    _raw_secret = 'dev-insecure-secret-change-me-in-production'
    print(
        '[auth] WARNING: JWT_SECRET_KEY is not set. '
        'Using an insecure default. Set this variable before port-forwarding.'
    )

SECRET_KEY             = _raw_secret
ALGORITHM              = 'HS256'
TOKEN_EXPIRE_SECONDS   = 8 * 3600   # 8 hours

SECURE_COOKIES = os.environ.get('SECURE_COOKIES', 'false').lower() == 'true'

# Cost factor 12 — ≈0.3 s per hash, frustrates brute-force without being
# noticeable to a human logging in.
_BCRYPT_ROUNDS = 12

# Pre-computed dummy hash used for constant-time rejection when a username
# does not exist, preventing timing-based username enumeration.
_DUMMY_HASH = bcrypt.hashpw(b'dummy', bcrypt.gensalt(rounds=4))


# ---------------------------------------------------------------------------
# AuthDB — user account storage
# ---------------------------------------------------------------------------

class AuthDB:
    """
    Manages the `users` table in the shared SQLite database.
    Passwords are stored only as bcrypt hashes.
    """

    def __init__(self):
        STORAGE_ROOT.mkdir(exist_ok=True)
        self._con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute('PRAGMA journal_mode=WAL')
        self._con.execute('PRAGMA foreign_keys=ON')
        self._create_schema()

    def _create_schema(self) -> None:
        self._con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT    NOT NULL UNIQUE,
                password_hash TEXT    NOT NULL,
                created_at    INTEGER NOT NULL
            )
        """)
        self._con.commit()

    # ------------------------------------------------------------------
    # Account management (used by the CLI tool)
    # ------------------------------------------------------------------

    def create_user(self, username: str, password: str) -> bool:
        """
        Hash `password` and insert a new user row.
        Returns False if the username is already taken.
        """
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
        )
        try:
            self._con.execute(
                'INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
                (username, password_hash.decode('utf-8'), int(time.time() * 1000)),
            )
            self._con.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def delete_user(self, username: str) -> bool:
        """Remove a user. Returns False if not found."""
        cur = self._con.execute('DELETE FROM users WHERE username=?', (username,))
        self._con.commit()
        return cur.rowcount > 0

    def list_users(self) -> list[str]:
        rows = self._con.execute(
            'SELECT username FROM users ORDER BY id'
        ).fetchall()
        return [r['username'] for r in rows]

    # ------------------------------------------------------------------
    # Authentication (used by the login endpoint)
    # ------------------------------------------------------------------

    def verify(self, username: str, password: str) -> bool:
        """
        Check username + password.

        When the username does not exist a dummy bcrypt check is still
        performed so the response time is the same regardless, preventing
        timing-based username enumeration.
        """
        row = self._con.execute(
            'SELECT password_hash FROM users WHERE username=?', (username,)
        ).fetchone()

        if row is None:
            bcrypt.checkpw(b'dummy', _DUMMY_HASH)   # constant-time guard
            return False

        stored = row['password_hash']
        if isinstance(stored, str):
            stored = stored.encode('utf-8')

        return bcrypt.checkpw(password.encode('utf-8'), stored)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_token(username: str) -> str:
    """Return a signed JWT that identifies `username`."""
    now = int(time.time())
    payload = {
        'sub': username,
        'iat': now,
        'exp': now + TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str | None:
    """
    Verify and decode a JWT.
    Returns the username on success, or None if the token is invalid / expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get('sub')
    except JWTError:
        return None
