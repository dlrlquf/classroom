import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

import lobby
import question
from database import close_db, get_db, init_app


class QuestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config["DATABASE"] = os.path.join(
            self.temp_dir.name, "question.sqlite3"
        )
        self.app.teardown_appcontext(close_db)
        with self.app.app_context():
            db = get_db()
            db.executescript(
                """
                CREATE TABLE seating_classes (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL
                );
                CREATE TABLE question_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL,
                    session_id INTEGER,
                    client_id TEXT NOT NULL,
                    participant_name TEXT NOT NULL,
                    question TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO seating_classes (id, name) VALUES (1, '1반');
                INSERT INTO question_sessions (id, class_id, name, is_active)
                    VALUES (1, 1, '1교시', 1);
                """
            )
            db.commit()
        self.addCleanup(self.temp_dir.cleanup)

    def test_user_join_is_blocked_before_class_starts(self):
        with (
            self.app.test_request_context(),
            patch.multiple(lobby, _class_started=False, _selected_class_id=1),
            patch.object(lobby, "request", SimpleNamespace(sid="user-sid")),
        ):
            result = lobby.on_user_join(
                {
                    "code": lobby.get_code(),
                    "name": "홍길동",
                    "client_id": "1234567890123456",
                }
            )

        self.assertFalse(result["ok"])
        self.assertIn("아직 시작하지", result["message"])

    def test_question_is_saved_to_active_session(self):
        with (
            self.app.test_request_context(),
            patch.object(question, "request", SimpleNamespace(sid="user-sid")),
            patch(
                "question.lobby.get_user_by_sid",
                return_value=(
                    "device-id",
                    {"name": "홍길동", "sid": "user-sid", "class_id": 1},
                ),
            ),
            patch("question.lobby.get_selected_class_id", return_value=1),
            patch("question.socketio.emit") as emit,
        ):
            result = question.on_ask_question(
                {"question": "  이 단원은 다시 설명해 주실 수 있나요?  "}
            )
            row = get_db().execute(
                "SELECT class_id, session_id, client_id, participant_name, question "
                "FROM questions"
            ).fetchone()

        self.assertTrue(result["ok"])
        self.assertEqual(result["session"]["name"], "1교시")
        self.assertEqual(
            dict(row),
            {
                "class_id": 1,
                "session_id": 1,
                "client_id": "device-id",
                "participant_name": "홍길동",
                "question": "이 단원은 다시 설명해 주실 수 있나요?",
            },
        )
        emitted = emit.call_args.args[1]
        self.assertEqual(emitted["session_id"], 1)
        self.assertEqual(emitted["question"]["name"], "홍길동")
        self.assertTrue(emitted["question"]["saved"])
        self.assertNotIn("client_id", emitted["question"])

    def test_question_is_rejected_when_no_session_is_active(self):
        with self.app.app_context():
            get_db().execute(
                "UPDATE question_sessions SET is_active = 0 WHERE class_id = 1"
            )
            get_db().commit()

        with (
            self.app.test_request_context(),
            patch.object(question, "request", SimpleNamespace(sid="user-sid")),
            patch(
                "question.lobby.get_user_by_sid",
                return_value=(
                    "device-id",
                    {"name": "홍길동", "sid": "user-sid", "class_id": 1},
                ),
            ),
            patch("question.lobby.get_selected_class_id", return_value=1),
        ):
            result = question.on_ask_question({"question": "질문"})

        self.assertFalse(result["ok"])
        self.assertIn("세션을 열지 않았습니다", result["message"])

    def test_host_can_create_and_select_question_sessions(self):
        with self.app.app_context():
            get_db().execute(
                "INSERT INTO question_sessions (class_id, name) VALUES (1, '2교시')"
            )
            get_db().commit()

        with (
            self.app.test_request_context(),
            patch.object(question, "_is_host", return_value=True),
            patch(
                "question.lobby.get_selected_class",
                return_value={"id": 1, "name": "1반"},
            ),
            patch("question.socketio.emit"),
        ):
            created = question.on_create_question_session({"name": "  정리 시간  "})
            selected = question.on_select_question_session({"session_id": 2})

        self.assertEqual(created["active_session"]["name"], "정리 시간")
        self.assertEqual(selected["active_session"]["name"], "2교시")
        with self.app.app_context():
            active = get_db().execute(
                "SELECT name FROM question_sessions "
                "WHERE class_id = 1 AND is_active = 1"
            ).fetchone()
        self.assertEqual(active["name"], "2교시")

    def test_session_selection_rejects_sessions_from_another_class(self):
        with self.app.app_context():
            db = get_db()
            db.execute("INSERT INTO seating_classes (id, name) VALUES (2, '2반')")
            db.execute(
                "INSERT INTO question_sessions (id, class_id, name) "
                "VALUES (2, 2, '다른 반')"
            )
            db.commit()

        with (
            self.app.test_request_context(),
            patch.object(question, "_is_host", return_value=True),
            patch(
                "question.lobby.get_selected_class",
                return_value={"id": 1, "name": "1반"},
            ),
        ):
            result = question.on_select_question_session({"session_id": 2})

        self.assertFalse(result["ok"])
        self.assertIn("찾을 수 없습니다", result["message"])

    def test_existing_questions_are_migrated_into_legacy_session(self):
        legacy_path = os.path.join(self.temp_dir.name, "legacy.sqlite3")
        legacy_db = sqlite3.connect(legacy_path)
        legacy_db.executescript(
            """
            CREATE TABLE seating_classes (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            INSERT INTO seating_classes (id, name) VALUES (1, '1반');
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY,
                class_id INTEGER NOT NULL,
                client_id TEXT NOT NULL,
                participant_name TEXT NOT NULL,
                question TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO questions
                (id, class_id, client_id, participant_name, question)
                VALUES (1, 1, 'device-id', '홍길동', '이전 질문');
            """
        )
        legacy_db.close()
        legacy_app = Flask(__name__)
        legacy_app.instance_path = self.temp_dir.name
        legacy_app.config["DATABASE"] = legacy_path
        init_app(legacy_app)

        with legacy_app.app_context():
            row = get_db().execute(
                "SELECT questions.question, question_sessions.name, "
                "questions.session_id "
                "FROM questions JOIN question_sessions "
                "ON question_sessions.id = questions.session_id"
            ).fetchone()

        self.assertEqual(row["question"], "이전 질문")
        self.assertEqual(row["name"], "기존 질문")
        self.assertEqual(row["session_id"], 1)

    def test_questions_are_grouped_by_participant(self):
        questions = [
            {"name": "홍길동", "question": "첫 질문", "saved": True},
            {"name": "김영희", "question": "다른 질문", "saved": True},
            {"name": "홍길동", "question": "두 번째 질문", "saved": True},
        ]

        grouped = question._participants_for_questions(questions)

        self.assertEqual(
            [participant["name"] for participant in grouped],
            ["홍길동", "김영희"],
        )
        self.assertEqual(
            [item["question"] for item in grouped[0]["questions"]],
            ["첫 질문", "두 번째 질문"],
        )


if __name__ == "__main__":
    unittest.main()
