"""Password hashing + session management."""
from __future__ import annotations

import sqlite3
from typing import Optional

import bcrypt
from fastapi import Request

from .db import get_conn


def _to_bytes(password: str) -> bytes:
    # bcrypt only supports up to 72 bytes; truncate longer passwords gracefully.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_to_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        )
        return cur.fetchone()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()


def authenticate(username: str, password: str) -> Optional[sqlite3.Row]:
    user = get_user_by_username(username)
    if user is None:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


def current_user(request: Request) -> Optional[sqlite3.Row]:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return get_user_by_id(user_id)


def create_user(
    username: str,
    display_name: str,
    password: str,
    is_admin: bool = False,
) -> int:
    username = username.strip()
    display_name = display_name.strip() or username
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash, is_admin) "
            "VALUES (?, ?, ?, ?)",
            (username, display_name, hash_password(password), 1 if is_admin else 0),
        )
        return int(cur.lastrowid)
