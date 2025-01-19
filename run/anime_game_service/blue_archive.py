# -*- coding: utf-8 -*-
from asyncio import sleep

import httpx
import yaml

from developTools.event.events import GroupMessageEvent, LifecycleMetaEvent
from developTools.message.message_components import Image
from plugins.onlineGameData_Service_plugin.blue_archive.arona_api import stageStrategy






def main(bot, logger):
    logger=bot.logger
    logger.info("arona loaded")


    @bot.on(GroupMessageEvent)
    async def selectMission(event: GroupMessageEvent):
        if str(event.raw_message).startswith("/攻略"):
            url = event.raw_message.strip()
        elif event.raw_message.startswith("/arona "):
            url = event.raw_message.strip()
        else:
            return
        logger.info_func("查询攻略：" + url)
        try:
            p = await stageStrategy(url)
            await bot.send(event, Image(file=p))
        except:
            logger.error_func("无效的角色或网络连接错误")
            await bot.send(event, "无效的角色 或网络连接出错")

    @bot.on(LifecycleMetaEvent)
    async def pushAronaData(event: LifecycleMetaEvent):
        while True:
            logger.info_func("检查arona订阅更新")
            with open("data/pictures/blueArchive/aronaSub.yaml", 'r', encoding='utf-8') as f:
                result9 = yaml.load(f.read(), Loader=yaml.FullLoader)
                for i in result9:
                    for ia in result9.get(i).get("hash"):
                        logger.info_func("检查" + ia + "更新")
                        await sleep(25)
                        url1 = "https://arona.diyigemt.com/api/v2/image?name=" + ia
                        async with httpx.AsyncClient(timeout=100) as client:  # 100s超时
                            try:
                                r = await client.get(url1)  # 发起请求
                            except Exception as e:
                                logger.error(e)
                                continue
                            r = r.json()
                            newHash = r.get("data")[0].get("hash")
                        if str(newHash) != result9.get(i).get("hash").get(ia):
                            p = await stageStrategy(ia)
                            alreadySend = []
                            for iss in result9.get(i).get("groups"):
                                if iss in alreadySend:
                                    continue
                                try:
                                    await bot.send_group_message(int(iss), (ia + "数据更新", Image(file=p)))
                                    alreadySend.append(iss)
                                except:
                                    if str(iss)!="789999":
                                        logger.error_func("向" + str(iss) + "推送更新失败")
                                    alreadySend.append(iss)
                            result9[i]["hash"][ia] = str(newHash)
                            with open('data/pictures/blueArchive/aronaSub.yaml', 'w', encoding="utf-8") as file:
                                yaml.dump(result9, file, allow_unicode=True)
            await sleep(600)  #600秒更新一次

    @bot.on(GroupMessageEvent)
    async def addSUBgroup(event: GroupMessageEvent):
        if event.raw_message == "/订阅日服":
            a = "日服"
        elif event.raw_message == "/订阅国际服":
            a = "国际服"
        elif event.raw_message == "/订阅国服":
            a = "国服"
        else:
            if event.raw_message.startswith("/订阅"):
                await bot.send(event, "无效的服务器")
                return
            else:
                return
        with open("data/pictures/blueArchive/aronaSub.yaml", 'r', encoding='utf-8') as f:
            result9 = yaml.load(f.read(), Loader=yaml.FullLoader)
            bsg = result9.get(a).get("groups")
            if event.group.id in bsg:
                await bot.send(event, "本群已订阅过")
                return
            bsg.append(event.group.id)
            result9[a]["groups"] = bsg
            with open('data/pictures/blueArchive/aronaSub.yaml', 'w', encoding="utf-8") as file:
                yaml.dump(result9, file, allow_unicode=True)
            bss = result9.get(a).get("hash")
            for i in bss:
                p = await stageStrategy(i)
                await bot.send(event, ("获取到" + i + "数据", Image(file=p)))
            logger.info(str(event.group.id) + "新增订阅")
            await bot.send(event, "成功订阅")

    @bot.on(GroupMessageEvent)
    async def aronad(event):
        if event.raw_message == "/arona" or event.raw_message == "/攻略":
            url = "杂图"
            logger.info("查询攻略：" + url)
            try:
                p = await stageStrategy(url)
                await bot.send(event, (
                "根据图中列出的项目，发送/arona 项目 即可查询，不需要艾特\n示例如下：\n/arona 国服人权\n/arona H11-2",
                Image(file=p)))
            except:
                logger.error("无效的角色或网络连接错误")
                await bot.send(event, "无效的角色 或网络连接出错")