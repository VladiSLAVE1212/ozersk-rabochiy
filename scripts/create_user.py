"""Создать аккаунт журналиста / редактора из командной строки.

Пример:
    python scripts/create_user.py ivanov "Иван Иванов" qwerty
    python scripts/create_user.py editor "Главред" hunter2 --admin
"""
from __future__ import annotations

import argparse
import sys

from app.auth import create_user, get_user_by_username
from app.db import init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Создать пользователя")
    parser.add_argument("username", help="Логин")
    parser.add_argument("display_name", nargs="?", default=None, help="Имя для подписи")
    parser.add_argument("password", help="Пароль")
    parser.add_argument("--admin", action="store_true", help="Сделать редактором")
    args = parser.parse_args(argv)

    init_db()

    if get_user_by_username(args.username):
        print(f"Пользователь '{args.username}' уже существует.", file=sys.stderr)
        return 1

    user_id = create_user(
        args.username,
        args.display_name or args.username,
        args.password,
        is_admin=args.admin,
    )
    role = "редактор" if args.admin else "журналист"
    print(f"Создан {role} '{args.username}' (id={user_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
