"""Точка входа для Phusion Passenger (ISPmanager / cPanel и т.п.).

Пассенджер на shared-хостингах обычно ждёт WSGI-приложение, поэтому мы
оборачиваем нашу ASGI-апку (FastAPI) через `a2wsgi`. Имя файла
`passenger_wsgi.py` и переменная `application` — стандарт Passenger.

Если у вашего хостинга Passenger 6+ с поддержкой `passenger_app_type asgi`,
вы можете напрямую указать `app.main:app` как ASGI-приложение и удалить этот
файл. Для большинства конфигов «обычного веб-хостинга» оставьте как есть.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Гарантируем, что Python видит наш пакет `app/`
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Если хостинг положил venv рядом — активируем его на всякий случай.
_venv = HERE / ".venv"
if _venv.is_dir():
    _site = _venv / "lib"
    for child in _site.glob("python*/site-packages"):
        if str(child) not in sys.path:
            sys.path.insert(0, str(child))

# Разумные дефолты, чтобы база и аплоды лежали рядом с приложением,
# а не в /data (которая существует только на Fly.io).
os.environ.setdefault("OZERSK_DB", str(HERE / "data" / "ozersk.db"))
os.environ.setdefault("OZERSK_UPLOADS", str(HERE / "data" / "uploads"))
(HERE / "data").mkdir(exist_ok=True)
(HERE / "data" / "uploads").mkdir(exist_ok=True)

from a2wsgi import ASGIMiddleware  # noqa: E402

from app.main import app as _asgi_app  # noqa: E402

application = ASGIMiddleware(_asgi_app)
