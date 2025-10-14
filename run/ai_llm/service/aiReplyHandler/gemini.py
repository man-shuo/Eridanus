import base64
import io
import os
import re
import traceback

import httpx
from PIL import Image

from developTools.utils.logger import get_logger
from framework_common.database_util.llmDB import get_user_history, update_user_history
from framework_common.utils.random_str import random_str
from run.ai_llm.service.aiReplyHandler.ModelFallBackManager import ModelFallbackManager

logger=get_logger("Gemini Prompt Construct and Request")
async def geminiRequest(ask_prompt,base_url: str,apikey: str,model: str,proxy=None,tools=None,system_instruction=None,temperature=0.7,maxOutputTokens=2048,fallback_models: list[str] = None):
    if proxy is not None and proxy !="":
        proxies={"http://": proxy, "https://": proxy}
    else:
        proxies=None
    #url = f"{base_url}/v1beta/models/{model}:generateContent?key={apikey}"
    """
    模型降级操作
    """
    if fallback_models:
        manager = ModelFallbackManager(fallback_models)
        models_to_try = fallback_models
    else:
        models_to_try = [model]
        manager = None
    # print(requests.get(url,verify=False))
    pay_load={
        "contents": ask_prompt,
        "systemInstruction": {
            "parts": [
                {
                    "text": system_instruction,
                }
            ]
        },
        "safetySettings": [
            {'category': 'HARM_CATEGORY_SEXUALLY_EXPLICIT', "threshold": "BLOCK_None"},
            {'category': 'HARM_CATEGORY_HATE_SPEECH', "threshold": "BLOCK_None"},
            {'category': 'HARM_CATEGORY_HARASSMENT', "threshold": "BLOCK_None"},
            {'category': 'HARM_CATEGORY_DANGEROUS_CONTENT', "threshold": "BLOCK_None"}],
        "generationConfig": {
            "temperature": temperature,
            "topK": 64,
            "topP": 0.95,
            "maxOutputTokens": maxOutputTokens,
            "responseMimeType": "text/plain"
        }
    }
    if tools is not None:
        pay_load["tools"] = tools


    #async with httpx.AsyncClient(proxies=proxies, timeout=100) as client:
        #r = await client.post(url, json=pay_load)
        #return r.json()
        #print(r.json())
        #return r.json()['candidates'][0]["content"]
    for attempt in range(len(models_to_try)):
        current_model = manager.get_current_model() if manager else model
        url = f"{base_url}/v1beta/models/{current_model}:generateContent?key={apikey}"

        async with httpx.AsyncClient(proxies=proxies, timeout=100) as client:
            r = await client.post(url, json=pay_load)
            result = r.json()

            if isinstance(result, dict) and 'error' in result:
                error_code = result.get('error', {}).get('code')
                if error_code == 429:
                    if manager and manager.fallback():
                        logger.warning(f"模型 {current_model} 配额耗尽(429),切换到: {manager.get_current_model()}")
                        continue
                    else:
                        logger.error(f"所有模型配额均已耗尽")
                        return result

            return result

"""
gemini标准prompt构建
"""
BASE64_PATTERN = re.compile(r"^data:([a-zA-Z0-9]+/[a-zA-Z0-9-.+]+);base64,([A-Za-z0-9+/=]+)$")
async def gemini_prompt_elements_construct(precessed_message,bot=None,func_result=False,event=None):
    prompt_elements=[]

    #{"role": "assistant","content":[{"type":"text","text":i["text"]}]}
    for i in precessed_message:
        if "text" in i:
            prompt_elements.append({"text": i["text"]})
        elif "image" in i or "mface" in i:
            try:
                if "mface" in i:
                    url=i["mface"]["url"]
                else:
                    try:
                        url=i["image"]["url"]
                    except:
                        url=i["image"]["file"]
                base64_match = BASE64_PATTERN.match(url)
                if base64_match:
                    img_base64 = base64_match.group(2)
                    prompt_elements.append({"inline_data": {"mime_type": "image/jpeg", "data": img_base64}})
                    continue
                prompt_elements.append({"text": f"system提示: 当前图片的url为{url}"})
                # 下载图片转base64
                async with httpx.AsyncClient(timeout=60) as client:
                    res = await client.get(url)
                    image = None
                    img_byte_arr = None
                    # res.raise_for_status()  # Check for HTTP errors
                    try:
                        image = Image.open(io.BytesIO(res.content))
                        image = image.convert("RGB")
                    except Exception as e:
                        logger.warning(f"下载图片失败:{url} 原因:{e}")
                        continue

                    quality = 85
                    while True:
                        img_byte_arr = io.BytesIO()
                        image.save(img_byte_arr, format='JPEG', quality=quality)
                        size_kb = img_byte_arr.tell() / 1024
                        if size_kb <= 400 or quality <= 10:
                            break
                        quality -= 5
                        img_byte_arr.close()  # 添加这行，关闭之前的BytesIO
                    img_base64 = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
                prompt_elements.append({"inline_data": {"mime_type": "image/jpeg", "data": img_base64}})
                #prompt_elements.append({"type":"image_url","image_url":i["image"]["url"]})
            except Exception as e:
                traceback.print_exc()
                prompt_elements.append({"text": f"系统提示：下载图片失败"})
            finally:
                # 清理资源
                if image is not None:
                    image.close()
                if img_byte_arr is not None:
                    img_byte_arr.close()
                del res

        elif "record" in i and bot is not None:
            origin_voice_url=i["record"]["file"]
            base64_match = BASE64_PATTERN.match(origin_voice_url)
            if base64_match:
                mime_type = base64_match.group(1)
                img_base64 = base64_match.group(2)
                prompt_elements.append({"inline_data": {"mime_type": "audio/mp3", "data": img_base64}})
                continue
            mp3_data=None
            try:
                r = await bot.get_record(origin_voice_url)
                logger.info(f"下载语音成功:{r}")
                mp3_filepath = r["data"]["file"]
                with open(mp3_filepath, "rb") as mp3_file:
                    mp3_data = mp3_file.read()
                    base64_encoded_data = base64.b64encode(mp3_data)
                    base64_message = base64_encoded_data.decode('utf-8')
                    prompt_elements.append({"inline_data": {"mime_type": "audio/mp3", "data": base64_message}})
                #prompt_elements.append({"type":"voice","voice":i["voice"]})
            except Exception as e:
                logger.warning(f"下载语音失败:{origin_voice_url} 原因:{e}")
            finally:
                if mp3_data is not None:
                    del mp3_data
        elif "video" in i and bot is not None:
            mp4_data=None
            base64_encoded_data=None
            try:
                video_url=i["video"]["url"]
            except:
                video_url=i["video"]["file"]
            base64_match = BASE64_PATTERN.match(video_url)
            if base64_match:
                mime_type = base64_match.group(1)
                img_base64 = base64_match.group(2)
                prompt_elements.append({"inline_data": {"mime_type": "video/mp4", "data": img_base64}})
                continue
            try:
                video=await bot.get_video(video_url,f"data/pictures/cache/{random_str()}.mp4")

                # 下载视频文件大小限制(15MB)
                file_size = os.path.getsize(video)
                if file_size > 15 * 1024 * 1024:
                    raise Exception(f"视频文件大小超出限制: {file_size / (1024 * 1024):.2f}MB，最大允许 15MB")

                with open(video, "rb") as mp4_file:
                    mp4_data = mp4_file.read()
                    base64_encoded_data = base64.b64encode(mp4_data)
                    base64_message = base64_encoded_data.decode('utf-8')
                    prompt_elements.append({"inline_data": {"mime_type": "video/mp4", "data": base64_message}})
            except Exception as e:
                logger.warning(f"下载视频失败:{video_url} 原因:{e}")
                prompt_elements.append({"text": str(i)})
            finally:
                if mp4_data is not None:
                    del mp4_data
                if base64_encoded_data is not None:
                    del base64_encoded_data
        elif "reply" in i and event is not None and bot is not None:
            try:
                event_obj=await bot.get_msg(int(event.get("reply")[0]["id"]))
                message = await gemini_prompt_elements_construct(event_obj.processed_message) #
                prompt_elements.extend(message["parts"])
            except Exception as e:
                traceback.print_exc()
                logger.warning(f"引用消息解析失败:{e}")
                continue
        else:
            prompt_elements.append({"text": str(i)})   #不知道还有什么类型，都需要做对应处理的，唉，任务还多着呢。
    if func_result:
        return {"role": "model","parts":prompt_elements}
    return {"role": "user","parts": prompt_elements}
async def construct_gemini_standard_prompt(processed_message, user_id, bot=None,func_result=False,event=None):
    message=await gemini_prompt_elements_construct(processed_message,bot,func_result,event=event)
    history = await get_user_history(user_id)
    original_history = history.copy()  # 备份，出错的时候可以rollback
    history.append(message)

    await update_user_history(user_id, history)  # 更新数据库中的历史记录
    return history, original_history
async def query_and_insert_gemini(user_id,aim_element,insert_message):
    if insert_message=={
        "parts": [
            {
                "text": "\n"
            }
        ],
        "role": "model"
    }:
        return
    history = await get_user_history(user_id)
    try:
        index=history.index(aim_element)
        history.insert(index+1,insert_message)
        await update_user_history(user_id, history)
    except Exception as e:
        logger.warning(f"插入gemini prompt失败:{e}\n原始消息:{aim_element} 要插入的消息:{insert_message}")
        return None

async def get_current_gemini_prompt(user_id):
    history = await get_user_history(user_id)
    return history
async def add_gemini_standard_prompt(prompt,user_id):
    history = await get_user_history(user_id)
    original_history = history.copy()  # 备份，出错的时候可以rollback
    history.append(prompt)

    await update_user_history(user_id, history)  # 更新数据库中的历史记录
    return history, original_history
