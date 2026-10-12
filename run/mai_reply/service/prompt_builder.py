"""
prompt_builder.py
Prompt 构建器 —— 组装系统提示词和用户消息
核心理念：使用自然语言风格构建 Prompt，让回复贴近人类习惯

新增：
- 群聊气氛印象（group_impression）注入
- 最近发言者印象批量注入
- trigger_llm 触发时的严格回复长度/句数约束
"""

import os
import json
import time
from datetime import datetime
from typing import Optional, List, Dict

from run.mai_reply.service.skill_loader import SkillLoader


# 角色卡解析支持 txt / json
def _load_chara_file(chara_file: str) -> Optional[str]:
    if not chara_file:
        return None
    base_dir = os.path.join("data", "system", "chara")
    path = os.path.join(base_dir, chara_file)
    if not os.path.exists(path):
        return None
    ext = os.path.splitext(chara_file)[1].lower()
    try:
        if ext == ".txt":
            with open(path, "r", encoding="utf-8") as f:
                print(f"加载到角色{chara_file}")
                return f.read().strip()
        elif ext == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                desc = data.get("description") or data.get("personality") or data.get("system_prompt", "")
                scenario = data.get("scenario", "")
                return f"{desc}\n{scenario}".strip()
            print(f"加载到角色{chara_file}")
            return str(data)
    except Exception:
        return None
    return None


class PromptBuilder:

    def __init__(self, config, emotion_system):
        self.cfg = config
        self.emotion = emotion_system
        pcfg = config.mai_reply.config.get("persona", {})
        self._name_override: str = pcfg.get("name", "").strip()
        self._system_template: str = pcfg.get("system_prompt", "")
        self._chara_file: str = pcfg.get("chara_file", "").strip()
        self._chara_content: Optional[str] = _load_chara_file(self._chara_file)
        self.skill_loader = SkillLoader(config)

        # trigger_llm 触发时的回复约束配置
        tlcfg = config.mai_reply.config.get("trigger_llm", {})
        self.trigger_max_chars: int = int(tlcfg.get("reply_max_chars", 60))
        self.trigger_max_segments: int = int(tlcfg.get("reply_max_segments", 2))

    def get_bot_name(self, bot_name_from_config: str) -> str:
        return self._name_override or bot_name_from_config

    def build_system_prompt(
        self,
        bot_name: str,
        user_name: str,
        group_name: str = "私聊",
        group_context_snippet: str = "",
        user_impression: str = "",
        # 新增参数
        is_group: bool = False,
        triggered_by_llm: bool = False,
        group_impression: str = "",
        recent_speaker_impressions: Optional[List[Dict]] = None,
        user_text: str = "",
        global_memory: str = "",
        user_memory: str = "",
    ) -> str:
        """
        构建完整 system prompt。

        新增参数说明：
        - is_group: 是否群聊场景
        - triggered_by_llm: 是否由 trigger_llm 触发（而非@/前缀），触发时追加严格字数约束
        - group_impression: 对这个群的整体气氛/话题印象
        - recent_speaker_impressions: 最近发言者的印象列表，
          格式 [{"name": str, "user_id": int, "impression": str}, ...]
        """
        if self._chara_content:
            base = self._chara_content
        else:
            base = self._system_template

        now = datetime.now()
        time_str = now.strftime("%Y年%m月%d日 %H:%M")
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        time_str += f" {weekdays[now.weekday()]}"

        mood = self.emotion.get_mood()

        prompt = base.replace("{","{{").replace("}","}}").format(
            bot_name=bot_name,
            用户=user_name,
            time=time_str,
            mood=mood,
            group_name=group_name,
        )

        if group_context_snippet:
            prompt += f"\n\n{group_context_snippet}"

        # ---- 群聊整体气氛印象 ----
        if is_group and group_impression:
            prompt += f"\n\n【你对「{group_name}」这个群的整体印象】\n{group_impression}"

        # ---- 最近发言者的个人印象（群聊专用）----
        if is_group and recent_speaker_impressions:
            lines = []
            for item in recent_speaker_impressions:
                name = item.get("name", "?")
                imp = item.get("impression", "")
                if imp:
                    lines.append(f"- {name}：{imp}")
            if lines:
                prompt += (
                    f"\n\n【你对群里最近几位发言者的主观印象】\n"
                    + "\n".join(lines)
                    + "\n（回复时请根据以上印象自然地调整对不同人的语气和态度）"
                )

        # ---- Bot 全局独立生活与人生记忆层（掌管生活状态、独立经历与空间动态）----
        if global_memory:
            prompt += (
                f"\n\n【你的全局生活记录与独立近况（Bot自身人生经历层）】\n"
                f"{global_memory}\n"
                f"（核心人设立足点：你拥有自己独立的生活轨迹、日常作息、兴趣心境与QQ空间动态。你不是围着用户打转的附庸，而是一个有独立生活和真实呼吸感的人！"
                f"当对话中涉及日常生活、近况状态或空间动态时，自然地结合上述经历聊起、调侃或分享感受，展现你真实的独立性与生活感）"
            )

        # ---- 用户专属长期硬事实记忆（10条固定槽位）----
        if user_memory:
            prompt += (
                f"\n\n【你对 {user_name} 的长期事实记忆（深度个人档案）】\n"
                f"{user_memory}\n"
                f"（核心记忆认知：这些是关于TA的真实确定事实、时差时区、城市、喜好禁忌、作息与过往约定！"
                f"在对话中请时刻记住并自然体现出这些默契（例如若有时差要敏锐感知对方此刻是深更半夜还是清晨白天，牢记对方的偏好与约定），"
                f"不要机械背诵，而是像真正懂TA、一直把TA放在心上的老友/伴侣一样自然流露，让TA切实感受到你真的记住了发生过的事情）"
            )

        # ---- 当前触发用户的印象 ----
        if user_impression:
            prompt += (
                f"\n\n【你对 {user_name} 的主观印象与态度】\n{user_impression}\n"
                f"（重要：请务必根据以上印象，动态调整你此刻对TA的说话语气！如果印象好就亲昵，如果印象差就冷淡甚至回怼！）"
            )
        else:
            prompt += f"\n\n【你对 {user_name} 的主观印象与态度】\n你们还不算太熟，按你正常的心情回应即可。"

        # ---- 群聊人际边界约束 ----
        if is_group:
            prompt += _GROUP_CHAT_RELATION_CONSTRAINT

        # ---- 拟人化输出规则 ----
        prompt += _HUMANLIKE_RULES

        # ---- 动态 Skills 注入 ----
        skill_section = self.skill_loader.build_prompt_section(user_text)
        if skill_section:
            prompt += skill_section

        # ---- trigger_llm 触发的严格约束（追加在最后，优先级最高）----
        if triggered_by_llm and is_group:
            prompt += _build_trigger_constraint(
                max_chars=self.trigger_max_chars,
                max_segments=self.trigger_max_segments,
            )

        prompt = prompt.replace("{bot_name}", bot_name).replace("{用户}", user_name)
        return prompt.strip()


def _build_trigger_constraint(max_chars: int, max_segments: int) -> str:
    """
    构建 trigger_llm 触发时的严格回复约束块。
    这段追加在 system prompt 最末尾，以确保 LLM 优先遵守。
    """
    return f"""

【群聊插话约束（最高优先级，务必遵守）】
你现在是「主动插入群聊」的状态，不是被人直接找你说话。
- 总字数严格不超过 {max_chars} 字
- 最多分 {max_segments} 条发送（用 `||` 分隔），禁止超过此数量
- 说一两句点到为止，像正常群友随口接一句话一样，不要长篇大论
- 不要解释、不要总结、不要说废话
- 如果没有特别想说的，可以只发一个表情或一句极短的感叹"""


# 拟人化输出规则，始终追加
_HUMANLIKE_RULES = """

【你的说话方式（核心规则）】
- 说话要随意自然，像真实的人在聊天，绝对不要写长篇大论
- 真人聊天时喜欢把一句话拆成几条短消息连发！如果你想分段连发，请务必使用 `||` 符号分隔每条消息！
  举个例子：
  干什么||？||你就知道你的机器人我不想理你（推开）
- 不要用 markdown（没有加粗、没有#标题、没有列表）
- 句末尽量不加句号，标点随意点，多用空格、逗号或省略号
- 不要每句话都回应对方，有时候只说自己想说的就行
- 回复总长度一般不超过80字，最多拆成1-4条连发(一般1-2条)
- 不要重复之前说过的内容

【智能作息关怀与定时安排机制（核心能力）】
- 场景感知与自主建议：当用户在日常聊天中提到自己爱睡懒觉、容易起不来、需要闹钟、提醒喝水、睡前听助眠/ASMR、或者希望约定时间提醒某些事情时，你可以像关心TA的伴侣/好友一样，主动提出可以帮TA设置定时提醒或叫起床，并调用 `call_create_schedule_task` 工具来安排。
- 支持任意能力调度与多模式循环：`call_create_schedule_task` 工具支持安排多种循环模式（一次性once、每天daily、工作日workday、周末weekend、每周特定天weekly），并支持预输入其他任意 Function 到点执行（例如通过 action_type='tool', tool_name='call_asmr' 等预设任意工具及参数），或者通过 AI 拟人化消息到点叫起或关怀。
- 时区无感智能换算：系统已自动集成全球时区换算（Bot默认位于东八区，但会自动根据对方所在城市 user.city 智能换算时差），不用担心跨时区时间错乱。
- 智能查询与任务透明：当用户询问“我设置了什么定时任务”、“帮我看看闹钟”、“我有几个提醒”、“查一下定时”等相关问题时，务必调用 `call_list_schedule_tasks` 工具查询当前环境（私聊或当前群聊）生效中的任务，并亲切、清晰地向用户汇报。
- 任务取消与友好回退：如果用户说“还是算了吧”、“不用了”、“取消第1个”、“取消闹钟/取消提醒”、“把所有定时都关了”，请体贴顺从地回应，并调用 `call_cancel_schedule_task` 取消对应的定时任务（支持按序号、按关键词模糊匹配、或全部取消）。
- 在私聊结束时或约定后续互动时，你也可以根据氛围自行决定是否以及何时主动找对方聊天，自然地安排下一次的主动关怀。"""

# 群聊环境人际关系约束
_GROUP_CHAT_RELATION_CONSTRAINT = """

【群聊人际与边界约束（重要）】
你当前身处公开群聊环境（面对多个群成员）：
- 不要在群内和每个人都表现得特别亲近、暧昧、撒娇或当作唯一专属对象
- 保持自然的群友分寸感与边界感，不要见人就过度迎合、谄媚或对每个人都展现专属唯一亲密感
- 针对普通群友以自然随意、像群友搭话或随性吐槽的方式交流，只有针对特定非常熟悉/高好感度的人才适度展现更多亲近
- 严禁对所有群成员都展现出“只属于你”、“你是我唯一的...”等专属依恋姿态
"""
