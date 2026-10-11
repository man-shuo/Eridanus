import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from run.git_update_notifier.git_service import GitService
from run.git_update_notifier.main import (
    perform_update_check,
    report_update_via_mai_reply,
    report_update_fallback,
    _get_plugin_config,
    _get_master_id,
)


class TestGitUpdateNotifier(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_data_dir = Path(__file__).resolve().parent / "test_data"
        self.git_service = GitService(data_dir=self.test_data_dir)

    async def asyncTearDown(self):
        if self.git_service.state_file.exists():
            self.git_service.state_file.unlink()
        if self.test_data_dir.exists():
            try:
                self.test_data_dir.rmdir()
            except Exception:
                pass

    async def test_get_current_branch_and_commit(self):
        branch = await self.git_service.get_current_branch()
        self.assertTrue(bool(branch))
        self.assertIn(branch, ["master", "main", "pr-318", "pr-328"])

        local_commit = await self.git_service.get_local_commit()
        self.assertTrue(bool(local_commit))
        self.assertEqual(len(local_commit), 40)

    async def test_state_management(self):
        self.assertFalse(self.git_service.is_notified("dummy_hash_1"))
        self.git_service.mark_notified("dummy_hash_1", ahead_count=3, branch="master")
        self.assertTrue(self.git_service.is_notified("dummy_hash_1"))
        self.assertFalse(self.git_service.is_notified("dummy_hash_2"))

        state = self.git_service.load_state()
        self.assertEqual(state["last_notified_commit"], "dummy_hash_1")
        self.assertEqual(state["last_notified_ahead_count"], 3)
        self.assertEqual(state["last_notified_branch"], "master")

    async def test_report_update_via_mai_reply(self):
        mock_bot = MagicMock()
        mock_config = MagicMock()
        mock_config.mai_reply.config = {"enable": True}

        simulated_update_info = {
            "success": True,
            "error": "",
            "is_ahead": True,
            "ahead_count": 2,
            "local_commit": "abcdef123456",
            "remote_commit": "fedcba6543210000000000000000000000000000",
            "branch": "master",
            "remote": "origin",
            "commit_list": "* [fedcba65] 修复重要bug (Alice, 2026-10-11)\n* [12345678] 增加新特性 (Bob, 2026-10-11)",
            "commit_details": "【提交 fedcba65】修复重要bug\n作者: Alice | 日期: 2026-10-11\n提交说明: 修复网络超时问题",
            "diff_stat": " main.py | 10 +++++-----\n 1 file changed, 5 insertions(+), 5 deletions(-)",
        }

        with patch("run.mai_reply.service.reply_engine.ReplyEngine") as mock_engine_cls:
            mock_engine = mock_engine_cls.return_value
            mock_engine.handle = AsyncMock()

            result = await report_update_via_mai_reply(mock_bot, mock_config, 123456, simulated_update_info)
            self.assertTrue(result)
            mock_engine.handle.assert_called_once()

            args = mock_engine.handle.call_args[0]
            self.assertEqual(args[0], mock_bot)
            self.assertEqual(args[1].user_id, 123456)
            prompt = args[2]
            self.assertIn("【系统事件：检测到 Git 远程仓库有新版本发布/更新】", prompt)
            self.assertIn("分支：master", prompt)
            self.assertIn("修复重要bug", prompt)

    async def test_report_update_fallback(self):
        mock_bot = MagicMock()
        mock_bot.send_friend_message = AsyncMock()
        mock_config = MagicMock()

        simulated_update_info = {
            "branch": "master",
            "ahead_count": 1,
            "commit_list": "* [abc12345] 更新说明",
            "diff_stat": "file.py | 2 +-",
        }

        await report_update_fallback(mock_bot, mock_config, 999888, simulated_update_info)
        mock_bot.send_friend_message.assert_called_once()
        call_args = mock_bot.send_friend_message.call_args[0]
        self.assertEqual(call_args[0], 999888)
        self.assertIn("【Git 仓库更新提醒】", call_args[1])
        self.assertIn("领先 1 个 commit", call_args[1])

    async def test_perform_update_check_flow(self):
        mock_bot = MagicMock()
        mock_config = MagicMock()
        mock_config.git_update_notifier.config = {
            "enable": True,
            "remote": "origin",
            "branch": "master",
            "max_commit_log_count": 5,
            "fetch_timeout": 30,
            "use_mai_reply": True,
            "notify_master": True,
            "master_id": 1840094972,
        }
        mock_config.mai_reply.config = {"enable": True}

        simulated_ahead = {
            "success": True,
            "error": "",
            "is_ahead": True,
            "ahead_count": 1,
            "local_commit": "111111",
            "remote_commit": "2222223333334444445555556666667777778888",
            "branch": "master",
            "remote": "origin",
            "commit_list": "* [22222233] 性能优化",
            "commit_details": "【提交 22222233】性能优化",
            "diff_stat": " 1 file changed",
        }

        with patch.object(self.git_service, "check_updates", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = simulated_ahead
            with patch("run.git_update_notifier.main.report_update_via_mai_reply", new_callable=AsyncMock) as mock_mai:
                mock_mai.return_value = True

                # 第一次检查：应当触发通知，并记录已通知状态
                res1 = await perform_update_check(mock_bot, mock_config, self.git_service, force_notify=False)
                self.assertTrue(res1["is_ahead"])
                mock_mai.assert_called_once()
                self.assertTrue(self.git_service.is_notified("2222223333334444445555556666667777778888"))

                # 第二次检查：已记录过，跳过重复通知
                mock_mai.reset_mock()
                res2 = await perform_update_check(mock_bot, mock_config, self.git_service, force_notify=False)
                self.assertTrue(res2["is_ahead"])
                mock_mai.assert_not_called()

                # 手动强制检查：忽略去重，再次通知
                mock_mai.reset_mock()
                res3 = await perform_update_check(mock_bot, mock_config, self.git_service, force_notify=True)
                self.assertTrue(res3["is_ahead"])
                mock_mai.assert_called_once()


if __name__ == "__main__":
    unittest.main()
