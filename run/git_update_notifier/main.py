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
    """获取插件配置，兼顾各种配置加载方式"""
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
        "max_commit_log_count": 10,
        "fetch_timeout": 45,
        "notify_up_to_date_on_manual": True,
    }


def _get_master_id(config, plugin_cfg: Dict[str, Any]) -> Optional[int]:
    """获取 Master 的 QQ 号"""
    # 1. 优先读取插件独立配置
    cfg_master = plugin_cfg.get("master_id")
    if cfg_master:
        try:
            return int(cfg_master)
        except (ValueError, TypeError):
            pass

    # 2. 读取全局 common_config
    try:
        master_id = config.common_config.basic_config["master"]["id"]
        return int(master_id)
    except Exception:
        pass

    return None


async def send_to_master(bot: ExtendBot, master_id: int, message: str):
    """向管理员发送私聊消息的兜底方法"""
    try:
        await bot.send_friend_message(master_id, message)
    except Exception as e:
        logger.error(f"[GitNotifier] 向 master ({master_id}) 发送私聊消息失败: {e}")


async def report_update_via_mai_reply(bot: ExtendBot, config, master_id: int, update_info: Dict[str, Any]) -> bool:
    """调用 mai_reply 的对话核心生成个性化更新汇报并发送给 master"""
    try:
        mai_cfg = getattr(config, "mai_reply", None)
        if not mai_cfg:
            logger.info("[GitNotifier] mai_reply 模块不存在，跳过角色化汇报")
            return False

        # 检查 mai_reply 是否开启
        mai_dict = getattr(mai_cfg, "config", {})
        if not isinstance(mai_dict, dict) or not mai_dict.get("enable", False):
            logger.info("[GitNotifier] mai_reply 未启用，跳过角色化汇报")
            return False

        from run.mai_reply.service.reply_engine import ReplyEngine

        engine = ReplyEngine(config)
        event = AnyEvent()
        event.user_id = int(master_id)

        prompt = (
            f"【系统事件：检测到 Git 远程仓库有新版本发布/更新】\n"
            f"仓库分支：{update_info['branch']}\n"
            f"远程仓库新增提交数量：领先本地 {update_info['ahead_count']} 个 commit\n"
            f"最新提交哈希：{update_info['remote_commit'][:8]}\n"
            f"本次新增的提交详细记录：\n{update_info['commit_details']}\n\n"
            f"文件改动概览：\n{update_info['diff_stat']}\n\n"
            f"【任务指示】：\n"
            f"请以你的第一人称和设定人设语气，主动向你的管理员（Master）汇报本次代码更新：\n"
            f"1. 态度自然亲切，符合你的角色性格，告诉管理员代码仓库有新的更新了。\n"
            f"2. 总结提炼出这次更新究竟改动了什么、更新了哪些功能或修复了什么问题，不要机械复制原始 git log，用你自己的口吻讲清楚。\n"
            f"3. 顺便提醒管理员有空可以拉取最新代码（例如执行 git pull 或运行更新脚本）。"
        )

        logger.info(f"[GitNotifier] 正在调用 mai_reply 对话核心向 master ({master_id}) 汇报更新...")
        await engine.handle(bot, event, prompt)
        return True

    except Exception as e:
        logger.error(f"[GitNotifier] 调用 mai_reply 对话核心失败: {e}", exc_info=True)
        return False


async def report_update_fallback(bot: ExtendBot, config, master_id: int, update_info: Dict[str, Any]):
    """mai_reply 不可用时的降级汇报策略：直接向 master 发送清晰格式化的更新汇总"""
    structured_msg = (
        f"📢 【Git 仓库更新提醒】\n"
        f"远程仓库有新提交（分支: {update_info['branch']}，领先 {update_info['ahead_count']} 个 commit）\n\n"
        f"最新提交记录：\n{update_info['commit_list']}\n\n"
        f"修改文件统计：\n{update_info['diff_stat']}\n\n"
        f"💡 提示：管理员可执行 git pull 或运行更新脚本拉取最新代码。"
    )
    await send_to_master(bot, master_id, structured_msg)


async def perform_update_check(
    bot: ExtendBot,
    config,
    git_service: GitService,
    is_manual: bool = False,
    force_notify: bool = False,
) -> Dict[str, Any]:
    """执行一次更新检查并在有更新时进行汇报"""
    plugin_cfg = _get_plugin_config(config)
    remote = plugin_cfg.get("remote", "origin")
    branch = plugin_cfg.get("branch", "auto")
    max_commits = int(plugin_cfg.get("max_commit_log_count", 10))
    fetch_timeout = int(plugin_cfg.get("fetch_timeout", 45))
    use_mai = bool(plugin_cfg.get("use_mai_reply", True))
    notify_master = bool(plugin_cfg.get("notify_master", True))

    master_id = _get_master_id(config, plugin_cfg)
    if not master_id and notify_master:
        logger.warning("[GitNotifier] 未配置 master_id，且无法从 common_config 获取，无法向 master 汇报")

    logger.info(f"[GitNotifier] 开始检查远程 Git 更新（remote={remote}, branch={branch}）...")
    update_info = await git_service.check_updates(
        remote=remote,
        branch=branch,
        max_commits=max_commits,
        fetch_timeout=fetch_timeout,
    )

    if not update_info["success"]:
        logger.warning(f"[GitNotifier] 检查更新失败: {update_info['error']}")
        return update_info

    if not update_info["is_ahead"]:
        logger.info(f"[GitNotifier] 当前分支 {update_info['branch']} 已是最新，无新提交领先。")
        return update_info

    remote_commit = update_info["remote_commit"]
    ahead_count = update_info["ahead_count"]
    logger.info(f"[GitNotifier] 发现远程仓库有新提交！领先本地 {ahead_count} 个 commit (最新 commit: {remote_commit[:8]})")

    # 检查是否已经通知过该 commit（手动触发且 force_notify 时忽略去重）
    if not force_notify and git_service.is_notified(remote_commit):
        logger.info(f"[GitNotifier] 该 commit {remote_commit[:8]} 之前已汇报过，跳过重复通知。")
        return update_info

    if notify_master and master_id:
        reported = False
        if use_mai:
            reported = await report_update_via_mai_reply(bot, config, master_id, update_info)

        if not reported:
            await report_update_fallback(bot, config, master_id, update_info)

        # 标记为已通知
        git_service.mark_notified(remote_commit, ahead_count, update_info["branch"])

    return update_info


async def git_monitor_loop(bot: ExtendBot, config, git_service: GitService):
    """后台定时检查循环"""
    plugin_cfg = _get_plugin_config(config)
    initial_delay = float(plugin_cfg.get("initial_delay", 20))
    check_interval = float(plugin_cfg.get("check_interval", 1800))

    logger.info(f"[GitNotifier] 定时监控任务已启动，将在 {initial_delay} 秒后进行首次检查，检查间隔 {check_interval} 秒")
    await asyncio.sleep(initial_delay)

    while True:
        try:
            # 重新获取配置以支持热重载
            current_cfg = _get_plugin_config(config)
            if not current_cfg.get("enable", True):
                logger.info("[GitNotifier] 插件已被配置禁用，暂停检查")
                await asyncio.sleep(60)
                continue

            interval = float(current_cfg.get("check_interval", 1800))
            await perform_update_check(bot, config, git_service, is_manual=False)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[GitNotifier] 定时监控循环已终止")
            break
        except Exception as e:
            logger.error(f"[GitNotifier] 定时监控异常: {e}", exc_info=True)
            await asyncio.sleep(60)


def main(bot: ExtendBot, config):
    """插件入口函数"""
    plugin_cfg = _get_plugin_config(config)
    if not plugin_cfg.get("enable", True):
        bot.logger.info("[GitNotifier] 插件未启用 (enable=false)")
        return

    git_service = GitService()

    global _bg_task, _loop_started

    def _start_background_loop():
        global _bg_task, _loop_started
        if _loop_started and _bg_task is not None and not _bg_task.done():
            return
        _loop_started = True
        _bg_task = asyncio.create_task(git_monitor_loop(bot, config, git_service))
        bot.logger.info("[GitNotifier] 后台定时检查任务已成功创建")

    # 监听 Bot 生命周期
    @bot.on(LifecycleMetaEvent)
    async def on_lifecycle(event: LifecycleMetaEvent):
        _start_background_loop()

    # 若当前事件循环已在运行，确保立即拉起后台任务
    bot_loop = getattr(bot, "loop", None)
    if bot_loop and bot_loop.is_running():
        try:
            bot_loop.call_soon_threadsafe(_start_background_loop)
        except Exception:
            pass

    # 管理员手动指令交互
    @bot.on(GroupMessageEvent)
    @bot.on(PrivateMessageEvent)
    async def handle_git_commands(event: GroupMessageEvent | PrivateMessageEvent):
        text = (getattr(event, "pure_text", "") or "").strip()
        command_list = ["/git check", "/git status", "检查更新", "查看更新", "/check_update"]
        if text not in command_list:
            return

        current_cfg = _get_plugin_config(config)
        master_id = _get_master_id(config, current_cfg)

        # 仅 Master 可触发
        if event.user_id != master_id:
            await bot.send(event, [Text("抱歉，只有管理员（Master）才可以检查 Git 仓库更新哦~")])
            return

        await bot.send(event, [Text("正在检查远程 Git 仓库是否有新提交，请稍候...")])

        try:
            update_info = await perform_update_check(
                bot, config, git_service, is_manual=True, force_notify=True
            )

            if not update_info["success"]:
                await bot.send(event, [Text(f"❌ 检查更新出错：\n{update_info['error']}")])
                return

            if not update_info["is_ahead"]:
                if current_cfg.get("notify_up_to_date_on_manual", True):
                    await bot.send(
                        event,
                        [Text(f"✨ 当前仓库已经是最新版本啦！\n分支: {update_info['branch']}\n当前提交: {update_info['local_commit'][:8]}\n暂无新的远程更新。")]
                    )
            else:
                await bot.send(
                    event,
                    [Text(f"🔔 发现远程分支 {update_info['branch']} 领先 {update_info['ahead_count']} 个 commit，正在由对话核心组织汇报并发送给 Master...")]
                )

        except Exception as e:
            bot.logger.error(f"[GitNotifier] 执行手动检查失败: {e}", exc_info=True)
            await bot.send(event, [Text(f"❌ 检查失败: {e}")])
