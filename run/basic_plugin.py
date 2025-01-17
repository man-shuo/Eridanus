import os

import asyncio
from asyncio import sleep

import httpx
import base64
from io import BytesIO
from bs4 import BeautifulSoup

from developTools.event.events import GroupMessageEvent

from developTools.message.message_components import Record, Node, Text, Image,Music
from plugins.basic_plugin.ai_text2img import bing_dalle3, ideo_gram, flux_speed, recraft_v3, flux_ultra
from plugins.basic_plugin.anime_setu import anime_setu, anime_setu1
from plugins.basic_plugin.cloudMusic import cccdddm
from plugins.basic_plugin.divination import tarotChoice
from plugins.basic_plugin.image_search import fetch_results
from plugins.basic_plugin.weather_query import weather_query
from plugins.core.tts import get_acgn_ai_speaker_list, tts


from plugins.core.userDB import get_user


from plugins.utils.utils import download_img,url_to_base64, parse_arguments
from plugins.utils.random_str import random_str

from plugins.core.aiReplyCore_without_funcCall import aiReplyCore_shadow


image_search={}

"""
供func call调用
"""
async def call_weather_query(bot,event,config,location=None):
    user_info = await get_user(event.user_id, event.sender.nickname)
    if location is None:
        location = user_info[5]
    r=await weather_query(config.api["proxy"]["http_proxy"],config.api["心知天气"]["api_key"],location)
    r = await aiReplyCore_shadow([{"text":f"{r}"}], event.user_id, config,func_result=True)
    await bot.send(event, str(r))
async def call_setu(bot,event,config,tags,num=3):
    user_info = await get_user(event.user_id, event.sender.nickname)
    if user_info[6] >= config.controller["basic_plugin"]["setu_operate_level"]:
        try:
            r=await anime_setu(tags,num,config.settings["basic_plugin"]["setu"]["r18mode"])
            fordMes=[]
            for i in r:
                try:
                    url=i["url"].replace("i.pximg.net","i.pixiv.re")
                    page=i["page"]
                    author=i["author"]
                    author_uid=i["author_uid"]
                    tags=i["tags"]
                    path=f"data/pictures/cache/{random_str()}.png"
                    bot.logger.info(f"Downloading {url} to {path}")
                    p=await download_img(url,path,config.settings["basic_plugin"]["setu"]["gray_layer"])
                    r = Node(content=[Text(f"link：{page}\n作者：{author}\nUID：{author_uid}\n标签：{tags}\n"),Image(file=p)])
                    fordMes.append(r)
                except Exception as e:
                    bot.logger.error(f"Error downloading: {e}")
                    continue
        except Exception as e:
            bot.logger.error(f"Error in setu: {e}")
            fordMes=[]
        if fordMes==[]:
            bot.logger.warning("No setu found.Change resource")
            r=await anime_setu1(tags,num,config.settings["basic_plugin"]["setu"]["r18mode"])
            for i in r:
                try:
                    url=i["urls"]["regular"]
                    title=i["title"]
                    author=i["author"]
                    tags=i["tags"]
                    path = f"data/pictures/cache/{random_str()}.png"
                    bot.logger.info(f"Downloading {url} to {path}")
                    p = await download_img(url, path, config.settings["basic_plugin"]["setu"]["gray_layer"])
                    r = Node(content=[Text(f"标题：{title}\n作者：{author}\n标签：{tags}\nurl：{url}"), Image(file=p)])
                    fordMes.append(r)
                except Exception as e:
                    bot.logger.error(f"Error downloading: {e}")
        if fordMes==[]:
            await bot.send(event, "没有找到符合条件的涩图呢，换个标签试试吧")
            return
        await bot.send(event, fordMes)
        for i in fordMes:
            path=i.content[1].file
            await sleep(30)
            os.remove(path.replace("file://",""))
            bot.logger.info(f"Deleted {path}")
    else:
        await bot.send(event, "权限不够呢.....")
async def call_image_search(bot,event,config,image_url=None):
    user_info = await get_user(event.user_id, event.sender.nickname)
    bot.logger.info("接收来自 用户：" + str(event.sender.user_id) + " 的搜图指令")
    if user_info[6] >= config.controller["basic_plugin"]["search_image_resource_operate_level"]:
        image_search[event.sender.user_id] = []
        if not image_url:
            img_url = event.get("image")[0]["url"]
        else:
            img_url = image_url
        results = await fetch_results(config.api["proxy"]["http_proxy"], img_url,
                                      config.api["image_search"]["sauceno_api_key"])
        image_search.pop(event.sender.user_id)
        forMeslist = []
        for name, result in results.items():
            if result and result[0] != "":
                bot.logger.info(f"{name} 成功返回: {result}")
                try:
                    path = "data/pictures/cache/" + random_str() + ".png"
                    imgpath = await download_img(result[0], path, proxy=config.api["proxy"]["http_proxy"])
                    forMeslist.append(Node(content=[Text(result[1]), Image(file=imgpath)]))

                except Exception as e:
                    bot.logger.error(f"预览图{name} 下载失败: {e}")
                    forMeslist.append(Node(content=[Text(result[1])]))
            else:
                bot.logger.error(f"{name} 返回失败或无结果")
                forMeslist.append(Node(content=[Text(f"{name} 返回失败或无结果")]))
        await bot.send(event, forMeslist)
    else:
        await bot.send(event, "权限不够呢.....")
async def call_tts(bot,event,config,text,speaker=None,mood="中立"):
    if speaker is None:
        mode = config.api["tts"]["tts_engine"]
        speaker=config.api["tts"][mode]["speaker"]
    try:
        speakers=await get_acgn_ai_speaker_list()
    except Exception as e:
        bot.logger.error(f"Error in tts: {e}")
        return
    if speaker in speakers:
        pass
    elif f"{speaker}【鸣潮】" in speakers:
        speaker=f"{speaker}【鸣潮】"
    elif f"{speaker}【原神】" in speakers:
        speaker=f"{speaker}【原神】"
    elif f"{speaker}【崩坏3】" in speakers:
        speaker=f"{speaker}【崩坏3】"
    elif f"{speaker}【星穹铁道】" in speakers:
        speaker=f"{speaker}【星穹铁道】"
    else:
        #bot.logger.error(f"Invalid speaker: {speaker}")
        return
    try:
        p=await tts(text,speaker,config,mood)
        await bot.send(event, Record(file=p))
    except Exception as e:
        bot.logger.error(f"Error in tts: {e}")

async def call_tarot(bot,event,config):
    txt, img = tarotChoice(config.settings["basic_plugin"]["tarot"]["mode"])
    await bot.send(event,[Text(txt),Image(file=img)])
    r=await aiReplyCore_shadow([{"text":txt}], event.user_id, config,func_result=True)
    if r and config.api["llm"]["aiReplyCore"]:
        await bot.send(event, r)
async def call_pick_music(bot,event,config,aim):
    try:
        r=await cccdddm(aim)
        #print(r)
        await bot.send(event, Music(type="163", id=r[0][1]))
    except Exception as e:
        bot.logger.error(f"Error in pick_music: {e}")
        await bot.send(event, "出错了，再试一次看看？")
def main(bot,config):
    global avatar
    avatar=False
    @bot.on(GroupMessageEvent)
    async def weather_query(event: GroupMessageEvent):
        if event.raw_message.startswith("查天气"):
            #await bot.send(event, "已修改")
            remark = event.raw_message.split("查天气")[1].strip()
            await bot.set_friend_remark(event.user_id, remark)
    @bot.on(GroupMessageEvent)
    async def weather(event: GroupMessageEvent):
        if event.raw_message.startswith("/setu"):
            tags=event.raw_message.replace("/setu","").split(" ")
            try:
                await call_setu(bot,event,config,tags[2:],int(tags[1]))
            except Exception as e:
                bot.logger.error(f"Error in setu: {e}")
                await bot.send(event, "出错，格式请按照\n/setu 数量 标签 标签")

    @bot.on(GroupMessageEvent)
    async def search_image(event):
        if "搜图" not in event.raw_message: return
        if str(event.raw_message) == "搜图" or (event.get("at") and event.get("at")[0]["qq"]==str(bot.id) and event.get("text")[0]=="搜图"):
            await bot.send(event, "请发送要搜索的图片")
            image_search[event.sender.user_id] = []
        if ("搜图" in str(event.raw_message) or event.sender.user_id in image_search) and event.get('image'):
            await call_image_search(bot,event,config)
            image_search.pop(event.sender.user_id)
    @bot.on(GroupMessageEvent)
    async def tts(event: GroupMessageEvent):
        if "说" in event.raw_message:
            speaker=event.raw_message.split("说")[0].strip()
            text=event.raw_message.split("说")[1].strip()
            await call_tts(bot,event,config,text,speaker)
        elif event.raw_message=="可用角色":
            #Node(content=[Text("可用角色：")]+[Text(i) for i in get_acgn_ai_speaker_list()])
            ffff=await get_acgn_ai_speaker_list()

            await bot.send(event, Node(content=[Text(f"可用角色：{ffff}")]))

    @bot.on(GroupMessageEvent)
    async def cyber_divination(event: GroupMessageEvent):
        if event.raw_message=="今日塔罗":
            txt, img = tarotChoice(config.settings["basic_plugin"]["tarot"]["mode"])
            await bot.send(event, [Text(txt), Image(file=img)]) #似乎没必要让这个也走ai回复调用
        elif event.raw_message=="抽象塔罗":
            txt, img = tarotChoice('AbstractImages')
            await bot.send(event, [Text(txt), Image(file=img)]) #似乎没必要让这个也走ai回复调用
        elif event.raw_message=="ba塔罗":
            txt, img = tarotChoice('blueArchive')
            await bot.send(event, [Text(txt), Image(file=img)]) #似乎没必要让这个也走ai回复调用
        elif event.raw_message=="bili塔罗" or event.raw_message=="2233塔罗":
            txt, img = tarotChoice('bilibili')
            await bot.send(event, [Text(txt), Image(file=img)]) #似乎没必要让这个也走ai回复调用
    @bot.on(GroupMessageEvent)
    async def pick_music(event: GroupMessageEvent):
        if event.raw_message.startswith("点歌 "):
            song_name = event.raw_message.split("点歌 ")[1]
            await call_pick_music(bot, event, config, song_name)


