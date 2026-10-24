import re
import httpx
from typing import Optional
from developTools.utils.logger import get_logger

logger = get_logger("tts_translator")

def clean_tts_text(text: str) -> str:
    """清洗文本：去除 Markdown 代码块、行内代码、各类心理描写/动作描写括号（小括号、方括号、黑括号等），保留纯发音字符"""
    if not text:
        return ""
    # 1. 优先去掉多行 markdown 代码块 ```...```
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # 2. 去掉行内代码 `...`
    text = re.sub(r"`.*?`", "", text)
    # 3. 去掉各类动作/心理描写的括号内容：
    #    - 全角/半角圆括号: （...）, (...)
    #    - 方括号与黑括号: 【...】, [...]
    #    - 星号动作: *...*
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"[【\[][^】\]]*[】\]]", "", text)
    text = re.sub(r"\*[^*]+\*", "", text)
    # 4. 去除可能残留的单边符号与特殊标点
    text = text.replace("```", "").replace("`", "")
    text = text.replace("～", "").replace("~", "").replace("-", "")
    return text.strip()

async def translate_text(
    text: str,
    target_lang: str = "JP",
    api_key: Optional[str] = None,
    base_url: str = "http://api.apollodorus.xyz/v1",
) -> str:
    """
    通用翻译函数：
    1. 优先使用 api.apollodorus.xyz/translate（携带 trigger_llm / apollodorus api_key）
    2. 若未配置 key 或失败，备用使用高可用翻译接口（有道等备用翻译源）
    """
    cleaned = clean_tts_text(text)
    if not cleaned:
        return ""

    target = target_lang.upper()
    if target in ["ZH", "ZH_CN", "CN"]:
        return cleaned

    direction = "zh2ja" if target in ["JP", "JA"] else "zh2en"

    # 1. 尝试使用 trigger_llm / apollodorus api_key 翻译
    if api_key:
        # 1.1 尝试专用 /translate 接口
        try:
            root_url = base_url.replace("/v1", "").rstrip("/")
            trans_url = f"{root_url}/translate"
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = {"text": cleaned, "direction": direction}
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(trans_url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    trans = data.get("translation")
                    if trans:
                        logger.info(f"[TTS Translator] Apollodorus /translate 翻译成功: '{cleaned}' -> '{trans}'")
                        return str(trans).strip()
        except Exception as e:
            logger.debug(f"[TTS Translator] /translate 接口异常: {e}")

        # 1.2 尝试 trigger_llm 的 Chat Completions 接口
        try:
            chat_url = f"{base_url.rstrip('/')}/chat/completions" if "/v1" in base_url else f"{base_url.rstrip('/')}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            target_desc = "日文" if target in ["JP", "JA"] else "英文"
            chat_payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": f"你是一个专业的口语文本文档翻译员。请直接将用户的输入文本翻译为自然的{target_desc}。要求：绝不要添加任何说明、解释、罗马音或符号，只返回翻译后的纯文本。"
                    },
                    {"role": "user", "content": cleaned}
                ],
                "temperature": 0.3,
                "max_tokens": 200
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(chat_url, json=chat_payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices and "message" in choices[0]:
                        trans = choices[0]["message"].get("content", "").strip()
                        if trans:
                            logger.info(f"[TTS Translator] LLM Chat 翻译成功: '{cleaned}' -> '{trans}'")
                            return trans
        except Exception as e:
            logger.debug(f"[TTS Translator] LLM Chat 翻译异常: {e}")

    # 2. 备用接口 1: 有道翻译（毫秒级高可用稳定接口）
    try:
        yd_lang = "ja" if target in ["JP", "JA"] else "en"
        yd_url = "https://aidemo.youdao.com/trans"
        yd_data = {"q": cleaned, "from": "zh-CHS", "to": yd_lang}
        yd_headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.post(yd_url, data=yd_data, headers=yd_headers)
            if r.status_code == 200:
                yd_res = r.json()
                translations = yd_res.get("translation")
                if translations and isinstance(translations, list) and translations[0]:
                    trans = str(translations[0]).strip()
                    logger.info(f"[TTS Translator] 有道翻译成功: '{cleaned}' -> '{trans}'")
                    return trans
    except Exception as e:
        logger.debug(f"[TTS Translator] 有道翻译异常: {e}")

    # 3. 备用接口 2: appworlds (通用备用)
    try:
        to_lang = "ja" if target in ["JP", "JA"] else "en"
        import urllib.parse
        encoded_text = urllib.parse.quote(cleaned)
        url = f"https://translate.appworlds.cn?text={encoded_text}&from=zh-CN&to={to_lang}"
        async with httpx.AsyncClient(timeout=6, verify=False) as client:
            r = await client.get(url)
            if r.status_code == 200:
                res = r.json()
                if isinstance(res, dict) and res.get("data"):
                    logger.info(f"[TTS Translator] AppWorlds 翻译成功: '{cleaned}' -> '{res['data']}'")
                    return str(res["data"])
    except Exception as e:
        logger.debug(f"[TTS Translator] AppWorlds 异常: {e}")

    # 4. 备用接口 3: findmyip
    try:
        to_lang = "ja" if target in ["JP", "JA"] else "en"
        url = f"https://findmyip.net/api/translate.php?text={cleaned}&target_lang={to_lang}"
        async with httpx.AsyncClient(timeout=6, verify=False) as client:
            r = await client.get(url)
            if r.status_code == 200:
                res = r.json()
                if "data" in res and "translate_result" in res["data"]:
                    return res["data"]["translate_result"]
    except Exception as e:
        logger.debug(f"[TTS Translator] findmyip 异常: {e}")

    # 5. 备用接口 4: pearktrue
    try:
        mode = "ZH_CN2JA" if target in ["JP", "JA"] else "ZH_CN2EN"
        url = f"https://api.pearktrue.cn/api/translate/?text={cleaned}&type={mode}"
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
            if r.status_code == 200:
                res = r.json()
                if "data" in res and "translate" in res["data"]:
                    return res["data"]["translate"]
    except Exception as e:
        logger.debug(f"[TTS Translator] pearktrue 异常: {e}")

    # 最终降级：直接返回原清洗文本
    return cleaned
