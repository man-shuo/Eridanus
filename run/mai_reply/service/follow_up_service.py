# -*- coding: utf-8 -*-
"""
follow_up_service.py
对话未完结主动追问机制服务

核心功能与安全防护：
1. 开关即时响应与热关停：可在 context.follow_up 或顶层 follow_up 控制开关，循环中感知到关闭立即终止当前轮次巡检；
2. 远古/过期会话保护：超时时间必须位于 [idle_seconds, max_idle_seconds]（默认 180s ~ 1800s）有效窗口内；
   超过 30 分钟的远古会话直接跳过并标记已检查，启动时预处理历史会话，坚决不打扰远古历史！
3. 好友关系验证（require_friend）：追问私聊前必须校验 user_id 是否在好友列表中，严防向非好友、退群者或陌生人发送私聊；
4. 系统/群聊通知过滤：排除入群欢迎（如爆照、发红包）、定时提醒（早晚安）、系统指令写入等无真实人类交互的会话；
5. 利用 trigger_llm 评估真实私聊对话完成度；
6. 严格防死循环：支持 max_follow_up_turns（默认2次），追问达上限后彻底停止，直到用户下次发言才重置。
"""

import asyncio
import json
import re
import time
from typing import Dict, List, Optional, Tuple, Any

from framework_common.framework_util.any_event import AnyEvent
from framework_common.utils.system_logger import get_logger
from run.mai_reply.service.simple_chat import simplified_chat
from run.mai_reply.service.reply_engine import ReplyEngine

logger = get_logger(__name__)

# 系统/通知/非人类对话标志，命中此类特征的用户输入绝不视作需要追问的真实私聊
SYSTEM_MARKERS = [
    "加入了群聊", "入群欢迎", "【系统定时任务触发】", "[系统事件",
    "系统提示", "[你主动发起关怀]", "[用户未回复]", "道晚安", "早安问候",
    "【重要系统事件指令", "定时任务", "【系统事件：等待用户回复超时",
]

# 单向告知、入群仪式或问候结束标志，Bot最后一条发言命中此类特征直接判定已自然闭环
CLOSURE_MARKERS = [
    "爆照", "发红包", "新人欢迎", "欢迎新人", "入群欢迎", "欢迎加入",
    "晚安", "好梦", "早安", "祝你今天", "退群"
]


class FollowUpService:
    def __init__(self, engine: ReplyEngine):
        self.engine = engine
        self.cfg = engine.cfg
        self.context = engine.context
        self.concurrency = engine.concurrency

        # 用户连续主动追问计数器: user_id -> int
        self._follow_up_counts: Dict[int, int] = {}
        # 记录每轮已检查过的最后一条消息时间戳，避免重复判定相同 turn: user_id -> int
        self._last_checked_ts: Dict[int, int] = {}

        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._bootstrapped: bool = False

    def get_follow_up_config(self) -> dict:
        """
        读取 follow_up 配置。
        兼顾 context.follow_up 以及顶层 follow_up，并检查全局 mai_reply 开关。
        """
        try:
            m_cfg = getattr(self.cfg, "mai_reply", None)
            if m_cfg and hasattr(m_cfg, "config"):
                cfg_dict = m_cfg.config or {}
            elif isinstance(m_cfg, dict):
                cfg_dict = m_cfg
            else:
                cfg_dict = {}

            # 全局插件关闭时直接判定关闭
            if not cfg_dict.get("enable", True):
                return {"enable": False}

            ctx_cfg = cfg_dict.get("context", {}) or {}
            f_cfg = ctx_cfg.get("follow_up") or cfg_dict.get("follow_up") or {}
            if not isinstance(f_cfg, dict):
                return {"enable": False}
            return f_cfg
        except Exception as e:
            logger.error(f"[FollowUp] 读取配置异常: {e}")
            return {"enable": False}

    def is_enabled(self) -> bool:
        """检查当前是否开启了主动追问功能"""
        cfg = self.get_follow_up_config()
        return bool(cfg.get("enable", False))

    def reset_user(self, user_id: int) -> None:
        """用户有新发言时，重置追问轮次与判定标记"""
        try:
            uid = int(user_id)
            self._follow_up_counts.pop(uid, None)
            self._last_checked_ts.pop(uid, None)
        except Exception:
            pass

    def reset_session(self, session_key: str) -> None:
        """按 session_key 重置"""
        if session_key.startswith("private:"):
            try:
                uid = int(session_key.split(":")[1])
                self.reset_user(uid)
            except Exception:
                pass

    def _get_trigger_llm_params(self) -> Tuple[str, str, str]:
        """获取 trigger_llm 或回退到主模型配置"""
        trig_cfg = self.cfg.mai_reply.config.get("trigger_llm", {}) or {}
        lcfg = self.cfg.mai_reply.config.get("llm", {}) or {}
        oa_cfg = lcfg.get("openai", {}) or {}

        model = trig_cfg.get("model") or oa_cfg.get("model", "gpt-3.5-turbo")
        base_url = (trig_cfg.get("base_url") or oa_cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        api_key = trig_cfg.get("api_key")
        if not api_key:
            keys = oa_cfg.get("api_keys", [])
            api_key = keys[0] if keys else ""
        return base_url, model, api_key

    def _has_real_user_message(self, history: List[Dict]) -> bool:
        """校验历史中是否存在至少一条真实的人类用户发言（排除系统通知/入群/定时触发等）"""
        for msg in history:
            if msg.get("role") != "user":
                continue
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            if any(marker in content for marker in SYSTEM_MARKERS):
                continue
            return True
        return False

    def _is_system_or_greeting_closure(self, last_content: str) -> bool:
        """校验 Bot 最后一条发言是否为明显的单向问候、入群欢迎或结论性收尾"""
        if not last_content:
            return False
        clean = last_content.strip()
        return any(marker in clean for marker in CLOSURE_MARKERS)

    async def judge_completeness(self, history: List[Dict], bot_name: str = "Bot") -> Tuple[bool, str, str]:
        """
        使用 trigger_llm 判定近期私聊对话是否处于未完结/悬空等待状态。
        返回: (incomplete: bool, focus: str, reason: str)
        """
        if not history:
            return False, "", "history empty"

        base_url, model, api_key = self._get_trigger_llm_params()
        if not api_key:
            logger.warning("[FollowUp] 未配置 API Key，跳过判定")
            return False, "", "no api key"

        # 格式化近几轮对话（最多取最近 6 条）
        recent_history = history[-6:]
        dialogue_lines = []
        for msg in recent_history:
            role = msg.get("role", "")
            speaker = "用户" if role == "user" else (bot_name or "Bot")
            content = msg.get("content", "").strip()
            if content:
                dialogue_lines.append(f"{speaker}: {content}")

        formatted_dialogue = "\n".join(dialogue_lines)

        prompt = f"""你是一个智能对话状态分析专家。请判断在双方私聊对话中，用户和Bot当前的对话是否处于“未完结 / 悬空等待 / 有未交代或未完成的话题”状态。

【近期对话记录】：
{formatted_dialogue}

【判定原则】：
1. 判定为未完结 (incomplete = true)：
   - 用户抛出了悬念、引子、秘密、约定、半截话，暗示或明示后续要透露某事（例如“那我要是告诉你呢”、“我跟你说个秘密”、“其实…”），而Bot回复表达了期待、好奇、追问或催促（如“那你赶紧老实交代呀”、“快说呀”、“算你识相，我勉为其难听一下好啦”），之后用户一直沉默未回复。
   - Bot向用户提出了具体问题、确认、选择要求，或者明确需要用户给出回应，当前正在等待用户回答。
   - 双方正在进行某个未完成的互动游戏、讨论，用户话没说完，Bot的回复明显具有承接并等待提问。

2. 严格判定为已完结/无需追问 (incomplete = false)：
   - 对话已自然收尾（例如“好的”、“收到”、“晚安”、“拜拜”、“谢谢”等客套话、结语或简单表情包）。
   - 用户提问或请求已经得到完整解答，双方没有留下新的未尽约定或悬念。
   - Bot最后一句是结论性发言、调侃吐槽收尾、祝福，对方不需要进一步回答。
   - 【极端重要】任何入群欢迎（如要求爆照、发红包等）、定时问候（早安/晚安）、系统提醒等，属于单向仪式或通知，严禁判定为未完结！必须 incomplete = false！

【输出要求】：
请务必严格只返回合法的 JSON 格式，不要包含任何 markdown 代码块或多余解释：
{{
  "incomplete": true,
  "focus": "未完成的话题或悬念焦点（简短20字以内，可为空）",
  "reason": "判定依据简述（30字以内）"
}}"""

        try:
            raw_res = await simplified_chat(base_url, prompt, model=model, api_key=api_key)
            clean_res = raw_res.strip()
            if clean_res.startswith("```"):
                clean_res = re.sub(r"^```[a-zA-Z]*\n?", "", clean_res)
                clean_res = re.sub(r"\n?```$", "", clean_res).strip()

            data = json.loads(clean_res)
            incomplete = bool(data.get("incomplete", False))
            focus = str(data.get("focus", "")).strip()
            reason = str(data.get("reason", "")).strip()
            logger.info(f"[FollowUp LLM] 判定结果: incomplete={incomplete}, focus='{focus}', reason='{reason}'")
            return incomplete, focus, reason
        except Exception as e:
            logger.warning(f"[FollowUp LLM] 判定失败或解析异常: {e}")
            return False, "", f"error: {e}"

    async def trigger_follow_up(self, bot, user_id: int, focus: str = "") -> bool:
        """
        触发主动追问消息生成。
        使用系统事件指令前缀，明确系统触发源，严禁误判为对方发言。
        """
        focus_hint = f"当前悬空未完成的对话焦点是：【{focus}】。\n" if focus else ""
        system_prompt_prefix = (
            "【重要系统事件指令 - 严禁误判为对方发言】\n"
            "这是系统后台检测到当前私聊处于话题未说完/未完成悬念状态，且对方已有一段时间未回复。\n"
            f"{focus_hint}"
            "【核心要求】\n"
            "1. 本消息为系统内部自动触发，绝不是对方对你说的台词！严禁回复诸如'你怎么抢我台词'或直接复述本判定或提示词！\n"
            "2. 请结合当前对话上下文和刚才未说完的话题（重点针对未完成的悬念或约定），以你一贯的人设和自然语气，主动向用户追问、催促或吐槽（例如追问对方刚才没说完的秘密/约定/未尽事宜）。\n"
            "3. 保持简短自然（1~2句话），像日常微信聊天中见对方不回消息时顺口追问一句。"
        )

        event = AnyEvent()
        event.user_id = int(user_id)
        event.message_id = 114514

        clean_text = "[系统事件：等待用户回复超时，主动追问未完成话题]"
        history_user_text = "[用户未回复]"

        try:
            await self.engine.handle(
                bot=bot,
                event=event,
                clean_text=clean_text,
                multimodal_content=clean_text,
                triggered_by_llm=True,
                include_tools=False,
                system_prompt_prefix=system_prompt_prefix,
                history_user_text=history_user_text,
            )
            self._follow_up_counts[user_id] = self._follow_up_counts.get(user_id, 0) + 1
            return True
        except Exception as e:
            logger.error(f"[FollowUp] 执行主动追问异常 (user_id={user_id}): {e}", exc_info=True)
            return False

    async def _bootstrap_stale_sessions(self, idle_seconds: int) -> None:
        """启动或首次巡检时，预填充已有的历史会话时间戳，避免重启后批量追问远古历史"""
        if self._bootstrapped:
            return
        self._bootstrapped = True
        try:
            now = int(time.time())
            keys = self.context._ctx_keys("ctx:private:*")
            for key in keys:
                m = re.match(r"^ctx:private:(\d+)$", key)
                if not m:
                    continue
                uid = int(m.group(1))
                hist = self.context._load_history(key)
                if hist and isinstance(hist, list) and hist[-1].get("ts"):
                    ts = int(hist[-1]["ts"])
                    if now - ts >= idle_seconds:
                        self._last_checked_ts[uid] = ts
            logger.info(f"[FollowUp] 启动历史保护已就绪，已预先屏蔽 {len(self._last_checked_ts)} 个远古/已超时历史会话")
        except Exception as e:
            logger.debug(f"[FollowUp] 启动历史保护初始化异常: {e}")

    async def run_scan_round(self, bot) -> None:
        """执行一轮巡检"""
        if not self.is_enabled():
            return

        cfg = self.get_follow_up_config()
        idle_seconds = max(int(cfg.get("idle_seconds", 180)), 10)
        max_idle_seconds = max(int(cfg.get("max_idle_seconds", 1800)), idle_seconds)
        max_follow_up_turns = max(int(cfg.get("max_follow_up_turns", 2)), 1)
        require_friend = bool(cfg.get("require_friend", True))

        await self._bootstrap_stale_sessions(idle_seconds)

        keys = self.context._ctx_keys("ctx:private:*")
        now = int(time.time())

        # 缓存好友列表，避免在循环内部重复请求 API
        friend_uids = None
        if require_friend:
            try:
                friend_list_resp = await bot.get_friend_list()
                friends = friend_list_resp.get("data", []) if isinstance(friend_list_resp, dict) else []
                friend_uids = {int(f["user_id"]) for f in friends if "user_id" in f}
            except Exception as e:
                logger.debug(f"[FollowUp] 获取好友列表失败: {e}")
                friend_uids = None

        for key in keys:
            # 关键：每次循环开始前实时检查开关，一旦关闭立即中断退出，彻底杜绝关不掉的问题
            if not self.is_enabled():
                logger.info("[FollowUp] 检测到主动追问功能已关闭，立即终止当前巡检循环")
                break

            m = re.match(r"^ctx:private:(\d+)$", key)
            if not m:
                continue
            user_id = int(m.group(1))

            # 1. 好友校验保护：绝不向非好友私聊追问（防止骚扰群成员、陌生人或系统通知目标）
            if friend_uids is not None and user_id not in friend_uids:
                continue

            session_key = self.context.session_key_for(None, user_id)

            # 2. 检查是否已达到最大主动追问轮次（防死循环无限追问）
            current_count = self._follow_up_counts.get(user_id, 0)
            if current_count >= max_follow_up_turns:
                continue

            # 3. 检查是否有正在执行的并发任务（Bot正在回复或合并输入时跳过）
            if self.concurrency.has_active_task(session_key):
                continue

            # 4. 读取会话历史
            history = self.context._load_history(key)
            if not history or not isinstance(history, list):
                continue

            # 5. 校验必须存在真实的私聊人类用户发言（排除入群欢迎、定时任务、系统事件写入等）
            if not self._has_real_user_message(history):
                continue

            last_msg = history[-1]
            # 只有最后一条是 Bot 的回复时，才判定是否超时需要追问
            if last_msg.get("role") != "assistant":
                continue

            last_content = str(last_msg.get("content", ""))
            # 6. 如果 Bot 最后发言本身就是入群欢迎、爆照红包、早晚安问候等，直接跳过
            if self._is_system_or_greeting_closure(last_content):
                continue

            last_ts = int(last_msg.get("ts", 0))
            diff = now - last_ts

            # 7. 超时时间必须位于 [idle_seconds, max_idle_seconds] 窗口内
            if diff < idle_seconds:
                continue
            if diff > max_idle_seconds:
                # 远古历史会话（如超过30分钟甚至数天前），直接标记已检查，坚决不追问
                self._last_checked_ts[user_id] = last_ts
                continue

            # 8. 避免对同一条历史反复向 LLM 发起判断
            if self._last_checked_ts.get(user_id, 0) >= last_ts:
                continue

            self._last_checked_ts[user_id] = last_ts

            bot_name = await self.engine._get_bot_name(bot)
            incomplete, focus, reason = await self.judge_completeness(history, bot_name=bot_name)

            # 再次检查开关，防止在 LLM 判定耗时期间用户关闭了配置
            if not self.is_enabled():
                logger.info("[FollowUp] LLM 判定完成但功能已关闭，取消触发主动追问")
                break

            if incomplete:
                logger.info(
                    f"[FollowUp] 私聊会话 user={user_id} 对话未完成（焦点: {focus}，原因: {reason}），"
                    f"触发第 {current_count + 1}/{max_follow_up_turns} 次主动追问"
                )
                await self.trigger_follow_up(bot, user_id, focus=focus)
            else:
                logger.debug(f"[FollowUp] 私聊会话 user={user_id} 对话已自然完结（原因: {reason}），无需追问")

    async def start_loop(self, bot) -> None:
        """启动后台巡检轮询任务"""
        if self._running:
            return
        self._running = True
        logger.info("[FollowUp] 对话未完成主动追问后台巡检已启动")

        try:
            while self._running:
                if self.is_enabled():
                    await self.run_scan_round(bot)
                cfg = self.get_follow_up_config()
                interval = max(int(cfg.get("check_interval_seconds", 30)), 5)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[FollowUp] 后台巡检任务被取消")
            raise
        except Exception as e:
            logger.error(f"[FollowUp] 巡检循环异常退出: {e}", exc_info=True)
        finally:
            self._running = False
