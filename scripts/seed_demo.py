"""Загрузить пару демо-новостей, чтобы было что показать на главной."""
from __future__ import annotations

import sys

from app.auth import create_user, get_user_by_username
from app.content import make_summary, render_body, slugify
from app.db import get_conn, init_db

DEMO_POSTS = [
    {
        "title": "На центральной площади открыт новый памятник пятилетке",
        "category": "kultura",
        "cover": "",
        "body": (
            "В торжественной обстановке у здания горисполкома состоялось открытие "
            "памятника, посвящённого выполнению очередной городской пятилетки. "
            "К постаменту были возложены цветы.\n\n"
            "[b]Корреспондент Озёрского Рабочего[/b] передаёт с места событий: "
            "после торжественной речи мэра присутствующие исполнили гимн города."
        ),
    },
    {
        "title": "ЖКХ обещает горячую воду к концу недели",
        "category": "zhkkh",
        "cover": "",
        "body": (
            "Управление жилищно-коммунального хозяйства сообщило, что плановое "
            "отключение горячей воды продлится ещё [u]три дня[/u]. "
            "Жителям рекомендуется запастись чайниками и терпением.\n\n"
            "[h2]Что советует ведомство[/h2]\n"
            "Не забывать, что холодная вода — тоже вода, а закаливание полезно для здоровья."
        ),
    },
    {
        "title": "В городском парке прошёл забег «Пятилетка за три минуты»",
        "category": "sport",
        "cover": "",
        "body": (
            "В минувшие выходные в городском парке состоялся традиционный забег "
            "[i]«Пятилетка за три минуты»[/i]. Победитель получил годовой запас "
            "пельменей от спонсоров.\n\n"
            "Следующий старт — через год."
        ),
    },
]


def main() -> int:
    init_db()

    author = get_user_by_username("demo")
    if author is None:
        author_id = create_user("demo", "Демокор Демокорович", "demopassword")
    else:
        author_id = author["id"]

    with get_conn() as conn:
        cats = {c["slug"]: c["id"] for c in conn.execute("SELECT * FROM categories").fetchall()}
        for p in DEMO_POSTS:
            slug = slugify(p["title"])
            existing = conn.execute("SELECT id FROM posts WHERE slug = ?", (slug,)).fetchone()
            if existing:
                continue
            rendered = render_body(p["body"])
            conn.execute(
                "INSERT INTO posts (slug, title, summary, body, cover_url, category_id, "
                "author_id, published) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    slug,
                    p["title"],
                    make_summary(rendered),
                    p["body"],
                    p["cover"],
                    cats.get(p["category"]),
                    author_id,
                ),
            )
    print("Демо-новости загружены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
