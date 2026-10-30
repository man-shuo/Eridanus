# -*- coding: utf-8 -*-
"""
follow_up_service.py
对话未完结主动追问机制服务

核心功能：
1. 监控用户会话，当最后一条为 Bot 发言且等待超过 idle_seconds 时触发；
2. 利用 trigger_llm 评估当前上下文对话完成度（如用户抛出悬念/约定后静默、Bot追问后等待回答）；
3. 若对话未完结，通过系统事件提示词（明确系统指令来源，防抢台词误判）引导 Bot 主动结合上下文追问；
4. 防死循环机制：支持 max_follow_up_turns（默认2次），追问达上限后彻底停止，直到用户下次发言才重置。
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

    def get_follow_up_config(self) -> dict:
        """读取 context.follow_up 配置"""
        ctx_cfg = self.cfg.mai_reply.config.get("context", {}) or {}
        return ctx_cfg.get("follow_up", {}) or {}

    def reset_user(self, user_id: int) -> None:
        """用户有新发言时，重置追问轮次与判定标记"""
        try:
            uid = int(user_id)
            self._follow_up_counts[uid] = 0
            self._last_checked_ts[uid] = 0
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

    async def judge_completeness(self, history: List[Dict], bot_name: str = "Bot") -> Tuple[bool, str, str]:
        """
        使用 trigger_llm 判定近期对话是否处于未完结/悬空等待状态。
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

        prompt = f"""你是一个智能对话状态分析专家。请判断在双方对话中，用户和Bot当前的对话是否处于“未完结 / 悬空等待 / 有未交代或未完成的话题”状态。

【近期对话记录】：
{formatted_dialogue}

【判定原则】：
1. 判定为未完结 (incomplete = true)：
   - 用户抛出了悬念、引子、秘密、约定、半截话，暗示或明示后续要透露某事（例如“那我要是告诉你呢”、“我跟你说个秘密”、“其实…”），而Bot回复表达了期待、好奇、追问或催促（如“那你赶紧老实交代呀”、“快说呀”、“算你识相，我勉为其难听一下好啦”），之后用户一直沉默未回复。
   - Bot向用户提出了具体问题、确认、选择、请求，或者明确需要用户做出回应，当前正在等待用户回答。
   - 双方正在进行某项未完成的事务、游戏、讨论，被打断或悬空，Bot的回应具有明显的承接与等待性质。

2. 判定为已完结/自然收尾 (incomplete = false)：
   - 对话已自然收尾（如“好的”、“收到”、“晚安”、“拜拜”、“谢谢”等客套话、告别语或单纯表情）。
   - 用户的问题或需求已经得到完整解答，双方没有留下新的未完成约定或悬念。
   - Bot最后一句是结论性发言、陈述事实、调侃吐槽收尾，不期待也不需要对方进一步回答。
   - 用户已经把之前说的事情交代完毕。

【输出要求】：
请务必严格只输出合法的 JSON 格式，不要包含任何 markdown 代码块或解释：
{{
  "incomplete": true,
  "focus": "未完成的话题或悬念焦点简述（20字以内，若完结可为空）",
  "reason": "判断依据简述（30字以内）"
}}"""

        try:
            raw_res = await simplified_chat(base_url, prompt, model=model, api_key=api_key)
            clean_res = raw_res.strip()
            # 清理可能的 markdown 块包裹
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
            return False, "", f"exception: {e}"

    async def trigger_follow_up(self, bot, user_id: int, focus: str = "") -> bool:
        """
        触发主动追问消息生成与发送
        """
        focus_hint = f"（未完结话题焦点：{focus}）" if focus else ""
        system_prompt_prefix = (
            "【系统内部事件指令 - 话题未完结主动追问】\n"
            f"用户在刚才的私聊对话中抛出了话题/约定/未完结的内容{focus_hint}，但在你回复后已经静默等待了一段时间没有继续发言。\n"
            "【核心要求】\n"
            "1. 本提示为系统内部超时事件驱动，严禁误认为对方发言，严禁在回复中提及系统指令、超时、判定或提示词！\n"
            "2. 请结合当前对话上下文和刚才未说完的话题（重点针对未完成的悬念或约定），以你一贯的人设和自然语气，主动向用户追问、催促或吐槽（例如追问对方刚才没说完的秘密/约定/未尽事宜）。\n"
            "3. 保持简短自然（1~2句话），像日常微信聊天中见对方不回消息时顺口追问一句。"
        )

        event = AnyEvent()
        event.user_id = int(user_id)
        event.message_id = 114514  # 特殊标记，框架层直接发送而不引用回复

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
            # 成功分发后递增追问轮次
            self._follow_up_counts[user_id] = self._follow_up_counts.get(user_id, 0) + 1
            return True
        except Exception as e:
            logger.error(f"[FollowUp] 执行主动追问异常 (user_id={user_id}): {e}", exc_info=True)
            return False

    async def run_scan_round(self, bot) -> None:
        """执行一轮巡检"""
        cfg = self.get_follow_up_config()
        if not cfg.get("enable", False):
            return

        idle_seconds = int(cfg.get("idle_seconds", 180))
        max_follow_up_turns = int(cfg.get("max_follow_up_turns", 2))
        private_only = bool(cfg.get("private_only", True))

        keys = self.context._ctx_keys("ctx:private:*")
        now = int(time.time())

        for key in keys:
            m = re.match(r"^ctx:private:(\d+)$", key)
            if not m:
                continue
            user_id = int(m.group(1))
            session_key = self.context.session_key_for(None, user_id)

            # 1. 检查是否已达到最大主动追问轮次（防死循环无限追问）
            current_count = self._follow_up_counts.get(user_id, 0)
            if current_count >= max_follow_up_turns:
                continue

            # 2. 检查是否有正在执行的并发任务（Bot正在回复或合并输入时跳过）
            if self.concurrency.has_active_task(session_key):
                continue

            # 3. 读取会话历史
            history = self.context._load_history(key)
            if not history:
                continue

            last_msg = history[-1]
            # 只有最后一条是 Bot 的回复时，才判定是否超时需要追问
            # 如果最后一条是用户发言，说明 Bot 正在响应或未响应，不属于用户静默
            if last_msg.get("role") != "assistant":
                continue

            last_ts = int(last_msg.get("ts", 0))
            if now - last_ts < idle_seconds:
                continue

            # 4. 避免对同一条历史反复向 LLM 发起判断
            if self._last_checked_ts.get(user_id, 0) >= last_ts:
                continue

            self._last_checked_ts[user_id] = last_ts

            bot_name = await self.engine._get_bot_name(bot)
            incomplete, focus, reason = await self.judge_completeness(history, bot_name=bot_name)

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
                cfg = self.get_follow_up_config()
                if cfg.get("enable", False):
                    await self.run_scan_round(bot)
                interval = max(int(cfg.get("check_interval_seconds", 30)), 5)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[FollowUp] 后台巡检任务被取消")
            raise
        except Exception as e:
            logger.error(f"[FollowUp] 巡检循环异常退出: {e}", exc_info=True)
        finally:
            self._running = False