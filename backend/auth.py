"""
Authentication helpers: user storage, bcrypt password hashing, JWT tokens.

Users are stored in a `users` table inside the existing SQLite database
(storage/history.db). Passwords are never stored in plain text — only the
bcrypt hash is persisted. Even with full database access an attacker cannot
recover passwords from bcrypt hashes without an exhaustive brute-force search.

Each user has a role: 'admin' or 'viewer'. Admins manage settings, identities
and history; viewers can only watch the live feed and review history.

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
from fastapi import HTTPException, Request
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

COOKIE_NAME = 'access_token'

ROLES = ('admin', 'viewer')

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
                role          TEXT    NOT NULL DEFAULT 'admin',
                created_at    INTEGER NOT NULL
            )
        """)
        # Migration for older DBs that pre-date the role column. Existing
        # users were created via the CLI before roles existed, so default
        # them to admin to keep them functional.
        cols = {row['name'] for row in self._con.execute('PRAGMA table_info(users)')}
        if 'role' not in cols:
            self._con.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        self._con.commit()

    # ------------------------------------------------------------------
    # Account management (used by the CLI tool and admin endpoints)
    # ------------------------------------------------------------------

    def create_user(self, username: str, password: str, role: str = 'viewer') -> bool:
        """
        Hash `password` and insert a new user row.
        Returns False if the username is already taken.
        """
        if role not in ROLES:
            raise ValueError(f'role must be one of {ROLES}')
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
        )
        try:
            self._con.execute(
                'INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)',
                (username, password_hash.decode('utf-8'), role, int(time.time() * 1000)),
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

    def list_users(self) -> list[dict]:
        rows = self._con.execute(
            'SELECT username, role, created_at FROM users ORDER BY id'
        ).fetchall()
        return [dict(r) for r in rows]

    def count_admins(self) -> int:
        row = self._con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role='admin'"
        ).fetchone()
        return int(row['n']) if row else 0

    def get_user(self, username: str) -> dict | None:
        row = self._con.execute(
            'SELECT username, role FROM users WHERE username=?', (username,)
        ).fetchone()
        return dict(row) if row else None

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


# ---------------------------------------------------------------------------
# Per-request dependencies — resolve the caller's identity and role
# ---------------------------------------------------------------------------

# Single shared AuthDB instance — sqlite is thread-safe in WAL mode and the
# router already uses one anyway. Importing it lazily would double-create.
_AUTH_DB = AuthDB()


def current_user(request: Request) -> dict:
    """
    Resolve the authenticated user from the JWT cookie.

    Returns a dict {username, role}. Raises 401 if the cookie is missing or
    invalid; raises 403 if the user no longer exists in the DB (e.g. an
    admin deleted them while their token was still valid).
    """
    token    = request.cookies.get(COOKIE_NAME)
    username = decode_token(token) if token else None
    if username is None:
        raise HTTPException(status_code=401, detail='Not authenticated.')

    user = _AUTH_DB.get_user(username)
    if user is None:
        raise HTTPException(status_code=403, detail='User no longer exists.')
    return user


def require_admin(request: Request) -> dict:
    """FastAPI dependency that allows only admin users to proceed."""
    user = current_user(request)
    if user['role'] != 'admin':
        raise HTTPException(status_code=403, detail='Admin privilege required.')
    return user
