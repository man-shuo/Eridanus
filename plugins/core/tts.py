# 语音合成接口
import asyncio
import re

import httpx

from ruamel.yaml import YAML

from plugins.utils.random_str import random_str

yaml = YAML(typ='safe')
with open('config/api.yaml', 'r', encoding='utf-8') as f:
    local_config = yaml.load(f)

async def tts(text, speaker=None, config=None,mood=None):
    pattern = re.compile(r'[\(\（][^\(\)（）（）]*?[\)\）]')

    # 去除括号及其中的内容
    cleaned_text = pattern.sub('', text)
    text = cleaned_text.replace("·", "").replace("~", "").replace("-", "")
    if config is None:
        config = YAMLManager(["config/settings.yaml", "config/basic_config.yaml", "config/api.yaml",
                              "config/controller.yaml"])  # 这玩意用来动态加载和修改配置文件

    mode = config.api["tts"]["tts_engine"]
    if mode == "acgn_ai":
        if speaker is None:
            speaker=config.api["tts"]["acgn_ai"]["speaker"]
        return await acgn_ai_tts(config.api["tts"]["acgn_ai"]["token"], config, text, speaker,mood)
    else:
        pass


async def gptVitsSpeakers():
    url = "https://infer.acgnai.top/infer/spks"
    async with httpx.AsyncClient(timeout=100) as client:
        r = await client.post(url, json={
            "type": "tts",
            "brand": "gpt-sovits",
            "name": "anime"
        })
    return r.json()["spklist"]


try:
    if local_config["tts"]["tts_engine"] == "acgn_ai" and local_config["tts"]["acgn_ai"]["token"]!= "":
        print("GPTSOVITS_SPEAKERS获取中")
        GPTSOVITS_SPEAKERS = asyncio.run(gptVitsSpeakers())
        #print(GPTSOVITS_SPEAKERS)
except:
    print("GPTSOVITS_SPEAKERS获取失败")

async def get_acgn_ai_speaker_list(a=None,b=None,c=None):
    spks=list(GPTSOVITS_SPEAKERS.keys())
    return spks
async def acgn_ai_tts(token, config, text, speaker,mood):
    if speaker not in GPTSOVITS_SPEAKERS:
        speaker = config.api["tts"]["acgn_ai"]["speaker"]
    inclination = "中立"
    if len(GPTSOVITS_SPEAKERS[speaker]) > 1:
        r=mood
        for i in GPTSOVITS_SPEAKERS[speaker]:
            if i==r:
                inclination = i
                break

    url = "https://infer.acgnai.top/infer/gen"
    async with httpx.AsyncClient(timeout=100) as client:
        r = await client.post(url, json={
            "access_token": token,
            "type": "tts",
            "brand": "gpt-sovits",
            "name": "anime",
            "method": "api",
            "prarm": {
                "speaker": speaker,
                "emotion": inclination,
                "text": text,
                "text_language": "多语种混合",
                "text_split_method": "按标点符号切",
                "fragment_interval": 0.3,
                "batch_size": 1,
                "batch_threshold": 0.75,
                "parallel_infer": True,
                "split_bucket": True,
                "top_k": 10,
                "top_p": 1.0,
                "temperature": 1.0,
                "speed_factor": 1.0
            }
        })
    async with httpx.AsyncClient(timeout=100) as client:
        r = await client.get(r.json()['audio'])
    p = "data/voice/cache/" + random_str() + '.wav'
    with open(p, "wb") as f:
        f.write(r.content)
    return p

if __name__ == '__main__':
    from plugins.core.yamlLoader import YAMLManager
    config = YAMLManager(["config/settings.yaml", "config/basic_config.yaml", "config/api.yaml",
                          "config/controller.yaml"])  # 这玩意用来动态加载和修改配置文件
    # http_server地址，access_token
    r=asyncio.run(tts("你好，欢迎使用语音合成服务，请说出你想说的话。", "玲可【星穹铁道】", config))
    print(r)