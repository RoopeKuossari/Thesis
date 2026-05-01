"""
FastAPI router for authentication and user management.

Public auth routes
------------------
POST /auth/login   — verify credentials, set httpOnly JWT cookie
POST /auth/logout  — clear the cookie
GET  /auth/me      — return the current user (used by the frontend to check
                     auth state on page load); response includes the role
                     so the frontend can render the right controls.

Admin-only routes
-----------------
GET    /auth/users           — list all users with their role
POST   /auth/users           — create a user (admin or viewer)
DELETE /auth/users/{username} — remove a user

The cookie is httpOnly (no JS access) and SameSite=lax (CSRF protection).
Set SECURE_COOKIES=true in production so the cookie is only sent over HTTPS.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from backend.auth import (
    AuthDB,
    COOKIE_NAME,
    ROLES,
    SECURE_COOKIES,
    TOKEN_EXPIRE_SECONDS,
    create_token,
    current_user,
    require_admin,
)

router   = APIRouter(prefix='/auth', tags=['auth'])
_auth_db = AuthDB()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str           = Field(min_length=1, max_length=64)
    password: str           = Field(min_length=8, max_length=128)
    role:     str           = Field(default='viewer')


# ---------------------------------------------------------------------------
# Login / logout / me
# ---------------------------------------------------------------------------

@router.post('/login')
async def login(body: LoginRequest, response: Response):
    """
    Verify username and password.
    On success, set an httpOnly JWT cookie and return the username + role.
    On failure, always return 401 with a generic message (no username hints).
    """
    if not _auth_db.verify(body.username, body.password):
        raise HTTPException(status_code=401, detail='Invalid username or password.')

    user = _auth_db.get_user(body.username)
    token = create_token(body.username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=TOKEN_EXPIRE_SECONDS,
        samesite='lax',
        secure=SECURE_COOKIES,
    )
    return {'username': user['username'], 'role': user['role']}


@router.post('/logout')
async def logout(response: Response):
    """Clear the auth cookie."""
    response.delete_cookie(COOKIE_NAME, samesite='lax', secure=SECURE_COOKIES)
    return {'ok': True}


@router.get('/me')
async def me(user: dict = Depends(current_user)):
    """
    Return the currently authenticated user's username and role.
    The frontend calls this on page load to decide whether to show the app
    or the login page, and to pick which controls to render.
    """
    return {'username': user['username'], 'role': user['role']}


# ---------------------------------------------------------------------------
# Admin-only user management
# ---------------------------------------------------------------------------

@router.get('/users')
async def list_users(_: dict = Depends(require_admin)):
    """List every account, including its role."""
    return {'users': _auth_db.list_users()}


@router.post('/users')
async def create_user(body: CreateUserRequest, _: dict = Depends(require_admin)):
    """Create a new user. Default role is 'viewer'."""
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f'role must be one of {list(ROLES)}.')

    if not _auth_db.create_user(body.username, body.password, body.role):
        raise HTTPException(status_code=409, detail='Username is already taken.')

    return {'username': body.username, 'role': body.role}


@router.delete('/users/{username}')
async def delete_user(username: str, admin: dict = Depends(require_admin)):
    """
    Remove a user. The current admin cannot delete themselves, and the
    last remaining admin account cannot be removed (otherwise nobody could
    administer the system).
    """
    if username == admin['username']:
        raise HTTPException(status_code=400, detail='You cannot delete your own account.')

    target = _auth_db.get_user(username)
    if target is None:
        raise HTTPException(status_code=404, detail='User not found.')

    if target['role'] == 'admin' and _auth_db.count_admins() <= 1:
        raise HTTPException(
            status_code=400,
            detail='Cannot delete the last admin account.',
        )

    _auth_db.delete_user(username)
    return {'ok': True}
