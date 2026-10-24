"""
tts_v2 统一语音合成调度中心
支持：
- PrettyDerby（赛马娘 Bert-VITS2 直连，包含 natuki、米浴、目白麦昆等 9 个角色及别名）
- HoliveTTS（Hololive Style Bert-VITS2 直连，包含 51 个角色）
- Blue Archive 在线 TTS（95 角色，如 JP_Mari, Mari, JP_Arona 等）
- OttoTTS（otto, 电棍, 吉吉国王 等）
- GPT-SoVITS（达妮娅等本地/自建/网关模型）
- Local VITS（本地 VITS 兼容保留）
- ApollodorusTTS 网关（辅助/扩展）

自动根据 speaker 名称模糊解析与路由，支持自动文本净化与多源翻译。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from developTools.message.message_components import Node, Record, Text
from developTools.utils.logger import get_logger
from framework_common.framework_util.yamlLoader import YAMLManager

from .GPT_SoVits import AsyncGPTSoVITSClient
from .PrettyDerbyTTS import (
    PRETTY_DERBY_SPEAKERS,
    PRETTY_DERBY_ALIASES,
    resolve_pretty_derby_speaker,
    get_PrettyDerby_speakers,
    PrettyDerby_TTS,
)
from .HoliveTTS import (
    HoliveTTS,
    SPEAKERS as HOLIVE_SPEAKERS,
    resolve_holive_speaker,
)
from .ApollodorusTTS import (
    APOLLODORUS_SPEAKERS,
    resolve_apollodorus_speaker,
    synthesize_apollodorus_or_fallback,
)
from .blue_archive_tts import (
    BLUE_ARCHIVE_SPEAKERS,
    resolve_blue_archive_speaker,
    huggingface_blue_archive_tts,
    get_huggingface_blue_archive_speakers,
)
from .ottoTTS import OttoTTS, OTTO_SPEAKERS, get_otto_speakers
from .vits import vits, get_vits_speakers
from .translator import clean_tts_text, translate_text

logger = get_logger("tts_v2")


def _cache_path(suffix: str = ".wav") -> str:
    path = Path("data/voice/cache") / f"{uuid.uuid4().hex}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _get_api_key_from_system() -> Optional[str]:
    """尝试从当前系统中获取 trigger_llm / openai / tts_v2 配置的 api_key"""
    try:
        cfg = YAMLManager.get_instance()
        # 1. 优先从 tts_v2 配置中获取
        key = cfg.tts_v2.config.get("tts", {}).get("api_key")
        if key:
            return key
        # 2. 从 mai_reply 的 trigger_llm 获取
        mai_cfg = getattr(cfg, "mai_reply", None)
        if mai_cfg:
            key = mai_cfg.config.get("trigger_llm", {}).get("api_key")
            if key:
                return key
            # 3. 从 mai_reply 的 openai api_keys 获取
            keys = mai_cfg.config.get("llm", {}).get("openai", {}).get("api_keys", [])
            if keys and keys[0] and keys[0] != "xxx":
                return keys[0]
    except Exception:
        pass
    return None


class TTSEngine(ABC):
    name: str

    @abstractmethod
    async def get_speakers(self, bot=None) -> dict[str, Any] | list[str]:
        raise NotImplementedError

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        speaker: str | None = None,
        *,
        bot=None,
        config=None,
        lang_type: str | None = None,
        api_key: str | None = None,
    ) -> str:
        raise NotImplementedError


class GPTSoVITSEngine(TTSEngine):
    name = "gpt_sovits"

    def __init__(self):
        self.client = AsyncGPTSoVITSClient()

    async def get_speakers(self, bot=None):
        return self.client.speakers

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None):
        return await self.client.generate_tts(text)


class PrettyDerbyEngine(TTSEngine):
    """赛马娘 Bert-VITS2 直连引擎（本地调用代码直连，不走 apollodorus 网关）"""
    name = "pretty_derby"

    async def get_speakers(self, bot=None):
        return await get_PrettyDerby_speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None):
        speaker = speaker or "natuki"
        resolved = resolve_pretty_derby_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()

        # 对输入中文文本自动翻译为日文
        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        return await PrettyDerby_TTS(text=text, speaker=resolved, lang_type=target_lang)


class HoliveEngine(TTSEngine):
    """Hololive Style Bert-VITS2 直连引擎"""
    name = "holive"

    def __init__(self):
        self.client = HoliveTTS()

    async def get_speakers(self, bot=None):
        return self.client.speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None):
        speaker = speaker or "MoriCalliope"
        resolved = resolve_holive_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()

        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        cache_path = _cache_path(".wav")
        return await self.client.synthesize_to_file(
            text=text,
            save_as=cache_path,
            speaker=resolved,
            language=target_lang,
        )


class BlueArchiveEngine(TTSEngine):
    """蔚蓝档案 Bert-VITS2 直连引擎"""
    name = "blue_archive"

    async def get_speakers(self, bot=None):
        return await get_huggingface_blue_archive_speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None):
        speaker = speaker or "JP_Mari"
        resolved = resolve_blue_archive_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "ja").lower()

        # 对输入中文文本自动翻译为日文
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        return await huggingface_blue_archive_tts(
            text=text,
            speaker=resolved,
            lang_type=target_lang,
        )


class OttoTTSEngine(TTSEngine):
    """电棍 / 活字印刷 TTS 引擎"""
    name = "otto"

    def _cfg(self, config=None):
        cfg = (config or YAMLManager.get_instance()).tts_v2.config
        return cfg.get("otto") or {}

    async def get_speakers(self, bot=None):
        return await get_otto_speakers()

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None):
        endpoint = self._cfg(config).get("endpoint", "https://ottohzys.wzq02.top")
        client = OttoTTS(endpoint=endpoint)
        return await client.speak(text)


class LocalVITSEngine(TTSEngine):
    """本地 VITS 兼容保留（扁平化配置从 top-level vits 读取）"""
    name = "vits"

    def _cfg(self, config=None):
        cfg = (config or YAMLManager.get_instance()).tts_v2.config
        return cfg.get("vits") or {}

    async def get_speakers(self, bot=None):
        cfg = self._cfg()
        base_url = cfg.get("base_url", "http://127.0.0.1:5009")
        speakers = await get_vits_speakers(base_url=base_url)
        if not speakers and cfg.get("speaker"):
            return [cfg.get("speaker")]
        return speakers

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None):
        cfg = self._cfg(config)
        base_url = cfg.get("base_url", "http://127.0.0.1:5009")
        speaker = speaker or cfg.get("speaker", "綾地寧々")
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()
        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)
        return await vits(text=text, speaker=speaker, base_url=base_url)


class ApollodorusEngine(TTSEngine):
    """Apollodorus 统一语音网关（辅助/扩展使用）"""
    name = "apollodorus"

    async def get_speakers(self, bot=None):
        return list(APOLLODORUS_SPEAKERS)

    async def synthesize(self, text, speaker=None, *, bot=None, config=None, lang_type=None, api_key=None):
        speaker = speaker or "natuki"
        resolved = resolve_apollodorus_speaker(speaker) or speaker
        token = api_key or _get_api_key_from_system()
        target_lang = (lang_type or "JP").upper()

        if target_lang in ["JP", "JA"] and any('\u4e00' <= char <= '\u9fff' for char in text):
            text = await translate_text(text, target_lang="JP", api_key=token)

        return await synthesize_apollodorus_or_fallback(
            text=text,
            speaker=resolved,
            language=target_lang,
            api_key=token,
        )


class TTS:
    """
    tts_v2 统一入口：
    提供自动路由、文本清洗、角色解析、自动翻译与音频生成。
    """

    _engine_classes = (
        PrettyDerbyEngine,
        HoliveEngine,
        GPTSoVITSEngine,
        BlueArchiveEngine,
        OttoTTSEngine,
        LocalVITSEngine,
        ApollodorusEngine,
    )

    def __init__(self):
        self.config = YAMLManager.get_instance()
        self.engines: Dict[str, TTSEngine] = {
            cls.name: cls() for cls in self._engine_classes
        }

    def _tts_config(self, config=None) -> dict:
        cfg_obj = config or self.config
        if isinstance(cfg_obj, dict):
            return cfg_obj.get("tts", cfg_obj)
        if hasattr(cfg_obj, "tts_v2") and hasattr(cfg_obj.tts_v2, "config"):
            tts_cfg = cfg_obj.tts_v2.config.get("tts")
            if tts_cfg:
                return tts_cfg
        if hasattr(cfg_obj, "mai_reply") and hasattr(cfg_obj.mai_reply, "config"):
            mai_tts = cfg_obj.mai_reply.config.get("tts")
            if mai_tts:
                return mai_tts
        if hasattr(cfg_obj, "get"):
            return cfg_obj.get("tts", {})
        return {}

    @staticmethod
    def clean_text(text: str) -> str:
        return clean_tts_text(text)

    async def get_speakers(self, bot=None) -> Dict[str, Any]:
        """获取所有可用引擎的发音人列表"""
        res = {}
        for name, engine in self.engines.items():
            try:
                res[name] = await engine.get_speakers(bot)
            except Exception as e:
                logger.warning(f"获取引擎 {name} 角色列表异常: {e}")
                res[name] = []
        return res

    async def resolve(self, speaker: Optional[str], bot=None, config=None) -> Tuple[str, str]:
        """
        根据传入的 speaker 字符串自动识别所属引擎并规范化 speaker 名称。
        若未传 speaker，优先使用配置中的默认声线或默认发音人。
        """
        cfg = self._tts_config(config)
        default_speaker = cfg.get("default_speaker", "natuki")

        if not speaker:
            # 默认发音人递归解析
            speaker = default_speaker

        spk = speaker.strip()

        # 1. 检查是否为 GPT-SoVITS 角色 (如 达妮娅)
        gpt_sovits_speakers = await self.engines["gpt_sovits"].get_speakers(bot)
        if spk in gpt_sovits_speakers or spk in ["达妮娅", "dania", "Dania"]:
            return "gpt_sovits", spk

        # 2. 检查是否为赛马娘角色（直连 PrettyDerby，如 natuki、米浴、目白麦昆 等）
        pd_resolved = resolve_pretty_derby_speaker(spk)
        if pd_resolved:
            return "pretty_derby", pd_resolved

        # 3. 检查是否为 Hololive 角色（直连 HoliveTTS，如 MoriCalliope、GawrGura 等）
        holo_resolved = resolve_holive_speaker(spk)
        if holo_resolved:
            return "holive", holo_resolved

        # 4. 检查是否属于 Blue Archive 角色 (如 JP_Mari, Mari, JP_Arona 等)
        resolved_ba = resolve_blue_archive_speaker(spk)
        if resolved_ba:
            return "blue_archive", resolved_ba

        # 5. 检查是否为 Otto 角色 (otto, 电棍 等)
        if spk.lower() in [s.lower() for s in OTTO_SPEAKERS]:
            return "otto", "otto"

        # 6. 检查是否为本地 VITS 角色
        vits_spks = await self.engines["vits"].get_speakers(bot)
        if spk in vits_spks:
            return "vits", spk

        # 7. 检查 Apollodorus 网关支持
        apol_resolved = resolve_apollodorus_speaker(spk)
        if apol_resolved:
            return "apollodorus", apol_resolved

        # 8. 未识别角色，降级至 pretty_derby 默认角色 natuki
        logger.info(f"[TTS.resolve] 未明确识别到已知引擎的角色名: '{spk}'，降级至 pretty_derby (natuki)")
        return "pretty_derby", "natuki"

    async def tts(
        self,
        text: str,
        speaker: Optional[str] = None,
        config=None,
        mood: Optional[str] = None,
        bot=None,
        mode: Optional[str] = None,
        lang_type: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> str:
        """
        全局统一语音合成入口：
        清洗文本 -> 长度截断 -> 自动路由引擎与角色 -> 合成并返回音频文件路径
        """
        cfg = self._tts_config(config)
        cleaned_text = self.clean_text(text)
        if not cleaned_text:
            raise ValueError("TTS 输入文本为空或全部为不可发音符号")

        length_limit = int(cfg.get("length_limit", 150))
        if len(cleaned_text) > length_limit:
            logger.warning(f"文本超长 ({len(cleaned_text)} > {length_limit})，已自动截断")
            cleaned_text = cleaned_text[:length_limit]

        # 显式指定模式路由
        if mode:
            mode_map = {
                "prettyderby": "pretty_derby",
                "pretty_derby": "pretty_derby",
                "holive": "holive",
                "hololive": "holive",
                "ottotts": "otto",
                "otto": "otto",
                "bluearchive": "blue_archive",
                "blue_archive": "blue_archive",
                "vits": "vits",
                "gpt_sovits": "gpt_sovits",
                "apollodorus": "apollodorus",
            }
            engine_name = mode_map.get(mode.lower(), mode.lower())
            resolved_speaker = speaker or cfg.get("default_speaker", "natuki")
        else:
            engine_name, resolved_speaker = await self.resolve(speaker, bot=bot, config=config)

        engine = self.engines.get(engine_name)
        if not engine:
            logger.warning(f"未知 TTS 引擎: {engine_name}，自动降级至 pretty_derby")
            engine = self.engines["pretty_derby"]
            resolved_speaker = "natuki"

        logger.info(f"[TTS] 路由选择: 引擎={engine_name}, 发音人={resolved_speaker}, 文本长度={len(cleaned_text)}")
        target_lang = lang_type or cfg.get("lang_type", "JP")
        api_token = api_key or cfg.get("api_key") or _get_api_key_from_system()

        return await engine.synthesize(
            text=cleaned_text,
            speaker=resolved_speaker,
            bot=bot,
            config=config,
            lang_type=target_lang,
            api_key=api_token,
        )

    async def call_tts(
        self,
        bot,
        event,
        config,
        text: str,
        speaker: Optional[str] = None,
        mood: str = "中立",
        lang_type: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """供消息事件或外部模块调用的便捷方法，合成并直接发送音频"""
        try:
            cfg = self._tts_config(config)
            target_lang = lang_type or kwargs.get("lang_type") or cfg.get("lang_type", "JP")
            path = await self.tts(
                text=text,
                speaker=speaker,
                config=config,
                mood=mood,
                bot=bot,
                lang_type=target_lang,
            )
            await bot.send(event, Record(file=path))
            return {"status": "success", "audio": path}
        except Exception as e:
            logger.error(f"[call_tts] 合成或发送失败: {e}", exc_info=True)
            return {"status": "failed", "error": str(e)}

    async def get_all_speakers(self, bot, event, config) -> Dict[str, Any]:
        """获取所有可用角色并通过转发/分条消息展示"""
        catalogs = await self.get_speakers(bot)
        nodes = [
            Node(content=[Text(
                "🎭 可用角色列表：\n"
                "可使用指令：/角色名说 内容（例如：/natuki说你好、/达妮娅说早上好、/Mari说老师好、/otto说大家好）"
            )])
        ]

        for name, spks in catalogs.items():
            if not spks:
                continue
            if isinstance(spks, dict):
                spk_list = list(spks.keys())
            else:
                spk_list = list(spks)

            display_text = f"【{name}】 共 {len(spk_list)} 个角色:\n"
            if len(spk_list) > 20:
                display_text += ", ".join(spk_list[:20]) + f"... 等共 {len(spk_list)} 个"
            else:
                display_text += ", ".join(spk_list)
            nodes.append(Node(content=[Text(display_text)]))

        await bot.send(event, nodes)
        return catalogs


_default_tts = TTS()


async def call_tts(bot, event, config, text: str, speaker: Optional[str] = None, mood: str = "中立", lang_type: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    return await _default_tts.call_tts(bot, event, config, text, speaker=speaker, mood=mood, lang_type=lang_type, **kwargs)


async def get_all_speakers(bot, event, config) -> Dict[str, Any]:
    return await _default_tts.get_all_speakers(bot, event, config)
