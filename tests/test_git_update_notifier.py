import asyncio
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from run.git_update_notifier.git_service import GitService
from run.git_update_notifier.main import perform_update_check, report_update_fallback, report_update_via_mai_reply


class TestGitUpdateNotifier(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = Path("tests/test_notifier_data").resolve()
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.service = GitService(data_dir=self.test_dir)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_state_persistence_and_is_notified(self):
        self.assertFalse(self.service.is_notified("abc12345"))
        self.service.mark_notified("abc12345", ahead_count=3, branch="master")
        self.assertTrue(self.service.is_notified("abc12345"))
        self.assertFalse(self.service.is_notified("def67890"))

        new_service = GitService(data_dir=self.test_dir)
        self.assertTrue(new_service.is_notified("abc12345"))

    async def test_no_repeat_notification_when_already_notified(self):
        bot = MagicMock()
        bot.send_friend_message = AsyncMock()
        bot.logger = MagicMock()

        config = MagicMock()
        config.git_update_notifier.config = {
            "enable": True,
            "use_mai_reply": False,
            "notify_master": True,
            "master_id": 123456,
        }
        config.common_config.basic_config = {"master": {"id": 123456}}

        mock_update_info = {
            "success": True,
            "error": "",
            "is_ahead": True,
            "ahead_count": 3,
            "local_commit": "11111111",
            "remote_commit": "22222233",
            "branch": "master",
            "remote": "origin",
            "commit_list": "* [22222233] commit 3\n* [22222222] commit 2\n* [11111122] commit 1",
            "commit_details": "[Commit 22222233] Title: commit 3\n[Commit 22222222] Title: commit 2",
            "diff_stat": "file.py | 10 +-\n 1 file changed, 5 insertions(+), 5 deletions(-)",
        }

        self.service.check_updates = AsyncMock(return_value=mock_update_info)

        # 1. ?????????
        res1 = await perform_update_check(bot, config, self.service, is_manual=False)
        self.assertEqual(bot.send_friend_message.call_count, 1)
        self.assertTrue(self.service.is_notified("22222233"))

        # 2. ???????????????? pull???????
        res2 = await perform_update_check(bot, config, self.service, is_manual=False)
        self.assertEqual(bot.send_friend_message.call_count, 1)

        # 3. ?????? commit 33333344????????
        mock_update_info_new = dict(mock_update_info)
        mock_update_info_new["remote_commit"] = "33333344"
        mock_update_info_new["ahead_count"] = 4
        self.service.check_updates = AsyncMock(return_value=mock_update_info_new)

        res3 = await perform_update_check(bot, config, self.service, is_manual=False)
        self.assertEqual(bot.send_friend_message.call_count, 2)
        self.assertTrue(self.service.is_notified("33333344"))

    async def test_multi_commit_details_in_prompt(self):
        bot = MagicMock()
        config = MagicMock()
        config.mai_reply.config = {"enable": True}

        update_info = {
            "branch": "master",
            "ahead_count": 3,
            "remote_commit": "33333333",
            "commit_details": (
                "[Commit 33333333]\nTitle: Fix login\nAuthor: Alice\nFiles: login.py\n\n"
                "[Commit 22222222]\nTitle: Add notifier\nAuthor: Bob\nFiles: notifier.py\n\n"
                "[Commit 11111111]\nTitle: Refactor DB\nAuthor: Charlie\nFiles: db.py"
            ),
            "diff_stat": "3 files changed, 50 insertions(+), 10 deletions(-)",
        }

        captured_prompt = {}

        class DummyReplyEngine:
            def __init__(self, cfg):
                pass

            async def handle(self, bot_arg, event_arg, prompt_arg):
                captured_prompt["text"] = prompt_arg
                return True

        with patch("run.mai_reply.service.reply_engine.ReplyEngine", DummyReplyEngine):
            ok = await report_update_via_mai_reply(bot, config, 123456, update_info)
            self.assertTrue(ok)
            text = captured_prompt.get("text", "")
            self.assertIn("33333333", text)
            self.assertIn("Fix login", text)
            self.assertIn("Add notifier", text)
            self.assertIn("Refactor DB", text)


if __name__ == "__main__":
    unittest.main()
