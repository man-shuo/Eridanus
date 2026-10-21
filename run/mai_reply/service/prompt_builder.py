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
        # 群聊相关
        is_group: bool = False,
        triggered_by_llm: bool = False,
        group_impression: str = "",
        recent_speaker_impressions: Optional[List[Dict]] = None,
        user_text: str = "",
        global_memory: str = "",
        user_memory: str = "",
        group_slots: str = "",
        recent_speaker_memories: Optional[List[Dict]] = None,
    ) -> str:
        """
        构建最终的 system prompt。

        参数说明：
        - is_group: 是否群聊场景
        - triggered_by_llm: 是否由 trigger_llm 判定触发（非@/前缀触发，此时追加更严格的约束）
        - group_impression: 你关于群聊的整体氛围/主观印象
        - group_slots: 本群专属的10个结构化特征槽位（社群定位、群规禁忌、黑话名梗等）
        - recent_speaker_impressions: 最近发言者的印象列表（向后兼容）
        - recent_speaker_memories: 最近发言者的记忆列表（支持槽位特征或主观印象）
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

        # ---- 最近发言者的记忆与槽位特征（群聊专属，让群交互认知更全面） ----
        speakers = recent_speaker_memories or recent_speaker_impressions
        if is_group and speakers:
            lines = []
            for item in speakers:
                name = item.get("name", "?")
                imp = item.get("impression", "")
                slots = item.get("slots", "")
                if slots and imp:
                    lines.append(f"- {name}：[槽位特征] {slots} | [主观态度] {imp}")
                elif slots:
                    lines.append(f"- {name}：{slots}")
                elif imp:
                    lines.append(f"- {name}：{imp}")
            if lines:
                prompt += (
                    f"\n\n【你在群里关注的最近几位发言者的记忆/槽位印象】：\n"
                    + "\n".join(lines)
                    + "\n（回复时结合这些记忆自然回应当事人或被提及的人，体现对不同群友的专属认知）"
                )

        # ---- 群聊专属结构化固定特征与生态槽位 (group_slots) ----
        if is_group and group_slots:
            prompt += (
                f"\n\n【关于群「{group_name}」的固定特征与社群生态记忆（10个槽位）】：\n"
                f"{group_slots}\n"
                f"（请时刻遵循本群定位、黑话名梗、规矩禁忌以及你在此群的角色定位）"
            )

        # ---- 群聊整体氛围印象 (group_impression) ----
        if is_group and group_impression:
            prompt += f"\n\n【你对「{group_name}」整个群的整体氛围与印象】：\n{group_impression}"

        # ---- Bot 全局多维自我记忆与经验（涵盖生活状态、人际网络与空间动态） ----
        if global_memory:
            prompt += (
                f"\n\n【你的全局生活记录与真实世界经验（Bot专属自我记忆层）】：\n"
                f"{global_memory}\n"
                f"（这是你的自我记忆：你拥有属于自己的生活轨迹、日常作息、感兴趣的经历与QQ空间动态。你不是围着用户打转的工具人，而是一个有独立生活的真实存在的人。"
                f"在对话涉及日常生活、生活状态、空间动态时，自然地结合这些记忆分享、吐槽或互动，展现真实的多维生活细节）"
            )

        # ---- 用户专属长期硬事实记忆（10个固定槽位） ----
        if user_memory:
            prompt += (
                f"\n\n【关于 {user_name} 的长期事实记忆（确凿客观的特征与画像）】：\n"
                f"{user_memory}\n"
                f"（这是你的记忆认知：这些是关于TA的真实确凿事实，随时可能在闲聊中派上用场。信息应当内化为你的认知，"
                f"在对话中自然体现出这些默契（如在深夜时体谅对方作息、记住对方的喜好与约定），"
                f"不要机械念经，但在合适时机自然流露出你确实记得这些细节）"
            )

        # ---- 当前交互对象的主观印象 ----
        if user_impression:
            prompt += (
                f"\n\n【你对 {user_name} 的主观印象与态度】：\n{user_impression}\n"
                f"（不要向对方复述这些印象，动态调整你此刻对TA说话的语气。印记随时间会变淡，不必拘泥）"
            )

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

