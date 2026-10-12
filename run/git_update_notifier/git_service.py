import asyncio
import json
from developTools.utils.logger import get_logger
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = get_logger("GitUpdateNotifier")


class GitService:
    def __init__(self, repo_root: Optional[Path] = None, data_dir: Optional[Path] = None):
        if repo_root is None:
            self.repo_root = Path(__file__).resolve().parent.parent.parent
        else:
            self.repo_root = Path(repo_root)

        if data_dir is None:
            self.data_dir = Path(__file__).resolve().parent / "data"
        else:
            self.data_dir = Path(data_dir)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / "git_update_state.json"

    def _run_git_sync(self, args: list[str], timeout: int = 30) -> Tuple[int, str, str]:
        try:
            res = subprocess.run(
                ["git"] + args,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"Git 命令超时（{timeout}秒）: git {' '.join(args)}"
        except Exception as e:
            return -1, "", str(e)

    async def run_git(self, args: list[str], timeout: int = 30) -> Tuple[int, str, str]:
        return await asyncio.to_thread(self._run_git_sync, args, timeout)

    async def get_current_branch(self) -> str:
        code, out, _ = await self.run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if code == 0 and out:
            return out
        return "master"

    async def get_local_commit(self) -> str:
        code, out, _ = await self.run_git(["rev-parse", "HEAD"])
        if code == 0 and out:
            return out
        return ""

    async def fetch_remote(self, remote: str = "origin", branch: str = "master", timeout: int = 45) -> Tuple[bool, str]:
        if branch == "auto":
            branch = await self.get_current_branch()

        code, out, err = await self.run_git(["fetch", remote, branch], timeout=timeout)
        if code == 0:
            return True, out
        else:
            logger.warning(f"git fetch {remote} {branch} 失败: {err}，尝试直接 git fetch {remote}")
            c2, o2, e2 = await self.run_git(["fetch", remote], timeout=timeout)
            if c2 == 0:
                return True, o2
            return False, f"{err}\n{e2}".strip()

    async def check_updates(
        self,
        remote: str = "origin",
        branch: str = "auto",
        max_commits: int = 20,
        fetch_timeout: int = 45,
    ) -> Dict[str, Any]:
        target_branch = branch
        if target_branch == "auto" or not target_branch:
            target_branch = await self.get_current_branch()

        local_commit = await self.get_local_commit()

        fetch_ok, fetch_msg = await self.fetch_remote(remote=remote, branch=target_branch, timeout=fetch_timeout)
        if not fetch_ok:
            return {
                "success": False,
                "error": f"拉取远程分支失败: {fetch_msg}",
                "is_ahead": False,
                "ahead_count": 0,
                "local_commit": local_commit,
                "remote_commit": "",
                "branch": target_branch,
                "remote": remote,
            }

        remote_ref = f"{remote}/{target_branch}"
        code, remote_commit, _ = await self.run_git(["rev-parse", remote_ref])
        if code != 0 or not remote_commit:
            code_fetch, fetch_head, _ = await self.run_git(["rev-parse", "FETCH_HEAD"])
            if code_fetch == 0 and fetch_head:
                remote_ref = "FETCH_HEAD"
                remote_commit = fetch_head
            else:
                return {
                    "success": False,
                    "error": f"无法解析远程引用 {remote_ref} 或 FETCH_HEAD",
                    "is_ahead": False,
                    "ahead_count": 0,
                    "local_commit": local_commit,
                    "remote_commit": "",
                    "branch": target_branch,
                    "remote": remote,
                }

        code_count, count_str, _ = await self.run_git(["rev-list", "--count", f"HEAD..{remote_ref}"])
        ahead_count = int(count_str) if (code_count == 0 and count_str.isdigit()) else 0

        is_ahead = ahead_count > 0

        commit_list = ""
        commit_details = ""
        diff_stat = ""

        if is_ahead:
            # 1. 提交摘要简要列表
            _, commit_list, _ = await self.run_git([
                "log",
                f"HEAD..{remote_ref}",
                "--pretty=format:* [%h] %s (%an, %cd)",
                "--date=format:%Y-%m-%d %H:%M",
                f"-n{max_commits}",
            ])

            # 2. 详细包含每个 commit 的变动内容、提交人与说明
            _, raw_log, _ = await self.run_git([
                "log",
                f"HEAD..{remote_ref}",
                "--name-status",
                "--pretty=format:===COMMIT_SPLIT===%n[Commit %h]%nTitle: %s%nAuthor: %an (%cd)%nBody: %b%nFiles:",
                "--date=format:%Y-%m-%d %H:%M",
                f"-n{max_commits}",
            ])

            parts = [p.strip() for p in raw_log.split("===COMMIT_SPLIT===") if p.strip()]
            commit_details = "\n\n".join(parts)

            # 3. 统计变动文件
            _, diff_stat, _ = await self.run_git([
                "diff",
                "--stat",
                f"HEAD..{remote_ref}",
            ])

        return {
            "success": True,
            "error": "",
            "is_ahead": is_ahead,
            "ahead_count": ahead_count,
            "local_commit": local_commit,
            "remote_commit": remote_commit,
            "branch": target_branch,
            "remote": remote,
            "commit_list": commit_list,
            "commit_details": commit_details,
            "diff_stat": diff_stat,
        }

    def load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取状态文件 {self.state_file} 失败: {e}")
            return {}

    def save_state(self, state: Dict[str, Any]) -> None:
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存状态文件 {self.state_file} 失败: {e}")

    def is_notified(self, remote_commit: str) -> bool:
        if not remote_commit:
            return False
        state = self.load_state()
        return state.get("last_notified_commit") == remote_commit

    def mark_notified(self, remote_commit: str, ahead_count: int, branch: str) -> None:
        import datetime
        state = self.load_state()
        state["last_notified_commit"] = remote_commit
        state["last_notified_ahead_count"] = ahead_count
        state["last_notified_branch"] = branch
        state["last_notified_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.save_state(state)