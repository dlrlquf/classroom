import os
import sqlite3

from flask import current_app, g

THEMES = {
    "동물": [
        "강아지", "고양이", "토끼", "사자", "호랑이", "코끼리", "기린", "원숭이",
        "곰", "여우", "늑대", "판다", "코알라", "캥거루", "얼룩말", "하마",
        "악어", "거북이", "뱀", "개구리", "돌고래", "고래", "상어", "문어",
        "펭귄", "독수리", "앵무새", "부엉이", "오리", "닭", "공작", "나비",
        "벌", "무당벌레", "거미", "개미", "달팽이", "고슴도치", "다람쥐", "사슴",
        "낙타", "양", "염소", "말", "돼지", "소", "거위", "플라밍고", "해파리",
        "불가사리",
    ],
    "음식": [
        "김치", "김밥", "떡볶이", "비빔밥", "불고기", "삼겹살", "라면", "만두",
        "냉면", "잡채", "피자", "햄버거", "핫도그", "감자튀김", "샌드위치", "스파게티",
        "초밥", "라멘", "타코", "카레", "치킨", "샐러드", "케이크", "도넛",
        "아이스크림", "와플", "쿠키", "초콜릿", "팝콘", "수박", "딸기", "바나나",
        "사과", "포도", "오렌지", "복숭아", "파인애플", "피자빵", "붕어빵", "호떡",
        "토스트", "팬케이크", "마카롱", "푸딩", "솜사탕", "옥수수", "고구마", "계란말이",
        "주먹밥", "빙수",
    ],
    "일상 물건": [
        "우산", "안경", "시계", "휴대전화", "컴퓨터", "텔레비전", "카메라", "책",
        "연필", "지우개", "가방", "신발", "모자", "의자", "책상", "침대",
        "전등", "선풍기", "냉장고", "세탁기", "청소기", "컵", "접시", "숟가락",
        "포크", "젓가락", "냄비", "프라이팬", "열쇠", "자전거", "자동차", "버스",
        "기차", "비행기", "배", "공", "풍선", "인형", "블록", "빗",
        "칫솔", "치약", "비누", "수건", "거울", "화분", "액자", "달력",
        "가위", "망치",
    ],
}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    os.makedirs(app.instance_path, exist_ok=True)
    if "DATABASE" not in app.config:
        legacy_path = os.path.join(app.instance_path, "users.sqlite3")
        database_path = os.path.join(app.instance_path, "game.sqlite3")
        if os.path.isfile(legacy_path):
            legacy_db = sqlite3.connect(legacy_path)
            try:
                legacy_db.execute("DROP TABLE IF EXISTS users")
                legacy_db.commit()
                legacy_db.execute("VACUUM")
            finally:
                legacy_db.close()
        app.config["DATABASE"] = database_path
        if os.path.isfile(legacy_path) and not os.path.exists(database_path):
            os.replace(legacy_path, database_path)
    app.teardown_appcontext(close_db)

    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS themes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                theme_id INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
                word TEXT NOT NULL,
                UNIQUE(theme_id, word)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS response_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module_type TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('active', 'closed')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_response_run
                ON response_runs(status) WHERE status = 'active';
            CREATE TABLE IF NOT EXISTS response_answers (
                run_id INTEGER NOT NULL REFERENCES response_runs(id),
                client_id TEXT NOT NULL,
                participant_name TEXT NOT NULL,
                answer TEXT NOT NULL,
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (run_id, client_id)
            );
            CREATE TABLE IF NOT EXISTS seating_classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                columns_count INTEGER NOT NULL DEFAULT 4,
                rows_count INTEGER NOT NULL DEFAULT 4,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS seating_seats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL REFERENCES seating_classes(id),
                seat_order INTEGER NOT NULL,
                student_name TEXT NOT NULL,
                UNIQUE(class_id, seat_order)
            );
            CREATE TABLE IF NOT EXISTS seating_locked_seats (
                class_id INTEGER NOT NULL REFERENCES seating_classes(id),
                seat_order INTEGER NOT NULL,
                PRIMARY KEY(class_id, seat_order)
            );
            DROP TABLE IF EXISTS users;
            """
        )
        seating_class_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(seating_classes)")
        }
        if "columns_count" not in seating_class_columns:
            db.execute(
                "ALTER TABLE seating_classes ADD COLUMN "
                "columns_count INTEGER NOT NULL DEFAULT 4"
            )
        if "rows_count" not in seating_class_columns:
            db.execute(
                "ALTER TABLE seating_classes ADD COLUMN "
                "rows_count INTEGER NOT NULL DEFAULT 4"
            )
        for theme_name, words in THEMES.items():
            db.execute(
                "INSERT OR IGNORE INTO themes (name) VALUES (?)", (theme_name,)
            )
            theme_id = db.execute(
                "SELECT id FROM themes WHERE name = ?", (theme_name,)
            ).fetchone()["id"]
            db.executemany(
                "INSERT OR IGNORE INTO words (theme_id, word) VALUES (?, ?)",
                ((theme_id, word) for word in words),
            )
        default_theme_id = db.execute(
            "SELECT id FROM themes WHERE name = '동물'"
        ).fetchone()["id"]
        db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('theme_id', ?)",
            (str(default_theme_id),),
        )
        db.execute(
            "INSERT OR IGNORE INTO settings (key, value) "
            "VALUES ('round_duration', '60')"
        )
        db.commit()
