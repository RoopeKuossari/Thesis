"""
FastAPI router for authentication endpoints.

Routes
------
POST /auth/login   — verify credentials, set httpOnly JWT cookie
POST /auth/logout  — clear the cookie
GET  /auth/me      — return the current user (used by the frontend to check
                     auth state on page load)

The cookie is httpOnly (no JS access) and SameSite=lax (CSRF protection).
Set SECURE_COOKIES=true in production so the cookie is only sent over HTTPS.
"""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from backend.auth import AuthDB, SECURE_COOKIES, TOKEN_EXPIRE_SECONDS, create_token, decode_token

router   = APIRouter(prefix='/auth', tags=['auth'])
_auth_db = AuthDB()

COOKIE_NAME = 'access_token'


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post('/login')
async def login(body: LoginRequest, response: Response):
    """
    Verify username and password.
    On success, set an httpOnly JWT cookie and return the username.
    On failure, always return 401 with a generic message (no username hints).
    """
    if not _auth_db.verify(body.username, body.password):
        raise HTTPException(status_code=401, detail='Invalid username or password.')

    token = create_token(body.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,           # not accessible from JavaScript
        max_age=TOKEN_EXPIRE_SECONDS,
        samesite='lax',          # CSRF protection
        secure=SECURE_COOKIES,   # True in production (HTTPS), False for localhost
    )
    return {'username': body.username}


@router.post('/logout')
async def logout(response: Response):
    """Clear the auth cookie."""
    response.delete_cookie(COOKIE_NAME, samesite='lax', secure=SECURE_COOKIES)
    return {'ok': True}


@router.get('/me')
async def me(request: Request):
    """
    Return the currently authenticated user.
    The frontend calls this on page load to decide whether to show the app
    or the login page.  Returns 401 if not authenticated or token expired.
    """
    token    = request.cookies.get(COOKIE_NAME)
    username = decode_token(token) if token else None
    if username is None:
        raise HTTPException(status_code=401, detail='Not authenticated.')
    return {'username': username}
