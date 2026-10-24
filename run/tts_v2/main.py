import traceback
from developTools.event.events import GroupMessageEvent, PrivateMessageEvent
from developTools.message.message_components import Text, Record
from framework_common.framework_util.websocket_fix import ExtendBot
from framework_common.framework_util.yamlLoader import YAMLManager
from run.tts_v2.service.tts import call_tts, get_all_speakers, TTS

def main(bot: ExtendBot, config: YAMLManager):
    bot.logger.info("[TTS V2] 统一语音服务加载成功")

    async def _handle_msg(event):
        raw_text = (event.pure_text or "").strip()
        if not raw_text:
            return

        # 1. 角色列表查询指令
        if raw_text in ["可用角色", "语音角色", "/可用角色", "/语音角色"]:
            try:
                await get_all_speakers(bot, event, config)
            except Exception as e:
                bot.logger.error(f"[TTS V2] 获取可用角色失败: {e}", exc_info=True)
                await bot.send(event, Text("获取可用角色列表失败，请查看后台日志。"))
            return

        # 2. "/xx说xxxxx" 语法触发
        if raw_text.startswith("/") and "说" in raw_text:
            parts = raw_text.split("说", 1)
            speaker_candidate = parts[0].replace("/", "").strip()
            tts_text = parts[1].strip()

            if not tts_text:
                await bot.send(event, Text("请输入要说的内容，例如：/natuki说早上好"))
                return

            try:
                bot.logger.info(f"[TTS V2] 收到语音请求: speaker={speaker_candidate}, text={tts_text}")
                res = await call_tts(bot, event, config, tts_text, speaker=speaker_candidate)
                if res.get("status") != "success":
                    error_msg = res.get("error", "未知错误")
                    bot.logger.warning(f"[TTS V2] 语音合成失败: {error_msg}")
            except Exception as e:
                bot.logger.error(f"[TTS V2] 处理语音请求异常: {e}", exc_info=True)

    @bot.on(GroupMessageEvent)
    async def handle_group(event: GroupMessageEvent):
        await _handle_msg(event)

    @bot.on(PrivateMessageEvent)
    async def handle_private(event: PrivateMessageEvent):
        await _handle_msg(event)
