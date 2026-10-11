import asyncio
import logging
from typing import Optional, Dict, Any

from developTools.event.events import GroupMessageEvent, PrivateMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Text
from framework_common.framework_util.any_event import AnyEvent
from framework_common.framework_util.websocket_fix import ExtendBot
from run.git_update_notifier.git_service import GitService

logger = logging.getLogger("GitUpdateNotifier")

_bg_task: Optional[asyncio.Task] = None
_loop_started = False
_lock = asyncio.Lock()


def _get_plugin_config(config) -> Dict[str, Any]:
    try:
        if hasattr(config, "git_update_notifier") and hasattr(config.git_update_notifier, "config"):
            return config.git_update_notifier.config
    except Exception:
        pass
    return {
        "enable": True,
        "check_interval": 1800,
        "initial_delay": 20,
        "remote": "origin",
        "branch": "auto",
        "use_mai_reply": True,
        "notify_master": True,
        "master_id": None,
        "max_commit_log_count": 15,
        "fetch_timeout": 45,
        "notify_up_to_date_on_manual": True,
    }


def _get_master_id(config, plugin_cfg: Dict[str, Any]) -> Optional[int]:
    cfg_master = plugin_cfg.get("master_id")
    if cfg_master:
        try:
            return int(cfg_master)
        except (ValueError, TypeError):
            pass

    try:
        master_id = config.common_config.basic_config["master"]["id"]
        return int(master_id)
    except Exception:
        pass

    return None


async def send_to_master(bot: ExtendBot, master_id: int, message: str):
    try:
        await bot.send_friend_message(master_id, message)
    except Exception as e:
        logger.error(f"[GitNotifier] ? master ({master_id}) ????????: {e}")


async def report_update_via_mai_reply(bot: ExtendBot, config, master_id: int, update_info: Dict[str, Any]) -> bool:
    try:
        mai_cfg = getattr(config, "mai_reply", None)
        if not mai_cfg:
            logger.info("[GitNotifier] mai_reply ?????????????")
            return False

        mai_dict = getattr(mai_cfg, "config", {})
        if not isinstance(mai_dict, dict) or not mai_dict.get("enable", False):
            logger.info("[GitNotifier] mai_reply ???????????")
            return False

        from run.mai_reply.service.reply_engine import ReplyEngine

        engine = ReplyEngine(config)
        event = AnyEvent()
        event.user_id = int(master_id)

        prompt = (
            f"????????? Git ??????????/???????\n"
            f"?????{update_info['branch']}\n"
            f"??????????????? {update_info['ahead_count']} ? commit\n"
            f"???????{update_info['remote_commit'][:8]}\n\n"
            f"???????? Commit ??????????????????????? commit??\n"
            f"{update_info['commit_details']}\n\n"
            f"???????????\n{update_info['diff_stat']}\n\n"
            f"????? - ?????????\n"
            f"?????????????????????????Master??????????\n"
            f"1. ????????????????????????????????????? {update_info['ahead_count']} ? commit??\n"
            f"2. ??????????????????????? commit ???????\n"
            f"   - ?????? commit????????????? commit ????????????? bug??????????????????\n"
            f"   - ??????????????????????? log???????????????? commit ??????\n"
            f"3. ???????????????????????? git pull ?????????"
        )

        logger.info(f"[GitNotifier] ???? mai_reply ????? master ({master_id}) ?????? {update_info['ahead_count']} ? commit?...")
        await engine.handle(bot, event, prompt)
        return True

    except Exception as e:
        logger.error(f"[GitNotifier] ?? mai_reply ??????: {e}", exc_info=True)
        return False


async def report_update_fallback(bot: ExtendBot, config, master_id: int, update_info: Dict[str, Any]):
    structured_msg = (
        f"?? ?Git ???????\n"
        f"???????????: {update_info['branch']}??? {update_info['ahead_count']} ? commit?\n\n"
        f"?????????\n{update_info['commit_details']}\n\n"
        f"?????????\n{update_info['diff_stat']}\n\n"
        f"?? ????????? git pull ??????????????"
    )
    await send_to_master(bot, master_id, structured_msg)


async def perform_update_check(
    bot: ExtendBot,
    config,
    git_service: GitService,
    is_manual: bool = False,
    force_notify: bool = False,
) -> Dict[str, Any]:
    plugin_cfg = _get_plugin_config(config)
    remote = plugin_cfg.get("remote", "origin")
    branch = plugin_cfg.get("branch", "auto")
    max_commits = int(plugin_cfg.get("max_commit_log_count", 15))
    fetch_timeout = int(plugin_cfg.get("fetch_timeout", 45))
    use_mai = plugin_cfg.get("use_mai_reply", True)
    notify_master = plugin_cfg.get("notify_master", True)

    master_id = _get_master_id(config, plugin_cfg)

    logger.info(f"[GitNotifier] ?????? Git ???remote={remote}, branch={branch}?...")
    update_info = await git_service.check_updates(
        remote=remote,
        branch=branch,
        max_commits=max_commits,
        fetch_timeout=fetch_timeout,
    )

    if not update_info["success"]:
        logger.error(f"[GitNotifier] ??????: {update_info['error']}")
        return update_info

    if not update_info["is_ahead"]:
        logger.info(f"[GitNotifier] ????????????????/???? {update_info['local_commit'][:8]}?")
        return update_info

    ahead_count = update_info["ahead_count"]
    remote_commit = update_info["remote_commit"]
    logger.info(
        f"[GitNotifier] ??????????????? {ahead_count} ? commit (?? commit: {remote_commit[:8]})"
    )

    if not force_notify and git_service.is_notified(remote_commit):
        logger.info(f"[GitNotifier] ? commit {remote_commit[:8]} ??????????????")
        return update_info

    if notify_master and master_id:
        reported = False
        if use_mai:
            reported = await report_update_via_mai_reply(bot, config, master_id, update_info)

        if not reported:
            await report_update_fallback(bot, config, master_id, update_info)

        git_service.mark_notified(remote_commit, ahead_count, update_info["branch"])

    return update_info


async def git_monitor_loop(bot: ExtendBot, config, git_service: GitService):
    plugin_cfg = _get_plugin_config(config)
    initial_delay = float(plugin_cfg.get("initial_delay", 20))
    check_interval = float(plugin_cfg.get("check_interval", 1800))

    logger.info(f"[GitNotifier] ???????????? {initial_delay} ????????????? {check_interval} ?")
    await asyncio.sleep(initial_delay)

    while True:
        try:
            current_cfg = _get_plugin_config(config)
            if not current_cfg.get("enable", True):
                logger.info("[GitNotifier] ?????????????")
                await asyncio.sleep(60)
                continue

            interval = float(current_cfg.get("check_interval", 1800))
            await perform_update_check(bot, config, git_service, is_manual=False)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[GitNotifier] ?????????")
            break
        except Exception as e:
            logger.error(f"[GitNotifier] ??????: {e}", exc_info=True)
            await asyncio.sleep(60)


def main(bot: ExtendBot, config):
    plugin_cfg = _get_plugin_config(config)
    if not plugin_cfg.get("enable", True):
        bot.logger.info("[GitNotifier] ????? (enable=false)")
        return

    git_service = GitService()

    global _bg_task, _loop_started

    def _start_background_loop():
        global _bg_task, _loop_started
        if _loop_started and _bg_task is not None and not _bg_task.done():
            return
        _loop_started = True
        _bg_task = asyncio.create_task(git_monitor_loop(bot, config, git_service))
        bot.logger.info("[GitNotifier] ?????????????")

    @bot.on(LifecycleMetaEvent)
    async def on_lifecycle(event: LifecycleMetaEvent):
        _start_background_loop()

    bot_loop = getattr(bot, "loop", None)
    if bot_loop and bot_loop.is_running():
        try:
            bot_loop.call_soon_threadsafe(_start_background_loop)
        except Exception:
            pass

    @bot.on(GroupMessageEvent)
    @bot.on(PrivateMessageEvent)
    async def handle_git_commands(event: GroupMessageEvent | PrivateMessageEvent):
        text = (getattr(event, "pure_text", "") or "").strip()
        command_list = ["/git check", "/git status", "????", "????", "/check_update"]
        if text not in command_list:
            return

        current_cfg = _get_plugin_config(config)
        master_id = _get_master_id(config, current_cfg)

        if event.user_id != master_id:
            await bot.send(event, [Text("?????????Master?????? Git ?????~")])
            return

        await bot.send(event, [Text("?????? Git ????????????...")])

        try:
            update_info = await perform_update_check(
                bot, config, git_service, is_manual=True, force_notify=True
            )

            if not update_info["success"]:
                await bot.send(event, [Text(f"? ???????\n{update_info['error']}")])
                return

            if not update_info["is_ahead"]:
                if current_cfg.get("notify_up_to_date_on_manual", True):
                    await bot.send(
                        event,
                        [Text(f"? ?????????????\n??: {update_info['branch']}\n????: {update_info['local_commit'][:8]}\n?????????")]
                    )
            else:
                await bot.send(
                    event,
                    [Text(f"?? ?????? {update_info['branch']} ?? {update_info['ahead_count']} ? commit???????????????????? Master...")]
                )

        except Exception as e:
            bot.logger.error(f"[GitNotifier] ????????: {e}", exc_info=True)
            await bot.send(event, [Text(f"? ????: {e}")])
