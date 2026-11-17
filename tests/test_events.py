import unittest
from types import SimpleNamespace
from unittest.mock import patch

import events


class GameChatTests(unittest.TestCase):
    def setUp(self):
        self.state = patch.multiple(
            events,
            _players={
                "drawer": {"nickname": "Drawer"},
                "player": {"nickname": "Player"},
            },
            _round={
                "drawer_sid": "drawer",
                "word": "apple",
                "started_monotonic": 10,
                "ends_at": 70,
                "number": 1,
                "solved": set(),
            },
            _scores={"drawer": 0, "player": 0},
            _answer_times={"drawer": [], "player": []},
            _participants={"drawer": "Drawer", "player": "Player"},
        )
        self.state.start()
        self.addCleanup(self.state.stop)

    def test_correct_answer_is_hidden_and_player_state_updates(self):
        with (
            patch.object(events, "request", SimpleNamespace(sid="player")),
            patch("events.time.monotonic", return_value=12),
            patch("events._should_finish_round_locked", return_value=False),
            patch("events.socketio.emit") as emit,
        ):
            result = events.on_game_chat_message(
                {"message": "the answer is apple"}
            )

        self.assertEqual(result, {"ok": True, "correct": True})
        emitted_events = [call.args[0] for call in emit.call_args_list]
        self.assertNotIn("game_chat", emitted_events)
        state = next(
            call.args[1]
            for call in emit.call_args_list
            if call.args[0] == "game_state"
        )
        player = next(player for player in state["players"] if player["nickname"] == "Player")
        self.assertTrue(player["solved"])

    def test_korean_answer_inside_chat_is_hidden(self):
        events._round["word"] = "사과"
        with (
            patch.object(events, "request", SimpleNamespace(sid="player")),
            patch("events.time.monotonic", return_value=12),
            patch("events._should_finish_round_locked", return_value=False),
            patch("events.socketio.emit") as emit,
        ):
            result = events.on_game_chat_message({"message": "정답은 사과입니다"})

        self.assertEqual(result, {"ok": True, "correct": True})
        self.assertNotIn(
            "game_chat", [call.args[0] for call in emit.call_args_list]
        )

    def test_incorrect_chat_is_still_published(self):
        with (
            patch.object(events, "request", SimpleNamespace(sid="player")),
            patch("events.socketio.emit") as emit,
        ):
            result = events.on_game_chat_message({"message": "hello"})

        self.assertEqual(result, {"ok": True, "correct": False})
        emit.assert_called_once_with(
            "game_chat",
            {
                "nickname": "Player",
                "message": "hello",
                "channel": "normal",
                "correct": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
