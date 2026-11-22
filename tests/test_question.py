import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

import question
import lobby
from database import close_db, get_db


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
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    class_id INTEGER NOT NULL,
                    client_id TEXT NOT NULL,
                    participant_name TEXT NOT NULL,
                    question TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO seating_classes (id, name) VALUES (1, '1반');
                """
            )
            db.commit()

        self.pending_state = patch.object(question, "_pending_questions", {})
        self.pending_state.start()
        self.addCleanup(self.pending_state.stop)
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

    def test_question_includes_participant_and_hides_client_id(self):
        with (
            self.app.test_request_context(),
            patch.object(question, "request", SimpleNamespace(sid="user-sid")),
            patch(
                "question.lobby.get_user_by_sid",
                return_value=(
                    "device-id",
                    {
                        "name": "홍길동",
                        "sid": "user-sid",
                        "class_id": 1,
                    },
                ),
            ),
            patch("question.lobby.get_selected_class_id", return_value=1),
            patch("question.socketio.emit") as emit,
        ):
            result = question.on_ask_question(
                {"question": "  이 단원은 다시 설명해 주실 수 있나요?  "}
            )

        self.assertEqual(result, {"ok": True})
        emitted = emit.call_args.args[1]["question"]
        self.assertEqual(emitted["name"], "홍길동")
        self.assertEqual(
            emitted["question"], "이 단원은 다시 설명해 주실 수 있나요?"
        )
        self.assertNotIn("client_id", emitted)

    def test_save_persists_only_selected_class_questions(self):
        question._pending_questions[1] = [
            {
                "id": "pending-1",
                "client_id": "device-id",
                "name": "홍길동",
                "question": "첫 번째 질문",
                "created_at": None,
                "saved": False,
            }
        ]
        question._pending_questions[2] = [
            {
                "id": "pending-2",
                "client_id": "other-device",
                "name": "김영희",
                "question": "다른 반 질문",
                "created_at": None,
                "saved": False,
            }
        ]

        with (
            self.app.test_request_context(),
            patch.object(question, "_is_host", return_value=True),
            patch(
                "question.lobby.get_selected_class",
                return_value={"id": 1, "name": "1반"},
            ),
        ):
            result = question.on_save_questions()
            db_rows = [
                dict(row)
                for row in get_db().execute(
                    "SELECT class_id, participant_name, question "
                    "FROM questions ORDER BY id"
                ).fetchall()
            ]

        self.assertEqual(result["saved_count"], 1)
        self.assertEqual(
            db_rows,
            [
                {
                    "class_id": 1,
                    "participant_name": "홍길동",
                    "question": "첫 번째 질문",
                }
            ],
        )
        self.assertEqual(question._pending_questions[1], [])
        self.assertEqual(len(question._pending_questions[2]), 1)

    def test_questions_are_grouped_by_participant(self):
        questions = [
            {"name": "홍길동", "question": "첫 질문", "saved": True},
            {"name": "김영희", "question": "다른 질문", "saved": True},
            {"name": "홍길동", "question": "두 번째 질문", "saved": False},
        ]

        grouped = question._participants_for_questions(questions)

        self.assertEqual([participant["name"] for participant in grouped], ["홍길동", "김영희"])
        self.assertEqual(
            [question["question"] for question in grouped[0]["questions"]],
            ["첫 질문", "두 번째 질문"],
        )


if __name__ == "__main__":
    unittest.main()
